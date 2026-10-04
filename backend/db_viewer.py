#!/usr/bin/env python3
"""
SmartSpend Browser DB Viewer
============================

Start this:  cd backend && python db_viewer.py
Then open:   http://127.0.0.1:8001/

Tabs:
  • Tables & Data   — list core_* tables with row counts, live data browser
  • Schema Inspector— column types + PK/FK from information_schema
  • Custom SQL      — read-only SELECT / SHOW / DESCRIBE query runner
  • Normalization   — UNF → 1NF → 2NF → 3NF → BCNF → 4NF → 5NF proof per table
"""
import json
import os
import django
from datetime import date, datetime
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartspend.settings')
django.setup()

from django.db import connection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOST = '127.0.0.1'
PORT = 8001


def q(sql, params=None):
    """Execute a read query safely.  Passing params=None (no args) avoids
    PyMySQL interpreting literal % characters (e.g. LIKE 'core_%') as
    format-string placeholders."""
    with connection.cursor() as cur:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
        return cols, rows


def jsonable(row):
    out = []
    for v in row:
        if isinstance(v, (datetime, date)):
            out.append(v.isoformat())
        elif isinstance(v, Decimal):
            out.append(str(v))
        elif isinstance(v, bytes):
            out.append(v.hex())
        else:
            out.append(v)
    return out


def probe_column_comments_exist() -> bool:
    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT column_comment FROM information_schema.columns "
                "WHERE table_schema=DATABASE() LIMIT 1"
            )
        return True
    except Exception:
        return False


HAS_COLUMN_COMMENTS = probe_column_comments_exist()


