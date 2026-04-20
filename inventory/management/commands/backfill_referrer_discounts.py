from django.core.management.base import BaseCommand

from inventory.models import Sale


class Command(BaseCommand):
    help = (
        "Backfill sale pricing for referrer rules. "
        "Gym code referrers are set to 10% discount and wholesale to at least 25% "
        "unless sale is manual_discount_locked."
    )

    def handle(self, *args, **options):
        sales = (
            Sale.objects.filter(referrer__isnull=False)
            .select_related("variant__product", "referrer")
            .order_by("pk")
        )

        updated = 0
        inspected = 0
        for sale in sales:
            inspected += 1
            changed = sale.apply_referrer_discount_policy(save=True)
            if changed:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete. Inspected {inspected} sale(s); updated {updated}."
            )
        )
