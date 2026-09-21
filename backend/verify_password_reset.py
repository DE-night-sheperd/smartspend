"""One-off live check of the password-reset flow against the running server.

Usage (from backend/): python3 verify_password_reset.py [api_base]
Walks register -> request reset -> verify code -> confirm new password ->
login with the new password -> code single-use rejection. Prints PASS/FAIL
per step and exits non-zero on any failure. Safe to re-run (email is
timestamped, previous run's user is reused/reset).
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

from core.models import LoginCode, User  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000/api'
EMAIL = f'qa.reset.{int(time.time())}@example.com'
NEW_PASSWORD = 'live-check-pw-98765'

failures = []


def check(name: str, ok: bool, extra: str = '') -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        failures.append(name)


def post(path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {'raw': body[:200]}


# 0. Make sure the QA user exists with a known starting password.
User.objects.filter(email=EMAIL).delete()
status, data = post('/auth/register/', {
    'email': EMAIL, 'first_name': 'Live', 'last_name': 'Check', 'password': 'start-pw-12345',
})
check('register QA user', status == 201, f'HTTP {status}')

# 1. Request a reset code.
status, data = post('/auth/password-reset/', {'email': EMAIL})
detail = str(data.get('detail', ''))
if status == 502 and 'not fully set up' in detail:
    # Resend testing mode (no verified domain): codes can only reach
    # Resend's own test inbox, so re-run the flow against it. The QA
    # account is recreated there so every step still runs live.
    print('NOTE: Resend testing mode detected (no verified domain) — '
          're-running against the Resend test inbox delivered@resend.dev.')
    EMAIL = 'delivered@resend.dev'
    User.objects.filter(email=EMAIL).delete()
    status, data = post('/auth/register/', {
        'email': EMAIL, 'first_name': 'Live', 'last_name': 'Check', 'password': 'start-pw-12345',
    })
    check('register QA user (test inbox)', status == 201, f'HTTP {status}')
    status, data = post('/auth/password-reset/', {'email': EMAIL})
    detail = str(data.get('detail', ''))
    if status == 502 and 'not fully set up' in detail:
        check('request reset code returns 200', False, 'provider misconfiguration: ' + detail)
        print('NOTE: verify a domain in the Resend dashboard to deliver to real inboxes.')
        print()
        sys.exit(1)
check('request reset code returns 200', status == 200, f'HTTP {status}')
code = LoginCode.objects.filter(email=EMAIL).order_by('-created_at').first()
check('reset code row created', code is not None)

# 2. Verify the code (must NOT consume it).
status, data = post('/auth/password-reset/verify/', {'email': EMAIL, 'code': code.code})
check('verify code returns verified=true', status == 200 and data.get('verified') is True, f'HTTP {status} {data}')
code.refresh_from_db()
check('code not consumed by verify', code.consumed_at is None)

# 3. Confirm the new password (consumes the code).
status, data = post('/auth/password-reset/confirm/', {
    'email': EMAIL, 'code': code.code, 'new_password': NEW_PASSWORD,
})
check('confirm sets new password', status == 200, f'HTTP {status} {data}')
code.refresh_from_db()
check('code consumed by confirm', code.consumed_at is not None)

# 4. Old code can't be reused.
status, data = post('/auth/password-reset/confirm/', {
    'email': EMAIL, 'code': code.code, 'new_password': 'another-pw-000',
})
check('used code rejected on reuse', status == 400, f'HTTP {status}')

# 5. Login with the new password.
status, data = post('/auth/login/', {'email': EMAIL, 'password': NEW_PASSWORD})
check('login works with new password', status == 200 and 'access' in data, f'HTTP {status}')

# 6. Old password no longer works.
status, data = post('/auth/login/', {'email': EMAIL, 'password': 'start-pw-12345'})
check('old password rejected', status == 401, f'HTTP {status}')

print()
if failures:
    print(f'{len(failures)} step(s) failed: {", ".join(failures)}')
    sys.exit(1)
print('All password-reset live checks passed.')
