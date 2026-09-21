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
  When a provider refuses the send (e.g. Resend's testing mode with no
  verified domain) the API returns 502 with an actionable hint instead of a
  silent generic failure — so "codes never arrive" always says why.
- **Forgot password** (`/api/auth/password-reset/` + `/verify/` + `/confirm/`):
  the same hardened code machinery — single-use, 10-minute TTL, 5 wrong
  attempts, shared 5-per-hour rate limit — used to set a new password by
  email. Unregistered addresses get the same response shape (no account
  probing), verification never burns the code, code-login accounts are told
  to sign in with a code instead, and the code is consumed only when the new
  password is actually set.
- **Passwordless SMS- and WhatsApp-code login** (`/api/auth/login-code/sms/`,
  `/api/auth/login-code/whatsapp/` + their `verify-` twins): the
  phone-number twin of the email flow — same code model, same rate limit,
  same single-use rules. Local numbers are normalized to E.164 ("082 123
  4567" → +27…), and the phone IS the identity on first login (the
  account's email is set to the normalized number; both fields are
  editable from Settings, and changing either re-issues a verification
  code to the new destination). Codes are delivered through
  [Telnyx](https://telnyx.com) (`TELNYX_API_KEY` + `TELNYX_FROM`, with
  `TELNYX_WHATSAPP_FROM` for the WhatsApp channel); without them the
  endpoints return `dev_code` so the flow stays testable in dev.
- **Sign in with Apple** (`/api/auth/apple/`): the login page loads
  Apple's JS flow and posts the identity token to the backend, which
  verifies the RS256 signature against Apple's published JWKS plus
  issuer/audience/expiry before trusting the email claim. Gated on
  `APPLE_CLIENT_ID` — unset, the button is hidden and the endpoint
  answers 503 rather than trusting unverified tokens.
- **Loyalty points tracking** (Pick n Pay Smart Shopper, Clicks ClubCard,
  eBucks, Dis-Chem): receipt extraction also reads spendable-points
  blocks and their printed expiry dates off the slip. Saving the receipt
  stores them as per-store `LoyaltyPoints` rows; the **Points page**
  (`/points`) groups what you can still spend by store, soonest expiry
  first, and flags anything lapsing within 7 days. The dashboard shows
  the same warning, and `python manage.py send_points_reminders` emails
  users whose points expire in exactly 7 days or 1 day (cron-friendly).
- **Bring-your-own Gemini key (BYOK)** (`/api/me/gemini-key/`): Google
  only issues Gemini API keys inside each user's own AI Studio account —
  there is no OAuth flow a third-party app can use to mint one — so the
  app prompts users to connect their own free key: paste it in Settings,
  it's verified against Google and stored Fernet-encrypted at rest
  (never returned by any endpoint), and from then on their scans bill to
  their quota first, falling back to the server key, then OCR. The
  dashboard nudges until connected, and disconnecting removes the key.
- **Digital receipts by paste** (`POST /api/receipts/extract_text/`):
  e-receipts that never touch paper — Uber and Bolt trip fares, online
  order summaries, invoice copies — are pasted as text and parsed into
  the same structured draft as a photo scan.
- **Backend test suite** (`python manage.py test core`): 52 tests covering
  email-, SMS-, WhatsApp- and Apple-code auth, receipt CRUD + per-user
  isolation, category match-or-create, loyalty-points extraction and
  expiry reminders, digital-receipt parsing, BYOK Gemini keys (connect/
  status/disconnect, encryption at rest, scan priority), analytics math,
  and default-category seeding
- Full CRUD on stores/categories/receipts/receipt-items via DRF ViewSets
  (receipts support full edit — replace line items, store, date, total — and
  delete)
- **12 default categories** seeded by migration (Groceries, Transport & Fuel,
  Fast Food & Takeaway, …) with sensible essential/non-essential flags
