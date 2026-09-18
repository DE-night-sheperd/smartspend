from django.db import migrations


DEFAULTS = [
    ('Groceries', True),
    ('Transport & Fuel', True),
    ('Fast Food & Takeaway', False),
    ('Airtime & Data', True),
    ('Academic & Study', True),
    ('Personal Care', True),
    ('Entertainment', False),
    ('Clothing', False),
    ('Household', True),
    ('Snacks & Drinks', False),
    ('Health & Pharmacy', True),
    ('Other', True),
]


def seed_defaults(apps, schema_editor):
    Category = apps.get_model('core', 'Category')
    for name, essential in DEFAULTS:
        Category.objects.get_or_create(
            category_name=name,
            defaults={'is_essential': essential},
        )


def unseed_defaults(apps, schema_editor):
    Category = apps.get_model('core', 'Category')
    # Only delete a default if no receipt items reference it (PROTECT FK).
    for name, _ in DEFAULTS:
        Category.objects.filter(category_name=name, receipt_items__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_logincode'),
    ]

    operations = [
        migrations.RunPython(seed_defaults, unseed_defaults),
    ]
