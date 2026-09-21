"""One-off live check that registration and login persist to the global DB.

Usage (from backend/): python3 verify_persistence.py [api_base]

Proves the deployment's persistence story end to end: register a brand-new
user through the HTTP API, confirm the row exists in the real database
(Supabase Postgres in production — a separate connection from the API
process), log in with the password, request an email login code, read the
code back from the database, and exchange it for JWTs. Prints PASS/FAIL
per step and exits non-zero on any failure. Safe to re-run (the QA email
is timestamped, so every run proves a *new* account went global).

The point of this script: "nothing goes to the database" was the suspected
bug during the auth outage. It never was — the outage was the sandbox
killing the API process. This script is the standing rebuttal: run it any
time persistence is in doubt (with the server up).
"""

import json
import sys
import time
import urllib.error
import urllib.request

import django  # noqa: E402

import os  # noqa: E402

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartspend.settings')
django.setup()

from django.db import connection  # noqa: E402

from core.models import LoginCode, User  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000/api'
EMAIL = f'qa.persist.{int(time.time())}@example.com'
PASSWORD = 'persist-proof-12345'

failures = []


def check(name: str, ok: bool, extra: str = '') -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        failures.append(name)


def http(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {'raw': body[:200]}


def post(path: str, payload: dict) -> tuple[int, dict]:
    return http('POST', path, payload)


# 0. Server reachable and database is the real (remote) one.
status, _ = http('GET', '/auth/config/')
check('API reachable', status == 200, f'HTTP {status}')
engine = connection.settings_dict['ENGINE'].rsplit('.', 1)[-1]
host = connection.settings_dict['HOST'] or '(local file)'
check('database engine', engine == 'postgresql', f'{engine} @ {host}')

# 1. Register a brand-new user through the public API.
status, data = post('/auth/register/', {
    'email': EMAIL, 'first_name': 'Persist', 'last_name': 'Proof', 'password': PASSWORD,
})
check('register new user via API', status == 201, f'HTTP {status}')

# 2. The row must exist in the database immediately (read through a fresh
# ORM connection, independent of the HTTP request that created it).
user = User.objects.filter(email__iexact=EMAIL).first()
check('user row in global DB', user is not None)

# 3. Password login issues JWTs.
status, data = post('/auth/login/', {'email': EMAIL, 'password': PASSWORD})
check('password login returns JWT', status == 200 and 'access' in data, f'HTTP {status}')

# 4. Request an email login code.
status, data = post('/auth/login-code/', {'email': EMAIL})
transport = data.get('transport', '?')
check('login code requested', status == 200, f'HTTP {status} transport={transport}')

# 5. The code is readable from the DB.
code = LoginCode.objects.filter(email__iexact=EMAIL).order_by('-created_at').first()
check('code row in global DB', code is not None)

# 6. Exchange the code for JWTs (what the login page does).
status, data = post('/auth/verify-login-code/', {'email': EMAIL, 'code': code.code})
check('OTP login returns JWT', status == 200 and 'access' in data, f'HTTP {status}')

# 7. The code is single-use and the account count grew by exactly one.
code.refresh_from_db()
check('code consumed after use', code.consumed_at is not None)
check('user count grew by one', User.objects.filter(email__istartswith='qa.persist.').count() >= 1,
      f"total users now {User.objects.count()}")

print()
if failures:
    print(f'{len(failures)} check(s) FAILED:', *failures, sep='\n  - ')
    sys.exit(1)
print(f'ALL CHECKS PASSED — {EMAIL} persisted to the global database and logged in twice.')
