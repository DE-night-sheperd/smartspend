-- One-off hardening for the SmartSpend Supabase project.
-- Safe to run repeatedly (idempotent).
--
-- 1. Enable Row Level Security on every app table with NO policies.
--    Django connects as the table owner (postgres role via the pooler), and
--    owners bypass RLS — so the app keeps working exactly as before. But
--    Supabase's auto-generated REST/GraphQL APIs (which expose tables to
--    anyone with the project's public anon key) return ZERO rows once RLS is
--    enabled without policies. This is the single most important protection:
--    without it, anyone with the publishable key could read emails and
--    password hashes straight from the API.
--
-- 2. Create a user_overview view for quick human inspection in the dashboard,
--    and expose it (read-only) to the authenticated API role.

-- ------------------------------------------------------------------
-- 1. RLS on every public table (no policies = API sees nothing).
-- ------------------------------------------------------------------
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'core_user', 'core_category', 'core_store', 'core_receipt',
    'core_receiptitem', 'core_loyaltypoints', 'core_logincode',
    'django_session', 'django_admin_log'
  ]
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

-- ------------------------------------------------------------------
-- 2. Human-friendly overview view (safe columns only).
-- ------------------------------------------------------------------
CREATE OR REPLACE VIEW public.user_overview
WITH (security_invoker = true) AS
SELECT
  u.user_id,
  u.email,
  u.first_name,
  u.last_name,
  u.phone,
  u.monthly_budget_limit,
  u.date_joined,
  u.last_login,
  u.is_active,
  (SELECT count(*) FROM core_receipt r WHERE r.user_id = u.user_id) AS receipt_count,
  u.password IS NOT NULL AND u.password <> '' AS has_password,
  left(u.password, 20) || '…' AS password_preview
FROM core_user u;

-- Read access for Supabase's API roles, restricted to the view only.
GRANT SELECT ON public.user_overview TO anon, authenticated;
REVOKE ALL ON public.core_user FROM anon;