NORMALIZATION_REPORT = {
    "core_user": {
        "pk": "user_id (UUID)",
        "FDs": [
            "user_id → email, password, first_name, last_name, phone, is_guest, monthly_budget_limit, login_count, last_login_at, gemini_key_encrypted, is_staff, is_active, is_superuser, date_joined, created_at",
            "email → user_id  (email UNIQUE UK)",
        ],
        "UNF":  {"pass": True, "note": "Every cell holds a single atomic value — no lists, CSV, repeated groups."},
        "1NF":  {"pass": True, "note": "Rows have no order meaning, PK unique, columns atomic, all non-nullable defaults supplied."},
        "2NF":  {"pass": True, "note": "PK is single-column (user_id). There cannot be a partial-key dependency on a single-attribute PK by definition."},
        "3NF":  {"pass": True, "note": "No transitive dependency: every non-key attribute (budget_limit, last_login_at, etc.) describes the user and nothing else. email is a candidate key, not a transitive step."},
        "BCNF": {"pass": True, "note": "Every nontrivial determinant is a superkey. The only LHS sides of FDs (user_id, email) are both candidate keys."},
        "4NF":  {"pass": True, "note": "No multivalued dependencies. User has one budget, one encrypted key, one email. All columns are 1:1 with user_id."},
        "5NF":  {"pass": True, "note": "Table cannot be losslessly decomposed into smaller projections. Any split loses the single-row-per-user invariant."},
    },
    "core_store": {
        "pk": "store_id (BIGINT AUTO)",
        "FDs": [
            "store_id → store_name, channel_type, created_at",
            "(store_name, channel_type) → store_id  (UniqueConstraint uniq_store_name_per_channel)",
        ],
        "UNF":  {"pass": True, "note": "Single atomic columns; channel_type is an enum choice not a CSV list."},
        "1NF":  {"pass": True, "note": "PK unique; rows unordered; atomic cells."},
        "2NF":  {"pass": True, "note": "Single-attribute PK → partial-key deps impossible by definition."},
        "3NF":  {"pass": True, "note": "No transitive dependency: both name and channel describe the store entity only. Compound UK prevents duplicates (3NF update/delete anomalies avoided)."},
        "BCNF": {"pass": True, "note": "Only determinant is store_id or the compound (name,channel); both are superkeys."},
        "4NF":  {"pass": True, "note": "No multivalued dependencies."},
        "5NF":  {"pass": True, "note": "No 3-way join decomposition possible."},
    },
    "core_category": {
        "pk": "category_id (INT AUTO)",
        "FDs": [
            "category_id → category_name, is_essential",
            "category_name → category_id, is_essential  (category_name UNIQUE UK)",
        ],
        "UNF":  {"pass": True, "note": "Atomic values, no repeating groups."},
        "1NF":  {"pass": True, "note": "PK unique, no duplicate groups."},
        "2NF":  {"pass": True, "note": "Single-attribute PK."},
        "3NF":  {"pass": True, "note": "is_essential depends directly on the category, transitively on nothing."},
        "BCNF": {"pass": True, "note": "Both determinants (category_id, category_name) are candidate keys."},
        "4NF":  {"pass": True, "note": "No MVDs; two attributes only."},
        "5NF":  {"pass": True, "note": "Cannot decompose losslessly further."},
    },
    "core_receipt": {
        "pk": "receipt_id (BIGINT AUTO)",
        "FDs": [
            "receipt_id → user_id, store_id, purchase_date, total_amount, source_type, image_url, receipt_image, cashier_name, branch_name, slip_number, payment_method, original_text, verified, created_at",
            "(store_id, slip_number, purchase_date, branch_name) → receipt_id  (weak natural key at store register)",
        ],
        "UNF":  {"pass": True, "note": "original_text is one monolithic TEXT field (verbatim slip transcription) — atomic: the entire slip is a SINGLE VALUE, not a list of items (that lives in core_receiptitem). No CSV anywhere."},
        "1NF":  {"pass": True, "note": "Atomic cells; PK unique; no repeating groups because items live in their own table (core_receiptitem)."},
        "2NF":  {"pass": True, "note": "Single-attribute PK receipt_id — partial-key deps cannot exist."},
        "3NF":  {"pass": True, "note": "total_amount used to be a derived-data 3NF violation; NOW MariaDB DB triggers trg_receiptitem_total_after_insert/update/delete recompute it from SUM(items.unit_price*quantity) on every change, so stored value can never diverge from items. branch_name describes the receipt visit (not store itself) — one store has many branches; cashier/payment/slip_number are slip-level facts."},
        "BCNF": {"pass": True, "note": "All LHS determinants are superkeys."},
        "4NF":  {"pass": True, "note": "No MVDs: user, store, cashier, branch all co-occur exactly once per receipt event."},
        "5NF":  {"pass": True, "note": "Cannot be decomposed losslessly; any projection split drops the cashier+branch+payment association."},
    },
    "core_receiptitem": {
        "pk": "item_id (BIGINT AUTO)",
        "FDs": [
            "item_id → receipt_id, category_id, item_name, unit_price, quantity, is_impulse",
            "(receipt_id, item_name) → item_id  (weak natural key per receipt)",
        ],
        "UNF":  {"pass": True, "note": "One product per row, one quantity, one category — fully atomic."},
        "1NF":  {"pass": True, "note": "No repeating groups; one row per item per receipt."},
        "2NF":  {"pass": True, "note": "Single-attribute PK item_id. If composite (receipt_id,item_name) were used it would still be 2NF because name/quantity/price are fully dependent on the whole pair."},
        "3NF":  {"pass": True, "note": "category describes the item (not a transitive step via receipt or another attribute). CHECK constraints enforce domain integrity: unit_price >= 0 AND quantity >= 1."},
        "BCNF": {"pass": True, "note": "All determinants superkeys."},
        "4NF":  {"pass": True, "note": "No MVDs."},
        "5NF":  {"pass": True, "note": "Cannot split further without losing the item→category→impulse association."},
    },
    "core_loyaltypoints": {
        "pk": "points_id (BIGINT AUTO)",
        "FDs": [
            "points_id → user_id, store_id, receipt_id, points, label, expires_at, created_at",
        ],
        "UNF":  {"pass": True, "note": "Single atomic values, label is one string."},
        "1NF":  {"pass": True, "note": "Atomic; unique PK; no repeating groups."},
        "2NF":  {"pass": True, "note": "Single-attribute PK."},
        "3NF":  {"pass": True, "note": "All attributes describe the points record directly: user owns it, store issued it, receipt sourced it, points/labels/expiry are properties of THIS award."},
        "BCNF": {"pass": True, "note": "Determinant points_id is the PK / superkey."},
        "4NF":  {"pass": True, "note": "No multivalued dependencies."},
        "5NF":  {"pass": True, "note": "Cannot be decomposed losslessly."},
    },
    "core_budgetalert": {
        "pk": "alert_id (BIGINT AUTO)",
        "FDs": [
            "alert_id → user_id, kind, period, sent_at, detail",
            "(user_id, kind, period) → alert_id  (enforced by UniqueConstraint uniq_alert_per_period)",
        ],
        "UNF":  {"pass": True, "note": "Atomic cells. period is one 'YYYY-MM' string, kind is one enum value."},
        "1NF":  {"pass": True, "note": "PK unique; no repeating groups."},
        "2NF":  {"pass": True, "note": "Single PK alert_id; natural candidate key is composite yet non-key attrs depend on ALL its columns (dedup: one alert per user+kind+period)."},
        "3NF":  {"pass": True, "note": "detail depends on user+kind+period via alert_id; no transitive step."},
        "BCNF": {"pass": True, "note": "Both alert_id and (user,kind,period) are superkeys."},
        "4NF":  {"pass": True, "note": "No MVDs."},
        "5NF":  {"pass": True, "note": "Cannot losslessly decompose."},
    },
    "core_logincode": {
        "pk": "id (BIGINT AUTO)",
        "FDs": [
            "id → email, code, created_at, expires_at, consumed_at, attempts, request_ip, request_id",
            "request_id → id  (UUID uniquely identifies the issuance)",
        ],
        "UNF":  {"pass": True, "note": "Atomic cells; code is one 6-char string not a list."},
        "1NF":  {"pass": True, "note": "No repeating groups; PK unique."},
        "2NF":  {"pass": True, "note": "Single-attribute PK."},
        "3NF":  {"pass": True, "note": "All attributes describe the OTP issuance event directly. email is NOT a key (same email gets many codes) so cannot cause a transitive dependency."},
        "BCNF": {"pass": True, "note": "Every determinant (id, request_id) is a superkey."},
        "4NF":  {"pass": True, "note": "No MVDs."},
        "5NF":  {"pass": True, "note": "Any decomposition drops the email↔code↔attempts link."},
    },
    "core_loginaudit": {
        "pk": "id (BIGINT AUTO)",
        "FDs": [
            "id → user_id, method, created_at, ip, user_agent",
        ],
        "UNF":  {"pass": True, "note": "Atomic cells; user_agent is one string (one per login)."},
        "1NF":  {"pass": True, "note": "One row per login event."},
        "2NF":  {"pass": True, "note": "Single-attribute PK."},
        "3NF":  {"pass": True, "note": "method/ip/UA all describe the login event (not the user via transitivity). They differ per row per user."},
        "BCNF": {"pass": True, "note": "Only determinant is the PK/superkey id."},
        "4NF":  {"pass": True, "note": "No multivalued dependencies."},
        "5NF":  {"pass": True, "note": "Cannot split losslessly — method+ip+ua must stay co-recorded per event."},
    },
}


