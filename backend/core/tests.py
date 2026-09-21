"""End-to-end API tests: email-code auth, receipts CRUD + isolation,
category match-or-create, analytics, and default-category seeding.

Run with: python manage.py test core
"""
from datetime import date, timedelta
from decimal import Decimal

import jwt
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from unittest import mock

from .models import BudgetAlert, Category, LoginAudit, LoginCode, LoyaltyPoints, Receipt, ReceiptItem, Store
from . import reminders as reminders_mod
from . import emails as emails_mod
from . import budget_emails as budget_emails_mod

User = get_user_model()


def auth_client(user):
    """APIClient with the user force-authenticated (bypasses JWT plumbing)."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# Hermetic suite: no provider keys, alphanumeric sender — every login code
# takes the dev/console path and nothing real is ever sent from a test run.
NO_LIVE_DELIVERY = override_settings(
    RESEND_API_KEY='',
    BREVO_API_KEY='',
    TELNYX_API_KEY='',
    TELNYX_FROM='SmartSpend',
)


@NO_LIVE_DELIVERY
class DefaultCategoriesTest(TestCase):
    def test_seed_migration_created_defaults(self):
        names = set(Category.objects.values_list('category_name', flat=True))
        self.assertIn('Groceries', names)
        self.assertIn('Snacks & Drinks', names)
        self.assertGreaterEqual(Category.objects.count(), 12)

    def test_essential_flags(self):
        self.assertTrue(Category.objects.get(category_name='Groceries').is_essential)
        self.assertFalse(Category.objects.get(category_name='Snacks & Drinks').is_essential)


@NO_LIVE_DELIVERY
class AuthCodeLoginTest(TestCase):
    def test_request_code_creates_code(self):
        response = self.client.post(
            reverse('request_login_code'), {'email': 'Student@example.com'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(LoginCode.objects.count(), 1)
        code = LoginCode.objects.first()
        self.assertEqual(len(code.code), 6)
        self.assertTrue(code.code.isdigit())

    def test_verify_creates_account_on_first_login(self):
        self.client.post(reverse('request_login_code'), {'email': 'new@user.com'}, format='json')
        code = LoginCode.objects.order_by('-created_at').first()
        response = self.client.post(
            reverse('verify_login_code'), {'email': 'new@user.com', 'code': code.code}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(response.data['created_account'])
        self.assertTrue(User.objects.filter(email='new@user.com').exists())

    def test_verify_signs_in_existing_user(self):
        User.objects.create_user(email='existing@user.com', password='pass-12345678')
        self.client.post(reverse('request_login_code'), {'email': 'existing@user.com'}, format='json')
        code = LoginCode.objects.order_by('-created_at').first()
        response = self.client.post(
            reverse('verify_login_code'), {'email': 'existing@user.com', 'code': code.code}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['created_account'])

    def test_wrong_code_rejected_and_attempts_incremented(self):
        self.client.post(reverse('request_login_code'), {'email': 'new@user.com'}, format='json')
        response = self.client.post(
            reverse('verify_login_code'), {'email': 'new@user.com', 'code': '000001'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        code = LoginCode.objects.order_by('-created_at').first()
        code.refresh_from_db()
        self.assertEqual(code.attempts, 1)

    def test_code_is_single_use(self):
        self.client.post(reverse('request_login_code'), {'email': 'new@user.com'}, format='json')
        code = LoginCode.objects.order_by('-created_at').first()
        first = self.client.post(
            reverse('verify_login_code'), {'email': 'new@user.com', 'code': code.code}, format='json'
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        second = self.client.post(
            reverse('verify_login_code'), {'email': 'new@user.com', 'code': code.code}, format='json'
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rate_limit_on_code_requests(self):
        for _ in range(5):
            self.client.post(reverse('request_login_code'), {'email': 'new@user.com'}, format='json')
        response = self.client.post(reverse('request_login_code'), {'email': 'new@user.com'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


@NO_LIVE_DELIVERY
class PasswordResetTest(TestCase):
    """Forgot-password flow: request a reset code by email, verify it
    without burning it, then set a new password. Shares the login-code
    model, rate limit and single-use rules."""

    def setUp(self):
        self.user = User.objects.create_user(email='reset@user.com', password='old-password-123')

    def _request(self, email='reset@user.com'):
        return self.client.post(reverse('password_reset_request'), {'email': email}, format='json')

    def _latest_code(self):
        return LoginCode.objects.order_by('-created_at').first().code

    def test_request_sends_code_for_registered_address(self):
        response = self._request()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(LoginCode.objects.filter(email='reset@user.com').exists())

    def test_unregistered_address_gets_same_response_without_code(self):
        # Same 200 shape either way — the endpoint must not leak which
        # addresses are registered.
        response = self._request('ghost@nowhere.com')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(LoginCode.objects.filter(email='ghost@nowhere.com').count(), 0)

    def test_verify_checks_without_consuming(self):
        self._request()
        code = self._latest_code()
        response = self.client.post(
            reverse('password_reset_verify'), {'email': 'reset@user.com', 'code': code}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['verified'])
        # The code is NOT consumed by verification.
        self.assertTrue(LoginCode.objects.filter(email='reset@user.com', consumed_at__isnull=True).exists())

    def test_verify_rejects_wrong_code(self):
        self._request()
        response = self.client.post(
            reverse('password_reset_verify'), {'email': 'reset@user.com', 'code': '000001'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_sets_new_password_and_consumes_code(self):
        self._request()
        code = self._latest_code()
        response = self.client.post(
            reverse('password_reset_confirm'),
            {'email': 'reset@user.com', 'code': code, 'new_password': 'brand-new-pw-456'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('brand-new-pw-456'))
        # Single-use: the consumed code can't reset again.
        second = self.client.post(
            reverse('password_reset_confirm'),
            {'email': 'reset@user.com', 'code': code, 'new_password': 'another-pw-789'},
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(self.user.check_password('brand-new-pw-456'))

    def test_confirm_rejects_weak_password(self):
        self._request()
        response = self.client.post(
            reverse('password_reset_confirm'),
            {'email': 'reset@user.com', 'code': self._latest_code(), 'new_password': '123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-password-123'))

    def test_password_login_still_works_after_reset(self):
        self._request()
        self.client.post(
            reverse('password_reset_confirm'),
            {'email': 'reset@user.com', 'code': self._latest_code(), 'new_password': 'brand-new-pw-456'},
            format='json',
        )
        response = self.client.post(
            reverse('token_obtain_pair'), {'email': 'reset@user.com', 'password': 'brand-new-pw-456'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_rate_limit_shared_with_login_codes(self):
        for _ in range(5):
            self._request()
        response = self._request()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


@NO_LIVE_DELIVERY
class SmsCodeLoginTest(TestCase):
    """POST /api/auth/login-code/sms/ + /api/auth/verify-login-code/sms/ —
    the phone-based twin of the email flow. Without TELNYX_API_KEY the
    request response carries dev_code (dev mode)."""

    def test_request_code_without_key_returns_dev_code(self):
        response = self.client.post(
            reverse('request_login_code_sms'), {'phone': '082 123 4567'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['transport'], 'dev')
        self.assertIn('dev_code', response.data)
        self.assertTrue(LoginCode.objects.filter(email='+27821234567').exists())

    def test_local_number_normalized_to_e164(self):
        self.client.post(reverse('request_login_code_sms'), {'phone': '0821234567'}, format='json')
        self.assertTrue(LoginCode.objects.filter(email='+27821234567').exists())

    def test_invalid_phone_rejected(self):
        response = self.client.post(reverse('request_login_code_sms'), {'phone': '123'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(LoginCode.objects.count(), 0)

    def test_verify_creates_account_and_sets_phone(self):
        self.client.post(reverse('request_login_code_sms'), {'phone': '0821234567'}, format='json')
        code = LoginCode.objects.order_by('-created_at').first()
        response = self.client.post(
            reverse('verify_login_code_sms'), {'phone': '0821234567', 'code': code.code}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertTrue(response.data['created_account'])
        user = User.objects.get(email='+27821234567')
        self.assertEqual(user.phone, '+27821234567')

    def test_verify_signs_in_existing_user(self):
        User.objects.create_user(email='+27821234567', password='pass-12345678')
        self.client.post(reverse('request_login_code_sms'), {'phone': '0821234567'}, format='json')
        code = LoginCode.objects.order_by('-created_at').first()
        response = self.client.post(
            reverse('verify_login_code_sms'), {'phone': '0821234567', 'code': code.code}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['created_account'])

    def test_wrong_code_rejected(self):
        self.client.post(reverse('request_login_code_sms'), {'phone': '0821234567'}, format='json')
        response = self.client.post(
            reverse('verify_login_code_sms'), {'phone': '0821234567', 'code': '999999'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rate_limit_shared_per_destination(self):
        for _ in range(5):
            self.client.post(reverse('request_login_code_sms'), {'phone': '0821234567'}, format='json')
        response = self.client.post(reverse('request_login_code_sms'), {'phone': '0821234567'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


@NO_LIVE_DELIVERY
class ReceiptCrudAndIsolationTest(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email='alice@x.com', password='pass-12345678')
        self.bob = User.objects.create_user(email='bob@x.com', password='pass-12345678')
        self.groceries = Category.objects.get(category_name='Groceries')
        self.store = Store.objects.create(store_name='Checkers', channel_type='Physical_Store')
        self.receipt = Receipt.objects.create(
            user=self.alice, store=self.store, purchase_date=date(2026, 8, 20),
            total_amount=Decimal('51.98'), verified=True,
        )
        ReceiptItem.objects.create(
            receipt=self.receipt, category=self.groceries, item_name='Milk 2L',
            unit_price=Decimal('25.99'), quantity=2,
        )

    def test_owner_can_read_and_update(self):
        client = auth_client(self.alice)
        response = client.get('/api/receipts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

        response = client.patch(
            f'/api/receipts/{self.receipt.receipt_id}/',
            {'total_amount': '55.00'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.total_amount, Decimal('55.00'))

    def test_other_user_cannot_read_or_write(self):
        client = auth_client(self.bob)
        self.assertEqual(client.get('/api/receipts/').data['count'], 0)
        self.assertEqual(
            client.get(f'/api/receipts/{self.receipt.receipt_id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            client.delete(f'/api/receipts/{self.receipt.receipt_id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_update_can_replace_line_items(self):
        client = auth_client(self.alice)
        snacks = Category.objects.get(category_name='Snacks & Drinks')
        response = client.patch(
            f'/api/receipts/{self.receipt.receipt_id}/',
            {
                'items': [
                    {'item_name': 'Chocolate bar', 'unit_price': '18.50', 'quantity': 1,
                     'category': snacks.category_id, 'is_impulse': True},
                ]
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.receipt.items.count(), 1)
        self.assertTrue(self.receipt.items.first().is_impulse)

    def test_create_receipt_with_category_names_and_inline_store(self):
        client = auth_client(self.alice)
        response = client.post(
            '/api/receipts/',
            {
                'store_name': 'Takealot',
                'channel_type': 'Online_Ecommerce',
                'purchase_date': '2026-09-10',
                'total_amount': '349.00',
                'source_type': 'upload',
                'verified': True,
                'items': [
                    {'item_name': 'USB cable', 'unit_price': '99.00', 'quantity': 1,
                     'category': 'Electronics', 'is_impulse': False},
                    {'item_name': 'Energy drink', 'unit_price': '125.00', 'quantity': 2,
                     'category': 'Snacks & Drinks', 'is_impulse': True},
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Inline store created with the right channel
        store = Store.objects.get(store_name='Takealot')
        self.assertEqual(store.channel_type, 'Online_Ecommerce')
        # Category matched-or-created by name
        self.assertTrue(Category.objects.filter(category_name='Electronics').exists())
        items = {i.item_name: i for i in ReceiptItem.objects.filter(receipt__pk=response.data['receipt_id'])}
        self.assertEqual(items['Energy drink'].category.category_name, 'Snacks & Drinks')
        self.assertTrue(items['Energy drink'].is_impulse)

    def test_delete_receipt(self):
        client = auth_client(self.alice)
        self.assertEqual(
            client.delete(f'/api/receipts/{self.receipt.receipt_id}/').status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertFalse(Receipt.objects.filter(pk=self.receipt.pk).exists())


@NO_LIVE_DELIVERY
class MonthlyAnalyticsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='ana@x.com', password='pass-12345678', monthly_budget_limit=Decimal('1000')
        )
        self.store = Store.objects.create(store_name='Spar', channel_type='Physical_Store')
        self.essential = Category.objects.get(category_name='Groceries')
        self.treats = Category.objects.get(category_name='Snacks & Drinks')

    def _add_receipt(self, day, total, items):
        receipt = Receipt.objects.create(
            user=self.user, store=self.store, purchase_date=date(2026, 8, day),
            total_amount=Decimal(str(total)), verified=True,
        )
        for name, category, price, qty in items:
            ReceiptItem.objects.create(
                receipt=receipt, category=category, item_name=name,
                unit_price=Decimal(str(price)), quantity=qty,
            )
        return receipt

    def test_month_breakdown_totals(self):
        self._add_receipt(3, 200, [('Bread', self.essential, 20, 2), ('Coke', self.treats, 40, 4)])
        self._add_receipt(10, 150, [('Chicken', self.essential, 150, 1)])

        client = auth_client(self.user)
        response = client.get('/api/receipts/month_breakdown/', {'year': 2026, 'month': 8})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(Decimal(data['total_spent']), Decimal('350.00'))
        self.assertEqual(Decimal(data['impulse_spend']), Decimal('160.00'))  # 4 x R40
        self.assertEqual(Decimal(data['essential_spend']), Decimal('190.00'))
        self.assertEqual(Decimal(data['budget_variance']), Decimal('650.00'))
        self.assertEqual(len(data['daily_totals']), 2)
        self.assertEqual(data['daily_totals']['2026-08-03'], '200.00')
        cats = {c['category_name']: c for c in data['categories']}
        self.assertEqual(cats['Snacks & Drinks']['total'], '160.00')
        self.assertTrue(any(s['store_name'] == 'Spar' for s in data['stores']))
        self.assertEqual(data['biggest_purchase']['item_name'], 'Coke')  # 4 × R40 = R160 beats R150

    def test_monthly_analytics_groups_by_month(self):
        self._add_receipt(3, 200, [('Bread', self.essential, 50, 4)])
        client = auth_client(self.user)
        response = client.get('/api/receipts/monthly_analytics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['total_spent'], '200.00')

    def test_me_endpoint_updates_budget(self):
        client = auth_client(self.user)
        response = client.patch('/api/me/', {'monthly_budget_limit': '2500'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.monthly_budget_limit, Decimal('2500'))

    def test_budget_advice_suggests_category_trim(self):
        """A big non-essential category gets a concrete 25% cut suggestion."""
        self._add_receipt(3, 200, [('Coke', self.treats, 100, 2)])  # R200 of treats
        client = auth_client(self.user)
        response = client.get('/api/receipts/budget_advice/', {'year': 2026, 'month': 8})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        kinds = {s['kind'] for s in data['suggestions']}
        self.assertIn('category_cut', kinds)
        cut = next(s for s in data['suggestions'] if s['kind'] == 'category_cut')
        self.assertEqual(Decimal(cut['potential_saving']), Decimal('50.00'))  # 25% of R200
        self.assertEqual(Decimal(data['potential_total_saving']), Decimal('50.00'))

    def test_budget_advice_flags_impulse_and_skips_tiny_categories(self):
        """Small non-essential spends don't lecture; impulse buys get named."""
        self._add_receipt(5, 30, [('Chappies', self.treats, 30, 1)])  # R30 — below the R50 floor
        client = auth_client(self.user)
        response = client.get('/api/receipts/budget_advice/', {'year': 2026, 'month': 8})
        data = response.data
        kinds = {s['kind'] for s in data['suggestions']}
        self.assertNotIn('category_cut', kinds)
        # is_impulse items still get the impulse suggestion even when the
        # category is small.
        receipt = Receipt.objects.filter(purchase_date__day=5).first()
        ReceiptItem.objects.filter(receipt=receipt).update(is_impulse=True)
        response = client.get('/api/receipts/budget_advice/', {'year': 2026, 'month': 8})
        kinds = {s['kind'] for s in response.data['suggestions']}
        self.assertIn('impulse', kinds)

    def test_budget_advice_empty_month_is_empty(self):
        """No receipts in the month — no filler advice."""
        client = auth_client(self.user)
        response = client.get('/api/receipts/budget_advice/', {'year': 2026, 'month': 7})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['suggestions'], [])
        self.assertEqual(Decimal(response.data['potential_total_saving']), Decimal('0'))

    def test_budget_advice_is_per_user(self):
        """Another user's spending never leaks into someone else's advice."""
        other = User.objects.create_user(email='other@x.com', password='pass-12345678')
        Receipt.objects.create(
            user=other, store=self.store, purchase_date=date(2026, 8, 9),
            total_amount=Decimal('500'), verified=True,
        )
        client = auth_client(self.user)
        response = client.get('/api/receipts/budget_advice/', {'year': 2026, 'month': 8})
        self.assertEqual(response.data['suggestions'], [])
        self.assertEqual(Decimal(response.data['total_spent']), Decimal('0'))


