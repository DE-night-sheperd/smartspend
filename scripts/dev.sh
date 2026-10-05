#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  SmartSpend — one-command full-stack dev launcher
#
#  Starts (in order):
#    1. Local MariaDB server (if not already running and mysql_data/ exists)
#    2. Django REST backend   —  http://127.0.0.1:$API_PORT/api/
#    3. Vite + React frontend —  http://127.0.0.1:$WEB_PORT/
#
#  Both processes share this shell as process group; Ctrl+C (or any signal)
#  kills every child cleanly including MariaDB so no ports are left squatted.
#
#  Usage (from project root):
#       ./scripts/dev.sh                 # defaults: API=8000, WEB=5173
#       API_PORT=8080 ./scripts/dev.sh   # override ports
#       WEB_PORT=4200 NO_MYSQL=1 ./scripts/dev.sh
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

# ── Tunables (override via env) ──────────────────────────────────────────────
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
NO_MYSQL="${NO_MYSQL:-0}"          # set =1 to skip embedded MariaDB startup
MYSQL_PORT="${MYSQL_PORT:-3307}"
MYSQL_USER="${MYSQL_USER:-smartspend_user}"
MYSQL_PASS="${MYSQL_PASSWORD:-smartspend_pass_2026}"
MYSQL_DB="${MYSQL_DB:-smartspend}"

export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
export MYSQL_PORT MYSQL_USER MYSQL_PASSWORD="$MYSQL_PASS" MYSQL_DB

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
MYSQL_DIR="$PROJECT_DIR/mysql_data"
SOCKET="$MYSQL_DIR/mysql.sock"
PID_FILE="$MYSQL_DIR/mysql.pid"
LOG_DIR="$PROJECT_DIR/.dev_logs"

mkdir -p "$LOG_DIR"
MYSQL_LOG="$LOG_DIR/mysql.log"
API_LOG="$LOG_DIR/django.log"
WEB_LOG="$LOG_DIR/vite.log"

# ── Colours ──────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  C_RED=$'\e[31m';   C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'
  C_BLUE=$'\e[34m';  C_CYAN=$'\e[36m';  C_BOLD=$'\e[1m';  C_RESET=$'\e[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_CYAN=""; C_BOLD=""; C_RESET=""
fi

ok()      { echo "  ${C_GREEN}✔${C_RESET} $*"; }
info()    { echo "  ${C_BLUE}i${C_RESET} $*"; }
warn()    { echo "  ${C_YELLOW}!${C_RESET} $*"; }
fail()    { echo "  ${C_RED}✘${C_RESET} $*"; }
banner()  { echo -e "\n${C_BOLD}${C_CYAN}═══ $* ═══${C_RESET}"; }

# ── Cleanup trap ─────────────────────────────────────────────────────────────
declare -a CHILDS=()
stop_all() {
  local exit_code=$1
  shift
  echo ""
  banner "Stopping all services"
  for pid in "${CHILDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE" 2>/dev/null || true
  fi
  pkill -P $$ 2>/dev/null || true
  wait 2>/dev/null
  echo -e "${C_GREEN}All services stopped.${C_RESET}"
  exit "$exit_code"
}
trap 'stop_all $?' INT TERM HUP EXIT

