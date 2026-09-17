"""Receipt OCR: image preprocessing + heuristic field extraction.

Stage 2 of the pipeline in the spec: raw photo -> structured attributes
(merchant name, date, total, line items). Phone photos of receipts are
messy — off-angle, low contrast thermal print, a background behind the
paper — so getting usable text out of Tesseract takes real preprocessing,
not just a straight OCR call. This module:

  1. auto-crops the photo down to the receipt itself where possible,
  2. boosts contrast and upscales (thermal print is grey, not black/white,
     and often small relative to the photo's resolution),
  3. runs Tesseract in "single uniform block of text" mode (psm 6), which
     performs far better on the narrow, single-column layout of a receipt
     than the default page-layout-detection mode,
  4. applies regex heuristics tuned to common till-slip patterns (a
     `qty @ unit_price  line_total` row split across two lines, `less ...
     Discount` promo lines that should reduce the item above them, dotted
     dd.mm.yy dates), and
  5. checks the extracted text against a short list of well-known retail
     chains before falling back to "first readable line is the merchant".

None of this is perfect — it's a best-guess pass to save typing, which the
user then corrects in the verification form (stage 3 of the pipeline).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytesseract
from PIL import Image

DATE_PATTERNS = [
    r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b',            # 2026-08-20
    r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b',         # 20/08/2026, 20-08-26, 03.09.26
]

TOTAL_KEYWORDS = re.compile(r'\b(total|amount due|grand total|balance due)\b', re.IGNORECASE)
SUBTOTAL_KEYWORDS = re.compile(r'\bsub[\s-]?total\b', re.IGNORECASE)
TAX_KEYWORDS = re.compile(r'\b(vat|tax|gst)\b', re.IGNORECASE)
DISCOUNT_KEYWORDS = re.compile(r'\b(less|discount|promo)\b', re.IGNORECASE)

# Matches a trailing price at the end of a line, e.g. "Milk 2L  34.99" or
# "CHOC LUNCH BAR ORIGINAL 44g 19.99#" (till slips often suffix a flag
# letter/hash after the amount for tax category — strip it separately).
LINE_ITEM_PRICE = re.compile(
    r'(?P<name>[A-Za-z][A-Za-z0-9 &/\'\.\-]{1,45}?)\s+R?\$?\s*(?P<price>\d{1,4}[.,]\d{2})\s*[A-Za-z#]{0,2}\s*$'
)

# "2 @ 25.99  51.98" — quantity, unit price, line total, all on one row
# (common on Pick n Pay / Checkers / Shoprite-style slips for qty > 1 items).
QTY_LINE = re.compile(
    r'^\s*(?P<qty>\d{1,3})\s*[@x]\s*(?P<unit>\d{1,4}[.,]\d{2})\s+[A-Za-z#]{0,2}\s*(?P<total>\d{1,4}[.,]\d{2})\s*[A-Za-z#]{0,2}\s*$'
)

NOISE_LINE = re.compile(
    r'^(thank you|tel|vat no|cashier|receipt|store|www\.|http|invoice|card|change|cash|customer|terms|'
    r'tax invoice|liquor lic|txn|till|rate|gross|net\b|smart shopper|rands|you missed|club benefits|'
    r'today you saved|this year|keep your|served by|savings?)',
    re.IGNORECASE,
)

KNOWN_MERCHANTS = [
    'Pick n Pay', 'Checkers', 'Woolworths', 'Shoprite', 'Spar', 'Makro',
    'Game', 'Clicks', 'Dis-Chem', 'Boxer', 'Food Lovers Market', 'OK Foods',
]


@dataclass
class ParsedItem:
    name: str
    price: float


@dataclass
class ParsedReceipt:
    raw_text: str
    merchant_name: str | None = None
    purchase_date: str | None = None  # ISO format, best guess
    total_amount: float | None = None
    items: list[ParsedItem] = field(default_factory=list)


def _load_gray(file) -> np.ndarray:
    if isinstance(file, str):
        with open(file, 'rb') as f:
            data = f.read()
    elif hasattr(file, 'read'):
        data = file.read()
        if hasattr(file, 'seek'):
            file.seek(0)
    else:
        data = file
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return np.array(Image.open(file).convert('L'))
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _find_receipt_crop(gray: np.ndarray) -> np.ndarray:
    """Best-guess bounding box of the receipt within the frame. Returns the
    full image unchanged if no confident region is found."""
    h, w = gray.shape
    try:
        blur = cv2.GaussianBlur(gray, (7, 7), 0)
        _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = np.ones((31, 31), np.uint8)
        cleaned = cv2.dilate(cv2.erode(mask, kernel), kernel)
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        img_area = h * w
        best = None
        for c in contours:
            area = cv2.contourArea(c)
            if area < 0.08 * img_area:
                continue
            x, y, cw, ch = cv2.boundingRect(c)
            if ch < cw:  # receipts are photographed portrait-orientation
                continue
            if best is None or area > best[0]:
                best = (area, x, y, cw, ch)
        if best:
            _, x, y, cw, ch = best
            pad = int(0.02 * max(cw, ch))
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(w, x + cw + pad), min(h, y + ch + pad)
            mx, my = int(0.035 * (x1 - x0)), int(0.015 * (y1 - y0))
            return gray[y0 + my:y1 - my, x0 + mx:x1 - mx]
    except cv2.error:
        pass
    return gray


def _enhance(crop: np.ndarray, binarize: bool) -> Image.Image:
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(crop)
    ch, cw = enhanced.shape
    scale = 2 if max(ch, cw) < 2200 else 1
    if scale > 1:
        enhanced = cv2.resize(enhanced, (cw * scale, ch * scale), interpolation=cv2.INTER_CUBIC)
    if binarize:
        _, enhanced = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(enhanced)


def _candidate_images(file) -> list[Image.Image]:
    """A handful of different preprocessing takes on the same photo. OCR
    quality on real, messy phone photos varies a lot between binarized vs.
    grayscale, and cropped vs. full-frame — trying several and keeping the
    one that actually parses best beats betting on a single pipeline."""
    gray = _load_gray(file)
    crop = _find_receipt_crop(gray)
    candidates = [
        _enhance(crop, binarize=True),
        _enhance(crop, binarize=False),
    ]
    # Only bother with the uncropped full frame if cropping actually
    # changed something — otherwise it's a wasted, identical OCR pass.
    if crop.shape != gray.shape:
        candidates.append(_enhance(gray, binarize=True))
    return candidates


def parse_receipt_image(file) -> ParsedReceipt:
    """Run OCR on an uploaded image/file-like object and extract best-guess
    receipt fields. `file` is a Django UploadedFile or any file-like object
    opened in binary mode.

    Tries a few different preprocessing + Tesseract page-segmentation-mode
    combinations. Real photo quality varies enough that no single pass wins
    on every field, so each field (merchant, date, total, items) is picked
    from whichever pass did best on *that* field specifically, rather than
    committing to one pass's output wholesale."""
    candidates = _candidate_images(file)
    passes = []
    for image in candidates:
        for psm in (6, 4):
            raw_text = pytesseract.image_to_string(image, config=f'--psm {psm}')
            lines = [l for l in raw_text.splitlines() if l.strip()]
            passes.append({
                'raw_text': raw_text,
                'merchant': _guess_merchant(raw_text, lines),
                'date': _guess_date(lines),
                'total': _guess_total(lines),
                'items': _guess_items(lines),
            })

    def first_known_merchant():
        for p in passes:
            if p['merchant'] and any(
                re.sub(r'[^a-z]', '', p['merchant'].lower()) == re.sub(r'[^a-z]', '', m.lower())
                for m in KNOWN_MERCHANTS
            ):
                return p['merchant']
        return next((p['merchant'] for p in passes if p['merchant']), None)

    best_items_pass = max(passes, key=lambda p: len(p['items']))
    best_raw_text = max(passes, key=lambda p: len(p['raw_text']))['raw_text']

    return ParsedReceipt(
        raw_text=best_raw_text,
        merchant_name=first_known_merchant(),
        purchase_date=next((p['date'] for p in passes if p['date']), None),
        total_amount=next((p['total'] for p in passes if p['total'] is not None), None),
        items=best_items_pass['items'],
    )


