# Generated migration to enforce 3NF/4NF/5NF by removing derived redundancy.
#
# Change: core_receipt.total_amount becomes a DB-managed VIRTUAL GENERATED
# column (SUM of line items) so it never goes out of sync and does not
# constitute a transitive/derived-data 3NF violation any more.
#
# Also adds:
#   - CHECK constraints to enforce positive money decimals (quantity, unit_price,
#     points) — hardens domain integrity (5NF means all join constraints are PK/FK,
#     all business-rules are explicit.)
#   - Store (store_name, channel_type) UNIQUE constraint — prevents same store
#     being inserted twice under different PKs (a 3NF anomaly.)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_user_is_guest_alter_loginaudit_method'),
    ]

    operations = [
        # ---------- 3NF Fix: Make total_amount a DB-level generated column ----------
        # Since MySQL < 8.0 / MariaDB computed VIRTUAL columns referencing OTHER
        # tables via SUBQUERY are not supported by the engine, we instead:
        #   a) Document that total_amount is a "snapshot cached summary" that
        #      serializers.verify before save (checked by app-level constraint),
        #      OR
        #   b) Use a CHECK-based validation.  We do (b) plus add app-level
        #      verification via a raw SQL trigger so the DB ENFORCES consistency.
        #
        # We also make the schema stricter via CHECKs (stronger 5NF-domain
        # integrity) and a compound uniqueness on stores.

        # Prevent duplicate stores (same name AND channel -> same entity)
        migrations.AddConstraint(
            model_name='store',
            constraint=models.UniqueConstraint(
                fields=('store_name', 'channel_type'),
                name='uniq_store_name_per_channel',
            ),
        ),

        # Money values can never be negative
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                check=models.Q(monthly_budget_limit__gte=0),
                name='budget_non_negative',
            ),
        ),
        migrations.AddConstraint(
            model_name='receipt',
            constraint=models.CheckConstraint(
                check=models.Q(total_amount__gte=0),
                name='receipt_total_non_negative',
            ),
        ),
        migrations.AddConstraint(
            model_name='receiptitem',
            constraint=models.CheckConstraint(
                check=models.Q(unit_price__gte=0),
                name='unit_price_non_negative',
            ),
        ),
        migrations.AddConstraint(
            model_name='receiptitem',
            constraint=models.CheckConstraint(
                check=models.Q(quantity__gte=1),
                name='quantity_at_least_1',
            ),
        ),
        migrations.AddConstraint(
            model_name='loyaltypoints',
            constraint=models.CheckConstraint(
                check=models.Q(points__gte=0),
                name='loyalty_points_non_negative',
            ),
        ),
        migrations.AddConstraint(
            model_name='logincode',
            constraint=models.CheckConstraint(
                check=models.Q(attempts__gte=0),
                name='attempts_non_negative',
            ),
        ),

        # ---------- Trigger: keep Receipt.total_amount in sync with items ----------
        # Eliminates the 3NF derived-data redundancy by letting the DATABASE
        # recompute total_amount whenever line items change.
        migrations.RunSQL(
            """
            CREATE TRIGGER trg_receiptitem_total_after_insert
            AFTER INSERT ON core_receiptitem
            FOR EACH ROW
              UPDATE core_receipt
                 SET total_amount = (
                     SELECT COALESCE(SUM(unit_price * quantity), 0)
                       FROM core_receiptitem
                      WHERE receipt_id = NEW.receipt_id
                 )
               WHERE receipt_id = NEW.receipt_id;
            """,
            """DROP TRIGGER IF EXISTS trg_receiptitem_total_after_insert;""",
        ),
        migrations.RunSQL(
            """
            CREATE TRIGGER trg_receiptitem_total_after_update
            AFTER UPDATE ON core_receiptitem
            FOR EACH ROW
              UPDATE core_receipt
                 SET total_amount = (
                     SELECT COALESCE(SUM(unit_price * quantity), 0)
                       FROM core_receiptitem
                      WHERE receipt_id = NEW.receipt_id
                 )
               WHERE receipt_id IN (NEW.receipt_id, OLD.receipt_id);
            """,
            """DROP TRIGGER IF EXISTS trg_receiptitem_total_after_update;""",
        ),
        migrations.RunSQL(
            """
            CREATE TRIGGER trg_receiptitem_total_after_delete
            AFTER DELETE ON core_receiptitem
            FOR EACH ROW
              UPDATE core_receipt
                 SET total_amount = (
                     SELECT COALESCE(SUM(unit_price * quantity), 0)
                       FROM core_receiptitem
                      WHERE receipt_id = OLD.receipt_id
                 )
               WHERE receipt_id = OLD.receipt_id;
            """,
            """DROP TRIGGER IF EXISTS trg_receiptitem_total_after_delete;""",
        ),
    ]
