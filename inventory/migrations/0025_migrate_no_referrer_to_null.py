from django.db import migrations


def migrate_no_referrer_to_null(apps, schema_editor):
    Referrer = apps.get_model("inventory", "Referrer")
    Sale = apps.get_model("inventory", "Sale")

    legacy_referrers = Referrer.objects.filter(name__iexact="no_referrer")
    if not legacy_referrers.exists():
        return

    Sale.objects.filter(referrer__in=legacy_referrers).update(referrer=None)
    legacy_referrers.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0024_remove_sale_legacy_discount_fields"),
    ]

    operations = [
        migrations.RunPython(migrate_no_referrer_to_null, migrations.RunPython.noop),
    ]
