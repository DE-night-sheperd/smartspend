"""Email delivery for login codes.

Preferred transport: Resend (https://resend.com) HTTP API — a single
RESEND_API_KEY env var and no SDK dependency. Falls back to Django's
console email backend (dev) when the key is missing, and to SMTP via
Django's regular EMAIL_* settings when configured.

Env vars:
  RESEND_API_KEY   — Resend API key (re_...)
  RESEND_FROM      — From address, e.g. "SmartSpend <login@yourdomain.com>"
                     (defaults to Resend's dev onboarding address)
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = 'https://api.resend.com/emails'


class EmailDeliveryError(RuntimeError):
    """The email provider refused the send. `hint` carries a user-facing
    explanation of the misconfiguration (empty when there's nothing more
    specific to say than the generic retry message)."""

    def __init__(self, message: str, hint: str = ''):
        super().__init__(message)
        self.hint = hint


def _resend_failure(resp) -> EmailDeliveryError:
    """Turn a Resend error response into an EmailDeliveryError, with an
    actionable hint for the known gotcha: an account with no verified
    domain may only email Resend-approved test inboxes (Resend testing
    mode), which reads to users as 'codes never arrive'. Testing mode
    shows up as 403 with 'testing' in the body, or as a 422 telling the
    caller to use the testing address instead of real domains."""
    try:
        detail = str(resp.json().get('message', '')) or resp.text[:200]
    except Exception:  # noqa: BLE001 — any body shape beats no message
        detail = resp.text[:200]
    lowered = detail.lower()
    testing_mode = (
        (resp.status_code == 403 and 'testing' in lowered)
        or (resp.status_code == 422 and ('testing email' in lowered or 'resend.dev' in lowered))
    )
    hint = ''
    if testing_mode:
        hint = (
            'Email delivery is not fully set up: the sending domain is not verified, '
            'so codes can only reach Resend test inboxes (delivered@resend.dev). '
            'Verify a domain in the Resend dashboard (Domains) to deliver to everyone.'
        )
    return EmailDeliveryError(f'Resend rejected the email: HTTP {resp.status_code} {detail}', hint)


def _deliver(to_email: str, subject: str, text: str, html: str) -> str:
    """Send one email through Resend when configured, else the console.
    Returns 'resend' or 'console'. Raises on hard failures so callers can
    return a clean 502 instead of pretending the mail was sent."""
    api_key = getattr(settings, 'RESEND_API_KEY', '')
    if api_key:
        resp = requests.post(
            RESEND_ENDPOINT,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'from': settings.RESEND_FROM,
                'to': [to_email],
                'subject': subject,
                'text': text,
                'html': html,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            raise _resend_failure(resp)
        return 'resend'

    # Dev fallback: print to the runserver console so local flows are testable.
    from django.core.mail import send_mail
    send_mail(subject, text, settings.RESEND_FROM, [to_email], html_message=html, fail_silently=False)
    return 'console'


def send_login_code_email(to_email: str, code: str) -> str:
    """Send a 6-digit login code. Returns 'resend' or 'console' (which
    transport was used)."""
    subject = 'Your SmartSpend login code'
    text = (
        f'Your SmartSpend login code is {code}.\n\n'
        'It expires in 10 minutes and can only be used once. '
        'If you did not request it, you can ignore this email.'
    )
    html = f"""\
<div style="font-family:ui-monospace,Consolas,monospace;max-width:480px;margin:0 auto;padding:24px 0;">
  <h2 style="letter-spacing:-0.5px;">SmartSpend</h2>
  <p>Your login code is:</p>
  <p style="font-size:32px;font-weight:700;letter-spacing:8px;background:#f6efd9;padding:12px 18px;border-radius:8px;text-align:center;">{code}</p>
  <p style="color:#5c6a5f;">It expires in 10 minutes and can only be used once.</p>
</div>"""
    return _deliver(to_email, subject, text, html)


def send_password_reset_email(to_email: str, code: str) -> str:
    """Send a 6-digit password-reset code. Same code model and single-use
    rules as the login code; the wording tells the user what it's for so a
    reset email can't be mistaken for a login attempt."""
    subject = 'Your SmartSpend password reset code'
    text = (
        f'Your SmartSpend password reset code is {code}.\n\n'
        'It expires in 10 minutes and can only be used once. '
        'If you did not ask to reset your password, ignore this email — '
        'your password stays as it was.'
    )
    html = f"""\
<div style="font-family:ui-monospace,Consolas,monospace;max-width:480px;margin:0 auto;padding:24px 0;">
  <h2 style="letter-spacing:-0.5px;">SmartSpend</h2>
  <p>You asked to reset your password. Your reset code is:</p>
  <p style="font-size:32px;font-weight:700;letter-spacing:8px;background:#f6efd9;padding:12px 18px;border-radius:8px;text-align:center;">{code}</p>
  <p style="color:#5c6a5f;">It expires in 10 minutes and can only be used once. Not you? Ignore this email and your password stays unchanged.</p>
</div>"""
    return _deliver(to_email, subject, text, html)


def send_loyalty_expiry_email(to_email: str, rows: list[dict]) -> str:
    """Warn a user that loyalty points are about to expire.

    rows: [{store_name, label, points, expires_at, days_left}]. Returns
    'resend' or 'console' like the login-code sender.
    """
    lines = [
        f"- {row['points']} {row['label']} at {row['store_name']}"
        f" — expires {row['expires_at']} ({row['days_left']} day{'s' if row['days_left'] != 1 else ''} left)"
        for row in rows
    ]
    subject = 'Your SmartSpend points are about to expire'
    text = (
        'Spend these before they lapse:\n\n' + '\n'.join(lines) +
        '\n\nOpen SmartSpend > Points to see everything you can still use.'
    )
    html_rows = ''.join(
        f"<li>{row['points']} <b>{row['label']}</b> at {row['store_name']} — "
        f"expires {row['expires_at']} ({row['days_left']} day{'s' if row['days_left'] != 1 else ''} left)</li>"
        for row in rows
    )
    html = f"""\
<div style="font-family:ui-monospace,Consolas,monospace;max-width:480px;margin:0 auto;padding:24px 0;">
  <h2 style="letter-spacing:-0.5px;">SmartSpend</h2>
  <p>Spend these points before they lapse:</p>
  <ul>{html_rows}</ul>
  <p style="color:#5c6a5f;">Open SmartSpend &rarr; Points to see everything you can still use.</p>
</div>"""

    api_key = getattr(settings, 'RESEND_API_KEY', '')
    if api_key:
        resp = requests.post(
            RESEND_ENDPOINT,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'from': settings.RESEND_FROM,
                'to': [to_email],
                'subject': subject,
                'text': text,
                'html': html,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            raise _resend_failure(resp)
        return 'resend'

    from django.core.mail import send_mail
    send_mail(subject, text, settings.RESEND_FROM, [to_email], html_message=html, fail_silently=False)
    return 'console'
