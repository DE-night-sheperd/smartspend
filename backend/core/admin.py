from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Category, Receipt, ReceiptItem, Store, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    list_display = ['email', 'first_name', 'last_name', 'monthly_budget_limit', 'is_staff']
    ordering = ['email']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'monthly_budget_limit')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'first_name', 'last_name', 'password1', 'password2')}),
    )


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'channel_type']
    list_filter = ['channel_type']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['category_name', 'is_essential']
    list_filter = ['is_essential']


class ReceiptItemInline(admin.TabularInline):
    model = ReceiptItem
    extra = 0


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['receipt_id', 'user', 'store', 'purchase_date', 'total_amount', 'verified']
    list_filter = ['verified', 'source_type', 'store__channel_type']
    inlines = [ReceiptItemInline]
