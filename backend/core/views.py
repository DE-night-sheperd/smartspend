import csv
import io
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from django.db.models import F, Q, Sum
from django.db.models.functions import TruncMonth

from .apple_auth import verify_apple_identity_token
from .budget_advice import build_budget_advice
from .crypto import mask_secret
from .emails import send_login_code_email, send_password_reset_email
from .models import Category, LoginAudit, LoginCode, LoyaltyPoints, Receipt, ReceiptItem, Store
from .receipt_ai import analyze_receipt, analyze_receipt_text, verify_gemini_key
from .reports import build_monthly_audit_pdf
from .serializers import (
    AppleSignInSerializer,
    CategorySerializer,
    ChangePasswordSerializer,
    LoyaltyWriteSerializer,
    MonthlyAnalyticsSerializer,
    MonthBreakdownSerializer,
    OCRExtractResultSerializer,
    ReceiptItemSerializer,
    ReceiptSerializer,
    RegisterSerializer,
    RequestLoginCodeSerializer,
    RequestSmsCodeSerializer,
    RequestWhatsappCodeSerializer,
    LoyaltyDraftSerializer,
    StoreSerializer,
    UserSerializer,
    VerifyLoginCodeSerializer,
    VerifySmsCodeSerializer,
    VerifyWhatsappCodeSerializer,
)
from .sms import send_login_code_sms
from .whatsapp import send_login_code_whatsapp

User = get_user_model()

LOGIN_CODE_TTL_MINUTES = 10
LOGIN_CODE_MAX_ATTEMPTS = 5


def _deliver_login_code(code: LoginCode, channel: str) -> str | None:
    """Deliver a LoginCode to its email address or phone number.

    Returns the transport name ('resend' / 'telnyx') when delivered for
    real, or None when no provider key is configured — in which case the
    code rides back to the client as dev_code so passwordless login stays
    testable with zero configuration. Raises on provider errors so callers
    can return a clean 502.
    """
    if channel in ('sms', 'whatsapp'):
        if not getattr(settings, 'TELNYX_API_KEY', ''):
            return None  # dev mode: no messaging provider configured
        if channel == 'whatsapp':
            return send_login_code_whatsapp(code.email, code.code)
        return send_login_code_sms(code.email, code.code)
    transport = send_login_code_email(code.email, code.code)
    return None if transport == 'console' else transport


def _create_login_code(destination: str, request) -> LoginCode | None:
    """Create a rate-limited login code for an email address or phone
    number (both live in LoginCode.email). Returns None when the
    per-destination hourly limit is hit so callers can return 429."""
    recent = LoginCode.objects.filter(
        email=destination,
        created_at__gte=timezone.now() - timedelta(hours=1),
    ).count()
    if recent >= 5:
        return None
    code_obj = LoginCode.objects.create(
        email=destination,
        code=f'{random.randint(0, 999999):06d}',
        expires_at=timezone.now() + timedelta(minutes=LOGIN_CODE_TTL_MINUTES),
        request_ip=request.META.get('REMOTE_ADDR'),
    )
    LoginCode.prune_for(destination)
    return code_obj


class RegisterView(generics.CreateAPIView):
    """Public sign-up endpoint. Everything else requires a JWT."""

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH the logged-in user's own profile (budget limit, name, etc)."""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def patch(self, request, *args, **kwargs):
        """Re-issue the code to the *new* email/phone on the fly when one was
        provided, so changing your email or phone ends with a verified
        channel instead of silently losing access."""
        response = super().patch(request, *args, **kwargs)
        new_email = (request.data.get('email') or '').strip().lower()
        new_phone = (request.data.get('phone') or '').strip()
        current = request.user
        try:
            code_obj = None
            if new_email and new_email != current.email:
                code_obj = _create_login_code(new_email, request)
                _deliver_login_code(code_obj, 'email')
            elif new_phone and new_phone != current.phone:
                code_obj = _create_login_code(new_phone, request)
                _deliver_login_code(code_obj, 'sms')
        except Exception:  # noqa: BLE001 — delivery is best-effort; profile save already happened
            pass
        return response


