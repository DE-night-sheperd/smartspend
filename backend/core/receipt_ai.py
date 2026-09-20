"""Stage 2 of the pipeline — real receipt analysis.

Two extractors:

1. Gemini vision (preferred, used when GEMINI_API_KEY is configured).
   The photo goes straight to a multimodal model which returns structured
   JSON: merchant, date, total, channel, and every line item with a
   suggested category and an impulse bet. This understands crumpled
   photos, multi-column layouts, small fonts and fine print far better
   than any regex pass over flat OCR text.

2. Tesseract + heuristics (fallback, always available — see ocr.py).
   Used when no Gemini key is configured or the Gemini call fails, so
   the scan feature never hard-fails; the verification form still lets
   the user correct anything the cheaper engine got wrong.

The returned ParsedReceipt always says which engine produced it so the
frontend can show an honest "AI read" vs "OCR read" hint.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field

import requests
from django.conf import settings

from .ocr import parse_receipt_image as _tesseract_parse

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'

DEFAULT_GEMINI_MODEL = 'gemini-3.6-flash'

PROMPT_TEMPLATE = """\
You are a receipt-parsing engine for a budgeting app. Read the receipt in \
the attached image and return ONLY a JSON object (no markdown, no prose) \
with exactly this shape:

{{
  "merchant": "store or service name as printed, or null",
  "date": "purchase date as YYYY-MM-DD, or null",
  "total": "final amount paid as a number, or null",
  "channel": "Physical_Store or Online_Ecommerce, best guess",
  "cashier": "cashier/teller name printed on the slip, or null",
  "branch": "store branch as printed (name/number), or null",
  "slip_number": "transaction/invoice/slip number, or null",
  "payment_method": "payment line as printed (e.g. Visa ****1234, Cash), or null",
  "items": [
    {{
      "name": "line item name",
      "price": "line total paid for this item as a number",
      "category": "one of: {categories}",
      "is_impulse": true if this looks like a non-essential impulse buy \
(snacks, sweets, soft drinks, energy drinks, magazines, gadgets, junk food), \
otherwise false
    }}
  ],
  "loyalty_points": [
    {{
      "points": "number of spendable loyalty points this slip grants or \
reports as balance, as an integer",
      "label": "loyalty programme or voucher name, e.g. Smart Shopper \
points, Clicks ClubCard points, eBucks",
      "expires_at": "YYYY-MM-DD when these points lapse, or null"
    }}
  ],
  "confidence": "0.0 to 1.0 — how confident you are in the extraction"
}}

The image is usually a paper till slip, but it can also be a photo of a \
phone or laptop screen showing a digital receipt or invoice — e.g. an \
Uber or Bolt trip fare, a Takealot order summary, a subscription invoice, \
a dark-mode e-mail receipt, a QR-ticket with a payment block. Treat those \
as first-class receipts:
- Read the service name as the merchant (Uber, Bolt, Netflix, ...).
- Map its charges to line items: base fare, distance/time fare, booking \
fee, service fee, tolls, tip, delivery fee, VAT lines, etc. One line per \
charge with its amount; use the receipt's own labels as names.
- The total is the amount actually charged to the card/wallet.
- Dark mode, glare, moiré patterns and cropped screenshots are common — \
infer carefully and lower "confidence" when unsure.

Loyalty points: South African till slips commonly print spendable points \
and their expiry — Pick n Pay "Smart Shopper" points, Clicks "ClubCard" \
points, eBucks, Dis-Chem bonus points, or a voucher worth points. Capture \
EACH points block once in loyalty_points: the number of points, the \
programme name, and the expiry date printed on the slip. Do NOT put \
points into items — they are not money spent. If the slip shows no \
points, return an empty loyalty_points array.

Rules:
- Use the line total for each item (quantity x unit price), not the unit price.
- Drop non-purchase lines (subtotals, VAT, loyalty, cashier, payment info).
- Apply the store's discount/promo lines to the item above them.
- If a field is unreadable, use null (or an empty items array).\
"""

TEXT_PROMPT_TEMPLATE = """\
You are a receipt-parsing engine for a budgeting app. The text below was \
pasted by the user and is a digital receipt, invoice or order \
confirmation — for example an Uber or Bolt trip fare e-mail, an online \
order summary, a subscription invoice or a till-slip copy. Return ONLY a \
JSON object (no markdown, no prose) with exactly this shape:

{{
  "merchant": "store or service name, or null",
  "date": "purchase date as YYYY-MM-DD (convert any format/timezone), or null",
  "total": "final amount charged as a number, or null",
  "channel": "Physical_Store or Online_Ecommerce (prefer Online_Ecommerce \
for app trips, e-mail receipts and online orders)",
  "cashier": "cashier/teller name if shown, else null",
  "branch": "store branch if shown, else null",
  "slip_number": "transaction/invoice/order number, or null",
  "payment_method": "payment method line (e.g. Visa ****1234, Cash), or null",
  "items": [
    {{
      "name": "line item or charge name",
      "price": "line total paid for this item as a number",
      "category": "one of: {categories}",
      "is_impulse": true if this looks like a non-essential impulse buy, \
otherwise false
    }}
  ],
  "confidence": "0.0 to 1.0 — how confident you are in the extraction"
}}

Rules:
- Map service charges to line items: base fare, distance fare, booking \
fee, service fee, tolls, tip, delivery fee, VAT, subscription plan, etc.
- Currency markers (R, ZAR, $, €) are not part of the number.
- Drop non-purchase lines (totals, balances, payment metadata).
- Loyalty points (Smart Shopper, ClubCard, eBucks, …) go in the \
loyalty_points array with their printed expiry date — never into items.\
- If a field is not present, use null (or an empty items array).\
"""


@dataclass
class ParsedItem:
    name: str
    price: float
    category: str | None = None
    is_impulse: bool = False


@dataclass
class ParsedLoyalty:
    """A spendable-points block read off a slip (Smart Shopper, ClubCard…)."""

    points: int
    label: str = 'Points'
    expires_at: str | None = None


@dataclass
class ParsedReceipt:
    raw_text: str
    merchant_name: str | None = None
    purchase_date: str | None = None
    total_amount: float | None = None
    channel_type: str | None = None
    cashier: str | None = None
    branch: str | None = None
    slip_number: str | None = None
    payment_method: str | None = None
    items: list[ParsedItem] = field(default_factory=list)
    loyalty: list[ParsedLoyalty] = field(default_factory=list)
    confidence: float = 0.0
    engine: str = 'tesseract'
    notes: list[str] = field(default_factory=list)


def _read_bytes(file) -> bytes:
    if isinstance(file, bytes):
        return file
    if hasattr(file, 'read'):
        data = file.read()
        if hasattr(file, 'seek'):
            file.seek(0)
        return data
    with open(file, 'rb') as f:
        return f.read()


def _gemini_extract(data: bytes, mime_type: str, category_names: list[str], api_key: str | None = None) -> dict:
    """Call Gemini with the raw photo and parse its JSON reply.

    Automatic retries with growing backoff absorb transient 429/5xx
    responses — the free tier's per-minute rate limit and Google's
    occasional "high demand" 503 spikes — before degrading to OCR."""
    api_key = api_key or getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY not configured')

    model = getattr(settings, 'GEMINI_MODEL', DEFAULT_GEMINI_MODEL)
    categories = ', '.join(category_names[:30]) if category_names else 'Groceries, Transport, Fast Food, Other'
    prompt = PROMPT_TEMPLATE.format(categories=categories)

    body = {
        'contents': [{
            'parts': [
                {'text': prompt},
                {'inline_data': {'mime_type': mime_type, 'data': base64.b64encode(data).decode()}},
            ]
        }],
        'generationConfig': {
            'temperature': 0.1,
            'response_mime_type': 'application/json',
        },
    }

    resp = None
    retry_delays = (2, 5, 10)
    for attempt in range(len(retry_delays) + 1):
        try:
            resp = requests.post(
                GEMINI_ENDPOINT.format(model=model),
                params={'key': api_key},
                headers={'Content-Type': 'application/json'},
                json=body,
                timeout=45,
            )
        except requests.RequestException:
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
                continue
            raise
        if resp.status_code in (429,) or resp.status_code >= 500:
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
                continue
        break

    if resp is None or resp.status_code >= 400:
        detail = resp.text[:200] if resp is not None else 'no response'
        code = resp.status_code if resp is not None else 0
        raise RuntimeError(f'Gemini HTTP {code}: {detail}')

    payload = resp.json()
    text = ''.join(
        part.get('text', '')
        for part in payload.get('candidates', [{}])[0].get('content', {}).get('parts', [])
    )
    # The API is asked for JSON-only but be tolerant of stray fences anyway.
    text = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def _mime_from_name(name: str) -> str:
    name = (name or '').lower()
    if name.endswith('.png'):
        return 'image/png'
    if name.endswith(('.webp',)):
        return 'image/webp'
    if name.endswith(('.heic', '.heif')):
        return 'image/heic'
    return 'image/jpeg'


def verify_gemini_key(api_key: str) -> tuple[bool, str]:
    """Check a candidate Gemini API key by listing models (free, no tokens).

    Returns (ok, message). ok=True means Google accepted the key. A network
    failure returns ok=False with a transient-error message so the caller
    doesn't store an unverified key on a flaky connection.
    """
    try:
        resp = requests.get(
            'https://generativelanguage.googleapis.com/v1beta/models',
            params={'key': api_key, 'pageSize': 1},
            timeout=15,
        )
    except requests.RequestException:
        return False, 'Could not reach Google to verify the key. Check your connection and try again.'
    if resp.status_code == 200:
        return True, 'Connected — your scans will use your own Gemini key.'
    if resp.status_code in (400, 401, 403):
        return False, 'Google rejected that key. Double-check you copied the whole key from AI Studio.'
    return False, f'Google answered HTTP {resp.status_code} while verifying the key. Try again shortly.'


def _parsed_from_gemini(raw: dict, user_key_hint: str | None = None) -> ParsedReceipt:
    """Map a successful Gemini reply onto a ParsedReceipt."""
    items = [
        ParsedItem(
            name=str(i.get('name', 'Item'))[:255],
            price=round(float(i.get('price') or 0), 2),
            category=(i.get('category') or None),
            is_impulse=bool(i.get('is_impulse')),
        )
        for i in (raw.get('items') or [])
        if i.get('name')
    ]
    total = raw.get('total')
    channel = raw.get('channel')
    return ParsedReceipt(
        raw_text=json.dumps(raw, indent=2),
        merchant_name=raw.get('merchant'),
        purchase_date=raw.get('date'),
        total_amount=round(float(total), 2) if total is not None else None,
        channel_type=channel if channel in ('Physical_Store', 'Online_Ecommerce') else None,
        cashier=raw.get('cashier'),
        branch=raw.get('branch'),
        slip_number=raw.get('slip_number'),
        payment_method=raw.get('payment_method'),
        items=items,
        loyalty=_loyalty_from_raw(raw),
        confidence=float(raw.get('confidence') or 0.8),
        engine='gemini',
        notes=['Read with your own Gemini key.'] if user_key_hint else [],
    )


def analyze_receipt(file, category_names: list[str] | None = None, user_key: str | None = None) -> ParsedReceipt:
    """Extract structured receipt data: Gemini first, Tesseract fallback.

    user_key (BYOK): when the requesting user has connected their own
    Gemini key it takes priority over the server's shared key, so their
    scans bill against their own free tier instead of the app's quota.
    """
    data = _read_bytes(file)
    notes: list[str] = []

    if user_key:
        try:
            raw = _gemini_extract(
                data,
                _mime_from_name(getattr(file, 'name', '')),
                category_names or [],
                api_key=user_key,
            )
            parsed = _parsed_from_gemini(raw, user_key_hint='user')
            return parsed
        except Exception as exc:  # noqa: BLE001 — a broken user key must never block a scan
            logger.warning('User Gemini key failed, falling back: %s', exc)
            notes.append('Your connected Gemini key could not read this slip — used the built-in engine instead.')

    if getattr(settings, 'GEMINI_API_KEY', ''):
        try:
            raw = _gemini_extract(
                data,
                _mime_from_name(getattr(file, 'name', '')),
                category_names or [],
                api_key=settings.GEMINI_API_KEY,
            )
            parsed = _parsed_from_gemini(raw)
            parsed.notes = notes
            return parsed
        except Exception as exc:  # noqa: BLE001 — any Gemini failure degrades to OCR
            logger.warning('Gemini receipt extraction failed, falling back to Tesseract: %s', exc)
            notes.append('AI read failed — used on-device OCR instead.')
    else:
        notes.append('Scanned with on-device OCR (no AI key configured).')

    # --- Tesseract fallback ------------------------------------------------
    try:
        legacy = _tesseract_parse(data)
    except Exception as exc:  # noqa: BLE001 — missing binary / unreadable image
        # Degrade to an empty draft rather than crash: the frontend falls
        # back to manual entry with a clean message.
        logger.warning('Tesseract fallback unavailable: %s', exc)
        notes.append('No OCR engine available on this server — please add the receipt manually.')
        return ParsedReceipt(raw_text='', confidence=0.0, engine='tesseract', notes=notes)
    identity = extract_slip_identity(legacy.raw_text)
    return ParsedReceipt(
        raw_text=legacy.raw_text,
        merchant_name=legacy.merchant_name,
        purchase_date=legacy.purchase_date,
        total_amount=legacy.total_amount,
        channel_type=None,
        cashier=identity.get('cashier'),
        branch=identity.get('branch'),
        slip_number=identity.get('slip_number'),
        payment_method=identity.get('payment_method'),
        items=[ParsedItem(name=i.name, price=i.price) for i in legacy.items],
        loyalty=_fallback_loyalty_parse(legacy.raw_text),
        confidence=0.45,
        engine='tesseract',
        notes=notes,
    )


# --- Digital receipts (pasted text) -----------------------------------------

_DATE_PATTERNS = [
    re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b'),
    re.compile(r'\b(\d{1,2})[/\.](\d{1,2})[/\.](\d{4})\b'),
    re.compile(r'\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b', re.I),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}

_MONEY_RE = re.compile(r'(?:R|ZAR|\$|€|£)\s?(\d[\d,]*(?:\.\d{1,2})?)', re.I)

_POINTS_LINE_RE = re.compile(r'\b(points?|pts|ebucks)\b', re.I)
_LOYALTY_PROGRAMS = ('smart shopper', 'clubcard', 'ebucks', 'baby club', 'live better', 'bonus points')


def _date_from_match(m: re.Match) -> str | None:
    """Convert a _DATE_PATTERNS match to ISO YYYY-MM-DD, or None."""
    groups = m.groups()
    if len(groups) != 3:
        return None
    if '-' in m.group(0):  # YYYY-MM-DD
        return m.group(0)
    if not groups[1].isdigit():  # 14 Sep 2026 (month name)
        month = _MONTHS.get(groups[1][:3].lower())
        if month:
            return f'{groups[2]}-{month:02d}-{int(groups[0]):02d}'
        return None
    if len(groups[0]) == 4:  # YYYY/MM/DD mis-detect guard
        return None
    try:
        return f'{groups[2]}-{int(groups[1]):02d}-{int(groups[0]):02d}'  # DD/MM/YYYY
    except ValueError:
        return None


def _loyalty_from_raw(raw: dict) -> list[ParsedLoyalty]:
    """Map the AI reply's loyalty_points array onto ParsedLoyalty objects."""
    out: list[ParsedLoyalty] = []
    for entry in (raw.get('loyalty_points') or []):
        try:
            points = int(float(entry.get('points') or 0))
        except (TypeError, ValueError):
            continue
        if points <= 0:
            continue
        out.append(ParsedLoyalty(
            points=points,
            label=str(entry.get('label') or 'Points')[:255],
            expires_at=entry.get('expires_at') or None,
        ))
        if len(out) >= 5:
            break
    return out


