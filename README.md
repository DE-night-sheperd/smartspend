# SmartSpend

Full working implementation of the SmartSpend platform described in the
spec docs: Django REST Framework API (`backend/`) + React/TypeScript
frontend (`frontend/`), covering all 5 stages of the pipeline end-to-end.

## What's implemented

**Backend (Django + DRF)**
- Custom `User` model with UUID PK (matches the ERD's `user_id`), email login
- `Store`, `Category`, `Receipt`, `ReceiptItem` models — the exact 3NF schema
  from the spec, as Django models instead of raw Supabase DDL
- JWT auth (`djangorestframework-simplejwt`): `/api/auth/register/`,
  `/api/auth/login/`, `/api/auth/refresh/`
- **Passwordless email-code login** (`/api/auth/login-code/` +
  `/api/auth/verify-login-code/`): 6-digit single-use codes with a 10-minute
  TTL, max 5 wrong attempts, per-email rate limiting, and account creation on
  first login. Codes are delivered through [Resend](https://resend.com) when
  `RESEND_API_KEY` is set, or printed to the runserver console in dev
  (the response also carries `dev_code` so the UI can show it).
- Full CRUD on stores/categories/receipts/receipt-items via DRF ViewSets
  (receipts support full edit — replace line items, store, date, total — and
  delete)
- **12 default categories** seeded by migration (Groceries, Transport & Fuel,
  Fast Food & Takeaway, …) with sensible essential/non-essential flags
- **Backend test suite** (`python manage.py test core`): 16 tests covering
  email-code auth, receipt CRUD + per-user isolation, category
  match-or-create, analytics math, and default-category seeding
- Per-user data isolation enforced in the ORM (`get_queryset` filters by
  `request.user`) — the application-layer equivalent of the Postgres
  Row-Level Security policies in the spec. The original RLS SQL is kept in
  `backend/infra/rls_policies.sql` for when you deploy to Supabase/Postgres.
- **AI receipt analysis** (`core/receipt_ai.py`, stage 2 of the pipeline):
  upload a receipt photo to `POST /api/receipts/ocr_extract/` and get back a
  best-guess merchant, date, total, channel, and every line item with a
  suggested category and impulse flag. With `GEMINI_API_KEY` set, the photo
  goes to Gemini vision (`gemini-2.5-flash` by default) which reads crumpled
  photos, multi-column layouts and fine print directly. Without a key (or if
  the AI call fails), it falls back to Tesseract OCR + regex heuristics
  (`core/ocr.py`: auto-crop, contrast boost, till-slip-pattern parsing).
  The response always names its `engine` so the UI can show an honest
  "AI read" vs "OCR read" hint. Nothing is saved at this point — the
  frontend pre-fills the verification form and the user corrects it (stage 3).
- **Real image storage**: receipts have a `receipt_image` file field, served
  from `/media/` in dev; swap in S3/Supabase Storage for production by
  changing `DEFAULT_FILE_STORAGE` in settings, no other code changes needed.
- **Monthly Audit PDF** (`core/reports.py`, stage 5): `GET
  /api/receipts/monthly_audit_pdf/?year=2026&month=8` renders all four
  report types from spec section 6 — Budget Variance, Daily Spending Spike
  Timeline, Impulse & Non-Essential Spend Audit, Multi-Channel Comparison —
  as a downloadable PDF with matplotlib charts.
- `GET /api/receipts/monthly_analytics/` — the JSON equivalent of the
  spec's `user_monthly_analytics` SQL view, used to drive the dashboard chart.
- `GET /api/receipts/month_breakdown/?year=&month=` — deep-dive analytics for
  one month: daily totals, per-category and per-store totals, channel split,
  essential vs impulse spend, and the biggest single purchase.
- **Budget settings**: the user's `monthly_budget_limit` is editable on the
  Settings page (`PATCH /api/me/`) and drives the dashboard thermometer,
  variance stats, and the audit PDF.
- SQLite for local dev by default; set `POSTGRES_HOST` etc. in `.env` to
  point at Supabase Postgres instead — no code changes needed

**Frontend (React + TypeScript + Vite)**
- Visual identity: a "till receipt" theme — torn-paper cards, dot-matrix
  monospace numerals for anything money-shaped, a paper-and-ink palette. Built
  with `framer-motion` for interaction-driven animation (sliding nav
  indicator, count-up numbers, staggered card entrances, an animated budget
  thermometer) and `canvas-confetti` for a celebratory burst when you're
  under budget or save a receipt. Respects `prefers-reduced-motion`.
- `axios` client with automatic JWT refresh-on-401
- Auth context + protected routes; email-code login, password login, and
  registration pages
- **Dashboard**: hero budget thermometer that fills up live, count-up stat
  cards, daily-spend and category-donut charts for the selected month, a
  month-over-month trend chart (recharts), top categories/stores lists, and a
  "Print audit PDF" button that pulls the real PDF from the backend. A month
  switcher browses past months.
- **Receipts page**: "📷 Scan receipt" button uploads a photo, shows a
  scanning-sweep animation, calls `ocr_extract`, and pre-fills the
  verification form (store, date, total, line items) for the user to check
  and correct before saving — or skip straight to "+ Add manually" for typed
  entry. Each line item can be flagged as an impulse buy and assigned a
  category. Every receipt can be edited or deleted from its card. Saving
  triggers a confetti burst and a toast.

## Running it locally

### Backend
```bash
cd backend
python3 -m venv venv && source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
cp .env.example .env        # edit if you want Postgres instead of SQLite
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```
API is served at `http://localhost:8000/api/`.

**Tesseract OCR** must be installed system-wide for the OCR fallback to
work — `pytesseract` is just a Python wrapper around it:
- Ubuntu/Debian/Kali: `sudo apt install tesseract-ocr`
- macOS: `brew install tesseract`
Without it, scans still work when `GEMINI_API_KEY` is set (AI does the
reading); otherwise the endpoint returns a 422 and the frontend falls back
to manual entry.

### Frontend
```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL, defaults to localhost:8000/api
npm run dev
```
App runs at `http://localhost:5173`.

### API keys (backend `backend/.env`)

| Key | What it unlocks |
| --- | --- |
| `GEMINI_API_KEY` | Real AI receipt analysis — Gemini vision extracts merchant, date, total, line items, categories and impulse flags straight from the photo. Without it, scans degrade to Tesseract OCR + regex heuristics. |
| `RESEND_API_KEY` | Login codes are emailed for real. Without it, codes print to the runserver console and the API returns `dev_code` so the UI can display it. |

Both features work without keys (dev fallbacks), so the app is fully usable
out of the box.

## Still worth building next
- **Mobile client**: the spec calls for Flutter; this repo gives you a web
  client instead. The Django API underneath is framework-agnostic either way.
- **Bounding-box OCR**: the Tesseract fallback reads full-page text and
  applies regex heuristics; a production version would use bounding-box
  output or a cloud OCR API for more layout-aware parsing. With
  `GEMINI_API_KEY` set, the AI path already handles layout natively.
- **PostGIS merchant location tracking**, mentioned in the technical spec,
  isn't implemented — `Store` has no location field yet.
- **Automated budget-adjustment suggestions**: the audit PDF reports current
  spend, but doesn't yet generate specific "cut X to save Y" suggestions.
