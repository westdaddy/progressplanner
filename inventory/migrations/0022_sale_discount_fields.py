from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0021_alter_orderitem_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="coupon_name_raw",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="sale",
            name="discount_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="discount_notes",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sale",
            name="discount_reasons",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="sale",
            name="is_discounted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sale",
            name="list_price",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="manual_discount_flag",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sale",
            name="product_short_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="sale",
            name="seller_note",
            field=models.TextField(blank=True, null=True),
        ),
    ]