# ── Helpers ──────────────────────────────────────────────────────────────────
port_listening() {
  python3 - "$1" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(0.4)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

wait_for_port() {
  local port="$1" label="$2" tries="${3:-60}"
  local i=0
  while [ "$i" -lt "$tries" ]; do
    if port_listening "$port"; then return 0; fi
    sleep 0.5; i=$((i+1))
  done
  fail "$label never opened port $port"
  return 1
}

stop_stale() {
  # Kill anything that already squats our ports (previous crashed runs)
  local port="$1" label="$2"
  if port_listening "$port"; then
    warn "Port $port already in use — killing stale $label process…"
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    sleep 1
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1
}

# ─────────────────────────────────────────────────────────────────────────────
#  BANNER
# ─────────────────────────────────────────────────────────────────────────────
clear 2>/dev/null || true
echo ""
echo "${C_BOLD}${C_CYAN}
  ███████╗███╗   ███╗ █████╗ ██████╗ ████████╗███████╗██████╗ ███████╗███╗   ██╗██████╗
  ██╔════╝████╗ ████║██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔════╝████╗  ██║██╔══██╗
  ███████╗██╔████╔██║███████║██████╔╝   ██║   ███████╗██████╔╝█████╗  ██╔██╗ ██║██║  ██║
  ╚════██║██║╚██╔╝██║██╔══██║██╔══██╗   ██║   ╚════██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║  ██║
  ███████║██║ ╚═╝ ██║██║  ██║██║  ██║   ██║   ███████║██║     ███████╗██║ ╚████║██████╔╝
  ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝     ╚══════╝╚═╝  ╚═══╝╚═════╝
${C_RESET}"
echo "  ${C_BOLD}SmartSpend Development Stack${C_RESET}  —  MariaDB :$MYSQL_PORT  →  Django :$API_PORT  →  Vite :$WEB_PORT"
echo "  Logs written to ${C_CYAN}$LOG_DIR/{mysql,django,vite}.log${C_RESET}"
echo "  Press ${C_RED}Ctrl+C${C_RESET} at any time to stop everything."
echo ""

# ─────────────────────────────────────────────────────────────────────────────
#  STEP 0 — Preflight / Dependency installs
# ─────────────────────────────────────────────────────────────────────────────
banner "Preflight checks"

if ! require_cmd python3; then fail "python3 not found in PATH"; exit 1; fi
if ! require_cmd node;    then fail "node not found in PATH — install Node 20+"; exit 1; fi
ok "python3 $(python3 --version | awk '{print $2}')  +  node v$(node --version | tr -d v)"

# --- Backend deps -------------------------------------------------------------
info "Checking Python dependencies…"
if ! python3 -c 'import django, rest_framework, rest_framework_simplejwt, corsheaders, dotenv' 2>/dev/null; then
  warn "Missing backend packages — installing into current interpreter…"
  PIP_FLAGS="-q"
  [ -z "$VIRTUAL_ENV" ] && PIP_FLAGS="$PIP_FLAGS --break-system-packages"
  (cd "$BACKEND_DIR" && python3 -m pip install $PIP_FLAGS -r requirements.txt 2>"$LOG_DIR/pip.log") \
    || { fail "pip install failed — see $LOG_DIR/pip.log"; exit 1; }
  ok "Python dependencies installed"
else
  ok "Python dependencies already present"
fi

# --- Frontend deps ------------------------------------------------------------
info "Checking Node dependencies…"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  warn "No frontend/node_modules — running npm install…"
  (cd "$FRONTEND_DIR" && npm install --no-audit --no-fund --loglevel=error 2>&1 | tail -n 5) \
    || { fail "npm install failed"; exit 1; }
  ok "Frontend dependencies installed"
else
  ok "Frontend dependencies already present"
fi

# ─────────────────────────────────────────────────────────────────────────────
#  STEP 1 — MariaDB (if mysql_data dir exists and NOT skipped)
# ─────────────────────────────────────────────────────────────────────────────
if [ "$NO_MYSQL" -eq 1 ]; then
  banner "MariaDB — skipped (\$NO_MYSQL=1)"
  warn "Django will use whatever DB backend is configured via env."
elif [ ! -d "$MYSQL_DIR/data" ]; then
  banner "MariaDB — skipped (no mysql_data/data/ directory)"
  warn "Falling back to Django's SQLite default (or POSTGRES_*, if set)."
else
  banner "1/3  MariaDB  :$MYSQL_PORT"

  mysql_alive=0
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    ok "Already running (pid=$(cat "$PID_FILE"))"; mysql_alive=1
  elif port_listening "$MYSQL_PORT"; then
    ok "Port :$MYSQL_PORT already listening"; mysql_alive=1
  else
    mkdir -p "$MYSQL_DIR"
    : > "$MYSQL_LOG"
    if require_cmd mariadbd-safe; then
      MARIADB_BIN="$(command -v mariadbd-safe)"
    elif require_cmd mysqld_safe; then
      MARIADB_BIN="$(command -v mysqld_safe)"
    elif require_cmd mariadbd; then
      MARIADB_BIN="$(command -v mariadbd)"
    else
      MARIADB_BIN="/usr/sbin/mariadbd"
    fi

    info "Launching: $MARIADB_BIN"
    stop_stale "$MYSQL_PORT" "MariaDB"

    if [[ "$MARIADB_BIN" == *safe ]]; then
      nohup "$MARIADB_BIN" \
        --datadir="$MYSQL_DIR/data" \
        --socket="$SOCKET" \
        --pid-file="$PID_FILE" \
        --port="$MYSQL_PORT" \
        --bind-address=127.0.0.1 \
        --user="$USER" \
        >"$MYSQL_LOG" 2>&1 &
      disown 2>/dev/null || true
    else
      "$MARIADB_BIN" \
        --datadir="$MYSQL_DIR/data" \
        --socket="$SOCKET" \
        --pid-file="$PID_FILE" \
        --port="$MYSQL_PORT" \
        --bind-address=127.0.0.1 \
        --user="$USER" \
        >"$MYSQL_LOG" 2>&1 &
    fi
    MYSQL_PID=$!
    CHILDS+=("$MYSQL_PID")

    if wait_for_port "$MYSQL_PORT" "MariaDB" 160; then
      ok "MariaDB ready on 127.0.0.1:$MYSQL_PORT (socket=$SOCKET)"
    else
      fail "MariaDB did not start. Tail of $MYSQL_LOG:"
      tail -20 "$MYSQL_LOG" >&2
      exit 1
    fi
  fi

  # DB connectivity check -----------------------------------------------------
  if [ "$mysql_alive" -eq 1 ] || port_listening "$MYSQL_PORT"; then
    if python3 -c "
import os,sys
os.environ.setdefault('MYSQL_HOST','127.0.0.1')
os.environ.setdefault('MYSQL_PORT','$MYSQL_PORT')
os.environ.setdefault('MYSQL_USER','$MYSQL_USER')
os.environ.setdefault('MYSQL_PASSWORD','$MYSQL_PASS')
os.environ.setdefault('MYSQL_DB','$MYSQL_DB')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','smartspend.settings')
sys.path.insert(0,'$BACKEND_DIR')
import django; django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute('SELECT 1')
    print('SELECT 1 →', c.fetchone()[0])
" >"$LOG_DIR/db_ping.log" 2>&1; then
      ok "Django DB connection → $MYSQL_DB@127.0.0.1:$MYSQL_PORT verified"
    else
      warn "Django could not ping MySQL — check backend/.env. Log tail:"
      tail -10 "$LOG_DIR/db_ping.log" >&2
    fi
  fi
fi

# --- Run migrations (DB must be up first) ------------------------------------
info "Running Django migrations…"
(cd "$BACKEND_DIR" && python3 manage.py migrate --noinput >"$LOG_DIR/migrate.log" 2>&1) \
  || { fail "migrate failed — see $LOG_DIR/migrate.log"; cat "$LOG_DIR/migrate.log"; exit 1; }
ok "Migrations applied"

# ─────────────────────────────────────────────────────────────────────────────
#  STEP 2 — Django backend  (runs on 0.0.0.0 so the Vite proxy still works
#           when you open the frontend from another host in preview)
# ─────────────────────────────────────────────────────────────────────────────
banner "2/3  Django API  http://127.0.0.1:$API_PORT/api/"

stop_stale "$API_PORT" "Django runserver"
: > "$API_LOG"

(cd "$BACKEND_DIR" && \
  exec python3 manage.py runserver "0.0.0.0:$API_PORT" --noreload \
  >"$API_LOG" 2>&1) &
API_PID=$!
CHILDS+=("$API_PID")

if wait_for_port "$API_PORT" "Django" 90; then
  ok "Django API listening on 0.0.0.0:$API_PORT"
else
  fail "Django did not start. Tail of $API_LOG:"
  tail -25 "$API_LOG" >&2
  exit 1
fi

# Smoke-test /api/auth/ — anything 200/401/403/405 proves Django is routing
API_HTTP=$(python3 -c "import urllib.request as u;
try: print(u.urlopen(u.Request('http://127.0.0.1:$API_PORT/api/auth/login/'), timeout=3).status)
except Exception as e:
  c=getattr(e,'code',0); print(c if c else 'err')")
case "$API_HTTP" in
  200|400|401|403|405) ok "API route probe → HTTP $API_HTTP (routing OK)" ;;
  *)                    warn "API probe → $API_HTTP — check $API_LOG" ;;
