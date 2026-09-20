# SmartSpend Database Guide (Supabase Postgres)

The app's data lives in the Supabase project **smartspend** (West EU / Ireland,
`aws-1-eu-west-1.pooler.supabase.com`, database `postgres`). Django owns and
migrates the schema — never edit table structures by hand in the dashboard.

**Where to look:** Supabase dashboard → **Table Editor** (browse data) or
**SQL Editor** (run queries). A ready-made friendly view, `user_overview`, is
in the Table Editor under *Views*.

---

## The tables (what lives where)

| Table | What it holds | Key columns |
|---|---|---|
| `core_user` | **Registered users** | `email`, `password` (**hashed** — pbkdf2, never plain text), `first_name`, `last_name`, `phone`, `monthly_budget_limit`, `gemini_key_encrypted` (their own Gemini API key, encrypted), `date_joined`, `last_login` |
| `core_receipt` | Scanned/uploaded receipts | `user_id` (owner), `store_id`, `receipt_date`, `total_amount`, `receipt_image` |
| `core_receiptitem` | Line items on each receipt | `receipt_id`, `item_name`, `quantity`, `unit_price`, `total_price`, `category_id`, `is_essential` |
| `core_category` | Spending categories | `category_name`, `is_essential` (12 seeded defaults: Groceries, Transport & Fuel, …) |
| `core_store` | Shops recognized on receipts | `store_name` |
| `core_loyaltypoints` | Store loyalty points (Pick n Pay, Clicks, …) | `user_id`, `store_id`, `points`, `expiry_date` |
| `core_logincode` | One-time login codes (email OTP) | `user_id`, `code` (hashed), `channel`, `expires_at`, `consumed_at` |
| `django_session`, `django_admin_log`, `django_migrations`, `auth_group*`, `django_content_type`, `auth_permission` | Django framework internals — safe to ignore | — |

Every user-owned table links back to `core_user.user_id` (a UUID).

---

## Safety already configured

- **Row Level Security is ON for every app table with no public policies.**
  Supabase's auto-generated REST/GraphQL API (reachable by anyone with the
  project's publishable key) returns **zero rows / permission denied** —
  verified. The only way in is the Django backend, which connects as the table
  owner (owners bypass RLS).
- Passwords are stored **hashed** (Django PBKDF2-SHA256, 1,000,000 iterations).
  `gemini_key_encrypted` is encrypted at the application layer.
- `user_overview` is the one API-readable object — safe columns only, and only
  for the `authenticated` role (not anon).

---

## Copy-paste queries (SQL Editor)

**How many users do I have?**
```sql
SELECT count(*) AS total_users FROM core_user;
```

**Who signed up, newest first (the friendly view):**
```sql
SELECT email, first_name, last_name, date_joined, receipt_count
FROM user_overview
ORDER BY date_joined DESC;
```

**Full user list with hashed passwords visible:**
```sql
SELECT email, password AS password_hash, date_joined, last_login
FROM core_user
ORDER BY date_joined DESC;
```

**Receipts per user:**
```sql
SELECT u.email, count(r.receipt_id) AS receipts, coalesce(sum(r.total_amount),0) AS total_spent
FROM core_user u
LEFT JOIN core_receipt r ON r.user_id = u.user_id
GROUP BY u.email
ORDER BY receipts DESC;
```

**Most popular spending categories:**
```sql
SELECT c.category_name, count(i.item_id) AS items, coalesce(sum(i.total_price),0) AS spent
FROM core_receiptitem i
JOIN core_category c ON c.category_id = i.category_id
GROUP BY c.category_name
ORDER BY spent DESC;
```

**Loyalty points still unexpired, per user per store:**
```sql
SELECT u.email, s.store_name, lp.points, lp.expiry_date
FROM core_loyaltypoints lp
JOIN core_user u ON u.user_id = lp.user_id
JOIN core_store s ON s.store_id = lp.store_id
WHERE lp.expiry_date >= current_date
ORDER BY lp.expiry_date;
```

**Signups per day (last 30 days):**
```sql
SELECT date_joined::date AS day, count(*)
FROM core_user
WHERE date_joined >= now() - interval '30 days'
GROUP BY day ORDER BY day;
```

> Column names above match the Django-generated schema. If a query errors,
> check the exact column in **Table Editor → core_user → columns**, or run:
> ```sql
> SELECT column_name, data_type FROM information_schema.columns
> WHERE table_name = 'core_user' ORDER BY ordinal_position;
> ```