- Per-user data isolation enforced in the ORM (`get_queryset` filters by
  `request.user`) — the application-layer equivalent of the Postgres
  Row-Level Security policies in the spec. The original RLS SQL is kept in
  `backend/infra/rls_policies.sql` for when you deploy to Supabase/Postgres.
- **AI receipt analysis** (`core/receipt_ai.py`, stage 2 of the pipeline):
  upload a receipt photo to `POST /api/receipts/ocr_extract/` and get back a
  best-guess merchant, date, total, channel, and every line item with a
  suggested category and impulse flag. With `GEMINI_API_KEY` set, the photo
  goes to Gemini vision (`gemini-3.6-flash` by default) which reads crumpled
  photos, multi-column layouts and fine print directly — transient rate-limit
  errors are retried automatically. Without a key (or if the AI call fails),
  it falls back to Tesseract OCR + regex heuristics (`core/ocr.py`: auto-crop,
  contrast boost, till-slip-pattern parsing), and if no OCR binary exists the
  endpoint degrades to a clean manual-entry prompt instead of crashing.
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
- **Automated budget-adjustment suggestions** (`GET
  /api/receipts/budget_advice/?year=&month=`): concrete, ranked "cut X to
  save Y" moves computed from the month's own receipts — trims the biggest
  non-essential categories by 25%, names the biggest impulse buy to skip,
  projects the month-end landing spot mid-month and gives the daily trim
  that gets back under budget, nudges batching when one store sees 3+
  separate trips, and compares the month against the previous one. Rule-based
  and deterministic (no AI call, no key needed), it shows up as a "Ways to
  save this month" card on the dashboard and as section 5 of the audit PDF.
- **Budget settings**: the user's `monthly_budget_limit` is editable only
  from the Settings page (`PATCH /api/me/`) — registration never asks for
  it — and drives the dashboard thermometer, variance stats, and the
  audit PDF.
- SQLite for local dev by default; set `POSTGRES_HOST` etc. in `.env` to
  point at Supabase Postgres instead — no code changes needed

**Frontend (React + TypeScript + Vite)**
- Visual identity: a "till receipt" theme — torn-paper cards, dot-matrix
  monospace numerals for anything money-shaped, a paper-and-ink palette. Built
  with `framer-motion` for interaction-driven animation (sliding nav
  indicator, count-up numbers, staggered card entrances, an animated budget
  thermometer) and `canvas-confetti` for a celebratory burst when you're
  under budget or save a receipt. Respects `prefers-reduced-motion`.
- **Sound effects** (`frontend/src/lib/sounds.ts`): a synthesized WebAudio
  layer — no audio files, just oscillators and filtered noise — that fits the
  till theme: a cash-register cha-ching when confetti flies, a scanner beep
  when a slip or pasted e-receipt is read, ascending tones on sign-in and
  saved settings, a paper-tear swish on deletes, and a soft pop for PDF
  downloads. Sounds are always on by design — there is no mute option — and
  every sound degrades to a silent no-op where WebAudio is unavailable.
- **Animated public landing page at `/`** — a looping cartoon story in the
  hero: a character walks into the corner store, grabs a basket, shops the
  shelves, pays at the till, walks out, scans the paper slip with their
  phone, tosses the paper in the bin, and walks off with the receipt kept
  digitally. Fully hand-built with framer-motion keyframes (no video, no
  images), narrated by synced captions, scaled with container-query units,
  and replaced by a static final-state frame under
  `prefers-reduced-motion`. Steps, feature cards, and closing CTA follow;
  every CTA funnels into `/register` or `/login`.
- **Email or SMS code login UI** — the login page has a channel toggle:
  pick email or phone, get a 6-digit code, verify, done. Dev mode shows the
  code inline when no delivery provider is configured. "Forgot your
  password?" opens an in-page reset flow (email → code → new password) that
  rides the same countdown/resend UI.
