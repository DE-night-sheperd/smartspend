from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import Category, Receipt, ReceiptItem, Store
from .receipt_ai import ParsedReceipt

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'user_id', 'email', 'phone', 'first_name', 'last_name',
            'monthly_budget_limit', 'created_at',
        ]
        read_only_fields = ['user_id', 'created_at']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'password', 'monthly_budget_limit']

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class RequestLoginCodeSerializer(serializers.Serializer):
    """Input for POST /api/auth/login-code/."""

    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class VerifyLoginCodeSerializer(serializers.Serializer):
    """Input for POST /api/auth/verify-login-code/. On success the view
    attaches JWT tokens to the response instead of echoing the input."""

    email = serializers.EmailField()
    code = serializers.RegexField(r'^\d{6}$')

    def validate_email(self, value):
        return value.strip().lower()


def _normalize_phone(value: str) -> str:
    """Normalise a phone number to E.164-ish: strip spaces/dashes/brackets
    and force a single leading +. A local 0-prefixed number (e.g.
    "082 123 4567") is treated as South African and becomes +27…; callers
    abroad can always enter the full international format."""
    cleaned = ''.join(ch for ch in value if ch.isdigit() or ch == '+')
    if cleaned.startswith('00'):
        cleaned = '+' + cleaned[2:]
    elif cleaned.startswith('+'):
        pass
    elif cleaned.startswith('0'):
        cleaned = '+27' + cleaned[1:]
    else:
        cleaned = '+' + cleaned
    return cleaned


def _validated_phone(value: str) -> str:
    phone = _normalize_phone(value)
    digits = phone[1:]
    if not digits.isdigit() or not 7 <= len(digits) <= 15:
        raise serializers.ValidationError('Enter a valid phone number, e.g. +27821234567.')
    return phone


class RequestSmsCodeSerializer(serializers.Serializer):
    """Input for POST /api/auth/login-code/sms/."""

    phone = serializers.CharField(min_length=8, max_length=24)

    def validate_phone(self, value):
        return _validated_phone(value)


class VerifySmsCodeSerializer(serializers.Serializer):
    """Input for POST /api/auth/verify-login-code/sms/."""

    phone = serializers.CharField(min_length=8, max_length=24)
    code = serializers.RegexField(r'^\d{6}$')

    def validate_phone(self, value):
        return _validated_phone(value)


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ['store_id', 'store_name', 'channel_type', 'created_at']
        read_only_fields = ['store_id', 'created_at']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['category_id', 'category_name', 'is_essential']
        read_only_fields = ['category_id']


class CategoryNameOrPKField(serializers.Field):
    """Accepts a category pk (int) or a category name (string) on input;
    always returns a Category instance, matching-or-creating by name.
    Serializes back to the pk so the API shape stays unchanged."""

    def to_internal_value(self, value):
        if value in (None, ''):
            raise serializers.ValidationError('category is required')
        if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
            try:
                return Category.objects.get(pk=int(value))
            except Category.DoesNotExist:
                pass  # fall through and treat it as a name
        name = str(value).strip()[:100] or 'Other'
        obj, _ = Category.objects.get_or_create(category_name=name)
        return obj

    def to_representation(self, value):
        return value.pk


class ReceiptItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    category_name = serializers.CharField(source='category.category_name', read_only=True)
    category = CategoryNameOrPKField()
    # Not required when nested inside ReceiptSerializer.create(), which sets
    # it explicitly; required when hitting /api/receipt-items/ directly.
    receipt = serializers.PrimaryKeyRelatedField(queryset=Receipt.objects.all(), required=False)

    class Meta:
        model = ReceiptItem
        fields = [
            'item_id', 'receipt', 'category', 'category_name',
            'item_name', 'unit_price', 'quantity', 'line_total', 'is_impulse',
        ]
        read_only_fields = ['item_id']