def make_store(name):
    return Store.objects.create(store_name=name, channel_type=Store.ChannelType.PHYSICAL)


@NO_LIVE_DELIVERY
class ReceiptSearchExportTests(TestCase):
    """Search/filter/order params on the receipts list + the CSV export."""

    def setUp(self):
        self.user = User.objects.create_user(email='shopper@example.com')
        self.client = auth_client(self.user)
        self._mk_receipt('Checkers', 'Milk', '25.00')
        self._mk_receipt('Kauai', 'Smoothie', '60.00', day='10')

    def _mk_receipt(self, store_name, item_name, total, day='01'):
        store = make_store(store_name)
        cat = Category.objects.create(category_name=f'cat-{store_name}')
        receipt = Receipt.objects.create(
            user=self.user, store=store, purchase_date=f'2026-09-{day}', total_amount=Decimal(total)
        )
        ReceiptItem.objects.create(
            receipt=receipt, category=cat, item_name=item_name, unit_price=Decimal(total), quantity=1
        )
        return receipt

    def _list(self, query=''):
        return self.client.get(reverse('receipt-list') + query)

    def test_search_matches_store_and_item(self):
        self.assertEqual(self._list('?search=kauai').data['count'], 1)
        self.assertEqual(self._list('?search=milk').data['count'], 1)
        self.assertEqual(self._list('?search=zzz').data['count'], 0)

    def test_store_and_category_filters(self):
        store_id = Store.objects.get(store_name='Checkers').store_id
        cat_id = Category.objects.get(category_name='cat-Kauai').category_id
        self.assertEqual(self._list(f'?store={store_id}').data['count'], 1)
        self.assertEqual(self._list(f'?category={cat_id}').data['count'], 1)

    def test_date_range_and_ordering(self):
        self.assertEqual(self._list('?date_from=2026-09-02').data['count'], 1)
        cheapest = self._list('?ordering=total_amount').data['results'][0]
        self.assertEqual(cheapest['store_name'], 'Checkers')
        priciest = self._list('?ordering=-total_amount').data['results'][0]
        self.assertEqual(priciest['store_name'], 'Kauai')

    def test_csv_export_contains_rows(self):
        response = self.client.get(reverse('receipt-export-csv'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        body = response.content.decode()
        self.assertIn('Checkers', body)
        self.assertIn('Milk', body)
        self.assertIn('Kauai', body)
        # Header + one row per line item.
        self.assertEqual(len(body.strip().splitlines()), 3)

    def test_csv_export_requires_auth(self):
        anon = APIClient()
        self.assertEqual(anon.get(reverse('receipt-export-csv')).status_code, 401)


@NO_LIVE_DELIVERY
class WhatsappCodeLoginTest(TestCase):
    """WhatsApp OTP: same LoginCode model, rate limit and identity rules
    as SMS — only the delivery channel differs (Telnyx type=whatsapp)."""

    def test_request_code_without_key_returns_dev_code(self):
        client = APIClient()
        with override_settings(TELNYX_API_KEY=''):
            response = client.post(
                reverse('request_login_code_whatsapp'),
                {'phone': '082 123 4567'},
                format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['transport'], 'dev')
        self.assertIn('dev_code', response.data)
        # Normalized to E.164 exactly like the SMS channel.
        self.assertTrue(LoginCode.objects.filter(email='+27821234567').exists())

    def test_verify_creates_account_and_sets_phone(self):
        client = APIClient()
        with override_settings(TELNYX_API_KEY=''):
            client.post(
                reverse('request_login_code_whatsapp'), {'phone': '0837771234'}, format='json'
            )
        code = LoginCode.objects.get(email='+27837771234').code
        response = client.post(
            reverse('verify_login_code_whatsapp'),
            {'phone': '0837771234', 'code': code},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertTrue(response.data['created_account'])
        user = User.objects.get(email='+27837771234')
        self.assertEqual(user.phone, '+27837771234')

    def test_wrong_code_rejected(self):
        client = APIClient()
        with override_settings(TELNYX_API_KEY=''):
            client.post(
                reverse('request_login_code_whatsapp'), {'phone': '+27821112222'}, format='json'
            )
        response = client.post(
            reverse('verify_login_code_whatsapp'),
            {'phone': '+27821112222', 'code': '000000'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rate_limit_shared_with_sms_per_destination(self):
        # SMS and WhatsApp share the LoginCode table keyed on the normalized
        # phone, so 5 codes across BOTH channels exhaust the hourly limit.
        for _ in range(5):
            response = APIClient().post(
                reverse('request_login_code_sms'), {'phone': '+27821110000'}, format='json'
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = APIClient().post(
            reverse('request_login_code_whatsapp'), {'phone': '+27821110000'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


@NO_LIVE_DELIVERY
class AppleSignInTest(TestCase):
    """Sign in with Apple: the view only trusts the email claim after the
    identity token verifies against Apple's keys — verified by mocking the
    verifier (network-free) and testing the failure paths directly."""

    def test_disabled_without_client_id(self):
        client = APIClient()
        with override_settings(APPLE_CLIENT_ID=''):
            response = client.post(
                reverse('apple_sign_in'), {'identity_token': 'x' * 40}, format='json'
            )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_auth_config_reports_apple_disabled_by_default(self):
        client = APIClient()
        with override_settings(APPLE_CLIENT_ID=''):
            response = client.get(reverse('auth_config'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['apple_enabled'])

    def test_auth_config_sms_flags_reflect_sender_configuration(self):
        """SMS/WhatsApp channel flags are only true when a real E.164 sender
        number is configured — a Telnyx key alone cannot deliver SMS."""
        client = APIClient()
        with override_settings(TELNYX_API_KEY='', TELNYX_FROM='SmartSpend'):
            response = client.get(reverse('auth_config'))
        self.assertFalse(response.data['sms_enabled'])
        self.assertFalse(response.data['whatsapp_enabled'])

        with override_settings(TELNYX_API_KEY='KEYtest', TELNYX_FROM='SmartSpend'):
            response = client.get(reverse('auth_config'))
        self.assertFalse(response.data['sms_enabled'])  # alphanumeric sender can't SMS

        with override_settings(TELNYX_API_KEY='KEYtest', TELNYX_FROM='+27601234567'):
            response = client.get(reverse('auth_config'))
        self.assertTrue(response.data['sms_enabled'])
        self.assertTrue(response.data['whatsapp_enabled'])

    @override_settings(APPLE_CLIENT_ID='com.example.smartspend')
    def test_valid_token_creates_account_and_signs_in(self):
        claims = {'email': 'AppleUser@ICloud.com', 'sub': '001234.abcdef.5678'}
        with mock.patch('core.views.verify_apple_identity_token', return_value=claims):
            response = APIClient().post(
                reverse('apple_sign_in'),
                {'identity_token': 'x' * 60, 'name': 'Thabo Mokoena'},
                format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['created_account'])
        self.assertIn('access', response.data)
        user = User.objects.get(email='appleuser@icloud.com')
        self.assertEqual(user.first_name, 'Thabo')
        self.assertEqual(user.last_name, 'Mokoena')

    @override_settings(APPLE_CLIENT_ID='com.example.smartspend')
    def test_invalid_token_rejected(self):
        with mock.patch(
            'core.views.verify_apple_identity_token',
            side_effect=jwt.InvalidTokenError('bad signature'),
        ):
            response = APIClient().post(
                reverse('apple_sign_in'), {'identity_token': 'x' * 60}, format='json'
            )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(APPLE_CLIENT_ID='com.example.smartspend')
    def test_token_without_email_claim_rejected(self):
        with mock.patch('core.views.verify_apple_identity_token', return_value={'sub': 'x'}):
            response = APIClient().post(
                reverse('apple_sign_in'), {'identity_token': 'x' * 60}, format='json'
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@NO_LIVE_DELIVERY
class LoginAuditTest(TestCase):
    """Per-user login auditing: every successful sign-in — password,
    email/SMS/WhatsApp code, Apple — appends a LoginAudit row and bumps the
    user's login_count/last_login_at; /api/me/logins/ serves the trail."""

    def _code_login(self, email: str) -> None:
        self.client.post(reverse('request_login_code'), {'email': email}, format='json')
        code = LoginCode.objects.order_by('-created_at').first()
        response = self.client.post(
            reverse('verify_login_code'), {'email': email, 'code': code.code}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_email_code_login_audited_with_counter(self):
        self._code_login('audit@user.com')
        user = User.objects.get(email='audit@user.com')
        self.assertEqual(user.login_count, 1)
        self.assertIsNotNone(user.last_login_at)
        entry = LoginAudit.objects.get(user=user)
        self.assertEqual(entry.method, LoginAudit.Method.EMAIL_CODE)

    def test_password_login_audited(self):
        User.objects.create_user(email='pw@user.com', password='pass-12345678')
        response = self.client.post(
            reverse('token_obtain_pair'),
            {'email': 'pw@user.com', 'password': 'pass-12345678'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user = User.objects.get(email='pw@user.com')
        self.assertEqual(user.login_count, 1)
        self.assertTrue(LoginAudit.objects.filter(user=user, method=LoginAudit.Method.PASSWORD).exists())

    def test_failed_password_login_not_audited(self):
        User.objects.create_user(email='pw2@user.com', password='pass-12345678')
        response = self.client.post(
            reverse('token_obtain_pair'),
            {'email': 'pw2@user.com', 'password': 'wrong-password'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        user = User.objects.get(email='pw2@user.com')
        self.assertEqual(user.login_count, 0)
        self.assertEqual(LoginAudit.objects.count(), 0)

    def test_sms_and_apple_logins_audited_with_channel(self):
        with override_settings(TELNYX_API_KEY=''):
            self.client.post(
                reverse('request_login_code_sms'), {'phone': '082 555 0001'}, format='json'
            )
        sms_code = LoginCode.objects.order_by('-created_at').first()
        response = self.client.post(
            reverse('verify_login_code_sms'),
            {'phone': '082 555 0001', 'code': sms_code.code},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with override_settings(APPLE_CLIENT_ID='com.example.smartspend'):
            with mock.patch(
                'core.views.verify_apple_identity_token',
                return_value={'email': 'audit.apple@icloud.com', 'sub': 'x'},
            ):
                response = APIClient().post(
                    reverse('apple_sign_in'), {'identity_token': 'x' * 60}, format='json'
                )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        sms_user = User.objects.get(email='+27825550001')
        apple_user = User.objects.get(email='audit.apple@icloud.com')
        self.assertTrue(LoginAudit.objects.filter(user=sms_user, method=LoginAudit.Method.SMS_CODE).exists())
        self.assertTrue(LoginAudit.objects.filter(user=apple_user, method=LoginAudit.Method.APPLE).exists())
        self.assertEqual(sms_user.login_count, 1)
        self.assertEqual(apple_user.login_count, 1)

    def test_me_logins_endpoint_serves_trail_newest_first(self):
        self._code_login('trail@user.com')
        self._code_login('trail@user.com')
        client = APIClient()
        client.force_authenticate(User.objects.get(email='trail@user.com'))
        response = client.get(reverse('me_logins'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['method'], LoginAudit.Method.EMAIL_CODE)
        self.assertGreaterEqual(response.data[0]['created_at'], response.data[1]['created_at'])
        self.assertEqual(response.data[0]['login_count'], 2)
        self.assertIsNotNone(response.data[0]['last_login_at'])

    def test_me_logins_requires_auth_and_isolates_users(self):
        self._code_login('iso@user.com')
        self._code_login('other@user.com')
        client = APIClient()
        client.force_authenticate(User.objects.get(email='iso@user.com'))
        response = client.get(reverse('me_logins'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(APIClient().get(reverse('me_logins')).status_code, 401)


@NO_LIVE_DELIVERY
class ExtractTextTest(TestCase):
    """Digital receipts by paste: Uber/Bolt fare e-mails and order
    summaries POSTed as text, parsed the same way as photo scans."""

    def setUp(self):
        self.user = User.objects.create_user(email='extract@example.com', password='pass12345')
        self.client = auth_client(self.user)

    def test_requires_auth(self):
        response = APIClient().post(
            reverse('receipt-extract-text'), {'text': 'Uber trip'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(GEMINI_API_KEY='')
    def test_parses_uber_style_text_without_ai(self):
        text = (
            'Uber\n'
            'Trip Receipt\n'
            '14 Sep 2026\n'
            'Trip fare R87.50\n'
            'Booking fee R12.00\n'
            'Total R99.50\n'
        )
        response = self.client.post(reverse('receipt-extract-text'), {'text': text}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['engine'], 'tesseract')  # regex fallback engine name
        self.assertEqual(response.data['merchant_name'], 'Uber')
        self.assertEqual(float(response.data['total_amount']), 99.5)
        self.assertEqual(response.data['channel_type'], 'Online_Ecommerce')

    def test_empty_text_rejected(self):
        response = self.client.post(reverse('receipt-extract-text'), {'text': '   '}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(GEMINI_API_KEY='')
    def test_extract_reports_loyalty_points(self):
        text = (
            'Pick n Pay\n'
            '14 Sep 2026\n'
            'Milk R24.99\n'
            'Bread R18.99\n'
            'Total R43.98\n'
            'Smart Shopper points 250\n'
            'Points expire 30 Sep 2026\n'
        )
        response = self.client.post(reverse('receipt-extract-text'), {'text': text}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        loyalty = response.data.get('loyalty_points', [])
        self.assertEqual(len(loyalty), 1)
        self.assertEqual(loyalty[0]['points'], 250)
        self.assertEqual(loyalty[0]['label'], 'Smart Shopper')
        self.assertEqual(loyalty[0]['expires_at'], '2026-09-30')


@NO_LIVE_DELIVERY
class LoyaltyPointsTest(TestCase):
    """Points blocks read off slips land in LoyaltyPoints when the receipt
    is saved, and the /api/points/ endpoint serves them per store."""

    def setUp(self):
        self.user = User.objects.create_user(email='points@example.com', password='pass12345')
        self.client = auth_client(self.user)
        self.store = Store.objects.create(store_name='Pick n Pay', channel_type=Store.ChannelType.PHYSICAL)
        self.category = Category.objects.get(category_name='Groceries')

    def _receipt_payload(self, **overrides):
        payload = {
            'store_name': 'Pick n Pay',
            'purchase_date': '2026-09-14',
            'total_amount': '43.98',
            'items': [
                {'item_name': 'Milk', 'unit_price': '24.99', 'quantity': 1, 'category': self.category.category_id},
            ],
        }
        payload.update(overrides)
        return payload

    def test_saving_receipt_with_points_creates_loyalty_rows(self):
        payload = self._receipt_payload(
            loyalty_points=[
                {'points': 250, 'label': 'Smart Shopper points', 'expires_at': '2026-09-30'},
                {'points': 100, 'label': 'Clicks ClubCard points', 'expires_at': None},
            ]
        )
        response = self.client.post(reverse('receipt-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rows = LoyaltyPoints.objects.filter(user=self.user).order_by('points')
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.last().points, 250)
        self.assertEqual(rows.last().store.store_name, 'Pick n Pay')
        self.assertEqual(rows.first().label, 'Clicks ClubCard points')

    def test_points_list_expires_soonest_first_and_active_filter(self):
        LoyaltyPoints.objects.create(
            user=self.user, store=self.store, points=100,
            label='Soon', expires_at=date(2026, 9, 25),
        )
        LoyaltyPoints.objects.create(
            user=self.user, store=self.store, points=500,
            label='Later', expires_at=date(2026, 10, 20),
        )
        LoyaltyPoints.objects.create(
            user=self.user, store=self.store, points=50,
            label='Expired', expires_at=date(2026, 9, 1),
        )
        response = self.client.get(reverse('loyaltypoints-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)  # the lapsed 1 Sep block is hidden by default
        self.assertEqual(response.data['results'][0]['label'], 'Soon')  # soonest expiry first

        expired = self.client.get(reverse('loyaltypoints-list'), {'include_expired': '1'})
        self.assertEqual(expired.data['count'], 3)

        active = self.client.get(reverse('loyaltypoints-list'), {'active': '1'})
        labels = [r['label'] for r in active.data['results']]
        self.assertEqual(labels, ['Soon', 'Later'])

    def test_points_isolated_per_user(self):
        other = User.objects.create_user(email='other@example.com', password='pass12345')
        LoyaltyPoints.objects.create(user=other, store=self.store, points=999)
        response = self.client.get(reverse('loyaltypoints-list'))
        self.assertEqual(response.data['count'], 0)

    def test_reminder_command_targets_7_and_1_day_windows(self):
        from datetime import timedelta

        from django.core import mail
        from django.utils import timezone

        from core.management.commands.send_points_reminders import Command

        today = timezone.now().date()
        LoyaltyPoints.objects.create(
            user=self.user, store=self.store, points=300,
            label='Smart Shopper points', expires_at=today + timedelta(days=7),
        )
        LoyaltyPoints.objects.create(
            user=self.user, store=self.store, points=75,
            label='ClubCard points', expires_at=today + timedelta(days=1),
        )
        LoyaltyPoints.objects.create(
            user=self.user, store=self.store, points=40,
            label='Not yet', expires_at=today + timedelta(days=3),
        )
        Command().handle()
        subjects = [m.subject for m in mail.outbox]
        self.assertEqual(len(subjects), 2)  # the 7-day and 1-day blocks, not the 3-day
        joined = '\n'.join(m.body for m in mail.outbox)
        self.assertIn('300', joined)
        self.assertIn('75', joined)
        self.assertNotIn('40', joined)


@NO_LIVE_DELIVERY
class GeminiByokTest(TestCase):
    """Bring-your-own Gemini key: connect (verified + encrypted at rest),
    status, disconnect, and scan priority (user key before the server's)."""

    def setUp(self):
        self.user = User.objects.create_user(email='byok@example.com', password='pass12345')
        self.client = auth_client(self.user)

    def test_status_disconnected_by_default(self):
        response = self.client.get(reverse('gemini_key_status'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['connected'])
        self.assertEqual(response.data['key_hint'], '')

    def test_connect_rejects_key_google_refuses(self):
        with mock.patch('core.views.verify_gemini_key', return_value=(False, 'Google rejected that key.')):
            response = self.client.post(
                reverse('gemini_key_connect'), {'api_key': 'AIzaNotARealKey'}, format='json'
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_gemini_key)  # unverified keys are never stored

    def test_connect_stores_key_encrypted_and_masks_hint(self):
        with mock.patch(
            'core.views.verify_gemini_key', return_value=(True, 'Connected')
        ):
            response = self.client.post(
                reverse('gemini_key_connect'), {'api_key': 'AIzaSyA0123456789abcdefgh'}, format='json'
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['connected'])
        self.user.refresh_from_db()
        # Stored encrypted, not as plaintext.
        self.assertNotIn('AIzaSyA0123456789abcdefgh', self.user.gemini_key_encrypted)
        self.assertEqual(self.user.gemini_key, 'AIzaSyA0123456789abcdefgh')
        # Status reports a masked hint only — never the key itself.
        status_response = self.client.get(reverse('gemini_key_status'))
        self.assertTrue(status_response.data['connected'])
        self.assertNotIn('AIzaSyA0123456789abcdefgh', status_response.content.decode())

    def test_disconnect_clears_key(self):
        self.user.set_gemini_key('AIzaSyA0123456789abcdefgh')
        self.user.save(update_fields=['gemini_key_encrypted'])
        response = self.client.post(reverse('gemini_key_disconnect'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_gemini_key)

    def test_connect_requires_auth(self):
        response = APIClient().post(reverse('gemini_key_connect'), {'api_key': 'x'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_scan_uses_user_key_before_server_key(self):
        """A connected user's scans call Gemini with THEIR key, even when a
        server key exists; users without one keep using the server key."""
        self.user.set_gemini_key('AIzaUserKey')
        self.user.save(update_fields=['gemini_key_encrypted'])
        with override_settings(GEMINI_API_KEY='AIzaServerKey'):
            with mock.patch(
                'core.receipt_ai._gemini_extract',
                return_value={'merchant': 'Pick n Pay', 'items': [], 'confidence': 0.9},
            ) as gemini:
                response = self.client.post(reverse('receipt-ocr-extract'), {'image': _png_file()})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(gemini.call_args.kwargs['api_key'], 'AIzaUserKey')

    def test_scan_without_user_key_uses_server_key(self):
        with override_settings(GEMINI_API_KEY='AIzaServerKey'):
            with mock.patch(
                'core.receipt_ai._gemini_extract',
                return_value={'merchant': 'Uber', 'items': [], 'confidence': 0.9},
            ) as gemini:
                response = self.client.post(reverse('receipt-ocr-extract'), {'image': _png_file()})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(gemini.call_args.kwargs['api_key'], 'AIzaServerKey')


def _png_file():
    """A 1x1 PNG as an uploadable file for ocr_extract tests."""
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (1, 1), 'white').save(buffer, format='PNG')
    buffer.seek(0)
    return SimpleUploadedFile('slip.png', buffer.read(), content_type='image/png')


class ChangePasswordTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='pw@x.com', password='old-password-123')
        self.client = auth_client(self.user)

    def test_change_with_correct_old_password(self):
        response = self.client.post(
            '/api/me/password/',
            {'old_password': 'old-password-123', 'new_password': 'brand-new-pw-456'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('brand-new-pw-456'))

    def test_rejects_wrong_old_password(self):
        response = self.client.post(
            '/api/me/password/',
            {'old_password': 'wrong', 'new_password': 'brand-new-pw-456'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-password-123'))

    def test_rejects_weak_new_password(self):
        response = self.client.post(
            '/api/me/password/',
            {'old_password': 'old-password-123', 'new_password': '123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_requires_login(self):
        anon = APIClient()
        response = anon.post(
            '/api/me/password/',
            {'old_password': 'x', 'new_password': 'yyyyyyyy'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LoyaltyPointsCrudTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='pts@x.com', password='pass-12345678')
        self.other = User.objects.create_user(email='pts2@x.com', password='pass-12345678')
        self.store = Store.objects.create(store_name='Clicks', channel_type='Physical_Store')
        self.block = LoyaltyPoints.objects.create(
            user=self.user, store=self.store, points=500, label='ClubCard',
        )

    def test_manual_create_match_or_create_store(self):
        response = auth_client(self.user).post(
            '/api/points/',
            {'store_name': 'Pick n Pay', 'label': 'Smart Shopper', 'points': 1200},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['store_name'], 'Pick n Pay')
        self.assertTrue(Store.objects.filter(store_name='Pick n Pay').exists())

    def test_update_and_delete_own_block(self):
        client = auth_client(self.user)
        response = client.patch(f'/api/points/{self.block.points_id}/', {'points': 750}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.block.refresh_from_db()
        self.assertEqual(self.block.points, 750)

        response = client.delete(f'/api/points/{self.block.points_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LoyaltyPoints.objects.filter(points_id=self.block.points_id).exists())

    def test_other_user_cannot_touch_block(self):
        client = auth_client(self.other)
        self.assertEqual(
            client.patch(f'/api/points/{self.block.points_id}/', {'points': 1}, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            client.delete(f'/api/points/{self.block.points_id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )


class BudgetThresholdAlertTest(TestCase):
    """Budget milestone emails: 50% spent, 80% spent, and budget depleted —
    each fires at most once per user per month, and a user who keeps
    spending collects all three in sequence."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='thresholds@x.com', password='pass-12345678', monthly_budget_limit='100.00'
        )
        store = Store.objects.create(store_name='Spar', channel_type='Physical_Store')
        self.store = store

    def _receipt(self, amount):
        Receipt.objects.create(
            user=self.user, store=self.store,
            purchase_date=timezone.now().date(),
            total_amount=Decimal(str(amount)),
        )

    def _run(self):
        from django.core import mail

        with override_settings(
            RESEND_API_KEY='', BREVO_API_KEY='',
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        ):
            before = len(mail.outbox)
            notified = reminders_mod.send_budget_alerts()
            return notified, list(mail.outbox[before:])

    def test_halfway_threshold_fires_first_email(self):
        self._receipt(55)
        notified, outbox = self._run()
        self.assertEqual(notified, 1)
        self.assertEqual(len(outbox), 1)
        self.assertIn('halfway', outbox[0].subject)
        self.assertIn('50%', outbox[0].subject)
        self.assertTrue(BudgetAlert.objects.filter(user=self.user, kind='budget_50').exists())

    def test_each_threshold_fires_exactly_once_and_in_sequence(self):
        # Cross 50%: halfway email.
        self._receipt(55)
        notified, outbox = self._run()
        self.assertEqual((notified, len(outbox)), (1, 1))
        # Cross 80%: the 80% email — not a repeat of 50%.
        self._receipt(30)  # now R85 of R100
        notified, outbox = self._run()
        self.assertEqual((notified, len(outbox)), (1, 1))
        self.assertIn('80%', outbox[0].subject)
        # Over budget: the depletion email.
        self._receipt(30)  # now R115 of R100
        notified, outbox = self._run()
        self.assertEqual((notified, len(outbox)), (1, 1))
        self.assertIn('over your', outbox[0].subject)
        # Every later run is silent — one email per threshold, ever.
        for _ in range(2):
            notified, outbox = self._run()
            self.assertEqual((notified, len(outbox)), (0, 0))
        kinds = list(
            BudgetAlert.objects.filter(user=self.user).order_by('kind').values_list('kind', flat=True)
        )
        self.assertEqual(kinds, ['budget_100', 'budget_50', 'budget_80'])

    def test_skipping_straight_past_80_still_sends_the_100_email(self):
        # A single big receipt blows the whole budget at once.
        self._receipt(140)
        notified, outbox = self._run()
        self.assertEqual(notified, 1)
        self.assertIn('over your', outbox[0].subject)
        # Later runs pick up nothing extra — 50/80 were skipped for good.
        notified, outbox = self._run()
        self.assertEqual((notified, len(outbox)), (0, 0))

    def test_budget_alert_email_rides_brevo_provider(self):
        # The budget-alert sender shares the login-code provider chain:
        # with only a Brevo key set, it must send through Brevo.
        with mock.patch.object(emails_mod, 'requests') as m_requests:
            m_requests.post.return_value = mock.Mock(status_code=200)
            with override_settings(
                RESEND_API_KEY='',
                BREVO_API_KEY='xkeysib-test-key',
                BREVO_FROM_EMAIL='me@gmail.com',
            ):
                transport = budget_emails_mod.send_budget_alert_email('a@b.com', 'Subj', 'Body')
        self.assertEqual(transport, 'brevo')
        args, kwargs = m_requests.post.call_args
        self.assertIn('brevo', args[0])
        self.assertEqual(kwargs['json']['subject'], 'Subj')


class CronDailyEndpointTest(TestCase):
    def setUp(self):
        self.url = '/api/cron/daily/'
        self.user = User.objects.create_user(email='cron@x.com', password='pass-12345678')

    def test_requires_secret_and_key(self):
        # No CRON_SECRET_KEY configured → 503.
        with override_settings(CRON_SECRET_KEY=''):
            self.assertEqual(
                APIClient().post(self.url, format='json').status_code,
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        # Secret configured but wrong key → 403.
        with override_settings(CRON_SECRET_KEY='s3cret'):
            self.assertEqual(
                APIClient().post(self.url, format='json', HTTP_X_CRON_KEY='nope').status_code,
                status.HTTP_403_FORBIDDEN,
            )

    @mock.patch('core.reminders.send_budget_alerts', return_value=0)
    @mock.patch('core.reminders.send_points_expiry_reminders', return_value=0)
    def test_runs_with_correct_key(self, m_reminders, m_budget):
        with override_settings(CRON_SECRET_KEY='s3cret'):
            response = APIClient().post(self.url, format='json', HTTP_X_CRON_KEY='s3cret')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['points_reminders_7day'], 0)

    def test_points_expiry_reminders_send_and_dedup(self):
        from core.models import BudgetAlert

        store = Store.objects.create(store_name='Pick n Pay', channel_type='Physical_Store')
        expiry = timezone.now().date() + timedelta(days=7)
        LoyaltyPoints.objects.create(user=self.user, store=store, points=300, expires_at=expiry)

        with override_settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
            # Force the console/locmem path — no live provider may intercept:
            # Resend test-mode rejects other recipients and Brevo would really send.
            RESEND_API_KEY='',
            BREVO_API_KEY='',
        ):
            from django.core import mail

            sent = reminders_mod.send_points_expiry_reminders(7)
            self.assertEqual(sent, 1)
            self.assertEqual(len(mail.outbox), 1)
            # Second run: deduped, no second email.
            self.assertEqual(reminders_mod.send_points_expiry_reminders(7), 0)
            self.assertEqual(len(mail.outbox), 1)
            self.assertTrue(BudgetAlert.objects.filter(user=self.user, kind='points_7day').exists())


class BrevoEmailTransportTest(TestCase):
    """Brevo is the domain-free email path: a single verified sender address
    (the developer's own inbox) delivers codes to ANY recipient — no DNS.
    These tests pin the contract without touching the network."""

    def _codes(self):
        """Ensure no live provider leaks into these tests."""
        return {
            'RESEND_API_KEY': '',
            'BREVO_API_KEY': 'xkeysib-test-key',
            'BREVO_FROM_EMAIL': 'me@gmail.com',
            'BREVO_FROM_NAME': 'SmartSpend',
        }

    def test_brevo_delivers_login_code_and_reports_transport(self):
        with mock.patch.object(emails_mod, 'requests') as m_requests:
            m_requests.post.return_value = mock.Mock(status_code=200)
            with override_settings(**self._codes()):
                transport = emails_mod.send_login_code_email('anyone@gmail.com', '424242')
        self.assertEqual(transport, 'brevo')
        args, kwargs = m_requests.post.call_args
        self.assertEqual(args[0], emails_mod.BREVO_ENDPOINT)
        payload = kwargs['json']
        self.assertEqual(payload['sender'], {'name': 'SmartSpend', 'email': 'me@gmail.com'})
        self.assertEqual(payload['to'], [{'email': 'anyone@gmail.com'}])
        self.assertIn('424242', payload['textContent'])

    def test_brevo_rejection_maps_to_hint(self):
        with mock.patch.object(emails_mod, 'requests') as m_requests:
            m_requests.post.return_value = mock.Mock(
                status_code=400,
                json=lambda: {'code': 'invalid_parameter', 'message': 'sender not verified'},
                text='sender not verified',
            )
            with override_settings(**self._codes()):
                with self.assertRaises(emails_mod.EmailDeliveryError) as ctx:
                    emails_mod.send_login_code_email('anyone@gmail.com', '424242')
        self.assertIn('sender', ctx.exception.hint.lower())

    def test_resend_takes_precedence_over_brevo(self):
        with mock.patch.object(emails_mod, 'requests') as m_requests:
            m_requests.post.return_value = mock.Mock(status_code=200)
            codes = {**self._codes(), 'RESEND_API_KEY': 're_test', 'RESEND_FROM': 'SmartSpend <onboarding@resend.dev>'}
            with override_settings(**codes):
                transport = emails_mod.send_login_code_email('anyone@gmail.com', '424242')
        self.assertEqual(transport, 'resend')
        args, _ = m_requests.post.call_args
        self.assertEqual(args[0], emails_mod.RESEND_ENDPOINT)
