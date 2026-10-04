# SmartSpend MySQL — Operations & Queries Reference
==================================================

📁 LOCAL CONNECTION
------------------
Engine  : MySQL / MariaDB 11.8
Host    : 127.0.0.1
Port    : 3307
Socket  : /home/de_night_shepherd/Desktop/smartspend/mysql_data/mysql.sock
DB name : smartspend
User    : smartspend_user
Pass    : smartspend_pass_2026

Django creds for .env (already set in backend/.env):
    MYSQL_HOST=127.0.0.1
    MYSQL_PORT=3307
    MYSQL_DB=smartspend
    MYSQL_USER=smartspend_user
    MYSQL_PASSWORD=smartspend_pass_2026
    MYSQL_UNIX_SOCKET=/home/de_night_shepherd/Desktop/smartspend/mysql_data/mysql.sock


╔══════════════════════════════════════════════════════════════════╗
║  WAY 1:  MYSQL CLI — raw SQL                                  ║
╚══════════════════════════════════════════════════════════════════╝

$ cd ~/Desktop/smartspend
$ SOCKET="$PWD/mysql_data/mysql.sock"
$ mysql --socket=$SOCKET -u smartspend_user -p'smartspend_pass_2026' smartspend

Now you are at the `MariaDB [smartspend]>` prompt.

# Run the pre-written demo (INSERT → UPDATE → DELETE → reports):
    $ mysql --socket=$SOCKET -u smartspend_user -p'smartspend_pass_2026' --table smartspend < demo_queries.sql

COMMON SQL SNIPPETS
-----------------

-- List all tables
    SHOW TABLES;

-- Describe a table (schema)
    DESCRIBE core_user;
    DESCRIBE core_receipt;

   👇 Shortcut: `DESC core_receiptitem;`

═══════════════════════════════════════════════════════════════
  1. READ / QUERY:  Users
═══════════════════════════════════════════════════════════════

-- All users (clean):
    SELECT user_id, email, first_name, last_name,
           monthly_budget_limit, date_joined
    FROM core_user ORDER BY date_joined DESC;

-- One user by email:
    SELECT * FROM core_user WHERE email = 'john@example.com'\G

-- Users with receipts (INNER JOIN):
    SELECT u.email, u.monthly_budget_limit, COUNT(r.receipt_id)
    FROM core_user u
    JOIN core_receipt r ON r.user_id = u.user_id
    GROUP BY u.user_id;

═══════════════════════════════════════════════════════════════
  2. CREATE: Insert
═══════════════════════════════════════════════════════════════

