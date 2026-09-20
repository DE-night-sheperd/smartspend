"""Symmetric encryption for per-user secrets (BYOK Gemini keys).

Keys are encrypted at rest with Fernet (AES-128-CBC + HMAC), using a key
derived from Django's SECRET_KEY. Rotating SECRET_KEY therefore invalidates
stored keys — they decrypt to '' and the app treats the user as
disconnected (they just reconnect with a fresh key).
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    """Encrypt a secret for storage. Returns '' for empty input."""
    if not value:
        return ''
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a stored secret. Returns '' when missing or undecryptable
    (e.g. after a SECRET_KEY rotation) so callers treat it as absent."""
    if not value:
        return ''
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return ''


def mask_secret(value: str) -> str:
    """Human-safe hint, e.g. 'AIzaSy…9f2c' — never enough to reuse."""
    if not value:
        return ''
    return f'{value[:6]}…{value[-4:]}' if len(value) > 14 else '…'
