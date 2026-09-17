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
- Full CRUD on stores/categories/receipts/receipt-items via DRF ViewSets
- Per-user data isolation enforced in the ORM (`get_queryset` filters by
  `request.user`) — the application-layer equivalent of the Postgres
  Row-Level Security policies in the spec. The original RLS SQL is kept in
  `backend/infra/rls_policies.sql` for when you deploy to Supabase/Postgres.
- **OCR extraction** (`core/ocr.py`, stage 2 of the pipeline): upload a
  receipt photo to `POST /api/receipts/ocr_extract/` and get back a
  best-guess merchant name, date, total, and line items via Tesseract OCR +
  regex heuristics. Nothing is saved at this point — the frontend pre-fills
  the verification form and the user corrects it (stage 3).
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
- Auth context + protected routes
- Login / register pages
- **Dashboard**: hero budget thermometer that fills up live, count-up stat
  cards, a monthly spend vs. impulse-spend bar chart (recharts), and a
  "Print audit PDF" button that pulls the real PDF from the backend
- **Receipts page**: "📷 Scan receipt" button uploads a photo, shows a
  scanning-sweep animation, calls `ocr_extract`, and pre-fills the
  verification form (store, date, total, line items) for the user to check
  and correct before saving — or skip straight to "+ Add manually" for typed
  entry. Each line item can be flagged as an impulse buy and assigned a
  category. Saving triggers a confetti burst and a toast.

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

**Tesseract OCR** must be installed system-wide for the `/ocr_extract/`
endpoint to work — `pytesseract` is just a Python wrapper around it:
- Ubuntu/Debian/Kali: `sudo apt install tesseract-ocr`
- macOS: `brew install tesseract`
Without it, everything else still works — `ocr_extract` will just return a
422 and the frontend falls back to manual entry.

### Frontend
```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL, defaults to localhost:8000/api
npm run dev
```
App runs at `http://localhost:5173`.

## Still worth building next
- **Mobile client**: the spec calls for Flutter; this repo gives you a web
  client instead. The Django API underneath is framework-agnostic either way.
- **Bounding-box OCR**: the current parser reads full-page text and applies
  regex heuristics (good enough for most receipts, per the spec's own framing
  of "multi-pass text extraction, coordinate alignment"). A production
  version would use Tesseract's bounding-box output or a cloud OCR API for
  more layout-aware parsing (aligning columns, handling multi-column
  receipts).
- **PostGIS merchant location tracking**, mentioned in the technical spec,
  isn't implemented — `Store` has no location field yet.
- **Automated budget-adjustment suggestions**: the audit PDF reports current
  spend, but doesn't yet generate specific "cut X to save Y" suggestions.

# smartspend