def _fallback_loyalty_parse(text: str) -> list[ParsedLoyalty]:
    """Regex pass for loyalty points when no AI key is configured (or the
    AI read failed). Conservative: only lines that clearly talk about
    points, preferring known South African programme names for the label
    and an 'expires' mention (same or next line) for the expiry date."""
    out: list[ParsedLoyalty] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if not _POINTS_LINE_RE.search(line):
            continue
        label = 'Points'
        lowered = line.lower()
        for program in _LOYALTY_PROGRAMS:
            if program in lowered:
                label = program.title()
                break
        # Strip any date from the line first so "30 Sep 2026" doesn't read
        # as points, then look for the balance in what remains.
        balance_source = line
        for pattern in _DATE_PATTERNS:
            m = pattern.search(balance_source)
            while m:
                balance_source = balance_source[: m.start()] + ' ' + balance_source[m.end() :]
                m = pattern.search(balance_source)
        numbers = [int(n) for n in re.findall(r'(?<![.,\d])\d{1,9}(?![\d])', balance_source)]
        numbers = [n for n in numbers if 0 < n <= 999999]
        if not numbers:
            continue  # expiry/balance-carrying line without a balance
        # Expiry: date in this line or the two lines after an "expir…" hint.
        window = ' '.join(lines[idx:idx + 3])
        if not re.search(r'expir|valid until|lapse', window, re.I):
            window = line
        expiry = None
        for pattern in _DATE_PATTERNS:
            m = pattern.search(window)
            if m:
                expiry = _date_from_match(m)
                if expiry:
                    break
        out.append(ParsedLoyalty(points=numbers[-1], label=label, expires_at=expiry))
        if len(out) >= 5:
            break
    return out


