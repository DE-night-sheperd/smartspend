"""SMS delivery for login codes.

Preferred transport: Telnyx (https://telnyx.com) HTTP API — a single
TELNYX_API_KEY env var and no SDK dependency (same approach as the email
transport in emails.py). Falls back to printing the code in the API
response (dev mode) when no key is configured.

Env vars:
  TELNYX_API_KEY    — Telnyx API key (KEY...)
  TELNYX_FROM       — the Telnyx phone number/alphanumeric sender ID that
                      sends the SMS (e.g. +27821234567)
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TELNYX_ENDPOINT = 'https://api.telnyx.com/v2/messages'


def send_login_code_sms(to_phone: str, code: str) -> str:
    """Send a 6-digit login code by SMS. Returns 'telnyx' on success.

    Raises on hard failures so callers can return a clean 502 instead of
    pretending the message was sent.
    """
    api_key = getattr(settings, 'TELNYX_API_KEY', '')
    if not api_key:
        raise RuntimeError('TELNYX_API_KEY not configured')

    body = {
        'to': to_phone,
        'from': settings.TELNYX_FROM,
        'text': (
            f'Your SmartSpend login code is {code}. '
            'It expires in 10 minutes and can only be used once.'
        ),
    }
    resp = requests.post(
        TELNYX_ENDPOINT,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json=body,
        timeout=10,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'Telnyx rejected the SMS: HTTP {resp.status_code} {resp.text[:200]}')
    return 'telnyx'
