"""Budget warning emails (50% / 80% used / over budget).

Rides the shared provider chain from emails.py (Resend → Brevo → console),
so budget alerts reach real inboxes through whichever provider is live.
Kept as its own module so each notification type stays self-contained.
"""
from __future__ import annotations

from .emails import _deliver


def send_budget_alert_email(to_email: str, subject: str, body: str) -> str:
    """Send a budget warning. Returns the transport used ('resend',
    'brevo' or 'console'). Raises on provider failures so the caller can
    log and retry on the next run."""
    text = f'{body}\n\n— SmartSpend'
    html = f"""\
<div style="font-family:ui-monospace,Consolas,monospace;max-width:480px;margin:0 auto;padding:24px 0;">
  <h2 style="letter-spacing:-0.5px;">SmartSpend</h2>
  <p>{body}</p>
  <p style="color:#5c6a5f;">Adjust your budget any time in Settings.</p>
</div>"""
    return _deliver(to_email, subject, text, html)
