# Generated by Django 4.2.18 on 2025-07-12 18:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0013_alter_order_options_alter_product_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="Group",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name="Series",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, unique=True)),
            ],
        ),
        migrations.AddField(
            model_name="product",
            name="groups",
            field=models.ManyToManyField(
                blank=True, related_name="products", to="inventory.group"
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="series",
            field=models.ManyToManyField(
                blank=True, related_name="products", to="inventory.series"
            ),
        ),
    ]
