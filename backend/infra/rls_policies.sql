-- Row-Level Security policies for the Supabase/Postgres deployment.
-- Django enforces the same "user can only touch their own rows" rule at the
-- application layer (see core/views.py IsOwner + get_queryset filtering).
-- Apply this SQL directly on the Postgres database so the guarantee also
-- holds for any client that talks to the DB directly (e.g. Supabase's
-- auto-generated REST/GraphQL API, or a future OCR Edge Function).

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE receipt_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_self_access ON users
    FOR ALL
    USING (auth.uid() = user_id);

CREATE POLICY user_receipts_access ON receipts
    FOR ALL
    USING (auth.uid() = user_id);

CREATE POLICY user_receipt_items_access ON receipt_items
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM receipts
            WHERE receipts.receipt_id = receipt_items.receipt_id
            AND receipts.user_id = auth.uid()
        )
    );

-- stores and categories are shared reference data (no RLS): every
-- authenticated user can read/add them, matching core/views.py.
