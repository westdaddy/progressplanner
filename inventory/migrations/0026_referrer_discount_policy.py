from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models


def backfill_referrer_discount_policy(apps, schema_editor):
    Sale = apps.get_model("inventory", "Sale")

    for sale in (
        Sale.objects.filter(referrer__isnull=False, manual_discount_locked=False)
        .select_related("variant__product", "referrer")
        .iterator()
    ):
        referrer = sale.referrer
        if not referrer:
            continue

        category = getattr(referrer, "category", "other")
        if category not in {"gym_code", "wholesale"}:
            continue

        sold_quantity = sale.sold_quantity or 0
        retail_price = sale.variant.product.retail_price or Decimal("0")
        if sold_quantity <= 0 or retail_price <= 0:
            continue

        current_discount = Decimal("0")
        actual_total = sale.sold_value or Decimal("0")
        actual_unit_price = actual_total / sold_quantity
        current_discount = ((retail_price - actual_unit_price) / retail_price) * Decimal("100")

        if category == "gym_code":
            target_discount = Decimal("10")
        else:
            target_discount = max(current_discount, Decimal("25"))

        multiplier = (Decimal("100") - target_discount) / Decimal("100")
        sale.sold_value = (retail_price * sold_quantity * multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        sale.save(update_fields=["sold_value"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0025_discountchipsetting"),
        ("inventory", "0025_migrate_no_referrer_to_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="referrer",
            name="category",
            field=models.CharField(
                choices=[
                    ("other", "Other"),
                    ("gym_code", "Gym code"),
                    ("wholesale", "Wholesale"),
                ],
                db_index=True,
                default="other",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="manual_discount_locked",
            field=models.BooleanField(
                default=False,
                help_text="Keep existing sale pricing when assigning/changing referrer discount rules.",
            ),
        ),
        migrations.RunPython(backfill_referrer_discount_policy, migrations.RunPython.noop),
    ]