def _fallback_text_parse(text: str) -> dict:
    """Regex pass over pasted receipt text for when no Gemini key exists.

    Deliberately conservative: it fills the total/date/merchant when they
    are clearly present and leaves everything else to the review form.
    """
    total = None
    # Prefer explicit total markers, fall back to the largest money amount.
    for line in text.splitlines():
        if re.search(r'\btotal\b|\bamount\s+(?:due|paid)\b|\bcharged\b', line, re.I):
            found = _MONEY_RE.search(line)
            if found:
                total = found.group(1)
                break
    if total is None:
        candidates = [float(m.group(1).replace(',', '')) for m in _MONEY_RE.finditer(text)]
        total = f'{max(candidates):.2f}' if candidates else None

    date = None
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        date = _date_from_match(m)
        if date:
            break

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    merchant = None
    for known in ('uber', 'bolt', 'takealot', 'netflix', 'spotify', 'mr d', 'checkers', 'woolworths', 'pnp', 'dischem'):
        if known in text.lower():
            merchant = known.title().replace('Mr D', 'Mr D')
            break
    if merchant is None and lines:
        merchant = lines[0][:60]

    items = []
    for line in lines:
        found = _MONEY_RE.search(line)
        if not found:
            continue
        name = _MONEY_RE.sub('', line).strip(' -:•	')
        if not name or len(name) < 2:
            continue
        items.append({'name': name[:255], 'price': round(float(found.group(1).replace(',', '')), 2)})
    items = items[:30]

    return {
        'merchant': merchant,
        'date': date,
        'total': round(float(total), 2) if total is not None else None,
        'channel': 'Online_Ecommerce',
        'items': items,
        'confidence': 0.5 if items or total else 0.0,
    }


