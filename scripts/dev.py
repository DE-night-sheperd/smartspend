#!/usr/bin/env python3
"""
SmartSpend — one-command full-stack dev launcher (cross-platform).
=================================================================

Starts, in order:
  1. Local MariaDB server (Linux only — if mysql_data/data/ exists and NO_MYSQL != 1)
  2. Django backend   →  http://127.0.0.1:8000/api/
  3. Vite frontend    →  http://127.0.0.1:5173/

Press Ctrl+C once to kill every child cleanly.

Works on Linux, macOS, Windows (Win users: skip MariaDB or run it as a service).

Usage:
    python scripts/dev.py
    API_PORT=8080  WEB_PORT=4200  python scripts/dev.py
    NO_MYSQL=1     python scripts/dev.py          # skip MariaDB launch
"""
from __future__ import annotations

import os
import socket
import shutil
import sys
import signal
import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Tunables (override via env vars) ─────────────────────────────────────────
API_PORT   = int(os.environ.get("API_PORT",   "8000"))
WEB_PORT   = int(os.environ.get("WEB_PORT",   "5173"))
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3307"))
NO_MYSQL   = bool(int(os.environ.get("NO_MYSQL", "0")))

MYSQL_USER = os.environ.get("MYSQL_USER",     "smartspend_user")
MYSQL_PASS = os.environ.get("MYSQL_PASSWORD", "smartspend_pass_2026")
MYSQL_DB   = os.environ.get("MYSQL_DB",       "smartspend")

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_DIR / "backend"
FRONT_DIR   = PROJECT_DIR / "frontend"
MYSQL_DIR   = PROJECT_DIR / "mysql_data"
LOG_DIR     = PROJECT_DIR / ".dev_logs"
LOG_DIR.mkdir(exist_ok=True)

