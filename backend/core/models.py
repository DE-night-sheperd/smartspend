import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """USERS entity.

    Uses email as the login identifier and a UUID primary key, matching the
    SmartSpend ERD (user_id UUID PK). Extends Django's AbstractUser so we
    keep password hashing, permissions, and admin integration for free.
    """

    username = None
    email = models.EmailField(unique=True)
    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monthly_budget_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    def __str__(self):
        return self.email


class Store(models.Model):
    """STORES entity."""

    class ChannelType(models.TextChoices):
        PHYSICAL = 'Physical_Store', 'Physical Store'
        ONLINE = 'Online_Ecommerce', 'Online Ecommerce'

    store_id = models.BigAutoField(primary_key=True)
    store_name = models.CharField(max_length=255)
    channel_type = models.CharField(max_length=50, choices=ChannelType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['store_name']

    def __str__(self):
        return self.store_name


class Category(models.Model):
    """CATEGORIES entity (e.g. Groceries, Academic, Fast Food)."""

    category_id = models.AutoField(primary_key=True)
    category_name = models.CharField(max_length=100)
    is_essential = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['category_name']

    def __str__(self):
        return self.category_name


class Receipt(models.Model):
    """RECEIPTS entity. One receipt captured (camera or upload) per purchase."""

    class SourceType(models.TextChoices):
        CAMERA = 'camera', 'In-App Camera'
        UPLOAD = 'upload', 'Digital Upload'

    receipt_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receipts', db_column='user_id')
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='receipts', db_column='store_id')
    purchase_date = models.DateField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.UPLOAD)
    image_url = models.TextField(blank=True, null=True)
    verified = models.BooleanField(default=False, help_text='Set true once user confirms OCR-parsed data.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date']

    def __str__(self):
        return f'{self.store.store_name} — {self.purchase_date} (R{self.total_amount})'


class ReceiptItem(models.Model):
    """RECEIPT_ITEMS entity. Line items belonging to a receipt."""

    item_id = models.BigAutoField(primary_key=True)
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='items', db_column='receipt_id')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='receipt_items', db_column='category_id')
    item_name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    is_impulse = models.BooleanField(default=False, help_text='User-flagged non-essential impulse purchase.')

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f'{self.item_name} x{self.quantity}'
