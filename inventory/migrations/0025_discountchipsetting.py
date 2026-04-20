from django.db import migrations, models


def seed_discount_chip_setting(apps, schema_editor):
    DiscountChipSetting = apps.get_model("inventory", "DiscountChipSetting")
    if DiscountChipSetting.objects.exists():
        return
    DiscountChipSetting.objects.create(
        palette=[
            "#1E88E5",
            "#43A047",
            "#FB8C00",
            "#8E24AA",
            "#E53935",
            "#00897B",
            "#5E35B1",
            "#3949AB",
            "#6D4C41",
            "#039BE5",
            "#7CB342",
            "#F4511E",
            "#546E7A",
            "#C2185B",
            "#FDD835",
        ],
        discount_color_map={},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0024_remove_sale_legacy_discount_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="DiscountChipSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("palette", models.JSONField(blank=True, default=list)),
                ("discount_color_map", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Discount Chip Setting",
                "verbose_name_plural": "Settings",
            },
        ),
        migrations.RunPython(seed_discount_chip_setting, migrations.RunPython.noop),
    ]