-- New user (Django-managed password hash; password normally.  If you INSERT a user manually,
-- use Django to avoid this format or the `PBKDF2 hash so Django generates. For manual
-- testing use `User.objects.create_user()` — but for SQL testing only:

    INSERT INTO core_user
      (user_id, password, email, first_name, last_name, phone,
       monthly_budget_limit, gemini_key_encrypted,
       is_staff, is_active, is_superuser, is_guest, login_count,
       date_joined, created_at)
    VALUES
      (UUID(),
       'pbkdf2_sha256$100000$saltstring$base64hashstringhere=',
       'new@example.com', 'New', 'User', '+27820001111',
       6000.00, '', 0, 1, 0, 0, 0, NOW(), NOW());

-- New store:
    INSERT INTO core_store (store_name, channel_type, created_at)
    VALUES ('Makro', 'Physical_Store', NOW());

-- New receipt (link to existing user + store):
    SET @uid = (SELECT user_id FROM core_user WHERE email='john@example.com');
    SET @sid = (SELECT store_id FROM core_store WHERE store_name='Makro');
    INSERT INTO core_receipt
      (user_id, store_id, purchase_date, total_amount, source_type,
       branch_name, cashier_name, slip_number, payment_method, verified,
       original_text, created_at)
    VALUES (@uid, @sid, CURDATE(), 1250.00, 'upload',
            'Makro Cape Gate', 'T. M.', 'MK-9900', 'Credit Card', 0,
            'Makro receipt raw text...', NOW());
    SET @rid = LAST_INSERT_ID();  -- keep for line items!

-- Receipt line item:
    INSERT INTO core_receiptitem (receipt_id, category_id, item_name, unit_price, quantity)
      SELECT @rid, category_id, 'Bulk Rice 10kg', 189.99, 1 FROM core_category
      WHERE category_name = 'Groceries';

═══════════════════════════════════════════════════════════════
  3. UPDATE
═══════════════════════════════════════════════════════════════

-- Change a user's budget:
    UPDATE core_user SET monthly_budget_limit = 20000.00
    WHERE email = 'john@example.com';

-- Mark all unreceipts as verified:
    UPDATE core_receipt SET verified = 1 WHERE verified = 0;

-- Bulk  across all grocery items priced below R10:
    UPDATE core_receiptitem SET unit_price = ROUND(unit_price * 1.05, 2)
    WHERE category_id = (SELECT category_id FROM core_category WHERE category_name='Groceries')
      AND unit_price < 10;

═══════════════════════════════════════════════════════════════
  4. DELETE
═══════════════════════════════════════════════════════════════

-- Delete one user's specific receipt (and cascade deletes items):
    DELETE FROM core_receipt
     WHERE user_id = (SELECT user_id FROM core_user WHERE email='john@example.com')
       AND slip_number = 'SLIP-99887';

-- Delete all unverified receipts older than 1 month:
    DELETE FROM core_receipt
     WHERE verified = 0
       AND purchase_date < DATE_SUB(CURDATE(), INTERVAL 1 MONTH);

-- Delete a user (CASCADE removes their receipts/items/points):
    DELETE FROM core_user WHERE email='john@example.com';

═══════════════════════════════════════════════════════════════
  5. REPORTS  (the useful stuff!
═══════════════════════════════════════════════════════════════

-- Category spend per user, current month):
    SELECT
      CONCAT(u.first_name, ' ', u.last_name) AS user_name,
      c.category_name,
      COUNT(ri.item_id)                     AS items,
      FORMAT(SUM(ri.unit_price * ri.quantity), 2) AS spent
    FROM core_user u
    JOIN core_receipt r      ON r.user_id = u.user_id
    JOIN core_receiptitem ri ON ri.receipt_id = r.receipt_id
    JOIN core_category c     ON c.category_id = ri.category_id
    WHERE r.purchase_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
    GROUP BY u.user_id, c.category_name
    ORDER BY u.email, spent DESC;

-- Budget % used per user this month:
    SELECT
      u.email,
      CONCAT('R', FORMAT(u.monthly_budget_limit,0)) AS budget,
      CONCAT('R', FORMAT(COALESCE(SUM(r.total_amount),0),0)) AS spent,
      CONCAT(FORMAT(
        CASE WHEN u.monthly_budget_limit > 0
        THEN (COALESCE(SUM(r.total_amount),0) / u.monthly_budget_limit * 100
        ELSE 0 END, 1), '%') AS pct_used
    FROM core_user u
    LEFT JOIN core_receipt r
           ON r.user_id = u.user_id
          AND EXTRACT(YEAR_MONTH FROM r.purchase_date) = EXTRACT(YEAR_MONTH FROM CURDATE())
    GROUP BY u.user_id;

-- Impulse purchases ranking:
    SELECT
      u.email,
      COUNT(ri.item_id) AS impulse_items,
      FORMAT(SUM(ri.unit_price * ri.quantity), 2) AS wasted
    FROM core_user u
    JOIN core_receipt r      ON r.user_id = u.user_id
    JOIN core_receiptitem ri ON ri.receipt_id = r.receipt_id
    WHERE ri.is_impulse = 1
    GROUP BY u.user_id
    ORDER BY wasted DESC;

-- Loyalty points expiring in the next 30 days:
    SELECT
      u.email, s.store_name, lp.points, lp.label,
      lp.expires_at,
      DATEDIFF(lp.expires_at, CURDATE()) AS days_left
    FROM core_loyaltypoints lp
    JOIN core_user u  ON u.user_id = lp.user_id
    JOIN core_store s ON s.store_id = lp.store_id
    WHERE lp.expires_at BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
    ORDER BY days_left ASC;

-- Top stores by total revenue:
    SELECT
      s.store_name,
      COUNT(r.receipt_id) AS visits,
      FORMAT(SUM(r.total_amount), 2) AS revenue
    FROM core_store s
    JOIN core_receipt r ON r.store_id = s.store_id
    GROUP BY s.store_id
    ORDER BY revenue DESC
    LIMIT 10;


╔══════════════════════════════════════════════════════════════════╗
║  WAY 2:  DJANGO ORM SHELL — type-safe Python queries           ║
╚══════════════════════════════════════════════════════════════════╝

$ cd ~/Desktop/smartspend/backend
$ python manage.py shell          # interactive Django shell

Now Python>>> from core.models import *  # imports all models

OR run a prepared demo:
    $ python demo_orm.py    # CREATE/READ/UPDATE/DELETE demo

═══════════════════════════════════════════════════════════════
  CREATE
═══════════════════════════════════════════════════════════════

# User (Django auto-hashes password, auto-UUID):
>>> u = User.objects.create_user(
...     email='you@example.com', password='Secret123!',
...     first_name='First', last_name='Last',
...     monthly_budget_limit=Decimal('9000'))

# Store + receipt + items atomic):
>>> store, _ = Store.objects.get_or_create(
...     store_name='Spar', channel_type=Store.ChannelType.PHYSICAL)
>>> cat = Category.objects.get(category_name='Groceries')
>>> with transaction.atomic():
...     r = Receipt.objects.create(user=u, store=store,
...         purchase_date=date.today(), total_amount=Decimal('123.45'),
...         source_type=Receipt.SourceType.CAMERA,
...         branch_name='Spar Linden', cashier_name='A.B',
...         slip_number='S123', payment_method='Cash',
...         original_text='spar receipt text', verified=True)
...     ReceiptItem.objects.create(receipt=r, category=cat,
...         item_name='Milk', unit_price=Decimal('25'), quantity=2)

═══════════════════════════════════════════════════════════════
  READ  (filters, lookups)
═══════════════════════════════════════════════════════════════

>>> User.objects.get(email='you@example.com')         # single
>>> User.objects.filter(first_name__istartswith='J')  # ILIKE 'J%'
>>> Receipt.objects.filter(user=u, total_amount__gt=500)   # > 500
>>> Receipt.objects.select_related('store', 'user')[:10]  # JOINs + LIMIT 10

# Category spend via reverse FK traversal with annotate:
>>> from django.db.models import Sum, Count, F
>>> u.receipts.aggregate(total=Sum('total_amount'))
>>> (ReceiptItem.objects.filter(receipt__user=u)
...  .values(name=F('category__category_name'))
...  .annotate(spent=Sum(F('unit_price')*F('quantity')))
...  .order_by('-spent'))

═══════════════════════════════════════════════════════════════
  UPDATE
═══════════════════════════════════════════════════════════════

>>> u.monthly_budget_limit = Decimal('12000')
>>> u.save()

# Bulk:
>>> Receipt.objects.filter(user=u).update(verified=True)

═══════════════════════════════════════════════════════════════
  DELETE
═══════════════════════════════════════════════════════════════

>>> ReceiptItem.objects.filter(item_name__icontains='chocolate').delete()
>>> User.objects.filter(email='you@example.com').delete()  # CASCADE


╔══════════════════════════════════════════════════════════════════╗
║  WAY 3:  DJANGO ADMIN — point-and-click                  ║
╚══════════════════════════════════════════════════════════════════╝

Start Django backend:
    $ cd ~/Desktop/smartspend && ./start_dev_stack.sh

Then open:
    http://127.0.0.1:8000/admin/

Log in with:
    Email   : admin@smartspend.local
    Pass   : Admin123!

From the Admin panel you can browse, search, edit, delete any row in any
of the tables.  Click "core" app → Users, Receipts, Categories, Stores, etc.


╔══════════════════════════════════════════════════════════════════╗
║  HELPER TOOL FILES (already on disk)                               ║
╚══════════════════════════════════════════════════════════════════╝

File                                                                   What it does
─────────────────────────────────────────────────────────────────────────────────────
demo_queries.sql                        Raw SQL demo script (INSERT/UPDATE/DELETE/REPORTS run it < demo_queries.sql
backend/demo_orm.py                Django ORM demo (crud + aggregates
backend/verify_mysql.py           Full integration test (35 checks – confirms CRUD on MySQL)
backend/create_admin.py        Creates/resets superuser admin@smartspend.local
SMARTSPEND_ERD.html                 Interactive ERD diagram – open in browser
start_mysql.sh                     Start just MariaDB server only
start_dev_stack.sh                 Start MariaDB + Django runserver
backend/verify_persistence.py  End-to-end HTTP API → DB proof (needs runserver running)
