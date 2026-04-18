from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0023_discount_sale_discounts"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="sale",
            name="discount_amount",
        ),
        migrations.RemoveField(
            model_name="sale",
            name="discount_notes",
        ),
        migrations.RemoveField(
            model_name="sale",
            name="discount_reasons",
        ),
        migrations.RemoveField(
            model_name="sale",
            name="is_discounted",
        ),
        migrations.RemoveField(
            model_name="sale",
            name="manual_discount_flag",
        ),
    ]