def analyze_receipt_text(text: str, category_names: list[str] | None = None, user_key: str | None = None) -> ParsedReceipt:
    """Parse pasted digital-receipt text (Uber/Bolt fare e-mails, order
    summaries, invoice copies). Gemini when configured, regex fallback
    otherwise — the feature always returns a draft the user can correct.

    user_key (BYOK): the requesting user's own Gemini key, tried first.
    """
    text = (text or '').strip()
    notes: list[str] = []

    if not text:
        return ParsedReceipt(raw_text='', confidence=0.0, engine='gemini', notes=['No text provided.'])

    if user_key:
        try:
            api_key = user_key
            model = getattr(settings, 'GEMINI_MODEL', DEFAULT_GEMINI_MODEL)
            categories = ', '.join(category_names[:30]) if category_names else 'Groceries, Transport, Fast Food, Other'
            body = {
                'contents': [{'parts': [{'text': TEXT_PROMPT_TEMPLATE.format(categories=categories) + '\n\nReceipt text:\n' + text[:20000]}]}],
                'generationConfig': {'temperature': 0.1, 'response_mime_type': 'application/json'},
            }
            resp = requests.post(
                GEMINI_ENDPOINT.format(model=model),
                params={'key': api_key},
                headers={'Content-Type': 'application/json'},
                json=body,
                timeout=45,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f'Gemini HTTP {resp.status_code}: {resp.text[:200]}')
            payload = resp.json()
            reply = ''.join(
                part.get('text', '')
                for part in payload.get('candidates', [{}])[0].get('content', {}).get('parts', [])
            )
            reply = re.sub(r'^```(?:json)?|```$', '', reply.strip(), flags=re.MULTILINE).strip()
            raw = json.loads(reply)
            parsed = _parsed_from_gemini(raw, user_key_hint='user')
            parsed.raw_text = text
            return parsed
        except Exception as exc:  # noqa: BLE001 — a broken user key must never block a paste-parse
            logger.warning('User Gemini key failed on text extraction, falling back: %s', exc)
            notes.append('Your connected Gemini key could not read this receipt — used the built-in engine instead.')

    if getattr(settings, 'GEMINI_API_KEY', ''):
        try:
            api_key = settings.GEMINI_API_KEY
            model = getattr(settings, 'GEMINI_MODEL', DEFAULT_GEMINI_MODEL)
            categories = ', '.join(category_names[:30]) if category_names else 'Groceries, Transport, Fast Food, Other'
            body = {
                'contents': [{'parts': [{'text': TEXT_PROMPT_TEMPLATE.format(categories=categories) + '\n\nReceipt text:\n' + text[:20000]}]}],
                'generationConfig': {'temperature': 0.1, 'response_mime_type': 'application/json'},
            }
            resp = requests.post(
                GEMINI_ENDPOINT.format(model=model),
                params={'key': api_key},
                headers={'Content-Type': 'application/json'},
                json=body,
                timeout=45,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f'Gemini HTTP {resp.status_code}: {resp.text[:200]}')
            payload = resp.json()
            reply = ''.join(
                part.get('text', '')
                for part in payload.get('candidates', [{}])[0].get('content', {}).get('parts', [])
            )
            reply = re.sub(r'^```(?:json)?|```$', '', reply.strip(), flags=re.MULTILINE).strip()
            raw = json.loads(reply)

            items = [
                ParsedItem(
                    name=str(i.get('name', 'Item'))[:255],
                    price=round(float(i.get('price') or 0), 2),
                    category=(i.get('category') or None),
                    is_impulse=bool(i.get('is_impulse')),
                )
                for i in (raw.get('items') or [])
                if i.get('name')
            ]
            total = raw.get('total')
            channel = raw.get('channel')
            return ParsedReceipt(
                raw_text=text,
                merchant_name=raw.get('merchant'),
                purchase_date=raw.get('date'),
                total_amount=round(float(total), 2) if total is not None else None,
                channel_type=channel if channel in ('Physical_Store', 'Online_Ecommerce') else None,
                cashier=raw.get('cashier'),
                branch=raw.get('branch'),
                slip_number=raw.get('slip_number'),
                payment_method=raw.get('payment_method'),
                items=items,
                loyalty=_loyalty_from_raw(raw),
                confidence=float(raw.get('confidence') or 0.8),
                engine='gemini',
                notes=notes,
            )
        except Exception as exc:  # noqa: BLE001 — degrade to the regex pass
            logger.warning('Gemini text extraction failed, using regex fallback: %s', exc)
            notes.append('AI read failed — used a basic text parser instead.')
    else:
        notes.append('Parsed with the built-in text parser (no AI key configured).')

    raw = _fallback_text_parse(text)
    items = [ParsedItem(name=i['name'], price=i['price']) for i in raw['items']]
    return ParsedReceipt(
        raw_text=text,
        merchant_name=raw['merchant'],
        purchase_date=raw['date'],
        total_amount=raw['total'],
        channel_type=raw['channel'],
        items=items,
        loyalty=_fallback_loyalty_parse(text),
        confidence=raw['confidence'],
        engine='tesseract',
        notes=notes,
    )


