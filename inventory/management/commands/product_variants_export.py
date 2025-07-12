# inventory/management/commands/export_product_variants.py


import os
import django
import sys
import csv

# Set the path to the project root (where manage.py is located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set the Django settings module
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "progressplanner.settings"
)  # Adjust if your settings module differs
django.setup()


from django.core.management.base import BaseCommand
from inventory.models import ProductVariant


class Command(BaseCommand):
    help = "Export all product variants to a CSV file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default="product_variants_export.csv",
            help="Output CSV file path",
        )

    def handle(self, *args, **options):
        output_file = options["output"]
        fieldnames = [
            "id",
            "product_id",  # From related Product (assuming product_id field)
            "product_name",  # From related Product
            "variant_code",
            "primary_color",
            "secondary_color",
            "size",
            "type",
            "style",
            "age",
            "gender",
        ]

        with open(output_file, mode="w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for variant in ProductVariant.objects.select_related("product").all():
                writer.writerow(
                    {
                        "id": variant.id,
                        "product_id": variant.product.product_id,
                        "product_name": variant.product.product_name,
                        "variant_code": variant.variant_code,
                        "primary_color": variant.primary_color,
                        "secondary_color": variant.secondary_color,
                        "size": variant.size,
                        "type": variant.product.type,
                        "style": variant.product.style,
                        "age": variant.product.age,
                        "gender": variant.gender,
                    }
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {ProductVariant.objects.count()} product variants to {output_file}"
            )
        )
