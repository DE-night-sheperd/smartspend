"""Sign in with Apple — identity-token verification.

The frontend runs the Apple JS flow (appleid.cdn-apple.com auth script),
receives the user's identity (JWT) token, and POSTs it here. This module
verifies the token is genuinely from Apple before trusting the email
inside it:

  1. Signature — RS256 against Apple's published JWKS (fetched and
     cached by PyJWT's PyJWKClient; Apple rotates these keys).
  2. Issuer — must be https://appleid.apple.com.
  3. Audience — must match APPLE_CLIENT_ID (the Services/Bundle ID the
     login button is configured with).
  4. Expiry — standard exp check by PyJWT.

Settings:
  APPLE_CLIENT_ID — the Services ID (web) or Bundle ID (iOS) the token
                    was issued for, e.g. "com.example.smartspend.signin".
                    When unset, Apple sign-in is disabled and /api/auth/
                    apple/ answers 503 rather than trusting unverified
                    tokens.
"""
from __future__ import annotations

import logging

import jwt
from django.conf import settings

logger = logging.getLogger(__name__)

APPLE_ISSUER = 'https://appleid.apple.com'
APPLE_JWKS_URL = 'https://appleid.apple.com/auth/keys'

_jwks_client: jwt.PyJWKClient | None = None


def apple_sign_in_enabled() -> bool:
    """True when APPLE_CLIENT_ID is configured (tokens can then be verified)."""
    return bool(getattr(settings, 'APPLE_CLIENT_ID', ''))


def verify_apple_identity_token(identity_token: str) -> dict:
    """Verify an Apple identity token and return its decoded claims.

    Raises jwt.PyJWTError on any validation failure; raises RuntimeError
    when Apple sign-in is not configured. The caller only reads the email
    claim after this function returns.
    """
    client_id = getattr(settings, 'APPLE_CLIENT_ID', '')
    if not client_id:
        raise RuntimeError('APPLE_CLIENT_ID not configured')

    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(APPLE_JWKS_URL, cache_keys=True)

    signing_key = _jwks_client.get_signing_key_from_jwt(identity_token)
    return jwt.decode(
        identity_token,
        signing_key.key,
        algorithms=['RS256'],
        audience=client_id,
        issuer=APPLE_ISSUER,
        options={'require': ['exp', 'iss', 'aud', 'sub']},
    )
