"""Budget warning emails (80% used / over budget).

Same transport selection as the other senders: Resend when configured,
Django console backend otherwise. Kept separate from emails.py's login-code
sender so each notification type stays self-contained.
"""
from __future__ import annotations

from django.conf import settings


def send_budget_alert_email(to_email: str, subject: str, body: str) -> str:
    """Send a budget warning. Returns 'resend' or 'console'. Raises on
    provider failures so the caller can log and retry on the next run."""
    text = f'{body}\n\n— SmartSpend'
    html = f"""\
<div style="font-family:ui-monospace,Consolas,monospace;max-width:480px;margin:0 auto;padding:24px 0;">
  <h2 style="letter-spacing:-0.5px;">SmartSpend</h2>
  <p>{body}</p>
  <p style="color:#5c6a5f;">Adjust your budget any time in Settings.</p>
</div>"""

    api_key = getattr(settings, 'RESEND_API_KEY', '')
    if api_key:
        import requests

        resp = requests.post(
            'https://api.resend.com/emails',
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
            raise RuntimeError(f'Resend rejected the email: HTTP {resp.status_code} {resp.text[:200]}')
        return 'resend'

    from django.core.mail import send_mail

    send_mail(subject, text, settings.RESEND_FROM, [to_email], html_message=html, fail_silently=False)
    return 'console'
