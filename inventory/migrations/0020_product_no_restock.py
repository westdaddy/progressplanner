from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0019_referrer_sale_referrer"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="no_restock",
            field=models.BooleanField(
                default=False,
                help_text="Exclude this product from reorder recommendations.",
            ),
        ),
    ]