def extract_slip_identity(text: str) -> dict:
    """Best-effort regex read of slip-identity lines (cashier, branch, slip
    number, payment) from raw receipt text — used by the tesseract/no-AI
    fallback path where the structured prompt never ran."""
    identity: dict = {}
    m = re.search(r'cashier\s*[:#]?\s*([A-Za-z][A-Za-z .\'-]{1,40})', text, re.IGNORECASE)
    if m:
        identity['cashier'] = m.group(1).strip()
    m = re.search(r'(?:branch|store)\s*(?:no\.?|#)?\s*[:#]?\s*([A-Za-z0-9 .&\'-]{2,60})', text, re.IGNORECASE)
    if m:
        identity['branch'] = m.group(1).strip()
    m = re.search(r'(?:trans(?:action)?|invoice|slip|receipt|doc)\s*(?:no\.?|#|num(?:ber)?)\s*[:#]?\s*([A-Za-z0-9/-]{3,40})', text, re.IGNORECASE)
    if m:
        identity['slip_number'] = m.group(1).strip()
    m = re.search(r'((?:visa|mastercard|amex|american express|maestro|debit|credit|cheque)\s*\**\s*\d{4}|cash|snapscan|zapper|eft|masterpass)', text, re.IGNORECASE)
    if m:
        identity['payment_method'] = m.group(1).strip()
    return identity
