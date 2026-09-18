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
the attached photo and return ONLY a JSON object (no markdown, no prose) \
with exactly this shape:

{{
  "merchant": "store name as printed, or null",
  "date": "purchase date as YYYY-MM-DD, or null",
  "total": "final amount paid as a number, or null",
  "channel": "Physical_Store or Online_Ecommerce, best guess",
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
  "confidence": "0.0 to 1.0 — how confident you are in the extraction"
}}

Rules:
- Use the line total for each item (quantity x unit price), not the unit price.
- Drop non-purchase lines (subtotals, VAT, loyalty, cashier, payment info).
- Apply the store's discount/promo lines to the item above them.
- If a field is unreadable, use null (or an empty items array).\
"""


@dataclass
class ParsedItem:
    name: str
    price: float
    category: str | None = None
    is_impulse: bool = False


@dataclass
class ParsedReceipt:
    raw_text: str
    merchant_name: str | None = None
    purchase_date: str | None = None
    total_amount: float | None = None
    channel_type: str | None = None
    items: list[ParsedItem] = field(default_factory=list)
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


def _gemini_extract(data: bytes, mime_type: str, category_names: list[str]) -> dict:
    """Call Gemini with the raw photo and parse its JSON reply.

    One automatic retry (2s backoff) absorbs transient 429/5xx responses —
    e.g. the free tier's per-minute rate limit when scans come in bursts."""
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
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
    for attempt in range(2):
        try:
            resp = requests.post(
                GEMINI_ENDPOINT.format(model=model),
                params={'key': api_key},
                headers={'Content-Type': 'application/json'},
                json=body,
                timeout=45,
            )
        except requests.RequestException:
            if attempt == 0:
                time.sleep(2)
                continue
            raise
        if resp.status_code in (429,) or resp.status_code >= 500:
            if attempt == 0:
                time.sleep(2)
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


def analyze_receipt(file, category_names: list[str] | None = None) -> ParsedReceipt:
    """Extract structured receipt data: Gemini first, Tesseract fallback."""
    data = _read_bytes(file)
    notes: list[str] = []

    if getattr(settings, 'GEMINI_API_KEY', ''):
        try:
            raw = _gemini_extract(
                data,
                _mime_from_name(getattr(file, 'name', '')),
                category_names or [],
            )
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
                items=items,
                confidence=float(raw.get('confidence') or 0.8),
                engine='gemini',
                notes=notes,
            )
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
    return ParsedReceipt(
        raw_text=legacy.raw_text,
        merchant_name=legacy.merchant_name,
        purchase_date=legacy.purchase_date,
        total_amount=legacy.total_amount,
        channel_type=None,
        items=[ParsedItem(name=i.name, price=i.price) for i in legacy.items],
        confidence=0.45,
        engine='tesseract',
        notes=notes,
    )
