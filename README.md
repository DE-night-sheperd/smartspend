# SmartSpend

Starter implementation of the SmartSpend platform described in the spec docs:
Django REST Framework API (`backend/`) + React/TypeScript frontend (`frontend/`).

This covers stages 3–5 of the pipeline (verification, relational ingestion,
analytics) end-to-end. Stages 1–2 (camera capture + OCR extraction) are
stubbed as plain image/URL upload for now — see "Next steps" below.

## What's implemented

**Backend (Django + DRF)**
- Custom `User` model with UUID PK (matches the ERD's `user_id`), email login
- `Store`, `Category`, `Receipt`, `ReceiptItem` models — the exact 3NF schema
  from the spec, as Django models instead of raw Supabase DDL
- JWT auth (`djangorestframework-simplejwt`): `/api/auth/register/`,
  `/api/auth/login/`, `/api/auth/refresh/`
- Full CRUD on stores/categories/receipts/receipt-items via DRF ViewSets
- Per-user data isolation enforced in the ORM (`get_queryset` filters by
  `request.user`) — this is the application-layer equivalent of the Postgres
  Row-Level Security policies in the spec. The original RLS SQL is kept in
  `backend/infra/rls_policies.sql` for when you deploy to Supabase/Postgres.
- `GET /api/receipts/monthly_analytics/` — equivalent of the spec's
  `user_monthly_analytics` SQL view (total spend, impulse spend, budget
  variance, grouped by month)
- SQLite for local dev by default; set `POSTGRES_HOST` etc. in `.env` to
  point at Supabase Postgres instead — no code changes needed

**Frontend (React + TypeScript + Vite)**
- `axios` client with automatic JWT refresh-on-401
- Auth context + protected routes
- Login / register pages
- Dashboard page with a monthly spend vs. impulse-spend bar chart (recharts)
  — the visual equivalent of the "Monthly Financial Audit PDF"
- Receipts page: list existing receipts, and a verification-style form to
  add a receipt with line items, categories, and an "impulse buy" flag —
  mirrors the spec's CRUD Verification Layer

## Running it locally

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # edit if you want Postgres instead of SQLite
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```
API is served at `http://localhost:8000/api/`.

### Frontend
```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL, defaults to localhost:8000/api
npm run dev
```
App runs at `http://localhost:5173`.

## Next steps (not yet built)
- **OCR pipeline**: the spec calls for a Supabase Edge Function running
  Tesseract against uploaded images. That's a separate service — a good next
  step is a Django endpoint that accepts an image, shells out to (or calls an
  API for) OCR, and pre-fills a draft `Receipt` + `ReceiptItem`s for the user
  to verify, rather than requiring manual entry as it does today.
- **PDF audit export**: add a `/api/receipts/monthly_audit_pdf/` endpoint
  (e.g. with `reportlab` or `weasyprint`) that renders the same data behind
  `monthly_analytics` into a downloadable PDF, per the spec's 4 report types.
- **Image storage**: wire `image_url` to actual object storage (Supabase
  Storage, S3, or Django's own `FileField` + media storage) instead of a
  plain text field.
- **Mobile client**: the spec calls for Flutter; this repo gives you a web
  client instead. The Django API underneath is framework-agnostic either way.
# smartspend
