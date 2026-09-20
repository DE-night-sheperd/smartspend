"""WhatsApp delivery for login codes.

Uses the same Telnyx account as the SMS transport (one TELNYX_API_KEY),
posting to the Messages API with type=whatsapp. Real delivery also needs
a WhatsApp-enabled sender in the Telnyx dashboard (Messaging → WhatsApp
business profile) — until that exists the login view falls back to dev
mode (the code rides back in the response) exactly like SMS without a
key.

Env vars:
  TELNYX_API_KEY     — Telnyx API key (KEY...), shared with the SMS channel
  TELNYX_WHATSAPP_FROM — the WhatsApp-enabled sender, e.g. +27821234567
                         (falls back to TELNYX_FROM when unset)
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TELNYX_MESSAGES_ENDPOINT = 'https://api.telnyx.com/v2/messages'


def send_login_code_whatsapp(to_phone: str, code: str) -> str:
    """Send a 6-digit login code as a WhatsApp message.

    Returns 'telnyx' on success. Raises on hard failures so callers can
    return a clean 502 instead of pretending the message was sent.
    """
    api_key = getattr(settings, 'TELNYX_API_KEY', '')
    if not api_key:
        raise RuntimeError('TELNYX_API_KEY not configured')

    sender = getattr(settings, 'TELNYX_WHATSAPP_FROM', '') or getattr(settings, 'TELNYX_FROM', '')
    body = {
        'type': 'whatsapp',
        'to': to_phone,
        'from': sender,
        'text': (
            f'Your SmartSpend login code is {code}. '
            'It expires in 10 minutes and can only be used once.'
        ),
    }
    resp = requests.post(
        TELNYX_MESSAGES_ENDPOINT,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json=body,
        timeout=10,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f'Telnyx rejected the WhatsApp message: HTTP {resp.status_code} {resp.text[:200]}'
        )
    return 'telnyx'
