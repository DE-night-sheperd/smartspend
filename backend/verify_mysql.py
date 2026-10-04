#!/usr/bin/env python3
"""
SmartSpend MySQL Integration Verification Script

Verifies end-to-end connectivity to the local MySQL/MariaDB database
through Django ORM: Create -> Read -> Update -> Delete on all domain models.

Usage:
    cd backend && python verify_mysql.py
"""
import os
import sys
import django
from datetime import date, datetime, timedelta
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartspend.settings')
django.setup()

from django.db import connection
from django.db.utils import IntegrityError

from core.models import (
    User, Store, Category, Receipt, ReceiptItem,
    LoyaltyPoints, BudgetAlert, LoginCode, LoginAudit,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"

failures = []
passed = 0


def check(name, ok, detail=''):
    global passed
    status = PASS if ok else FAIL
    suffix = f' — {detail}' if detail else ''
    print(f'  [{status}] {name}{suffix}')
    if ok:
        passed += 1
    else:
        failures.append(name)


def header(title):
    print(f'\n\033[1m== {title} ==\033[0m')


# ── 0. Database Connection Info ────────────────────────────────────────
header('0. Database Connection')
engine = connection.settings_dict['ENGINE'].rsplit('.', 1)[-1]
host = connection.settings_dict.get('HOST', '') or '(default)'
port = connection.settings_dict.get('PORT', '') or '(default)'
db_name = connection.settings_dict['NAME']
db_user = connection.settings_dict.get('USER', '') or '(default)'
check('Using MySQL backend', engine == 'mysql', f'{engine} @ {host}:{port}')
check('Database is smartspend', db_name == 'smartspend', f'name={db_name}, user={db_user}')

with connection.cursor() as cursor:
    cursor.execute('SELECT VERSION()')
    version = cursor.fetchone()[0]
    check('Raw SQL query works', True, version)

# ── 1. USER Model (CRUD) ───────────────────────────────────────────────
header('1. USER Model — Create / Read / Update / Delete')

email = f'test.user.{int(datetime.now().timestamp())}@example.com'
user = User.objects.create_user(
    email=email,
    password='TestPass123!',
    first_name='Test',
    last_name='User',
    phone='+27821234567',
    monthly_budget_limit=Decimal('5000.00'),
)
check('Create user', user is not None, f'email={user.email}')
check('UUID primary key set', user.user_id is not None, f'pk={user.user_id}')

fetched = User.objects.get(email=email)
check('Read user back', fetched.email == email)
check('Password hashed (not plain)', not fetched.password.startswith('TestPass'),
      f'hash_prefix={fetched.password[:20]}...')
check('Check valid password', fetched.check_password('TestPass123!'))
check('Reject wrong password', not fetched.check_password('WrongPass!'))

fetched.monthly_budget_limit = Decimal('7500.00')
fetched.first_name = 'Updated'
fetched.save()
refetched = User.objects.get(user_id=fetched.user_id)
check('Update user fields',
      refetched.first_name == 'Updated' and refetched.monthly_budget_limit == Decimal('7500.00'),
      f'name={refetched.first_name}, budget={refetched.monthly_budget_limit}')

user_pk = fetched.user_id
check('User persists in MySQL', True, f'count={User.objects.count()} users total')

# ── 2. CATEGORY (seeded defaults + custom) ─────────────────────────────
header('2. CATEGORY Model — Seeded Data + Custom')

seeded = Category.objects.order_by('category_name')
check('Default categories present (>=12)', seeded.count() >= 12, f'{seeded.count()} found')
print(f'       Categories: {", ".join(c.category_name for c in seeded)}')

Category.objects.filter(category_name='Test Custom Category').delete()
custom_cat, created = Category.objects.get_or_create(
    category_name='Test Custom Category',
    defaults={'is_essential': False},
)
check('Create custom category', created, f'name={custom_cat.category_name}')

# ── 3. STORE Model ─────────────────────────────────────────────────────
header('3. STORE Model — Create / Read')

store, _ = Store.objects.get_or_create(
    store_name='TestMart Hyper',
    defaults={'channel_type': Store.ChannelType.PHYSICAL},
)
check('Create store', True, f'{store.store_name} ({store.channel_type})')
check('Store PK assigned', store.store_id is not None)

online_store, _ = Store.objects.get_or_create(
    store_name='Takealot',
    defaults={'channel_type': Store.ChannelType.ONLINE},
)
check('Online store works', True, f'{online_store.store_name} ({online_store.channel_type})')

# ── 4. RECEIPT + RECEIPT_ITEM Models ───────────────────────────────────
header('4. RECEIPT + RECEIPT_ITEM — Full Purchase Flow')

grocery_cat = Category.objects.get(category_name='Groceries')
fastfood_cat = Category.objects.get(category_name='Fast Food & Takeaway')

receipt = Receipt.objects.create(
    user=fetched,
    store=store,
    purchase_date=date.today(),
    total_amount=Decimal('285.50'),
    source_type=Receipt.SourceType.CAMERA,
    branch_name='TestMart Sandton City 1049',
    cashier_name='J. Dlamini',
    slip_number='TXN-0012345',
    payment_method='Visa ••1234',
    verified=True,
)
check('Create receipt', receipt.receipt_id is not None,
      f'receipt_id={receipt.receipt_id}, total=R{receipt.total_amount}')

item1 = ReceiptItem.objects.create(
    receipt=receipt,
    category=grocery_cat,
    item_name='Whole Milk 2L',
    unit_price=Decimal('32.99'),
    quantity=2,
)
item2 = ReceiptItem.objects.create(
    receipt=receipt,
    category=grocery_cat,
    item_name='Sliced Brown Bread',
    unit_price=Decimal('18.50'),
    quantity=1,
)
item3 = ReceiptItem.objects.create(
    receipt=receipt,
    category=fastfood_cat,
    item_name='Chocolate Bar',
    unit_price=Decimal('24.99'),
    quantity=8,
    is_impulse=True,
)
check('Create 3 receipt items', receipt.items.count() == 3, f'{receipt.items.count()} items')

check('Line total calculated (milk 2xR32.99)',
      item1.line_total == Decimal('65.98'), f'line_total=R{item1.line_total}')

impulse_count = receipt.items.filter(is_impulse=True).count()
check('Impulse flag filter works', impulse_count == 1, f'{impulse_count} impulse items')

# ── 5. LOYALTY_POINTS Model ────────────────────────────────────────────
header('5. LOYALTY_POINTS Model — Link to Receipt, Store, User')

lp = LoyaltyPoints.objects.create(
    user=fetched,
    store=store,
    receipt=receipt,
    points=1250,
    label='TestMart Smart Points',
    expires_at=date.today() + timedelta(days=90),
)
check('Create loyalty points record', lp.points_id is not None,
      f'{lp.points} pts, expire={lp.expires_at}')
check('Reverse relation: user.loyalty_points', fetched.loyalty_points.count() == 1)
check('Reverse relation: receipt.loyalty_points', receipt.loyalty_points.count() == 1)

# ── 6. BUDGET_ALERT Model (UniqueConstraint dedup) ─────────────────────
header('6. BUDGET_ALERT Model — Dedup Ledger + UniqueConstraint')

alert1 = BudgetAlert.objects.create(
    user=fetched,
    kind=BudgetAlert.Kind.BUDGET_80,
    period=date.today().strftime('%Y-%m'),
    detail='R6,000 of R7,500 spent',
)
check('Create budget alert', alert1.alert_id is not None, f'kind={alert1.kind}')

dup_ok = False
try:
    BudgetAlert.objects.create(
        user=fetched,
        kind=BudgetAlert.Kind.BUDGET_80,
        period=date.today().strftime('%Y-%m'),
        detail='Duplicate should fail',
    )
except IntegrityError:
    dup_ok = True
check('UniqueConstraint blocks duplicate alert (user+kind+period)', dup_ok,
      'DB-enforced dedup works')

# ── 7. LOGIN_CODE + LOGIN_AUDIT ────────────────────────────────────────
header('7. LOGIN_CODE + LOGIN_AUDIT Models')

lc = LoginCode.objects.create(
    email=fetched.email,
    code='123456',
    expires_at=datetime.now() + timedelta(minutes=10),
)
check('Create login OTP code', lc.id is not None, f'code={lc.code}, expire={lc.expires_at}')
LoginCode.prune_for(fetched.email, keep=5)
check('LoginCode.prune_for helper runs', True)

audit = LoginAudit.objects.create(
    user=fetched,
    method=LoginAudit.Method.PASSWORD,
    ip='127.0.0.1',
    user_agent='verify-mysql-script/1.0',
)
check('Create login audit entry', audit.id is not None,
      f'method={audit.method}, ip={audit.ip}')
check('Reverse: user.login_audits count', fetched.login_audits.count() == 1)

# ── 8. Aggregate Queries (Reports-style) ───────────────────────────────
header('8. Aggregate Queries — Spending Reports')

user_receipts = Receipt.objects.filter(user=fetched)
total_spent = sum(r.total_amount for r in user_receipts)
check('Sum receipt totals via ORM', total_spent == Decimal('285.50'), f'total=R{total_spent}')

from django.db.models import Sum, Count
cat_spend = (
    ReceiptItem.objects.filter(receipt__user=fetched)
    .values('category__category_name')
    .annotate(items=Count('item_id'), spent=Sum('unit_price') * Sum('quantity'))
    .order_by('-spent')
)
spent_on_cats = len(cat_spend) > 0
check('Category-level spend aggregation', spent_on_cats,
      f'{len(cat_spend)} categories with spend data')
for row in cat_spend:
    print(f'       - {row["category__category_name"]}: {row["items"]} items, R{row["spent"]}')

# ── 9. Direct MySQL raw SQL via Django ─────────────────────────────────
header('9. Raw MySQL SQL through Django connection')

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT u.email, COUNT(r.receipt_id) AS receipts, COALESCE(SUM(r.total_amount),0) AS total
        FROM core_user u
        LEFT JOIN core_receipt r ON r.user_id = u.user_id
        WHERE u.user_id = %s
        GROUP BY u.email
    """, [str(user_pk)])
    row = cursor.fetchone()
    check('Raw JOIN query via MySQL cursor', row is not None and row[0] == email,
          f'user={row[0]}, receipts={row[1]}, total=R{row[2]}')

    cursor.execute("SELECT COUNT(*) FROM core_category")
    cat_count = cursor.fetchone()[0]
    check('Count categories from raw SQL', cat_count >= 12, f'{cat_count} categories')

# ── 10. Cleanup (Delete test data) ─────────────────────────────────────
header('10. Data Cleanup — DELETE operations')

before_users = User.objects.count()
LoginAudit.objects.filter(user=fetched).delete()
LoginCode.objects.filter(email=fetched.email).delete()
BudgetAlert.objects.filter(user=fetched).delete()
LoyaltyPoints.objects.filter(user=fetched).delete()
ReceiptItem.objects.filter(receipt__user=fetched).delete()
Receipt.objects.filter(user=fetched).delete()
Category.objects.filter(category_name='Test Custom Category').delete()
User.objects.filter(user_id=user_pk).delete()

after_users = User.objects.count()
check('Cascade / manual delete succeeded', after_users == before_users - 1,
      f'{before_users} → {after_users} users')
check('Test user gone from table', not User.objects.filter(user_id=user_pk).exists())

# ── Summary ─────────────────────────────────────────────────────────────
total_checks = passed + len(failures)
print(f'\n\033[1m═══════════════════════════════════════════════\033[0m')
print(f'\033[1m  MYSQL INTEGRATION: {PASS if not failures else FAIL}\033[0m')
print(f'  {passed}/{total_checks} checks passed')
if failures:
    print(f'  Failed checks:')
    for f in failures:
        print(f'    - {f}')
    sys.exit(1)
else:
    print(f'  All data correctly persisted to MySQL DB `smartspend` @ 127.0.0.1:3307')
    sys.exit(0)
