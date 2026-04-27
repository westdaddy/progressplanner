from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0026_referrer_discount_policy"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="restock_time",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Number of months required to restock this product.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="productvariant",
            name="primary_color",
            field=models.CharField(blank=True, max_length=7, null=True),
        ),
        migrations.AlterField(
            model_name="productvariant",
            name="size",
            field=models.CharField(
                blank=True,
                choices=[
                    ("XXS", "Extra-Extra-Small"),
                    ("XS", "Extra-Small"),
                    ("S", "Small"),
                    ("M", "Medium"),
                    ("L", "Large"),
                    ("XL", "Extra Large"),
                    ("XXL", "Extra-Extra Large"),
                    ("A0", "A0"),
                    ("A1", "A1"),
                    ("A1L", "A1L"),
                    ("A2", "A2"),
                    ("A2L", "A2L"),
                    ("A3", "A3"),
                    ("A3L", "A3L"),
                    ("A4", "A4"),
                    ("A5", "A5"),
                    ("F0", "F0"),
                    ("F1", "F1"),
                    ("F2", "F2"),
                    ("F3", "F3"),
                    ("F4", "F4"),
                    ("M000", "M000"),
                    ("M00", "M00"),
                    ("M0", "M0"),
                    ("M1", "M1"),
                    ("M2", "M2"),
                    ("M3", "M3"),
                    ("M4", "M4"),
                    ("KXS", "KXS"),
                    ("KS", "KS"),
                    ("KM", "KM"),
                    ("KL", "KL"),
                    ("KXL", "KXL"),
                ],
                max_length=4,
                null=True,
            ),
        ),
    ]
