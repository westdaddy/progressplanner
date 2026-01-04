from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0019_referrer_sale_referrer"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="subtype",
            field=models.CharField(
                blank=True,
                choices=[
                    ("tw", "Twill"),
                    ("rs", "Ripstop"),
                    ("ss", "Short Sleeve"),
                    ("ls", "Long Sleeve"),
                    ("rt", "Rolling Tee"),
                    ("bs", "Board Shorts"),
                    ("dl", "Double Layer"),
                    ("vt", "Vale Tudo"),
                ],
                help_text="More detailed subcategory (e.g. Short Sleeve Rashguard)",
                max_length=20,
                null=True,
            ),
        ),
    ]