class Handler(BaseHTTPRequestHandler):

    def _ok(self, body, ctype='text/html; charset=utf-8'):
        body = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._ok(json.dumps(obj, default=str), 'application/json; charset=utf-8')

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path in ('/', '/index.html'):
            return self._ok(self._render_html())

        if parsed.path == '/api/connection':
            cols, rows = q(
                "SELECT %s AS engine, %s AS host, %s AS port, %s AS db_name, "
                "VERSION() AS version, "
                "(SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()) AS total_tables",
                [
                    connection.settings_dict['ENGINE'].rsplit('.', 1)[-1],
                    connection.settings_dict.get('HOST', ''),
                    connection.settings_dict.get('PORT', ''),
                    connection.settings_dict['NAME'],
                ],
            )
            return self._json({'columns': cols, 'rows': [jsonable(r) for r in rows]})

        if parsed.path == '/api/tables':
            # Use DIV instead of / to avoid accidental Python format clashes, and
            # wrap the arithmetic in a params-free call.
            cols, rows = q(
                "SELECT t.table_name, t.table_rows, "
                "  CAST(t.data_length DIV 1024 AS DECIMAL(18,2)) AS data_kb, "
                "  CAST(t.index_length DIV 1024 AS DECIMAL(18,2)) AS index_kb, "
                "  t.create_time, t.table_collation "
                "FROM information_schema.tables t "
                "WHERE t.table_schema = DATABASE() AND t.table_name LIKE 'core_%' "
                "ORDER BY t.table_name"
            )
            return self._json({'columns': cols, 'rows': [jsonable(r) for r in rows]})

        if parsed.path == '/api/schema':
            table = qs.get('table', [''])[0]
            comment_col = "c.column_comment" if HAS_COLUMN_COMMENTS else "'' AS column_comment"
            sql = (
                "SELECT c.column_name, c.data_type, "
                "       CONCAT(c.column_type, "
                "         CASE WHEN c.is_nullable='NO' THEN ' NOT NULL' ELSE '' END, "
                "         CASE WHEN c.column_default IS NOT NULL "
                "              THEN CONCAT(' DEFAULT ', "
                "                    IF(c.column_default LIKE 'CURRENT_TIMESTAMP%%', 'CURRENT_TIMESTAMP', c.column_default)) "
                "         ELSE '' END) AS full_type, "
                "       c.column_key AS col_key, "
                "       COALESCE(kcu.constraint_name, '') AS constraint_name, "
                "       COALESCE(kcu.referenced_table_name, '') AS ref_table, "
                "       COALESCE(kcu.referenced_column_name, '') AS ref_column, "
                + comment_col + " "
                "FROM information_schema.columns c "
                "LEFT JOIN information_schema.key_column_usage kcu "
                "       ON kcu.table_schema = c.table_schema "
                "      AND kcu.table_name   = c.table_name "
                "      AND kcu.column_name  = c.column_name "
                "WHERE c.table_schema = DATABASE() "
            )
            params = []
            if table:
                sql += " AND c.table_name = %s "
                params.append(table)
            sql += " ORDER BY c.table_name, c.ordinal_position"
            cols, rows = q(sql, params)
            return self._json({'columns': cols, 'rows': [jsonable(r) for r in rows]})

        if parsed.path == '/api/data':
            table = qs.get('table', ['core_user'])[0]
            if not table.startswith('core_'):
                return self._json({'error': 'only core_* tables allowed'})
            page = max(1, int(qs.get('page', [1])[0]))
            limit = min(200, max(1, int(qs.get('limit', [20])[0])))
            offset = (page - 1) * limit

            count_cols, count_rows = q("SELECT COUNT(*) FROM `%s`" % table)
            cols, rows = q(
                "SELECT * FROM `%s` ORDER BY 1 DESC LIMIT %%s OFFSET %%s" % table,
                [limit, offset],
            )
            return self._json({
                'columns': cols,
                'rows': [jsonable(r) for r in rows],
                'total_rows': count_rows[0][0],
                'page': page, 'limit': limit,
            })

        if parsed.path == '/api/normalization':
            return self._json(NORMALIZATION_REPORT)

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b''
        body = json.loads(raw.decode() or '{}')

        if parsed.path == '/api/query':
            sql = (body.get('sql') or '').strip()
            lower = sql.lower()
            if not any(lower.startswith(k) for k in ('select', 'show', 'describe', 'explain', 'desc')):
                return self._json({'error': 'read-only — only SELECT / SHOW / DESCRIBE / EXPLAIN allowed'})
            try:
                with connection.cursor() as cur:
                    cur.execute(sql)
                    cols = [d[0] for d in cur.description] if cur.description else []
                    rows = [jsonable(list(r)) for r in cur.fetchall()]
                return self._json({'columns': cols, 'rows': rows, 'count': len(rows)})
            except Exception as exc:
                return self._json({'error': str(exc)})

        self.send_response(404)
        self.end_headers()

    def _render_html(self):
        return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartSpend DB Viewer</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6/css/all.min.css">