class ReceiptSerializer(serializers.ModelSerializer):
    items = ReceiptItemSerializer(many=True, required=False)
    store_name = serializers.CharField(source='store.store_name', read_only=True)
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all(), required=False)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = [
            'receipt_id', 'user', 'store', 'store_name', 'purchase_date',
            'total_amount', 'source_type', 'image_url', 'receipt_image', 'verified',
            'created_at', 'items',
        ]
        read_only_fields = ['receipt_id', 'user', 'created_at', 'image_url']
        extra_kwargs = {'receipt_image': {'write_only': False, 'required': False}}

    def get_image_url(self, obj):
        if obj.receipt_image:
            request = self.context.get('request')
            url = obj.receipt_image.url
            return request.build_absolute_uri(url) if request else url
        return None

    def _resolve_store(self, validated_data):
        """Allow creating a store inline by passing store_name instead of
        store — mirrors what the AI draft / quick-add flow needs."""
        store = validated_data.get('store')
        store_name = (self.initial_data.get('store_name') or '').strip()
        if not store and store_name:
            channel = self.initial_data.get('channel_type')
            if channel not in ('Physical_Store', 'Online_Ecommerce'):
                channel = 'Physical_Store'
            store, _ = Store.objects.get_or_create(
                store_name=store_name,
                defaults={'channel_type': channel},
            )
            validated_data['store'] = store
        elif not store:
            raise serializers.ValidationError({'store': 'Provide a store id or a store_name to create one inline.'})
        return validated_data

    def _validate_items(self, items_data):
        """Default missing categories to 'Other' (CategoryNameOrPKField has
        already matched-or-created named categories by this point)."""
        resolved = []
        for item in items_data:
            if not item.get('category'):
                item['category'] = Category.objects.get_or_create(category_name='Other')[0]
            resolved.append(item)
        return resolved

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        validated_data = self._resolve_store(validated_data)
        validated_data['user'] = self.context['request'].user
        items_data = self._validate_items(items_data)
        receipt = Receipt.objects.create(**validated_data)
        for item_data in items_data:
            ReceiptItem.objects.create(receipt=receipt, **item_data)
        return receipt

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        items_data = self._validate_items(items_data) if items_data is not None else None
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                ReceiptItem.objects.create(receipt=instance, **item_data)
        return instance


class OCRItemSerializer(serializers.Serializer):
    name = serializers.CharField()
    price = serializers.FloatField()
    category = serializers.CharField(allow_null=True, required=False)
    is_impulse = serializers.BooleanField(required=False)


class OCRExtractResultSerializer(serializers.Serializer):
    """Draft data returned to the frontend for the user to review/correct —
    nothing is saved to the database at this point (Verification Layer)."""

    merchant_name = serializers.CharField(allow_null=True)
    purchase_date = serializers.CharField(allow_null=True)
    total_amount = serializers.FloatField(allow_null=True)
    channel_type = serializers.ChoiceField(
        choices=['Physical_Store', 'Online_Ecommerce'], allow_null=True, required=False
    )
    items = OCRItemSerializer(many=True)
    raw_text = serializers.CharField()
    confidence = serializers.FloatField()
    engine = serializers.ChoiceField(choices=['gemini', 'tesseract'])
    notes = serializers.ListField(child=serializers.CharField(), required=False)


class MonthlyAnalyticsSerializer(serializers.Serializer):
    """Mirrors the `user_monthly_analytics` SQL view from the spec, computed
    in the ORM so it works identically on SQLite (dev) and Postgres (prod)."""

    audit_month = serializers.DateField()
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2)
    impulse_spend = serializers.DecimalField(max_digits=12, decimal_places=2)
    monthly_budget_limit = serializers.DecimalField(max_digits=10, decimal_places=2)
    budget_variance = serializers.DecimalField(max_digits=12, decimal_places=2)


class CategoryBreakdownSerializer(serializers.Serializer):
    category_name = serializers.CharField()
    is_essential = serializers.BooleanField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    item_count = serializers.IntegerField()


class StoreBreakdownSerializer(serializers.Serializer):
    store_name = serializers.CharField()
    channel_type = serializers.CharField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    receipt_count = serializers.IntegerField()


class MonthBreakdownSerializer(serializers.Serializer):
    """Response shape for /api/receipts/month_breakdown/."""

    year = serializers.IntegerField()
    month = serializers.IntegerField()
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2)
    impulse_spend = serializers.DecimalField(max_digits=12, decimal_places=2)
    essential_spend = serializers.DecimalField(max_digits=12, decimal_places=2)
    budget_limit = serializers.DecimalField(max_digits=10, decimal_places=2)
    budget_variance = serializers.DecimalField(max_digits=12, decimal_places=2)
    daily_totals = serializers.DictField(child=serializers.DecimalField(max_digits=10, decimal_places=2))
    categories = CategoryBreakdownSerializer(many=True)
    stores = StoreBreakdownSerializer(many=True)
    channels = serializers.DictField(child=serializers.DecimalField(max_digits=12, decimal_places=2))
    biggest_purchase = serializers.DictField()
