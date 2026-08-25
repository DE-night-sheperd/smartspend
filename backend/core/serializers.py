from django.contrib.auth import get_user_model
from django.db.models import Sum, Case, When, F, DecimalField
from django.utils import timezone
from rest_framework import serializers

from .models import Category, Receipt, ReceiptItem, Store

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['user_id', 'email', 'first_name', 'last_name', 'monthly_budget_limit', 'created_at']
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


class ReceiptItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    category_name = serializers.CharField(source='category.category_name', read_only=True)
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

    class Meta:
        model = Receipt
        fields = [
            'receipt_id', 'user', 'store', 'store_name', 'purchase_date',
            'total_amount', 'source_type', 'image_url', 'verified',
            'created_at', 'items',
        ]
        read_only_fields = ['receipt_id', 'user', 'created_at']

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        validated_data['user'] = self.context['request'].user
        receipt = Receipt.objects.create(**validated_data)
        for item_data in items_data:
            ReceiptItem.objects.create(receipt=receipt, **item_data)
        return receipt

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                ReceiptItem.objects.create(receipt=instance, **item_data)
        return instance


class MonthlyAnalyticsSerializer(serializers.Serializer):
    """Mirrors the `user_monthly_analytics` SQL view from the spec, computed
    in the ORM so it works identically on SQLite (dev) and Postgres (prod)."""

    audit_month = serializers.DateField()
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2)
    impulse_spend = serializers.DecimalField(max_digits=12, decimal_places=2)
    monthly_budget_limit = serializers.DecimalField(max_digits=10, decimal_places=2)
    budget_variance = serializers.DecimalField(max_digits=12, decimal_places=2)
