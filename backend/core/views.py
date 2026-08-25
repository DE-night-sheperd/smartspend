from django.contrib.auth import get_user_model
from django.db.models import Sum, Case, When, DecimalField, Value
from django.db.models.functions import TruncMonth
from rest_framework import generics, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Category, Receipt, ReceiptItem, Store
from .serializers import (
    CategorySerializer,
    MonthlyAnalyticsSerializer,
    ReceiptItemSerializer,
    ReceiptSerializer,
    RegisterSerializer,
    StoreSerializer,
    UserSerializer,
)

User = get_user_model()


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
            impulse = (
                ReceiptItem.objects.filter(
                    receipt__user=request.user,
                    receipt__purchase_date__year=month.year,
                    receipt__purchase_date__month=month.month,
                    category__is_essential=False,
                )
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


class ReceiptItemViewSet(viewsets.ModelViewSet):
    serializer_class = ReceiptItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return ReceiptItem.objects.filter(receipt__user=self.request.user).select_related('category', 'receipt')
