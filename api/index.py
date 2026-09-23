"""WSGI bridge so the managed host can serve the Django API in-process.

The production frontend is a Vite SPA built to `dist/`. The hosting builder
is Node-only for the build, but it executes Python from `api/*.py` (after
installing `api/requirements.txt`). This entrypoint boots the real Django
app from `backend/` on first request and hands every request to it — no
separate API server, no tunnel: the deployed frontend talks to the API
same-origin at `/api/`.

If the Django app cannot be imported (bad deploy, missing dependency,
startup crash), requests get a structured 503 JSON response naming the
failure instead of a raw connection error that reads as "the backend is
not responding".

Env knobs:
- API_BRIDGE_SKIP_MIGRATIONS=1  skip the automatic `migrate` on boot
                                (manage migrations elsewhere instead).
"""

from __future__ import annotations

import json
import os
import sys
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartspend.settings")

# The managed proxy serves the app on a deploy-specific public domain that
# isn't known at build time. Default to accepting any Host here — this
# entrypoint only ever runs on the managed host, and requests reach Django
# only through that proxy. Tighten by setting DJANGO_ALLOWED_HOSTS in the
# deployment environment.
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "*")


def _log(message: str) -> None:
    print(f"[api-bridge] {message}", flush=True)


class DjangoApiBridge:
    """Lazily boot Django once, then delegate every request to it."""

    def __init__(self) -> None:
        self._app = None
        self._failed = False

    def _ensure_app(self):
        if self._app is not None:
            return self._app
        if self._failed:
            raise RuntimeError("Django failed to initialize (see earlier logs).")

        _log("booting Django app from backend/ (first request)…")
        import django

        django.setup()

        # Migrate on boot so a fresh database works with no manual step.
        # Cheap when nothing is pending; opt out with
        # API_BRIDGE_SKIP_MIGRATIONS=1.
        if os.environ.get("API_BRIDGE_SKIP_MIGRATIONS", "").strip() != "1":
            from django.core.management import call_command

            _log("applying migrations (API_BRIDGE_SKIP_MIGRATIONS to skip)…")
            call_command("migrate", interactive=False)

            # Keep whitenoise's STATIC_ROOT populated so /admin/ styling
            # works. Failure is non-fatal (cosmetic only).
            try:
                _log("collecting static files…")
                call_command("collectstatic", interactive=False, verbosity=0)
            except Exception as exc:  # noqa: BLE001
                _log(f"collectstatic failed (non-fatal): {exc}")

        from django.core.handlers.wsgi import WSGIHandler
        from django.core.wsgi import get_wsgi_application

        get_wsgi_application()  # finalize settings/apps exactly like wsgi.py
        self._app = WSGIHandler()
        _log("Django ready — serving /api/.")
        return self._app

    def __call__(self, environ, start_response):
        try:
            app = self._ensure_app()
        except Exception as exc:  # noqa: BLE001 - report, don't crash the worker
            self._failed = True
            traceback.print_exc()
            _log(f"FAILED to boot Django: {exc}")
            return _unavailable_response(start_response, exc)
        return app(environ, start_response)


def _unavailable_response(start_response, exc: Exception):
    """Structured 503 so a broken deploy is diagnosable from the outside."""
    debug = False
    try:
        from django.conf import settings

        debug = bool(settings.DEBUG)
    except Exception:  # noqa: BLE001 - settings may be the broken part
        pass

    payload = {
        "detail": "API unavailable: the Django app failed to start.",
        "hint": "Check the deployment logs for the api-bridge traceback.",
        "runtime": "python-bridge",
    }
    if debug:
        payload["error"] = f"{type(exc).__name__}: {exc}"
    body = json.dumps(payload).encode("utf-8")
    start_response(
        "503 Service Unavailable",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ],
    )
    return [body]


# Hosting contracts may import one of these names; all point at the bridge.
app = DjangoApiBridge()
application = app
handler = app
