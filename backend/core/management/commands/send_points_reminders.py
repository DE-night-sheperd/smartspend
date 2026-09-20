"""Email users whose loyalty points are about to expire.

Cron-friendly (run daily, e.g. 07:00):

    python manage.py send_points_reminders

Sends one email per user listing every points block that expires in
exactly 7 days (a week's warning) or exactly 1 day (last chance).
Delivery goes through Resend when RESEND_API_KEY is set, otherwise to
the console email backend so the command is testable in dev.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.emails import send_loyalty_expiry_email
from core.models import LoyaltyPoints

User = get_user_model()

WARNINGS = {7: 'a week', 1: 'a day'}


class Command(BaseCommand):
    help = 'Email users whose loyalty points expire in 7 days or 1 day.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        notified = 0
        for days_left in WARNINGS:
            expiry = today + timedelta(days=days_left)
            expiring = (
                LoyaltyPoints.objects.filter(expires_at=expiry)
                .select_related('user', 'store')
                .order_by('user_id')
            )
            by_user: dict = {}
            for row in expiring:
                by_user.setdefault(row.user_id, []).append(row)
            for rows in by_user.values():
                user = rows[0].user
                if not user.email:
                    continue
                payload = [
                    {
                        'store_name': r.store.store_name,
                        'label': r.label or 'points',
                        'points': r.points,
                        'expires_at': r.expires_at,
                        'days_left': days_left,
                    }
                    for r in rows
                ]
                transport = send_loyalty_expiry_email(user.email, payload)
                notified += 1
                self.stdout.write(
                    f'{user.email}: {len(payload)} block(s) expiring in {WARNINGS[days_left]} via {transport}'
                )
        if not notified:
            self.stdout.write('Nothing expiring within the warning windows.')