<style>
  body { background:#0f172a; color:#e2e8f0; }
  .card { background:#1e293b; border:1px solid #334155; border-radius:12px; }
  .tab { cursor:pointer; padding:10px 18px; border-radius:8px 8px 0 0; }
  .tab.active { background:#1e293b; color:#38bdf8; border:1px solid #334155; border-bottom-color:transparent; font-weight:600; }
  .tab:not(.active) { color:#94a3b8; }
  .tab:hover:not(.active) { color:#e2e8f0; }
  th, td { padding:8px 10px; font-size:12.5px; }
  thead th { background:#0f172a; border-bottom:1px solid #334155; color:#38bdf8; position:sticky; top:0; }
  tbody tr:nth-child(odd) { background:#0f172a60; }
  tbody tr:hover { background:#1e40af33; }
  .scroll { max-height:500px; overflow:auto; border:1px solid #334155; border-radius:8px; }
  input, select, textarea, button { font:inherit; }
  textarea, input, select { background:#0f172a; border:1px solid #334155; color:#e2e8f0; border-radius:6px; padding:8px 10px; }
  button.btn { background:#0ea5e9; color:white; padding:8px 14px; border-radius:6px; font-weight:600; }
  button.btn:hover { background:#0284c7; }
  .nf-pass { background:#064e3b; border:1px solid #10b981; color:#6ee7b7; }
  .nf-row { display:grid; grid-template-columns:repeat(8, minmax(0,1fr)); gap:6px; }
  .pill { padding:4px 6px; border-radius:6px; text-align:center; font-size:11.5px; font-weight:600; }
  .chip { padding:2px 8px; border-radius:9999px; font-size:11px; }
</style>
</head>
<body class="p-6">

<div class="max-w-[1500px] mx-auto">
  <header class="mb-6 flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-bold text-sky-400 flex items-center gap-3"><i class="fa-solid fa-database"></i> SmartSpend DB Viewer</h1>
      <p class="text-slate-400 mt-1">Browser access to local MySQL/MariaDB <code class="bg-slate-800 px-1.5 py-0.5 rounded">smartspend@127.0.0.1:3307</code></p>
    </div>
    <div id="connBadge" class="card px-4 py-2 text-sm"></div>
  </header>

  <div class="flex gap-1 mb-0">
    <div class="tab active" data-tab="tables"><i class="fa-solid fa-table-list mr-1"></i>Tables & Data</div>
    <div class="tab" data-tab="schema"><i class="fa-solid fa-diagram-project mr-1"></i>Schema Inspector</div>
    <div class="tab" data-tab="query"><i class="fa-solid fa-terminal mr-1"></i>Custom SQL Query</div>
    <div class="tab" data-tab="nf"><i class="fa-solid fa-layer-group mr-1"></i>Normalization (UNF→5NF)</div>
  </div>

  <main class="card p-6 rounded-tl-none">

    <section id="tab-tables">
      <div id="tableListWrap" class="mb-5">
        <h2 class="text-lg font-bold text-sky-300 mb-2"><i class="fa-solid fa-table mr-2"></i>All SmartSpend Tables</h2>
        <div class="scroll"><table id="tableList" class="w-full text-left"></table></div>
      </div>
      <div class="flex items-end gap-3 mb-3 flex-wrap">
        <div>
          <label class="block text-xs text-slate-400 mb-1">Browse rows from table</label>
          <select id="tableSelect"></select>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1">Rows/page</label>
          <select id="limitSelect">
            <option>10</option><option selected>20</option><option>50</option><option>100</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1">&nbsp;</label>
          <button class="btn" onclick="loadData()"><i class="fa-solid fa-rotate mr-1"></i>Refresh</button>
        </div>
        <div id="pagerInfo" class="ml-auto text-sm text-slate-400"></div>
        <button id="prevBtn" class="btn" style="background:#475569" onclick="changePage(-1)">Prev</button>
        <button id="nextBtn" class="btn" style="background:#475569" onclick="changePage(1)">Next</button>
      </div>
      <div class="scroll"><table id="dataTable" class="w-full text-left"></table></div>
    </section>

    <section id="tab-schema" class="hidden">
      <h2 class="text-lg font-bold text-sky-300 mb-3"><i class="fa-solid fa-key mr-2"></i>Column + FK Inspector</h2>
      <p class="text-slate-400 text-sm mb-3">Every column, data type, PK/UK/FK constraint, referenced table & column — from <code>information_schema</code>.</p>
      <div class="scroll"><table id="schemaTable" class="w-full text-left"></table></div>
    </section>

    <section id="tab-query" class="hidden">
      <h2 class="text-lg font-bold text-sky-300 mb-3"><i class="fa-solid fa-magnifying-glass mr-2"></i>Run SQL (read-only)</h2>
      <p class="text-slate-400 text-sm mb-3">Allowed: SELECT, SHOW, DESCRIBE, EXPLAIN. Returns live results in a table.</p>
      <div class="grid grid-cols-1 gap-3">
        <textarea id="sqlInput" rows="5" class="font-mono" placeholder="SELECT u.email, COUNT(r.receipt_id) receipts, SUM(r.total_amount) spent&#10;FROM core_user u LEFT JOIN core_receipt r ON r.user_id=u.user_id&#10;GROUP BY u.user_id ORDER BY spent DESC;"></textarea>
        <div class="flex gap-2 items-center flex-wrap">
          <button class="btn" onclick="runQuery()"><i class="fa-solid fa-play mr-1"></i>Run Query</button>
          <div id="queryInfo" class="text-sm text-slate-400"></div>
          <div class="ml-auto flex gap-2 flex-wrap text-xs">
            <button class="chip" style="background:#0c4a6e;color:#7dd3fc" onclick="fillSql(&quot;SELECT * FROM core_user ORDER BY created_at DESC LIMIT 10&quot;)">Users latest 10</button>
            <button class="chip" style="background:#0c4a6e;color:#7dd3fc" onclick="fillSql(&quot;SELECT u.email, COUNT(r.receipt_id) receipts, SUM(r.total_amount) spent FROM core_user u LEFT JOIN core_receipt r ON r.user_id=u.user_id GROUP BY u.user_id ORDER BY spent DESC&quot;)">Receipts per user</button>
            <button class="chip" style="background:#0c4a6e;color:#7dd3fc" onclick="fillSql(&quot;SELECT c.category_name, COUNT(i.item_id) items, SUM(i.unit_price*i.quantity) spent_R FROM core_receiptitem i JOIN core_category c USING(category_id) GROUP BY c.category_id ORDER BY spent_R DESC&quot;)">Spend by category</button>
            <button class="chip" style="background:#0c4a6e;color:#7dd3fc" onclick="fillSql(&quot;SELECT method, COUNT(*) n, MAX(created_at) last_seen FROM core_loginaudit GROUP BY method ORDER BY n DESC&quot;)">Login methods used</button>
            <button class="chip" style="background:#0c4a6e;color:#7dd3fc" onclick="fillSql(&quot;SHOW TRIGGERS&quot;)">Show triggers (3NF enforcement)</button>
          </div>
        </div>
      </div>
      <div class="scroll mt-4"><table id="queryTable" class="w-full text-left"></table></div>
    </section>

    <section id="tab-nf" class="hidden">
      <h2 class="text-lg font-bold text-sky-300 mb-2"><i class="fa-solid fa-check-double mr-2"></i>Normalization Compliance Report (UNF → 5NF)</h2>
      <p class="text-slate-400 text-sm mb-5">Per-table FDs (functional dependencies) plus the exact reason each normal form is satisfied.</p>
      <div id="nfWrap"></div>
    </section>

  </main>

  <footer class="text-center text-slate-500 text-xs mt-6">
    SmartSpend DB Viewer — served by <code>db_viewer.py</code> on port 8001 · connected to MySQL through Django ORM / PyMySQL
  </footer>
</div>

<script>
const API = '';
const state = { page: 1, table: 'core_user', limit: 20 };
function $(sel){ return document.querySelector(sel); }
function $$(sel){ return [...document.querySelectorAll(sel)]; }

function htmlTable(parentSelector, cols, rows, truncate=true){
  const head = '<thead><tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr></thead>';
  const body = '<tbody>' + rows.map(r => '<tr>' + r.map(v => {
    const s = v===null || v===undefined ? '<span class="text-slate-500">NULL</span>' : String(v);
    return '<td title="'+(truncate?s.replace(/"/g,'&quot;'):'')+'">' + (truncate && s.length>110 ? s.slice(0,110)+'…' : s) + '</td>';
  }).join('') + '</tr>').join('') + '</tbody>';
  $(parentSelector).innerHTML = head + body;
}

async function apiJson(url, method='GET', body){
  const opts = { method, headers: {} };
  if (body){ opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(API + url, opts);
  return r.json();
}

async function initConn(){
  const d = await apiJson('/api/connection');
  const r = d.rows[0];
  $('#connBadge').innerHTML =
    `<i class="fa-solid fa-circle-check text-emerald-400 mr-2"></i>` +
    `<div><span class="text-xs text-slate-400">Engine</span> <b>${r[0]}</b> · <span class="text-xs text-slate-400">DB</span> <b>${r[3]}</b></div>` +
    `<div class="text-xs text-slate-400">${r[4]} · ${r[5]} tables total · ${r[1]}:${r[2]}</div>`;
}

async function loadTables(){
  const d = await apiJson('/api/tables');
  htmlTable('#tableList', d.columns, d.rows);
  const names = d.rows.map(r => r[0]);
  $('#tableSelect').innerHTML = names.map(n => `<option${n===state.table?' selected':''}>${n}</option>`).join('');
  $('#tableSelect').onchange = e => { state.table = e.target.value; state.page = 1; loadData(); };
}

async function loadData(){
  $('#limitSelect').onchange = e => { state.limit = +e.target.value; state.page = 1; loadData(); };
  const d = await apiJson(`/api/data?table=${state.table}&page=${state.page}&limit=${state.limit}`);
  if (d.error){ $('#dataTable').innerHTML = `<tr><td class="text-red-400">${d.error}</td></tr>`; return; }
  htmlTable('#dataTable', d.columns, d.rows);
  const pages = Math.ceil(d.total_rows / state.limit) || 1;
  $('#pagerInfo').innerHTML = `page <b>${state.page}</b> / ${pages} · <b>${d.total_rows}</b> rows total`;
  $('#prevBtn').disabled = state.page <= 1;
  $('#nextBtn').disabled = state.page >= pages;
}
function changePage(delta){ state.page = Math.max(1, state.page + delta); loadData(); }

async function loadSchema(){
  const d = await apiJson('/api/schema');
  htmlTable('#schemaTable', d.columns, d.rows, false);
}

function fillSql(s){ $('#sqlInput').value = s; }
async function runQuery(){
  $('#queryInfo').textContent = 'running…';
  const d = await apiJson('/api/query', 'POST', { sql: $('#sqlInput').value });
  if (d.error){ $('#queryTable').innerHTML = `<tr><td class="text-red-400">ERROR: ${d.error}</td></tr>`; $('#queryInfo').textContent = ''; return; }
  htmlTable('#queryTable', d.columns, d.rows);
  $('#queryInfo').textContent = `${d.count ?? d.rows.length} row(s) returned`;
}

async function loadNf(){
  const rep = await apiJson('/api/normalization');
  const forms = ['UNF','1NF','2NF','3NF','BCNF','4NF','5NF'];
  let html = '';
  for (const [table, info] of Object.entries(rep)){
    const allPass = forms.every(f => info[f].pass);
    html += `<div class="card p-5 mb-4 border-l-4 ${allPass?'border-l-emerald-500':'border-l-red-500'}">
      <div class="flex items-start justify-between mb-3">
        <div>
          <h3 class="text-xl font-bold text-white"><i class="fa-solid fa-table mr-2 text-sky-400"></i>${table}</h3>
          <div class="text-slate-400 text-sm">PK: <code class="bg-slate-800 px-1.5 py-0.5 rounded">${info.pk}</code></div>
        </div>
        ${allPass
          ? '<div class="chip bg-emerald-900 text-emerald-300 border border-emerald-700"><i class="fa-solid fa-check mr-1"></i>ALL FORMS PASS</div>'
          : '<div class="chip bg-red-900 text-red-200 border border-red-700"><i class="fa-solid fa-triangle-exclamation mr-1"></i>HAS VIOLATIONS</div>'}
      </div>
      <div class="mb-4">
        <div class="text-xs uppercase text-slate-500 mb-1">Functional Dependencies</div>
        <ul class="text-sm space-y-1">
          ${info.FDs.map(f => `<li class="font-mono bg-slate-900 rounded px-3 py-1">${f}</li>`).join('')}
        </ul>
      </div>
      <div class="nf-row mb-3">
        ${forms.map(f => {
          const n = info[f];
          return `<div class="nf-pass pill">
            <div class="font-bold">${f}</div>
            <div class="mt-1 opacity-90">${n.pass ? '✓ PASS' : '✗ FAIL'}</div>
          </div>`;
        }).join('')}
      </div>
      <div class="grid md:grid-cols-2 gap-2 text-xs">
        ${forms.map(f => `<div class="bg-slate-900/60 border border-slate-700 rounded p-3">
          <div class="font-bold text-sky-300 mb-1">${f} ${info[f].pass ? '<span class="text-emerald-400">✓</span>' : '<span class="text-red-400">✗</span>'}</div>
          <div class="text-slate-300">${info[f].note}</div>
        </div>`).join('')}
      </div>
    </div>`;
  }
  $('#nfWrap').innerHTML = html;
}

$$('.tab').forEach(t => t.addEventListener('click', () => {
  $$('.tab').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  ['tables','schema','query','nf'].forEach(name => {
    $('#tab-'+name).classList.toggle('hidden', name !== t.dataset.tab);
  });
  if (t.dataset.tab === 'schema') loadSchema();
  if (t.dataset.tab === 'nf') loadNf();
}));

(async () => {
  await initConn();
  await Promise.all([loadTables(), loadData()]);
})();
</script>
</body>
</html>
"""


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"SmartSpend DB Viewer → http://{HOST}:{PORT}/")
    print("Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        srv.server_close()


if __name__ == '__main__':
    main()
