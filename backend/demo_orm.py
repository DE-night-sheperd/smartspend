#!/usr/bin/env python3
"""
SmartSpend Django ORM CRUD Demo
Run: cd backend && python demo_orm.py
"""
import os, django, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartspend.settings')
django.setup()

from decimal import Decimal
from datetime import date, timedelta

from core.models import (User, Store, Category, Receipt, ReceiptItem,
                         LoyaltyPoints, BudgetAlert)

p = lambda *a: print(*a)

p("=" * 65)
p("  SmartSpend Django ORM — CRUD + Query Demo")
p("=" * 65)

# ──  Cleanup previous demo run (idempotent) ──────────────────────────
User.objects.filter(email__startswith='sarah.').delete()

# ─────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────
p("\n✅ CREATE")

# 1. User (via Django's create_user — auto-hashes password!)
email = f"sarah.{int(time.time())}@example.com"
sarah = User.objects.create_user(
    email=email, password='Sarah$pendz1',
    first_name='Sarah', last_name='Khumalo',
    phone='+27825551212', monthly_budget_limit=Decimal('8000.00'),
)
p(f"   • User  : {sarah.email}  (UUID {sarah.user_id})")

# 2. Store
checkers, _ = Store.objects.get_or_create(
    store_name='Checkers', defaults={'channel_type': Store.ChannelType.PHYSICAL})
p(f"   • Store : {checkers.store_name}")

# 3. Receipt + 3 line items (atomic: all-or-nothing)
from django.db import transaction
with transaction.atomic():
    grocery_cat = Category.objects.get(category_name='Groceries')
    trans_cat   = Category.objects.get(category_name='Transport & Fuel')

    receipt = Receipt.objects.create(
        user=sarah, store=checkers,
        purchase_date=date.today(),
        total_amount=Decimal('456.20'),
        source_type=Receipt.SourceType.UPLOAD,
        branch_name='Checkers Northcliff',
        cashier_name='P. Nkosi', slip_number='CHQ-2026-55443',
        payment_method='Debit Card',
        original_text='Checkers Northcliff\n...demo...\nTOTAL R456.20',
        verified=True,
    )
    ReceiptItem.objects.bulk_create([
        ReceiptItem(receipt=receipt, category=grocery_cat,
                    item_name='Brown Bread 700g', unit_price=Decimal('21.99'), quantity=2),
        ReceiptItem(receipt=receipt, category=grocery_cat,
                    item_name='Cheddar Cheese 500g', unit_price=Decimal('79.95'), quantity=1),
        ReceiptItem(receipt=receipt, category=trans_cat,   is_impulse=True,
                    item_name='Mini Mocha (impulse)',   unit_price=Decimal('39.00'), quantity=1),
    ])
p(f"   • Receipt #{receipt.receipt_id}: R{receipt.total_amount} — {receipt.items.count()} line items")

# 4. Loyalty points
lp = LoyaltyPoints.objects.create(
    user=sarah, store=checkers, receipt=receipt,
    points=1150, label='Checkers Xtra Savings',
    expires_at=date.today() + timedelta(days=45),
)
p(f"   • Points: {lp.points} Xtra Savings (expire {lp.expires_at})")

# ─────────────────────────────────────────────────────────────────────
# READ (filters, lookups, aggregates)
# ─────────────────────────────────────────────────────────────────────
p("\n📖 READ & QUERY")

p("   • Fetch Sarah by email:")
u = User.objects.get(email=email)
p(f"     → {u.first_name} {u.last_name}  budget R{u.monthly_budget_limit}")

p("   • Category count + list:")
p(f"     → {Category.objects.count()} categories total")
p(f"     → Essential: {list(Category.objects.filter(is_essential=True).values_list('category_name', flat=True))}")

p("   • Sarah's receipts (select_related store — 1 query):")
for r in Receipt.objects.select_related('store').filter(user=sarah):
    total_lines = sum(i.line_total for i in r.items.all())
    p(f"     → [{r.purchase_date}] {r.store.store_name:20s}  R{r.total_amount}  "
      f"({r.items.count()} items, impulse={r.items.filter(is_impulse=True).count()})")

p("   • Sarah's spending by category (annotate + aggregate):")
from django.db.models import Sum, Count, F
qs = (ReceiptItem.objects
      .filter(receipt__user=sarah)
      .values(category_name=F('category__category_name'))
      .annotate(items=Count('item_id'),
                spent=Sum(F('unit_price') * F('quantity')))
      .order_by('-spent'))
for row in qs:
    p(f"     → {row['category_name']:25s}  {row['items']} items  R{row['spent']:>8}")

p("   • Impulse purchases (filter by related field):")
for i in ReceiptItem.objects.filter(receipt__user=sarah, is_impulse=True):
    p(f"     → ⚠ {i.item_name}: R{i.line_total}")

p("   • Total spent across all Sarah's receipts:")
total = (Receipt.objects.filter(user=sarah)
         .aggregate(total=Sum('total_amount'))['total'] or Decimal('0'))
p(f"     → R{total} lifetime")

# ─────────────────────────────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────────────────────────────
p("\n📝 UPDATE")

p("   • Sarah got a raise — bump budget to R12,000 and add phone note:")
sarah.monthly_budget_limit = Decimal('12000.00')
sarah.phone = '+27825559999'
sarah.save()
p(f"     → budget={sarah.monthly_budget_limit}  phone={sarah.phone}")

p("   • Bulk mark all 'impulse' grocery items as not-impulse (bulk UPDATE):")
updated = (ReceiptItem.objects
           .filter(receipt__user=sarah, category__category_name='Groceries')
           .update(is_impulse=False))
p(f"     → {updated} item(s) updated")

# ─────────────────────────────────────────────────────────────────────
# DELETE
# ─────────────────────────────────────────────────────────────────────
p("\n🗑️  DELETE")

p("   • Delete 1 specific line item (the mocha impulse):")
n, _ = ReceiptItem.objects.filter(
    receipt__user=sarah, item_name__contains='Mocha').delete()
p(f"     → {n} rows deleted (cascade to any child rows)")

p("   • Delete Sarah + all her rows (CASCADE via FK on_delete=CASCADE):")
n2, _ = User.objects.filter(pk=sarah.pk).delete()
p(f"     → {n2} rows deleted total (user, receipts, items, points, alerts, audits)")

p("\n" + "=" * 65)
p("  All ORM operations complete — persisted to MySQL!")
p("=" * 65)
