#!/usr/bin/env python3
"""Launch SmartSpend full stack (MariaDB + Django + Vite) in background, report health."""
import os, subprocess, time, socket, sys, signal, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG  = ROOT / ".dev_logs" / "launcher_wrapper.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

child_env = os.environ.copy()
child_env["API_PORT"] = "8000"
child_env["WEB_PORT"] = "5173"
child_env["MYSQL_PORT"] = "3307"
if os.environ.get("VIRTUAL_ENV"):
    venv_bin = Path(os.environ["VIRTUAL_ENV"]) / "bin"
    child_env["PATH"] = str(venv_bin) + os.pathsep + child_env.get("PATH", "")

with open(LOG, "wb") as fp:
    p = subprocess.Popen(
        ["bash", str(ROOT / "scripts" / "dev.sh")],
        cwd=str(ROOT), stdout=fp, stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        env=child_env,
    )
print(f"Launcher PID {p.pid} — booting MariaDB → Django :8000 → Vite :5173")
sys.stdout.flush()

def up(port: int, t: int = 120) -> bool:
    for _ in range(t * 2):
        if p.poll() is not None:
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False

def http(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0

print("Waiting for MariaDB :3307 …", end=" ", flush=True)
maria_ok = up(3307, 60)
print("OK" if maria_ok else "FAIL (optional — might skip)")

if p.poll() is not None:
    print(f"\n✘ dev.sh exited early with code {p.returncode} — Tail of launcher_wrapper.log:")
    lines = LOG.read_text(errors="replace").splitlines()
    print("\n".join(lines[-60:]))
    sys.exit(1)

print("Waiting for Django  :8000 …", end=" ", flush=True)
django_ok = up(8000, 90)
print("OK" if django_ok else "FAIL")
print("Waiting for Vite    :5173 …", end=" ", flush=True)
vite_ok = up(5173, 140)
print("OK" if vite_ok else "FAIL")

print(f"\nDjango /api/      → HTTP {http('http://127.0.0.1:8000/api/')}")
print(f"Django admin/     → HTTP {http('http://127.0.0.1:8000/admin/')}")
print(f"Django auth/login → HTTP {http('http://127.0.0.1:8000/api/auth/login/')}")
print(f"Vite frontend     → HTTP {http('http://127.0.0.1:5173/')}")
print(f"DB viewer :8001   → HTTP {http('http://127.0.0.1:8001/api/connection')}")

print("\n── SERVICES READY ──")
print(f"Stack launcher PID: {p.pid}   kill via:  kill -- -{p.pid}  or  Ctrl+C in terminal 7")