def _guess_date(lines: list[str]) -> str | None:
    for line in lines:
        for pattern in DATE_PATTERNS:
            m = re.search(pattern, line)
            if not m:
                continue
            groups = m.groups()
            try:
                if len(groups[0]) == 4:  # yyyy-mm-dd
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                else:  # dd-mm-yy(yy) / dd.mm.yy(yy)
                    d, mo, y = int(groups[0]), int(groups[1]), int(groups[2])
                    if y < 100:
                        y += 2000
                from datetime import date as _date
                return _date(y, mo, d).isoformat()
            except ValueError:
                continue
    return None


def _guess_total(lines: list[str]) -> float | None:
    candidates = []
    for line in lines:
        if TOTAL_KEYWORDS.search(line) and not SUBTOTAL_KEYWORDS.search(line):
            m = re.findall(r'(\d{1,6}[.,]\d{2})', line)
            if m:
                # The total amount is the last decimal figure on the TOTAL
                # line — earlier ones are often an "(N items)" count that
                # happened to include a decimal-looking OCR artifact.
                candidates.append(float(m[-1].replace(',', '.')))
    if candidates:
        return max(candidates)
    return None


def _fuzzy_contains(key: str, text: str, threshold: float) -> bool:
    """Whether a substring of `text` roughly matches `key`, sliding a
    window rather than comparing the whole (often much longer, noisier)
    line — comparing 'picknpay' against an entire garbled 40-character OCR
    line dilutes the ratio even when the actual match is strong."""
    n = len(key)
    if n == 0 or len(text) < n:
        return difflib.SequenceMatcher(None, key, text).ratio() >= threshold
    best = 0.0
    step = max(1, n // 4)
    for start in range(0, len(text) - n + 1, step):
        window = text[start:start + n + 2]
        ratio = difflib.SequenceMatcher(None, key, window).ratio()
        best = max(best, ratio)
        if best >= threshold:
            return True
    return best >= threshold


def _guess_merchant(raw_text: str, lines: list[str]) -> str | None:
    normalized_text = re.sub(r'[^a-z]', '', raw_text.lower())
    for name in KNOWN_MERCHANTS:
        key = re.sub(r'[^a-z]', '', name.lower())
        if key in normalized_text:
            return name
    # Exact substring failed (logos in particular OCR very badly) — try a
    # fuzzy sliding-window match against every line, header or footer.
    # Skip short names here: a 4-letter key like "Spar" matches garbled
    # noise far too easily at any threshold loose enough to be useful.
    for name in KNOWN_MERCHANTS:
        key = re.sub(r'[^a-z]', '', name.lower())
        if len(key) < 6:
            continue
        for line in lines:
            norm_line = re.sub(r'[^a-z]', '', line.lower())
            if norm_line and _fuzzy_contains(key, norm_line, threshold=0.78):
                return name

    # No known chain matched — fall back to "first readable line at the top".
    for line in lines[:5]:
        clean = line.strip()
        if len(clean) >= 3 and not NOISE_LINE.match(clean) and not re.match(r'^[\d\s./-]+$', clean):
            return clean
    return None


def _is_plausible_item_name(name: str) -> bool:
    """Rejects OCR garbage like 'Z e roe' — needs a reasonable run of
    letters and can't be dominated by stray punctuation/symbols."""
    letters = sum(c.isalpha() for c in name)
    if letters < 3:
        return False
    if not re.search(r'[A-Za-z]{3,}', name):
        return False
    alnum_ratio = sum(c.isalnum() or c.isspace() for c in name) / max(1, len(name))
    return alnum_ratio >= 0.75


def _guess_items(lines: list[str]) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    pending_name: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if TOTAL_KEYWORDS.search(line) or SUBTOTAL_KEYWORDS.search(line) or TAX_KEYWORDS.search(line):
            pending_name = None
            continue
        if NOISE_LINE.match(line):
            continue

        # "less ... Discount  -7.99" — reduce the previous item rather than
        # add a new line item, matching what the shopper actually paid.
        if DISCOUNT_KEYWORDS.search(line):
            m = re.search(r'(\d{1,4}[.,]\d{2})', line)
            if m and items:
                discount = float(m.group(1).replace(',', '.'))
                items[-1].price = max(0.0, items[-1].price - discount)
            pending_name = None
            continue

        # "2 @ 25.99  51.98" on its own row — attach to the item name from
        # the line above, if we've got one pending.
        qm = QTY_LINE.match(line)
        if qm:
            total = float(qm.group('total').replace(',', '.'))
            name = pending_name or 'Item'
            if _is_plausible_item_name(name) or pending_name is None:
                items.append(ParsedItem(name=name, price=total))
            pending_name = None
            continue

        m = LINE_ITEM_PRICE.search(line)
        if m:
            try:
                price = float(m.group('price').replace(',', '.'))
            except ValueError:
                pending_name = None
                continue
            name = m.group('name').strip(' -.')
            if name and price > 0 and _is_plausible_item_name(name):
                items.append(ParsedItem(name=name, price=price))
            pending_name = None
            continue

        # No price on this line at all — could be a wrapped item name
        # waiting for a qty line next, e.g. "PEANUTS+RAISINS 150GR".
        if re.search(r'[A-Za-z]{3,}', line) and not re.match(r'^[\d\s.,#@%-]+$', line):
            pending_name = line
        else:
            pending_name = None

    return items