esac

# ─────────────────────────────────────────────────────────────────────────────
#  STEP 3 — Vite React dev server
# ─────────────────────────────────────────────────────────────────────────────
banner "3/3  Vite Frontend  http://127.0.0.1:$WEB_PORT/"

stop_stale "$WEB_PORT" "Vite"
: > "$WEB_LOG"

# Expose so vite.config proxy → Django backend always reachable
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:$API_PORT}"

(cd "$FRONTEND_DIR" && \
  exec npm run dev -- --host 0.0.0.0 --port "$WEB_PORT" --strictPort \
  >"$WEB_LOG" 2>&1) &
WEB_PID=$!
CHILDS+=("$WEB_PID")

if wait_for_port "$WEB_PORT" "Vite" 120; then
  ok "Vite dev server listening on 0.0.0.0:$WEB_PORT"
else
  fail "Vite did not start. Tail of $WEB_LOG:"
  tail -25 "$WEB_LOG" >&2
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
#  READY — summary
# ─────────────────────────────────────────────────────────────────────────────
banner "READY"
echo ""
echo "  ${C_GREEN}📊  DB Viewer       →${C_RESET}  http://127.0.0.1:8001/   (if you ran python backend/db_viewer.py separately)"
echo "  ${C_GREEN}🧠  Django Admin    →${C_RESET}  http://127.0.0.1:$API_PORT/admin/"
echo "  ${C_GREEN}🔌  REST API Root   →${C_RESET}  http://127.0.0.1:$API_PORT/api/"
echo "  ${C_GREEN}🎨  Frontend App    →${C_RESET}  http://127.0.0.1:$WEB_PORT/"
echo "  ${C_GREEN}📂  Source          →${C_RESET}  backend/   ·   frontend/   ·   scripts/"
echo ""
echo "  ${C_CYAN}Tip:${C_RESET}  ${C_BOLD}export API_PORT=XXXX WEB_PORT=YYYY NO_MYSQL=1${C_RESET}  then re-run to customise."
echo "  ${C_CYAN}Tip:${C_RESET}  ${C_BOLD}tail -f $LOG_DIR/*.log${C_RESET}  to watch all three log streams side by side."
echo ""
echo "  ───────────── ${C_RED}Ctrl+C to stop all services${C_RESET} ─────────────"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
#  Live tail of each child's log, prefixed with a coloured service tag, so
#  you get a single interleaved console the same way you would if you ran
#  them manually (but readable).
# ─────────────────────────────────────────────────────────────────────────────
TAG_MYSQL="${C_BOLD}${C_YELLOW}[mysql]${C_RESET}"
TAG_API="${C_BOLD}${C_BLUE}[api  ]${C_RESET}"
TAG_WEB="${C_BOLD}${C_GREEN}[web  ]${C_RESET}"

# Tail all logs in the background, so `wait` below owns the foreground and we
# can still signal-trap to stop the whole group.
if command -v tail >/dev/null 2>&1; then
  ( tail -q -n 0 -F "$MYSQL_LOG" 2>/dev/null | awk -v t="$TAG_MYSQL"   '{print t, $0; fflush()}' ) &
  CHILDS+=($!)
  ( tail -q -n 0 -F "$API_LOG"   2>/dev/null | awk -v t="$TAG_API"     '{print t, $0; fflush()}' ) &
  CHILDS+=($!)
  ( tail -q -n 0 -F "$WEB_LOG"   2>/dev/null | awk -v t="$TAG_WEB"     '{print t, $0; fflush()}' ) &
  CHILDS+=($!)
fi

wait