def _delivery_error_response(exc: Exception, channel: str = 'email') -> Response:
    """502 for a failed provider send, with the provider's actionable hint
    when there is one (e.g. Resend testing mode: no verified domain) so the
    user sees WHY codes aren't arriving instead of a generic failure."""
    hint = getattr(exc, 'hint', '')
    if hint:
        return Response(
            {'detail': f"Could not send the {channel} right now. {hint}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response(
        {'detail': f"Could not send the {channel} right now. Please try again."},
        status=status.HTTP_502_BAD_GATEWAY,
    )


def _deliver_password_reset(destination: str, code_obj: LoginCode) -> None:
    """Deliver a password-reset code by email. Raises on provider errors so
    the caller can return a clean 502."""
    send_password_reset_email(destination, code_obj.code)


class RequestLoginCodeView(generics.GenericAPIView):
    """POST /api/auth/login-code/ — email a single-use 6-digit login code.

    Always responds 200 (never reveals whether the address is registered;
    verification creates the account on first login). Rate-limited in-app:
    max 5 codes per email per rolling hour.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = RequestLoginCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        code_obj = _create_login_code(email, request)
        if code_obj is None:
            return Response(
                {'detail': 'Too many codes requested. Try again in a little while.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            transport = _deliver_login_code(code_obj, 'email')
        except Exception as exc:  # noqa: BLE001 — never leak provider internals to clients
            return _delivery_error_response(exc)

        dev_hint = {'dev_code': code_obj.code} if transport is None else {}
        return Response({'detail': f'Code sent to {email}.', 'transport': transport, **dev_hint})


class RequestPasswordResetView(generics.GenericAPIView):
    """POST /api/auth/password-reset/ — email a single-use 6-digit reset
    code to a REGISTERED address. Unregistered addresses get the same 200
    shape with no email sent, so the endpoint can't be used to probe which
    accounts exist. Same 5-codes-per-hour rate limit as login codes."""

    permission_classes = [permissions.AllowAny]
    serializer_class = RequestLoginCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        user = User.objects.filter(email=email).first()
        if user is None:
            # Don't reveal whether the address is registered.
            return Response({'detail': f'If that address is registered, a reset code is on its way to {email}.'})

        code_obj = _create_login_code(email, request)
        if code_obj is None:
            return Response(
                {'detail': 'Too many codes requested. Try again in a little while.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            _deliver_password_reset(email, code_obj)
        except Exception as exc:  # noqa: BLE001 — never leak provider internals to clients
            return _delivery_error_response(exc)

        # No dev_code here: the code grants account access, so it must only
        # ever ride the email channel.
        return Response({'detail': f'If that address is registered, a reset code is on its way to {email}.'})


class VerifyPasswordResetCodeView(generics.GenericAPIView):
    """POST /api/auth/password-reset/verify/ — check a reset code WITHOUT
    consuming it, and report whether the account logs in with a password.
    Consuming happens only in the confirm step, so a verified-but-abandoned
    reset doesn't burn the code. Code-login accounts (no usable password)
    are told to log in with a code instead."""

    permission_classes = [permissions.AllowAny]
    serializer_class = VerifyLoginCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        login_code = (
            LoginCode.objects.filter(email=email, consumed_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        if not login_code or login_code.expires_at < timezone.now():
            return Response(
                {'detail': 'That code is invalid or expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if login_code.attempts >= LOGIN_CODE_MAX_ATTEMPTS:
            return Response(
                {'detail': 'Too many wrong attempts. Request a new code.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if login_code.code != code:
            LoginCode.objects.filter(pk=login_code.pk).update(attempts=login_code.attempts + 1)
            return Response(
                {'detail': 'That code is invalid or expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email=email).first()
        if user is None or not user.has_usable_password():
            return Response(
                {'detail': 'This account signs in with one-time codes. Log in with a code instead — no password needed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'detail': 'Code verified — choose a new password.', 'verified': True})


class ConfirmPasswordResetView(generics.GenericAPIView):
    """POST /api/auth/password-reset/confirm/ — set a new password using a
    valid reset code. The code is consumed (single-use) and Django's normal
    password validators apply to the new value."""

    permission_classes = [permissions.AllowAny]
    serializer_class = VerifyLoginCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']
        new_password = str(request.data.get('new_password') or '')

        user = User.objects.filter(email=email).first()
        if user is None:
            return Response(
                {'detail': 'That code is invalid or expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        login_code = (
            LoginCode.objects.filter(email=email, consumed_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        invalid = Response({'detail': 'That code is invalid or expired.'}, status=status.HTTP_400_BAD_REQUEST)
        if not login_code or login_code.expires_at < timezone.now():
            return invalid
        if login_code.attempts >= LOGIN_CODE_MAX_ATTEMPTS:
            return Response(
                {'detail': 'Too many wrong attempts. Request a new code.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if login_code.code != code:
            LoginCode.objects.filter(pk=login_code.pk).update(attempts=login_code.attempts + 1)
            return invalid

        from django.contrib.auth.password_validation import validate_password

        try:
            validate_password(new_password, user=user)
        except Exception as exc:  # noqa: BLE001 — DRF maps ValidationError messages for us
            return Response({'new_password': [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=['password'])
        login_code.consumed_at = timezone.now()
        login_code.save(update_fields=['consumed_at'])
        return Response({'detail': 'Password updated. You can log in with it now.'})


class VerifyLoginCodeView(generics.GenericAPIView):
    """POST /api/auth/verify-login-code/ — exchange email + code for JWTs.

    Signs the user in if the address exists; creates the account on first
    login (the email IS the identity, so nothing to fill in).
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = VerifyLoginCodeSerializer
    identity_defaults: dict = {}

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        destination = serializer.validated_data['email']
        code = serializer.validated_data['code']
        return _verify_and_sign_in(destination, code, request, 'email', self.identity_defaults)


class RequestSmsCodeView(RequestLoginCodeView):
    """POST /api/auth/login-code/sms/ — text a single-use 6-digit login
    code. Same rate limit (5/hour), same code model, same 200 shape; the
    only differences are the phone number input and the delivery channel.

    Without TELNYX_API_KEY the response carries dev_code so the flow stays
    testable; with the key configured the code is delivered by SMS only.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = RequestSmsCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data['phone']

        code_obj = _create_login_code(phone, request)
        if code_obj is None:
            return Response(
                {'detail': 'Too many codes requested. Try again in a little while.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            transport = _deliver_login_code(code_obj, 'sms')
        except Exception as exc:  # noqa: BLE001 — never leak provider internals to clients
            return _delivery_error_response(exc, 'SMS')

        dev_hint = {'dev_code': code_obj.code} if transport is None else {}
        return Response({'detail': f'Code sent to {phone}.', 'transport': transport or 'dev', **dev_hint})


class VerifySmsCodeView(VerifyLoginCodeView):
    """POST /api/auth/verify-login-code/sms/ — exchange phone + code for
    JWTs. The phone number IS the identity here: first login creates the
    account with email = phone so both channels converge on one Users row
    (the email/phone is editable later from Settings).
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = VerifySmsCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        destination = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        return _verify_and_sign_in(destination, code, request, 'sms', {'phone': destination})


class RequestWhatsappCodeView(RequestSmsCodeView):
    """POST /api/auth/login-code/whatsapp/ — send the 6-digit login code as
    a WhatsApp message. Shares the phone normalization, rate limit, code
    model and response shape with the SMS view; only the delivery channel
    differs (Telnyx Messages API, type=whatsapp — same TELNYX_API_KEY).

    Without a WhatsApp-enabled sender the response carries dev_code so the
    flow stays testable; once TELNYX_API_KEY and a WhatsApp profile exist
    the code is delivered by WhatsApp only.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = RequestWhatsappCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data['phone']

        code_obj = _create_login_code(phone, request)
        if code_obj is None:
            return Response(
                {'detail': 'Too many codes requested. Try again in a little while.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            transport = _deliver_login_code(code_obj, 'whatsapp')
        except Exception as exc:  # noqa: BLE001 — never leak provider internals to clients
            return _delivery_error_response(exc, 'WhatsApp message')

        dev_hint = {'dev_code': code_obj.code} if transport is None else {}
        return Response({'detail': f'Code sent to {phone}.', 'transport': transport or 'dev', **dev_hint})


class VerifyWhatsappCodeView(VerifySmsCodeView):
    """POST /api/auth/verify-login-code/whatsapp/ — exchange phone + code
    for JWTs via the WhatsApp channel (same identity rules as SMS)."""

    permission_classes = [permissions.AllowAny]
    serializer_class = VerifyWhatsappCodeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        destination = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        return _verify_and_sign_in(destination, code, request, 'whatsapp', {'phone': destination})


class MeLoginsView(generics.ListAPIView):
    """GET /api/me/logins/ — this user's sign-in audit trail (newest
    first), plus the aggregate counters. Part of the public-ish surface for
    auditing: the user can see every successful access to their account,
    with the channel, timestamp and IP."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # audit trail is a plain array, newest first

    class Serializer(serializers.Serializer):
        """Read-only projection — no write surface anywhere."""

        login_count = serializers.IntegerField(source='user.login_count')
        last_login_at = serializers.DateTimeField(source='user.last_login_at')
        method = serializers.CharField()
        created_at = serializers.DateTimeField()
        ip = serializers.IPAddressField()
        user_agent = serializers.CharField()

    serializer_class = Serializer

    def get_queryset(self):
        return (
            LoginAudit.objects.filter(user=self.request.user)
            .select_related('user')
            .only('method', 'created_at', 'ip', 'user_agent', 'user__login_count', 'user__last_login_at')
        )


