"""End-to-end API tests: email-code auth, receipts CRUD + isolation,
category match-or-create, analytics, and default-category seeding.

Run with: python manage.py test core
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import Category, LoginCode, Receipt, ReceiptItem, Store

User = get_user_model()


def auth_client(user):
    """APIClient with the user force-authenticated (bypasses JWT plumbing)."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class DefaultCategoriesTest(TestCase):
    def test_seed_migration_created_defaults(self):
        names = set(Category.objects.values_list('category_name', flat=True))
        self.assertIn('Groceries', names)
        self.assertIn('Snacks & Drinks', names)
        self.assertGreaterEqual(Category.objects.count(), 12)

    def test_essential_flags(self):
        self.assertTrue(Category.objects.get(category_name='Groceries').is_essential)
        self.assertFalse(Category.objects.get(category_name='Snacks & Drinks').is_essential)


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


def make_store(name):
    return Store.objects.create(store_name=name, channel_type=Store.ChannelType.PHYSICAL)


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
