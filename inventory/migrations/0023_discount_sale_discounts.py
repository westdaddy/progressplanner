from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0022_sale_discount_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="Discount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("code", models.CharField(db_index=True, max_length=255, unique=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="sale",
            name="discounts",
            field=models.ManyToManyField(blank=True, related_name="sales", to="inventory.discount"),
        ),
    ]
