#!/bin/bash
# SmartSpend Complete Development Stack Starter
# Starts: 1) Local MariaDB instance, 2) Django backend on :8000
#
# Usage: ./start_dev_stack.sh   (from project root)

set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
MYSQL_DIR="$PROJECT_DIR/mysql_data"
BACKEND_DIR="$PROJECT_DIR/backend"
SOCKET="$MYSQL_DIR/mysql.sock"
PID_FILE="$MYSQL_DIR/mysql.pid"
PORT=3307

cleanup() {
  echo ""
  echo "🛑  Stopping services..."
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
  kill 0 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM EXIT

echo "═══════════════════════════════════════════════════════"
echo "  SmartSpend Dev Stack"
echo "  MySQL :3307  →  Django API :8000"
echo "═══════════════════════════════════════════════════════"

# ── 1. MariaDB (if not already running) ────────────────────────────────
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "✅  MariaDB already running (pid=$(cat "$PID_FILE"))"
elif mysqladmin --socket="$SOCKET" ping 2>/dev/null; then
  echo "✅  MariaDB already reachable via socket"
else
  echo "🚀  Starting MariaDB on 127.0.0.1:$PORT ..."
  /usr/sbin/mariadbd \
    --datadir="$MYSQL_DIR/data" \
    --socket="$SOCKET" \
    --pid-file="$PID_FILE" \
    --port=$PORT \
    --bind-address=127.0.0.1 \
    --user=$USER \
    --log-error="$MYSQL_DIR/error.log" \
    &
  MYSQL_PID=$!
  for i in $(seq 1 30); do
    if mysqladmin --socket="$SOCKET" ping 2>/dev/null; then
      echo "✅  MariaDB ready (socket=$SOCKET)"
      break
    fi
    sleep 0.5
  done
fi

# ── 2. Verify DB connectivity ──────────────────────────────────────────
echo -n "🔍  Verifying smartspend DB... "
if mysql --socket="$SOCKET" -u smartspend_user -p'smartspend_pass_2026' smartspend -e 'SELECT 1' >/dev/null 2>&1; then
  echo "connected"
else
  echo "FAILED — check credentials in backend/.env"
fi

# ── 3. Django backend ──────────────────────────────────────────────────
echo "🚀  Starting Django backend on http://127.0.0.1:8000"
cd "$BACKEND_DIR"
exec python manage.py runserver 0.0.0.0:8000