MYSQL_PID_FILE = MYSQL_DIR / "mysql.pid"
MYSQL_SOCKET   = MYSQL_DIR / "mysql.sock"
# ── Terminal colours ─────────────────────────────────────────────────────────
USE_COLOR = sys.stdout.isatty()
def c(code: int, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if USE_COLOR else s
BOLD   = lambda s: c(1, s)
RED    = lambda s: c(31, s)
GREEN  = lambda s: c(32, s)
YELLOW = lambda s: c(33, s)
BLUE   = lambda s: c(34, s)
CYAN   = lambda s: c(36, s)

def ok(msg: str) -> None:   print(f"  {GREEN('✔')} {msg}")
def info(msg: str) -> None: print(f"  {BLUE('i')} {msg}")
def warn(msg: str) -> None: print(f"  {YELLOW('!')} {msg}")
def fail(msg: str) -> None: print(f"  {RED('✘')} {msg}", file=sys.stderr)
def banner(title: str) -> None: print(f"\n{BOLD(CYAN(f'═══ {title} ═══'))}")

# ── Helpers ──────────────────────────────────────────────────────────────────
CHILDS: list[subprocess.Popen] = []
def shutdown_all() -> None:
    print()
    banner("Stopping all services")
    for p in CHILDS:
        try:
            p.terminate()
        except Exception:
            pass
    if MYSQL_PID_FILE.is_file():
        try:
            pid = int(MYSQL_PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            MYSQL_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
    # Give them 5s, then force-kill anything left
    end = time.time() + 5
    alive = [p for p in CHILDS if p.poll() is None]
    while alive and time.time() < end:
        time.sleep(0.2)
        alive = [p for p in alive if p.poll() is None]
    for p in alive:
        try: p.kill()
        except Exception: pass
    print(GREEN("All services stopped."))

def on_signal(signum, frame):  # noqa: ARG001 — required signature
    shutdown_all()
    sys.exit(0)
signal.signal(signal.SIGINT,  on_signal)
signal.signal(signal.SIGTERM, on_signal)
if sys.platform != "win32":
    signal.signal(signal.SIGHUP, on_signal)

def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0

def wait_port(port: int, label: str, tries: int = 80) -> bool:
    for _ in range(tries):
        if port_open(port):
            return True
        time.sleep(0.5)
    fail(f"{label} never opened port {port}")
    return False

def stop_stale(port: int, label: str) -> None:
    if port_open(port):
        warn(f"Port {port} is in use — killing stale {label} process…")
        if sys.platform == "win32":
            # Windows: find the owning PID by port, then taskkill
            try:
                res = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True
                )
                for line in res.stdout.splitlines():
                    if f":{port} " in line and "LISTENING" in line:
                        pid = line.strip().split()[-1]
                        subprocess.run(["taskkill", "/F", "/PID", pid],
                                       capture_output=True)
            except Exception:
                pass
        else:
            try:
                subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
            except Exception:
                pass
        time.sleep(1)

def require(cmd: str) -> str | None:
    return shutil.which(cmd)

# ── Log-tail thread ──────────────────────────────────────────────────────────
def start_tailer(logfile: Path, tag: str) -> None:
    """Follow a log file, print each line prefixed with a coloured service tag."""
    def worker():
        try:
            f = open(logfile, "r", errors="replace")
        except FileNotFoundError:
            return
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                # Subprocess might still be starting — don't spin hard
                time.sleep(0.2)
                continue
            sys.stdout.write(f"{tag} {line}")
            sys.stdout.flush()
    threading.Thread(target=worker, daemon=True).start()

def spawn(cmd: list[str], cwd: Path, log: Path, env: dict | None = None) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    fp = open(log, "w", buffering=1)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.Popen(
        cmd, cwd=str(cwd), stdout=fp, stderr=subprocess.STDOUT,
        text=True, env=merged_env,
    )

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    if os.name != "nt":
        os.system("clear 2>/dev/null || true")
    print()
    print(BOLD(CYAN("""
  ███████╗███╗   ███╗ █████╗ ██████╗ ████████╗███████╗██████╗ ███████╗███╗   ██╗██████╗
  ██╔════╝████╗ ████║██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔════╝████╗  ██║██╔══██╗
  ███████╗██╔████╔██║███████║██████╔╝   ██║   ███████╗██████╔╝█████╗  ██╔██╗ ██║██║  ██║
  ╚════██║██║╚██╔╝██║██╔══██║██╔══██╗   ██║   ╚════██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║  ██║
  ███████║██║ ╚═╝ ██║██║  ██║██║  ██║   ██║   ███████║██║     ███████╗██║ ╚████║██████╔╝
  ╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝     ╚══════╝╚═╝  ╚═══╝╚═════╝
""")))
    print(f"  {BOLD('SmartSpend Development Stack')}  —  "
          f"MariaDB :{MYSQL_PORT}  →  Django :{API_PORT}  →  Vite :{WEB_PORT}")
    print(f"  Logs written to {CYAN(str(LOG_DIR))}"
          f"/{{mysql,django,vite}}.log")
    print(f"  Press {RED('Ctrl+C')} at any time to stop everything.")
    print()

    # ── Step 0: Preflight ───────────────────────────────────────────────────
    banner("Preflight checks")

    py = require("python3") or require("py") or require("python")
    nd = require("node")
    if not py: fail("python3 not in PATH"); sys.exit(1)
    if not nd: fail("node not in PATH — install Node 20+"); sys.exit(1)

    pyver = subprocess.run([py, "--version"], capture_output=True, text=True).stdout.strip().split()[-1]
    ndver = subprocess.run([nd, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    ok(f"python3 {pyver}  +  node v{ndver}")

    # Backend deps
    info("Checking Python dependencies…")
    probe = subprocess.run(
        [py, "-c",
         "import django, rest_framework, simplejwt, corsheaders, dotenv"],
        cwd=str(BACKEND_DIR), capture_output=True,
    )
    if probe.returncode != 0:
        warn("Missing backend packages — running pip install -r requirements.txt…")
        pip_log = LOG_DIR / "pip.log"
        res = subprocess.run(
            [py, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
            cwd=str(BACKEND_DIR), capture_output=True, text=True,
        )
        if res.returncode != 0:
            pip_log.write_text(res.stdout + "\n---STDERR---\n" + res.stderr)
            fail(f"pip install failed — see {pip_log}")
            sys.exit(1)
        ok("Python dependencies installed")
    else:
        ok("Python dependencies already present")

    # Frontend deps
    info("Checking Node dependencies…")
    if not (FRONT_DIR / "node_modules").is_dir():
        warn("No frontend/node_modules — running npm install…")
        subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
                       cwd=str(FRONT_DIR), check=True)
        ok("Frontend dependencies installed")
    else:
        ok("Frontend dependencies already present")

    # Migrations
    info("Running Django migrations…")
    mig_log = LOG_DIR / "migrate.log"
    res = subprocess.run(
        [py, "manage.py", "migrate", "--noinput"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True,
    )
    if res.returncode != 0:
        mig_log.write_text(res.stdout + "\n---STDERR---\n" + res.stderr)
        fail(f"migrate failed — see {mig_log}")
        print(mig_log.read_text())
        sys.exit(1)
    ok("Migrations applied")

    # ── Step 1: MariaDB (Linux only) ────────────────────────────────────────
    if NO_MYSQL:
        banner("MariaDB — skipped (NO_MYSQL=1)")
        warn("Django will use whatever DB backend is configured via env.")
    elif not (MYSQL_DIR / "data").is_dir():
        banner("MariaDB — skipped (no mysql_data/data/ directory)")
        warn("Falling back to SQLite default (or POSTGRES_*, if set).")
    elif sys.platform == "win32":
        banner("MariaDB — skipped on Windows")
        warn("Start MariaDB as a service, or use NO_MYSQL=1 for SQLite.")
    else:
        banner(f"1/3  MariaDB  :{MYSQL_PORT}")

        mysql_up = port_open(MYSQL_PORT)
        if mysql_up:
            ok(f"Port :{MYSQL_PORT} already listening")
        else:
            MYSQL_DIR.mkdir(exist_ok=True)
            mysql_bin = (require("mariadbd-safe") or require("mysqld_safe")
                         or require("mariadbd") or require("mysqld")
                         or "/usr/sbin/mariadbd")
            info(f"Launching: {mysql_bin}")
            stop_stale(MYSQL_PORT, "MariaDB")

            cmd: list[str]
            if "safe" in mysql_bin:
                cmd = [mysql_bin,
                       f"--datadir={MYSQL_DIR}/data",
                       f"--socket={MYSQL_SOCKET}",
                       f"--pid-file={MYSQL_PID_FILE}",
                       f"--port={MYSQL_PORT}",
                       "--bind-address=127.0.0.1",
                       f"--user={os.environ.get('USER','mysql')}"]
                p = spawn(cmd, PROJECT_DIR, LOG_DIR / "mysql.log")
            else:
                cmd = [mysql_bin,
                       f"--datadir={MYSQL_DIR}/data",
                       f"--socket={MYSQL_SOCKET}",
                       f"--pid-file={MYSQL_PID_FILE}",
                       f"--port={MYSQL_PORT}",
                       "--bind-address=127.0.0.1",
                       f"--user={os.environ.get('USER','mysql')}",
                       f"--log-error={LOG_DIR / 'mysql.log'}"]
                p = subprocess.Popen(cmd)
            CHILDS.append(p)

            if not wait_port(MYSQL_PORT, "MariaDB", 100):
                fail("MariaDB did not start. Tail of mysql.log:")
                log = LOG_DIR / "mysql.log"
                if log.is_file():
                    print("\n".join(log.read_text().splitlines()[-20:]),
                          file=sys.stderr)
                sys.exit(1)
            ok(f"MariaDB ready on 127.0.0.1:{MYSQL_PORT}")

        # DB ping through Django ORM
        info("Verifying Django → MySQL connectivity…")
        env_add = {
            "MYSQL_HOST": "127.0.0.1",
            "MYSQL_PORT": str(MYSQL_PORT),
            "MYSQL_USER": MYSQL_USER,
            "MYSQL_PASSWORD": MYSQL_PASS,
            "MYSQL_DB":   MYSQL_DB,
            "DJANGO_SETTINGS_MODULE": "smartspend.settings",
        }
        probe = f'''
import os, sys
for k,v in {env_add!r}.items(): os.environ.setdefault(k,v)
sys.path.insert(0, {str(BACKEND_DIR)!r})
import django; django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute("SELECT 1"); print("ok", c.fetchone()[0])
'''
        ping_log = LOG_DIR / "db_ping.log"
        res = subprocess.run([py, "-c", probe], capture_output=True, text=True)
        ping_log.write_text(res.stdout + "\n---STDERR---\n" + res.stderr)
        if res.returncode == 0:
            ok(f"Django DB → {MYSQL_DB}@127.0.0.1:{MYSQL_PORT} verified")
        else:
            warn("Django could not ping MySQL — check backend/.env. "
                 "Tail of db_ping.log:")
            print("\n".join(ping_log.read_text().splitlines()[-10:]),
                  file=sys.stderr)

    # ── Step 2: Django API ──────────────────────────────────────────────────
    banner(f"2/3  Django API  http://127.0.0.1:{API_PORT}/api/")
    stop_stale(API_PORT, "Django runserver")
    api_log = LOG_DIR / "django.log"
    p = spawn([py, "manage.py", "runserver",
               f"0.0.0.0:{API_PORT}", "--noreload"],
              BACKEND_DIR, api_log)
    CHILDS.append(p)
    if not wait_port(API_PORT, "Django", 100):
        fail("Django did not start. Tail of django.log:")
        print("\n".join(api_log.read_text().splitlines()[-25:]), file=sys.stderr)
        sys.exit(1)
    ok(f"Django API listening on 0.0.0.0:{API_PORT}")

    # Route probe
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{API_PORT}/api/auth/login/")
        with urllib.request.urlopen(req, timeout=3) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    if code in {200, 400, 401, 403, 405}:
        ok(f"API route probe → HTTP {code} (routing OK)")
    else:
        warn(f"API probe → {code or 'error'} — check django.log")

    # ── Step 3: Vite ────────────────────────────────────────────────────────
    banner(f"3/3  Vite Frontend  http://127.0.0.1:{WEB_PORT}/")
    stop_stale(WEB_PORT, "Vite")
    web_log = LOG_DIR / "vite.log"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    p = spawn(
        [npm, "run", "dev", "--",
         "--host", "0.0.0.0", "--port", str(WEB_PORT), "--strictPort"],
        FRONT_DIR, web_log,
        env={"VITE_API_BASE_URL": f"http://127.0.0.1:{API_PORT}"},
    )
    CHILDS.append(p)
    if not wait_port(WEB_PORT, "Vite", 140):
        fail("Vite did not start. Tail of vite.log:")
        print("\n".join(web_log.read_text().splitlines()[-25:]), file=sys.stderr)
        sys.exit(1)
    ok(f"Vite dev server listening on 0.0.0.0:{WEB_PORT}")

    # ── Ready ───────────────────────────────────────────────────────────────
    banner("READY")
    print()
    print(f"  {GREEN('📊  DB Viewer       →')}  http://127.0.0.1:8001/   "
          "(run `python backend/db_viewer.py` separately to enable)")
    print(f"  {GREEN('🧠  Django Admin    →')}  http://127.0.0.1:{API_PORT}/admin/")
    print(f"  {GREEN('🔌  REST API Root   →')}  http://127.0.0.1:{API_PORT}/api/")
    print(f"  {GREEN('🎨  Frontend App    →')}  http://127.0.0.1:{WEB_PORT}/")
    print(f"  {GREEN('📂  Source          →')}  backend/   ·   frontend/   ·   scripts/")
    print()
    print(f"  {CYAN('Tip:')}  {BOLD('$env:API_PORT=8080; $env:NO_MYSQL=1; python scripts/dev.py')}   (PowerShell / custom ports)")
    print(f"  {CYAN('Tip:')}  {BOLD('tail -f {LOG_DIR}/*.log')}   to watch all three raw log files.")
    print()
    print(f"  ───────────── {RED('Ctrl+C to stop all services')} ─────────────")
    print()

    # ── Tailed logs with tags ───────────────────────────────────────────────
    tag_mysql = f"{BOLD(YELLOW('[mysql]'))}"
    tag_api   = f"{BOLD(BLUE ('[api  ]'))}"
    tag_web   = f"{BOLD(GREEN('[web  ]'))}"
    start_tailer(LOG_DIR / "mysql.log", tag_mysql)
    start_tailer(LOG_DIR / "django.log", tag_api)
    start_tailer(LOG_DIR / "vite.log",   tag_web)

    # Sleep forever (Ctrl+C → shutdown_all via signal handler)
    try:
        while True:
            # Also reap any dead children silently
            for p in list(CHILDS):
                if p.poll() is not None and p.returncode not in (None, 0, -15):
                    warn(f"Child process {p.args[0] if hasattr(p,'args') else ''} exited with code {p.returncode}")
            time.sleep(2)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    try:
        main()
    finally:
        shutdown_all()
