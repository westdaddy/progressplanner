# Generated by Django 4.2.10 on 2025-07-17 08:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0017_alter_inventorysnapshot_date_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="restock_time",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of months required to restock this product.",
            ),
        ),
    ]
