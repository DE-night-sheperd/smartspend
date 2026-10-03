#!/bin/sh
# One-command dev: Django API (0.0.0.0:8000) + Vite frontend (0.0.0.0:$PORT).
# The frontend talks to the API same-origin via the Vite /api proxy, so the
# preview works from any host. Usage: sh ./scripts/dev.sh
set -e

API_PORT="${API_PORT:-8000}"
WEB_PORT="${PORT:-5173}"

cd "$(dirname "$0")/../backend"
# Self-heal: the managed preview only runs the Node install command, so make
# sure the Django stack is present before migrating. Skips entirely when the
# dependencies already exist (the common case).
python3 -c 'import django, rest_framework, rest_framework_simplejwt, corsheaders, dotenv' 2>/dev/null \
  || pip3 install -q -r requirements.txt
python3 manage.py migrate --noinput

# Stale-instance guard: a previous preview generation can leave its runserver
# behind (it outlives the tracked Vite process), squatting the API port and
# serving outdated code while this script's runserver fails to bind. Stop any
# earlier instance of this exact service, then wait for the port to free so
# the fresh process below actually owns it.
pkill -f "manage.py runserver 0.0.0.0:$API_PORT" 2>/dev/null || true
i=0
while [ "$i" -lt 30 ]; do
  if ! python3 -c "import socket,sys; s=socket.socket(); s.settimeout(0.3); sys.exit(0 if s.connect_ex(('127.0.0.1', $API_PORT)) != 0 else 1)" 2>/dev/null; then
    : # something is still listening — keep waiting
  else
    break
  fi
  i=$((i + 1))
  sleep 0.3
done

# --noreload: the managed preview restarts deliberately; the file-watcher
# reloader can race-crash during rapid edits and take the preview down.
python3 manage.py runserver "0.0.0.0:$API_PORT" --noreload &
API_PID=$!
# Keep this shell alive (no `exec`) so the trap survives and cleans up the
# API child whenever the preview stops this script.
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

cd ../frontend
npm run dev -- --host 0.0.0.0 --port "$WEB_PORT" --strictPort