- **Auth-gated app**: the dashboard lives at `/dashboard` and every
  authenticated route (dashboard, receipts, settings) redirects signed-out
  visitors to `/login?returnTo=<original-path>`; after sign-in they land
  exactly where they were headed. First-login (code-created) accounts go to
  Settings to set a budget. There is no unauthenticated access to app data —
  the API returns 401 without a JWT.
- `axios` client with automatic JWT refresh-on-401; API base URL defaults to
  same-origin `/api` through the Vite dev proxy, so any preview host works
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
cp .env.example .env        # VITE_API_BASE_URL (optional — /api proxy is the default)
npm run dev
```
App runs at `http://localhost:5173`. One command for both servers:
`sh ./scripts/dev.sh` (Django API on `:8000` + Vite on `${PORT:-5173}`, both
bound to `0.0.0.0`).

### API keys (backend `backend/.env`)

| Key | What it unlocks |
| --- | --- |
| `GEMINI_API_KEY` | Real AI receipt analysis — Gemini vision extracts merchant, date, total, line items, categories and impulse flags straight from the photo. Without it, scans degrade to Tesseract OCR + regex heuristics. |
| `RESEND_API_KEY` | Login codes are emailed for real. Without it, codes print to the Django runserver console and the API returns `dev_code` so the UI can display it. |
| `TELNYX_API_KEY` + `TELNYX_FROM` | SMS login codes are texted for real through Telnyx. Add `TELNYX_WHATSAPP_FROM` (a WhatsApp-enabled sender) to deliver the codes as WhatsApp messages instead. Without keys, the SMS/WhatsApp endpoints return `dev_code` so the flow stays testable. |
| `APPLE_CLIENT_ID` | Shows the "Continue with Apple" button and lets `/api/auth/apple/` verify Apple identity tokens. Unset, Apple sign-in stays hidden. |

All features work without keys (dev fallbacks), so the app is fully usable
out of the box.

## Deploying

**Frontend** — a standard Vite SPA. The repo root carries a `package.json`
and `vite.config.ts` so managed hosting can detect the Vite + React stack:
`npm run build` from the **repo root** builds the app out of `frontend/`
and emits static output to `dist/` at the root (verified: clean exit with
`index.html` + hashed assets + the PWA manifest/service worker). Static
hosts need the usual SPA history fallback so `/dashboard`, `/receipts`,
`/points` and `/settings` serve `index.html`.

**API** — the Django backend is a long-running Python process (SQLite/
Postgres, media uploads, JWT, admin), so it needs a Python host; it
cannot run inside a Node-only static builder. Deploy it to any Python
platform (or keep using the managed preview, which runs the full stack
via `sh ./scripts/dev.sh`), then build the frontend with
`VITE_API_BASE_URL=https://your-api-host/api` so the deployed app talks
to it (unset, the built app expects the API at same-origin `/api`).

**Backend production settings** (all env-driven, see `backend/.env.example`):
`DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS=<your-api-host>`,
`CORS_ALLOWED_ORIGINS=<your-frontend-origin>`, `POSTGRES_HOST/NAME/USER/
PASSWORD/PORT` for Postgres (SQLite is dev-only), plus the optional
`GEMINI_API_KEY` / `RESEND_API_KEY` / `TELNYX_*` / `APPLE_CLIENT_ID` keys —
users can now connect their own Gemini key in Settings, so the server key
is only a fallback.

**Scheduler** — the points-expiry email reminders need a daily cron (or
platform scheduler) running `python manage.py send_points_reminders`.

## Still worth building next
- **Mobile client**: the spec calls for Flutter; this repo gives you a web
  client instead. The Django API underneath is framework-agnostic either way.
- **Bounding-box OCR**: the Tesseract fallback reads full-page text and
  applies regex heuristics; a production version would use bounding-box
  output or a cloud OCR API for more layout-aware parsing. With
  `GEMINI_API_KEY` set, the AI path already handles layout natively.
- **PostGIS merchant location tracking**, mentioned in the technical spec,
  isn't implemented — `Store` has no location field yet.
