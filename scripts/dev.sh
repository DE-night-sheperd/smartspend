#!/bin/sh
# One-command dev: Django API (0.0.0.0:8000) + Vite frontend (0.0.0.0:$PORT).
# The frontend talks to the API same-origin via the Vite /api proxy, so the
# preview works from any host. Usage: sh ./scripts/dev.sh
set -e

API_PORT="${API_PORT:-8000}"
WEB_PORT="${PORT:-5173}"

cd "$(dirname "$0")/../backend"
python3 manage.py migrate --noinput
# --noreload: the managed preview restarts deliberately; the file-watcher
# reloader can race-crash during rapid edits and take the preview down.
python3 manage.py runserver "0.0.0.0:$API_PORT" --noreload &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

cd ../frontend
exec npm run dev -- --host 0.0.0.0 --port "$WEB_PORT" --strictPort
