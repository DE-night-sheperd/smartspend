"""Automated budget-adjustment suggestions ("cut X to save Y").

Rule-based and deterministic — no AI call needed, so advice is instant and
free. It reads the same data the audit PDF uses (receipts + line items for
one month) and produces concrete, ranked moves:

  1. Category cuts     — the biggest non-essential categories, trimmed 25%.
  2. Impulse audit     — skipping flagged impulse buys, biggest first.
  3. Pacing check      — mid-month projection vs. the budget, with the
                         daily trim that gets back under it.
  4. Store frequency   — many small trips to one store (batching saves).
  5. Trend comparison  — this month vs. the previous one.

Every suggestion carries `potential_saving` so the UI can total them and
show what staying on-script is actually worth. Suggestions never invent
data: each one is backed by the month's own numbers, and empty months get
no advice rather than filler.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from .models import Receipt, ReceiptItem, User

# Suggested trim for a non-essential category — enough to matter, small
# enough to be doable ("cut a quarter of your takeaway spend", not "quit food").
CATEGORY_CUT_FRACTION = Decimal('0.25')

# A category must be at least this big for a 25% cut to feel worth it.
MIN_CATEGORY_SUGGESTION = Decimal('50')

# Frequency nudge: this many separate receipts at one store in one month
# means the user is popping in rather than shopping.
STORE_TRIP_THRESHOLD = 3

SuggestionKind = str  # 'category_cut' | 'impulse' | 'pacing' | 'store_frequency' | 'trend'


def _r(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'))


def build_budget_advice(user: User, year: int, month: int) -> dict:
    """Compute the suggestion list for one calendar month of the user's
    spending. Pure read — nothing is saved, nothing is emailed."""
    receipts = list(
        Receipt.objects.filter(user=user, purchase_date__year=year, purchase_date__month=month)
        .select_related('store')
    )
    items = list(
        ReceiptItem.objects.filter(
            receipt__user=user, receipt__purchase_date__year=year, receipt__purchase_date__month=month
        ).select_related('category', 'receipt', 'receipt__store')
    )

    budget = user.monthly_budget_limit or Decimal('0')
    total_spent = sum((r.total_amount for r in receipts), start=Decimal('0'))
    suggestions: list[dict] = []

    # --- 1. Category cuts: trim the biggest non-essential spend -----------
    cat_totals: dict[str, Decimal] = {}
    for i in items:
        if not i.category.is_essential:
            cat_totals[i.category.category_name] = (
                cat_totals.get(i.category.category_name, Decimal('0')) + i.line_total
            )
    for name, total in sorted(cat_totals.items(), key=lambda kv: -kv[1]):
        saving = _r(total * CATEGORY_CUT_FRACTION)
        if saving < MIN_CATEGORY_SUGGESTION:
            continue
        suggestions.append({
            'kind': 'category_cut',
            'title': f'Trim {name} by a quarter',
            'detail': (
                f'{name} ran to R{_r(total)} this month. Shaving 25% off it — '
                f'roughly R{_r(total * Decimal("0.75"))} — keeps the habit and banks the rest.'
            ),
            'potential_saving': saving,
        })
        if sum(1 for s in suggestions if s['kind'] == 'category_cut') >= 2:
            break  # two categories is advice; five is a lecture

    # --- 2. Impulse audit: the flagged buys the user already regretted ----
    impulse_items = [i for i in items if i.is_impulse]
    if impulse_items:
        impulse_total = sum((i.line_total for i in impulse_items), start=Decimal('0'))
        biggest = max(impulse_items, key=lambda i: i.line_total)
        suggestions.append({
            'kind': 'impulse',
            'title': 'Skip the impulse buys',
            'detail': (
                f'{len(impulse_items)} impulse purchase(s) cost R{_r(impulse_total)} this month. '
                f'Skipping the biggest — {biggest.item_name} at R{_r(biggest.line_total)} — '
                f'is the single easiest saving on this list.'
            ),
            'potential_saving': _r(biggest.line_total),
        })

    # --- 3. Pacing check: where this month is heading ---------------------
    today = date.today()
    is_current_month = (year, month) == (today.year, today.month)
    if is_current_month and budget > 0 and total_spent > 0:
        day_of_month = today.day
        days_in_month = monthrange(year, month)[1]
        if day_of_month >= 2 and day_of_month < days_in_month:
            daily_pace = total_spent / day_of_month
            projected = daily_pace * days_in_month
            if projected > budget:
                over = projected - budget
                trim_per_day = over / (days_in_month - day_of_month)
                suggestions.insert(0, {
                    'kind': 'pacing',
                    'title': 'Slow down to land under budget',
                    'detail': (
                        f'At today\u2019s pace you\u2019ll finish the month around R{_r(projected)} — '
                        f'R{_r(over)} over your R{_r(budget)} budget. Spending about '
                        f'R{_r(max(Decimal("0"), daily_pace - trim_per_day))}/day for the rest of '
                        f'the month gets you back inside it.'
                    ),
                    'potential_saving': _r(over),
                })

    # --- 4. Store frequency: many small trips add up -----------------------
    store_counts: dict[str, int] = {}
    store_totals: dict[str, Decimal] = {}
    for r in receipts:
        store_counts[r.store.store_name] = store_counts.get(r.store.store_name, 0) + 1
        store_totals[r.store.store_name] = store_totals.get(r.store.store_name, Decimal('0')) + r.total_amount
    for name, count in store_counts.items():
        if count < STORE_TRIP_THRESHOLD:
            continue
        avg = store_totals[name] / count
        suggestions.append({
            'kind': 'store_frequency',
            'title': f'Batch your {name} trips',
            'detail': (
                f'{count} separate trips to {name} this month averaged R{_r(avg)} each — '
                f'top-up shopping. One planned weekly shop usually beats three impulsive ones.'
            ),
            'potential_saving': _r(avg),  # one avoided top-up trip
        })
        break  # nudge the worst offender only

    # --- 5. Trend: this month vs. last -------------------------------------
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    prev_spent = sum(
        Receipt.objects.filter(
            user=user, purchase_date__year=prev_year, purchase_date__month=prev_month
        ).values_list('total_amount', flat=True),
        start=Decimal('0'),
    )
    if prev_spent > 0 and total_spent > prev_spent:
        increase = total_spent - prev_spent
        pct = (increase / prev_spent * 100).quantize(Decimal('0.1'))
        suggestions.append({
            'kind': 'trend',
            'title': f'This month is {pct}% above last',
            'detail': (
                f'You\u2019ve spent R{_r(increase)} more than {date(prev_year, prev_month, 1):%B}. '
                f'Matching last month\u2019s total is a clean target: R{_r(prev_spent)}.'
            ),
            'potential_saving': _r(increase),
        })

    potential_total = sum((s['potential_saving'] for s in suggestions), start=Decimal('0'))
    return {
        'year': year,
        'month': month,
        'budget_limit': budget,
        'total_spent': _r(total_spent),
        'has_budget': budget > 0,
        'suggestions': suggestions,
        'potential_total_saving': _r(potential_total),
    }
