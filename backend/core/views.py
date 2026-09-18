import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from django.db.models import Sum
from django.db.models.functions import TruncMonth

from .emails import send_login_code_email
from .models import Category, LoginCode, Receipt, ReceiptItem, Store
from .receipt_ai import analyze_receipt
from .reports import build_monthly_audit_pdf
from .serializers import (
    CategorySerializer,
    MonthlyAnalyticsSerializer,
    MonthBreakdownSerializer,
    OCRExtractResultSerializer,
    ReceiptItemSerializer,
    ReceiptSerializer,
    RegisterSerializer,
    RequestLoginCodeSerializer,
    StoreSerializer,
    UserSerializer,
    VerifyLoginCodeSerializer,
)

User = get_user_model()

LOGIN_CODE_TTL_MINUTES = 10
LOGIN_CODE_MAX_ATTEMPTS = 5


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

        recent = LoginCode.objects.filter(
            email=email,
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).count()
        if recent >= 5:
            return Response(
                {'detail': 'Too many codes requested. Try again in a little while.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        code = f'{random.randint(0, 999999):06d}'
        LoginCode.objects.create(
            email=email,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=LOGIN_CODE_TTL_MINUTES),
            request_ip=request.META.get('REMOTE_ADDR'),
        )
        LoginCode.prune_for(email)

        try:
            transport = send_login_code_email(email, code)
        except Exception:  # noqa: BLE001 — never leak provider errors to clients
            return Response(
                {'detail': 'Could not send the email right now. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        dev_hint = {'dev_code': code} if transport == 'console' else {}
        return Response({'detail': f'Code sent to {email}.', 'transport': transport, **dev_hint})


class VerifyLoginCodeView(generics.GenericAPIView):
    """POST /api/auth/verify-login-code/ — exchange email + code for JWTs.

    Signs the user in if the address exists; creates the account on first
    login (the email IS the identity, so nothing to fill in).
    """

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
            user, created = User.objects.get_or_create(email=email)
            if created:
                # Give first-login users a budget prompt rather than a zero default.
                user.monthly_budget_limit = 0
                user.set_unusable_password()
                user.save()

        refresh = TokenObtainPairSerializerForUser.get_token(user)
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
        return (
            Receipt.objects.filter(user=self.request.user)
            .select_related('store')
            .prefetch_related('items', 'items__category')
        )

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
            parsed = analyze_receipt(image, category_names)
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
            'items': [
                {'name': i.name, 'price': i.price, 'category': i.category, 'is_impulse': i.is_impulse}
                for i in parsed.items
            ],
            'raw_text': parsed.raw_text,
            'confidence': parsed.confidence,
            'engine': parsed.engine,
            'notes': parsed.notes,
        })
        return Response(serializer.data)

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


class ReceiptItemViewSet(viewsets.ModelViewSet):
    serializer_class = ReceiptItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return ReceiptItem.objects.filter(receipt__user=self.request.user).select_related('category', 'receipt')
