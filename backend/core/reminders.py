"""Automated user notifications: points-expiry warnings and budget alerts.

Shared by the daily cron entrypoint (`POST /api/cron/daily/`, protected by
CRON_SECRET_KEY) and the management commands, so GitHub Actions / any
scheduler gets the exact same behaviour with zero drift.

Emails ride the existing Resend transport. Every alert is deduped through
the BudgetAlert ledger (one row per user/kind/period) so a cron that runs
twice — or both the cron and a manual trigger — never double-sends.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .budget_emails import send_budget_alert_email
from .emails import send_loyalty_expiry_email
from .models import BudgetAlert, LoyaltyPoints, Receipt

logger = logging.getLogger(__name__)


def _user_model():
    from django.contrib.auth import get_user_model

    return get_user_model()


def _already_sent(user_id, kind: str, period: str = '') -> bool:
    return BudgetAlert.objects.filter(user_id=user_id, kind=kind, period=period).exists()


def _mark_sent(user_id, kind: str, period: str = '', detail: str = '') -> None:
    BudgetAlert.objects.get_or_create(
        user_id=user_id, kind=kind, period=period, defaults={'detail': detail[:255]}
    )


def send_points_expiry_reminders(days_left: int) -> int:
    """Email every user whose points expire exactly `days_left` days from
    now (7 = a week's warning, 1 = last chance). Returns users notified."""
    today = timezone.now().date()
    expiry = today + timedelta(days=days_left)
    expiring = (
        LoyaltyPoints.objects.filter(expires_at=expiry)
        .select_related('user', 'store')
        .order_by('user_id')
    )
    kind = BudgetAlert.Kind.POINTS_7DAY if days_left >= 7 else BudgetAlert.Kind.POINTS_1DAY
    by_user: dict = {}
    for row in expiring:
        by_user.setdefault(row.user_id, []).append(row)

    notified = 0
    for user_id, rows in by_user.items():
        if _already_sent(user_id, kind):
            continue
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
        try:
            send_loyalty_expiry_email(user.email, payload)
        except Exception:  # noqa: BLE001 — one bad address must not stop the rest
            logger.warning('points reminder to %s failed', user.email, exc_info=True)
            continue
        _mark_sent(user_id, kind, detail=f'{len(payload)} block(s), {rows[0].points}+ points')
        notified += 1
    return notified


def send_budget_alerts() -> int:
    """Email users at each budget milestone: 50% spent, 80% spent, and
    budget depleted (>=100%). Each threshold fires at most once per user
    per month, and a user gets every threshold they cross (50% today,
    80% next week, over-budget at month end)."""
    today = timezone.now().date()
    month_start = today.replace(day=1)
    period = month_start.strftime('%Y-%m')

    User = _user_model()
    alerted = 0
    for user in User.objects.filter(monthly_budget_limit__gt=0):
        spent = (
            Receipt.objects.filter(user=user, purchase_date__gte=month_start)
            .aggregate(total=__import__('django').db.models.Sum('total_amount'))['total']
        )
        if not spent:
            continue
        budget = user.monthly_budget_limit
        ratio = float(spent) / float(budget)

        # Highest crossed threshold first. The first crossed tier decides
        # this run: fire it if unsent. If it was already sent, stop — a
        # higher tier having fired permanently suppresses the lower ones
        # (no noisy backfilled warnings after an over-budget email).
        thresholds = [
            (BudgetAlert.Kind.BUDGET_100, ratio >= 1, lambda: (
                f'SmartSpend: you are over your {period} budget',
                f'You have spent R{spent:,.2f} of your R{budget:,.2f} budget for {period} '
                f'— R{float(spent) - float(budget):,.2f} over. Time for a no-spend stretch.'
            )),
            (BudgetAlert.Kind.BUDGET_80, ratio >= 0.8, lambda: (
                f'SmartSpend: 80% of your {period} budget is gone',
                f'You have spent R{spent:,.2f} of your R{budget:,.2f} budget for {period}. '
                f'R{float(budget) - float(spent):,.2f} left for the rest of the month.'
            )),
            (BudgetAlert.Kind.BUDGET_50, ratio >= 0.5, lambda: (
                f'SmartSpend: halfway — 50% of your {period} budget is spent',
                f'You have spent R{spent:,.2f} of your R{budget:,.2f} budget for {period} '
                f'— halfway there, with R{float(budget) - float(spent):,.2f} still to spend.'
            )),
        ]
        kind, subject, body = '', '', ''
        for candidate, crossed, message in thresholds:
            if not crossed:
                continue
            if _already_sent(user.user_id, candidate, period):
                break  # this (highest crossed) tier already fired — lower tiers stay silent
            kind = candidate
            subject, body = message()
            break
        if not kind:
            continue
        try:
            send_budget_alert_email(user.email, subject, body)
        except Exception:  # noqa: BLE001
            logger.warning('budget alert to %s failed', user.email, exc_info=True)
            continue
        _mark_sent(user.user_id, kind, period, detail=f'spent {spent} of {budget}')
        alerted += 1
    return alerted


def run_daily() -> dict:
    """Everything the daily cron should do, in one call. Returns a summary
    dict the cron endpoint logs and returns to the caller."""
    return {
        'points_reminders_7day': send_points_expiry_reminders(7),
        'points_reminders_1day': send_points_expiry_reminders(1),
        'budget_alerts': send_budget_alerts(),
    }