class AuthConfigView(generics.GenericAPIView):
    """GET /api/auth/config/ — public capability flags so the login page
    can render honest buttons: Apple sign-in only when configured, and the
    SMS/WhatsApp channel tabs only when a real E.164 sender number exists
    (a Telnyx key alone cannot deliver SMS in ZA without a purchased number,
    so advertising those channels would just dead-end the user)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .apple_auth import apple_sign_in_enabled

        sender = (getattr(settings, 'TELNYX_FROM', '') or '').strip()
        # A real sender is an E.164 phone number; anything else (e.g. the
        # alphanumeric default 'SmartSpend') cannot deliver SA SMS.
        sms_enabled = bool(getattr(settings, 'TELNYX_API_KEY', '')) and sender.startswith('+')
        return Response(
            {
                'apple_enabled': apple_sign_in_enabled(),
                'sms_enabled': sms_enabled,
                'whatsapp_enabled': sms_enabled,
            }
        )


class AppleSignInView(generics.GenericAPIView):
    """POST /api/auth/apple/ — exchange a Sign in with Apple identity
    token for SmartSpend JWTs. The token's signature, issuer, audience and
    expiry are verified against Apple's published keys before the email
    claim is trusted; first login creates the account.

    Requires APPLE_CLIENT_ID to be configured (the Services/Bundle ID the
    frontend Apple button uses); otherwise answers 503.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = AppleSignInSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity_token = serializer.validated_data['identity_token']

        try:
            claims = verify_apple_identity_token(identity_token)
        except RuntimeError:
            return Response(
                {'detail': 'Apple sign-in is not configured on this server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:  # noqa: BLE001 — any jwt validation failure
            return Response(
                {'detail': 'That Apple sign-in could not be verified. Please try again.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = (claims.get('email') or '').strip().lower()
        if not email:
            return Response(
                {'detail': 'Your Apple account did not share an email address.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Apple private-relay addresses are real, deliverable inboxes — fine
        # as the identity. Display name only arrives on the FIRST consent, in
        # a separate `user` field of the Apple response; the frontend may
        # pass it along so new accounts do not start anonymous.
        defaults = {}
        apple_name = (request.data.get('name') or '').strip()
        if apple_name:
            parts = apple_name.split(' ', 1)
            defaults['first_name'] = parts[0][:150]
            if len(parts) > 1:
                defaults['last_name'] = parts[1][:150]

        with transaction.atomic():
            user, created = User.objects.get_or_create(email=email, defaults=defaults)
            if created:
                user.monthly_budget_limit = 0
                user.set_unusable_password()
                user.save()

        refresh = TokenObtainPairSerializerForUser.get_token(user)
        record_login(user, request, LoginAudit.Method.APPLE)
        return Response(
            {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': UserSerializer(user).data,
                'created_account': created,
            },
            status=status.HTTP_200_OK,
        )


class TokenObtainPairSerializerForUser:
    """Minimal stand-in for simplejwt's serializer so code-login can mint
    tokens with the same claims (user_id) as the password endpoint."""

    @staticmethod
    def get_token(user):
        from rest_framework_simplejwt.tokens import RefreshToken

        token = RefreshToken.for_user(user)
        # Match SIMPLE_JWT settings: our PK field is user_id.
        token['user_id'] = str(user.user_id)
        return token


def record_login(user, request, method: LoginAudit.Method) -> None:
    """Audit a successful sign-in: bump the user's counters and append a
    LoginAudit row. Called from every path that mints tokens (password,
    email/SMS/WhatsApp code, Apple) so the trail is complete no matter how
    the user got in. Never raises — auditing must not block a login."""
    try:
        type(user).objects.filter(pk=user.pk).update(
            login_count=F('login_count') + 1,
            last_login_at=timezone.now(),
        )
        LoginAudit.objects.create(
            user=user,
            method=method,
            ip=request.META.get('REMOTE_ADDR') or None,
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:300],
        )
    except Exception:  # noqa: BLE001 — auditing must never block a login
        pass


class PasswordLoginAuditView(TokenObtainPairView):
    """POST /api/auth/login/ — simplejwt's token pair, plus a login-audit
    row. Wrapping the view (rather than the serializer) keeps the audit
    recording at the same layer as the other channels."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200 and isinstance(response.data, dict) and 'access' in response.data:
            user = User.objects.filter(email__iexact=str(request.data.get('email') or '')).first()
            if user is not None:
                record_login(user, request, LoginAudit.Method.PASSWORD)
        return response


def _verify_and_sign_in(destination: str, code: str, request, channel: str = 'email',
                        identity_defaults: dict | None = None):
    """Shared verifier for the email and SMS/WhatsApp code flows: checks
    the code, consumes it, creates the account on first login, audits the
    login, and mints JWTs. `channel` picks the audit method."""
    login_code = (
        LoginCode.objects.filter(email=destination, consumed_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    invalid = Response({'detail': 'That code is invalid or expired.'}, status=status.HTTP_400_BAD_REQUEST)

    if not login_code or login_code.expires_at < timezone.now():
        return invalid
    if login_code.attempts >= LOGIN_CODE_MAX_ATTEMPTS:
        return Response(
            {'detail': 'Too many wrong attempts. Request a new code.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if login_code.code != code:
        LoginCode.objects.filter(pk=login_code.pk).update(attempts=login_code.attempts + 1)
        return invalid

    login_code.consumed_at = timezone.now()
    login_code.save(update_fields=['consumed_at'])

    with transaction.atomic():
        user, created = User.objects.get_or_create(
            email=destination, defaults=identity_defaults or {}
        )
        if created:
            # Give first-login users a budget prompt rather than a zero default.
            user.monthly_budget_limit = 0
            user.set_unusable_password()
            user.save()

    refresh = TokenObtainPairSerializerForUser.get_token(user)
    record_login(
        user,
        request,
        {
            'email': LoginAudit.Method.EMAIL_CODE,
            'sms': LoginAudit.Method.SMS_CODE,
            'whatsapp': LoginAudit.Method.WHATSAPP_CODE,
        }[channel],
    )
    return Response(
        {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
            'created_account': created,
        },
        status=status.HTTP_200_OK,
    )


class GeminiKeyStatusView(generics.GenericAPIView):
    """GET /api/me/gemini-key/ — connection status without ever returning
    the key itself."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        connected = request.user.has_gemini_key
        return Response({
            'connected': connected,
            'key_hint': mask_secret(request.user.gemini_key) if connected else '',
        })


class GeminiKeyConnectView(generics.GenericAPIView):
    """POST /api/me/gemini-key/connect/ — connect the user's own Gemini
    API key (BYOK). Google has no OAuth flow that mints Gemini keys for a
    third-party app, so the flow is: send the user to AI Studio (they're
    signed in as themselves), they create a free key, paste it here; we
    verify it against Google and store it encrypted at rest.

    Their scans then use their key/quota before the server's shared key;
    disconnecting removes it. Keys are never returned by any endpoint.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        raw_key = str(request.data.get('api_key') or '').strip()
        if not raw_key:
            raise ParseError('Send the key under the "api_key" field.')
        if len(raw_key) > 256:
            return Response(
                {'detail': 'That does not look like a Gemini API key.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ok, message = verify_gemini_key(raw_key)
        if not ok:
            return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_gemini_key(raw_key)
        request.user.save(update_fields=['gemini_key_encrypted'])
        return Response({
            'detail': message,
            'connected': True,
            'key_hint': mask_secret(request.user.gemini_key),
        })


class GeminiKeyDisconnectView(generics.GenericAPIView):
    """POST /api/me/gemini-key/disconnect/ — forget the stored key."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        request.user.clear_gemini_key()
        request.user.save(update_fields=['gemini_key_encrypted'])
        return Response({'connected': False})


class StoreViewSet(viewsets.ModelViewSet):
    """Shared reference data — every authenticated user can read/add stores."""

    queryset = Store.objects.all()
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]


class CategoryViewSet(viewsets.ModelViewSet):
    """Shared reference data — every authenticated user can read/add categories."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]


class IsOwner(permissions.BasePermission):
    """Application-level equivalent of the Postgres RLS policies in the spec:
    `auth.uid() = user_id`. Enforced here in Python for SQLite dev; when the
    project moves to Supabase/Postgres, mirror this with the RLS SQL in
    infra/rls_policies.sql so the same guarantee holds at the DB layer too.
    """

    def has_object_permission(self, request, view, obj):
        owner = obj.user if hasattr(obj, 'user') else obj.receipt.user
        return owner == request.user


class ReceiptViewSet(viewsets.ModelViewSet):
    serializer_class = ReceiptSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        # RLS equivalent: never return another user's receipts.
        qs = (
            Receipt.objects.filter(user=self.request.user)
            .select_related('store')
            .prefetch_related('items', 'items__category')
        )

        params = self.request.query_params
        # ?search= matches store or any line-item name.
        search = (params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(store__store_name__icontains=search) | Q(items__item_name__icontains=search)
            ).distinct()
        # ?store=<id> and ?category=<id> exact filters (dropdown-driven).
        store_id = params.get('store')
        if store_id:
            qs = qs.filter(store_id=store_id)
        category_id = params.get('category')
        if category_id:
            qs = qs.filter(items__category_id=category_id).distinct()
        # ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD inclusive range.
        date_from, date_to = params.get('date_from'), params.get('date_to')
        if date_from:
            qs = qs.filter(purchase_date__gte=date_from)
        if date_to:
            qs = qs.filter(purchase_date__lte=date_to)
        # ?ordering=-purchase_date | purchase_date | -total_amount | total_amount
        ordering = params.get('ordering')
        if ordering in ('purchase_date', '-purchase_date', 'total_amount', '-total_amount'):
            qs = qs.order_by(ordering, '-created_at')
        return qs

    @action(detail=False, methods=['get'], url_path='export')
    def export_csv(self, request):
        """Full data export: every receipt and line item as CSV, honouring the
        same search/filter params as the list endpoint."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ['receipt_id', 'store', 'channel', 'date', 'item', 'category',
             'quantity', 'unit_price', 'line_total', 'is_impulse', 'receipt_total']
        )
        receipts = self.get_queryset().prefetch_related('items', 'items__category')
        for r in receipts:
            for i in r.items.all():
                writer.writerow(
                    [r.receipt_id, r.store.store_name, r.store.channel_type, r.purchase_date,
                     i.item_name, i.category.category_name, i.quantity, i.unit_price,
                     i.line_total, i.is_impulse, r.total_amount]
                )
        response = HttpResponse(buffer.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="smartspend-receipts.csv"'
        return response

    @action(detail=False, methods=['get'])
    def monthly_analytics(self, request):
        """Equivalent of the `user_monthly_analytics` SQL view in the spec.

        Grouped by calendar month: total spend, impulse (non-essential)
        spend, and variance against the user's monthly_budget_limit.
        line_total (unit_price * quantity) is computed in Python here since
        it's a DB-generated column on Postgres but not on SQLite dev.
        """
        results = []
        budget_limit = request.user.monthly_budget_limit
        months = (
            Receipt.objects.filter(user=request.user)
            .annotate(month=TruncMonth('purchase_date'))
            .values('month')
            .annotate(total_spent=Sum('total_amount'))
            .order_by('-month')
        )
        for row in months:
            month = row['month']
            impulse = ReceiptItem.objects.filter(
                receipt__user=request.user,
                receipt__purchase_date__year=month.year,
                receipt__purchase_date__month=month.month,
                category__is_essential=False,
            )
            impulse_total = sum(i.line_total for i in impulse)
            total_spent = row['total_spent'] or 0
            results.append({
                'audit_month': month,
                'total_spent': total_spent,
                'impulse_spend': impulse_total,
                'monthly_budget_limit': budget_limit,
                'budget_variance': budget_limit - total_spent,
            })
        serializer = MonthlyAnalyticsSerializer(results, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='month_breakdown')
    def month_breakdown(self, request):
        """Deep-dive analytics for one month: daily totals, category totals,
        per-store totals, channel split, essential vs impulse, and the
        biggest single purchase. Query params: ?year=2026&month=8."""
        today = timezone.now().date()
        try:
            year = int(request.query_params.get('year', today.year))
            month = int(request.query_params.get('month', today.month))
        except (TypeError, ValueError):
            raise ParseError('year and month must be integers')
        if not 1 <= month <= 12:
            raise ParseError('month must be 1-12')

        receipts = list(
            Receipt.objects.filter(user=request.user, purchase_date__year=year, purchase_date__month=month)
            .select_related('store')
        )
        items = list(
            ReceiptItem.objects.filter(
                receipt__user=request.user, receipt__purchase_date__year=year, receipt__purchase_date__month=month
            ).select_related('category', 'receipt')
        )

        total_spent = sum((r.total_amount for r in receipts), start=Decimal('0'))
        impulse_spend = sum(
            (i.line_total for i in items if i.is_impulse or not i.category.is_essential),
            start=Decimal('0'),
        )
        essential_spend = sum(
            (i.line_total for i in items if not (i.is_impulse or not i.category.is_essential)),
            start=Decimal('0'),
        )

        daily_totals: dict[str, Decimal] = {}
        for r in receipts:
            key = r.purchase_date.isoformat()
            daily_totals[key] = daily_totals.get(key, Decimal('0')) + r.total_amount

        cat_totals: dict[str, dict] = {}
        for i in items:
            entry = cat_totals.setdefault(
                i.category.category_name,
                {'category_name': i.category.category_name, 'is_essential': i.category.is_essential,
                 'total': Decimal('0'), 'item_count': 0},
            )
            entry['total'] += i.line_total
            entry['item_count'] += 1

        store_totals: dict[str, dict] = {}
        for r in receipts:
            entry = store_totals.setdefault(
                r.store.store_name,
                {'store_name': r.store.store_name, 'channel_type': r.store.channel_type,
                 'total': Decimal('0'), 'receipt_count': 0},
            )
            entry['total'] += r.total_amount
            entry['receipt_count'] += 1

        channels: dict[str, Decimal] = {}
        for r in receipts:
            channels[r.store.channel_type] = channels.get(r.store.channel_type, Decimal('0')) + r.total_amount

        biggest = max(items, key=lambda i: i.line_total, default=None)

        budget = request.user.monthly_budget_limit
        data = {
            'year': year,
            'month': month,
            'total_spent': total_spent,
            'impulse_spend': impulse_spend,
            'essential_spend': essential_spend,
            'budget_limit': budget,
            'budget_variance': budget - total_spent,
            'daily_totals': {k: v for k, v in sorted(daily_totals.items())},
            'categories': sorted(cat_totals.values(), key=lambda e: -e['total']),
            'stores': sorted(store_totals.values(), key=lambda e: -e['total']),
            'channels': channels,
            'biggest_purchase': (
                {'item_name': biggest.item_name, 'line_total': biggest.line_total,
                 'store_name': biggest.receipt.store.store_name, 'purchase_date': biggest.receipt.purchase_date}
                if biggest else None
            ),
        }
        return Response(MonthBreakdownSerializer(data).data)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def ocr_extract(self, request):
        """Stage 2 of the pipeline: AI receipt analysis. Returns best-guess
        structured fields (merchant, date, total, line items with suggested
        categories + impulse flags). Nothing is saved — the frontend pre-fills
        the verification form with this and the user corrects it before
        POSTing a real receipt to this same viewset."""
        image = request.FILES.get('image')
        if not image:
            raise ParseError('Attach the receipt image under the "image" field.')

        category_names = list(Category.objects.values_list('category_name', flat=True))
        try:
            parsed = analyze_receipt(image, category_names, user_key=request.user.gemini_key or None)
        except Exception as exc:  # noqa: BLE001 — extraction failures shouldn't 500 the app
            return Response(
                {'detail': f'Could not read this image: {exc}'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        serializer = OCRExtractResultSerializer({
            'merchant_name': parsed.merchant_name,
            'purchase_date': parsed.purchase_date,
            'total_amount': parsed.total_amount,
            'channel_type': parsed.channel_type,
            'cashier': parsed.cashier,
            'branch': parsed.branch,
            'slip_number': parsed.slip_number,
            'payment_method': parsed.payment_method,
            'original_lines': parsed.original_lines,
            'items': [
                {'name': i.name, 'price': i.price, 'category': i.category, 'is_impulse': i.is_impulse}
                for i in parsed.items
            ],
            'raw_text': parsed.raw_text,
            'confidence': parsed.confidence,
            'engine': parsed.engine,
            'notes': parsed.notes,
            'loyalty_points': [
                {'points': l.points, 'label': l.label, 'expires_at': l.expires_at}
                for l in parsed.loyalty
            ],
        })
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def extract_text(self, request):
        """Digital-receipt intake for e-receipts (Uber, Bolt, Takealot, …):
        paste or forward the receipt TEXT and get back the same structured
        draft as ocr_extract — merchant, date, total, line items with
        categories and impulse flags. Nothing is saved; the user reviews
        the draft in the verification form before saving.

        Body: {"text": "<the receipt contents>"}.
        """
        text = (request.data.get('text') or '').strip()
        if not text:
            raise ParseError('Send the receipt contents under the "text" field.')
        if len(text) > 20000:
            raise ParseError('That receipt text is too long (20000 character limit).')

        category_names = list(Category.objects.values_list('category_name', flat=True))
        try:
            parsed = analyze_receipt_text(text, category_names, user_key=request.user.gemini_key or None)
        except Exception as exc:  # noqa: BLE001 — extraction failures shouldn't 500 the app
            return Response(
                {'detail': f'Could not read this receipt text: {exc}'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        serializer = OCRExtractResultSerializer({
            'merchant_name': parsed.merchant_name,
            'purchase_date': parsed.purchase_date,
            'total_amount': parsed.total_amount,
            'channel_type': parsed.channel_type,
            'cashier': parsed.cashier,
            'branch': parsed.branch,
            'slip_number': parsed.slip_number,
            'payment_method': parsed.payment_method,
            'original_lines': parsed.original_lines,
            'items': [
                {'name': i.name, 'price': i.price, 'category': i.category, 'is_impulse': i.is_impulse}
                for i in parsed.items
            ],
            'raw_text': parsed.raw_text,
            'confidence': parsed.confidence,
            'engine': parsed.engine,
            'notes': parsed.notes,
            'loyalty_points': [
                {'points': l.points, 'label': l.label, 'expires_at': l.expires_at}
                for l in parsed.loyalty
            ],
        })
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='budget_advice')
    def budget_advice(self, request):
        """Automated budget-adjustment suggestions for one month: concrete
        "cut X to save Y" moves ranked by what they're worth, computed from
        this user's own receipts (categories, impulse flags, pacing, store
        frequency, month-over-month trend). Query params: ?year=&month=."""
        today = timezone.now().date()
        try:
            year = int(request.query_params.get('year', today.year))
            month = int(request.query_params.get('month', today.month))
        except (TypeError, ValueError):
            raise ParseError('year and month must be integers')
        if not 1 <= month <= 12:
            raise ParseError('month must be 1-12')
        return Response(build_budget_advice(request.user, year, month))

    @action(detail=False, methods=['get'])
    def monthly_audit_pdf(self, request):
        """Stage 5 of the pipeline: downloadable Monthly Financial Audit PDF
        (spec section 6). Query params: ?year=2026&month=8 (defaults to the
        current month)."""
        today = timezone.now().date()
        year = int(request.query_params.get('year', today.year))
        month = int(request.query_params.get('month', today.month))
        pdf_bytes = build_monthly_audit_pdf(request.user, year, month)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        filename = f'smartspend-audit-{year}-{month:02d}.pdf'
        response['Content-Disposition'] = f'attachment; filename=\"{filename}\"'
        return response


class ChangePasswordView(generics.GenericAPIView):
    """POST /api/me/password/ — change password with the current one."""

    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Password updated.'})


class CronDailyView(generics.GenericAPIView):
    """POST /api/cron/daily/ — the scheduler entrypoint for automated
    notifications: points-expiry emails (7-day and 1-day warnings) and
    budget alerts (80% used / over budget). Guarded by a shared secret so
    only the scheduler can fire it; safe to call repeatedly (per-user,
    per-period dedup in the BudgetAlert ledger)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        secret = getattr(settings, 'CRON_SECRET_KEY', '')
        provided = (request.headers.get('X-Cron-Key') or '')
        if not secret:
            return Response(
                {'detail': 'CRON_SECRET_KEY is not configured on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if provided != secret:
            return Response({'detail': 'Invalid cron key.'}, status=status.HTTP_403_FORBIDDEN)
        from .reminders import run_daily

        summary = run_daily()
        return Response({'detail': 'Daily reminders processed.', **summary})


class LoyaltyPointsViewSet(viewsets.ModelViewSet):
    """Spendable loyalty points per store (Smart Shopper, ClubCard, …).

    GET /api/points/            — all of the user's points, soonest expiry first
    GET /api/points/?active=1   — only unexpired (or never-expiring) points
    GET /api/points/?store=<id> — one store's points
    """

    serializer_class = LoyaltyWriteSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        # Default view = points the user can still use today. ?include_expired=1
        # brings back lapsed blocks (handy for history); ?active=1 stays as an
        # explicit alias for the same behaviour.
        today = timezone.now().date()
        queryset = LoyaltyPoints.objects.filter(user=self.request.user)
        include_expired = (
            self.request.query_params.get('include_expired') == '1'
            and self.request.query_params.get('active') != '1'
        )
        if not include_expired:
            queryset = queryset.filter(
                Q(expires_at__isnull=True) | Q(expires_at__gte=today)
            )
        store_id = self.request.query_params.get('store')
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        return queryset.select_related('store')

    def list(self, request, *args, **kwargs):
        # Custom shape: flat rows with the fields the Points page renders.
        rows = [
            {
                'points_id': p.points_id,
                'store_id': p.store_id,
                'store_name': p.store.store_name,
                'label': p.label,
                'points': p.points,
                'expires_at': p.expires_at,
                'created_at': p.created_at,
            }
            for p in self.get_queryset()
        ]
        return Response({'count': len(rows), 'results': rows})

    def perform_create(self, serializer):
        # POST /points/ mirrors the list response so the client can prepend
        # the new row without a refetch round-trip.
        instance = serializer.save()
        self._created = instance

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        p = self._created
        return Response(
            {
                'points_id': p.points_id,
                'store_id': p.store_id,
                'store_name': p.store.store_name,
                'label': p.label,
                'points': p.points,
                'expires_at': p.expires_at,
                'created_at': p.created_at,
            },
            status=status.HTTP_201_CREATED,
        )


class ReceiptItemViewSet(viewsets.ModelViewSet):
    serializer_class = ReceiptItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return ReceiptItem.objects.filter(receipt__user=self.request.user).select_related('category', 'receipt')
