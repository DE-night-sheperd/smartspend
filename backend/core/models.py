import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserManager(BaseUserManager):
    """Email-is-the-identity manager — there is no username field."""

    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('An email address is required')
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password) if password else user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """USERS entity.

    Uses email as the login identifier and a UUID primary key, matching the
    SmartSpend ERD (user_id UUID PK). Extends Django's AbstractUser so we
    keep password hashing, permissions, and admin integration for free.
    """

    username = None
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True, help_text='E.164 number, e.g. +27821234567')
    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monthly_budget_limit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gemini_key_encrypted = models.TextField(
        blank=True, default='', editable=False,
        help_text='The user\'s own Gemini API key (BYOK), Fernet-encrypted at rest.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    def __str__(self):
        return self.email

    # --- Bring-your-own Gemini key (BYOK) --------------------------------
    @property
    def gemini_key(self) -> str:
        """The user's decrypted Gemini API key ('' when not connected)."""
        from .crypto import decrypt

        return decrypt(self.gemini_key_encrypted)

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_key)

    def set_gemini_key(self, raw_key: str) -> None:
        from .crypto import encrypt

        self.gemini_key_encrypted = encrypt(raw_key.strip())

    def clear_gemini_key(self) -> None:
        self.gemini_key_encrypted = ''


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
    category_name = models.CharField(max_length=100, unique=True)
    is_essential = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['category_name']

    def __str__(self):
        return self.category_name


class LoginCode(models.Model):
    """Short-lived 6-digit code for passwordless email login.

    Codes are single-use, expire after 10 minutes, and only the last 5
    requests per email are kept so the table can't grow without bound.
    """

    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    request_ip = models.GenericIPAddressField(blank=True, null=True)
    request_id = models.UUIDField(default=uuid.uuid4, editable=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.email} · {self.code}'

    @classmethod
    def prune_for(cls, email: str, keep: int = 5) -> None:
        """Keep only the most recent `keep` codes for this email."""
        ids = list(
            cls.objects.filter(email=email).values_list('id', flat=True)[:keep]
        )
        if ids:
            cls.objects.filter(email=email).exclude(id__in=ids).delete()


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
    receipt_image = models.ImageField(upload_to='receipts/%Y/%m/', blank=True, null=True)
    verified = models.BooleanField(default=False, help_text='Set true once user confirms OCR-parsed data.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date']

    def __str__(self):
        return f'{self.store.store_name} — {self.purchase_date} (R{self.total_amount})'


class LoyaltyPoints(models.Model):
    """LOYALTY_POINTS entity — spendable points earned on a receipt.

    Pick n Pay Smart Shopper and Clicks ClubCard both print points balances
    and vouchers on till slips with expiry dates. Every extraction from a
    scanned/pasted receipt lands here so the user can see, per store, how
    many points are waiting and when they lapse.
    """

    points_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loyalty_points', db_column='user_id')
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='loyalty_points', db_column='store_id')
    receipt = models.ForeignKey(
        Receipt, on_delete=models.SET_NULL, blank=True, null=True,
        related_name='loyalty_points', db_column='receipt_id',
    )
    points = models.PositiveIntegerField(help_text='Points available to spend.')
    label = models.CharField(max_length=255, blank=True, help_text='E.g. "Smart Shopper points" or the voucher title.')
    expires_at = models.DateField(blank=True, null=True, help_text='Date the points lapse, printed on the slip.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['expires_at', '-created_at']  # soonest expiry first
        indexes = [models.Index(fields=['user', 'expires_at'])]

    def __str__(self):
        return f'{self.store.store_name} · {self.points} pts · exp {self.expires_at}'


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
