# inventory/management/commands/import_product_variants.py
import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import Product, ProductVariant

class Command(BaseCommand):
    help = 'Import product variants from a CSV file and update/create records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input',
            type=str,
            default='product_variants_export.csv',
            help='Input CSV file path'
        )

    def handle(self, *args, **options):
        input_file = options['input']

        updated_count = 0
        created_count = 0

        with open(input_file, mode='r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            with transaction.atomic():
                for row in reader:
                    # Assume product_id in CSV corresponds to Product.product_id
                    product, _ = Product.objects.get_or_create(
                        product_id=row['product_id'],
                        defaults={'product_name': row.get('product_name', '')}
                    )
                    variant_data = {
                        'product': product,
                        'variant_code': row['variant_code'],
                        'primary_color': row.get('primary_color'),
                        'secondary_color': row.get('secondary_color'),
                        'size': row.get('size'),
                        'type': row.get('type'),
                        'style': row.get('style'),
                        'age': row.get('age'),
                        'gender': row.get('gender'),
                    }
                    # If the CSV has an id field, try updating that record.
                    if row.get('id'):
                        try:
                            variant = ProductVariant.objects.get(id=row['id'])
                            for field, value in variant_data.items():
                                setattr(variant, field, value)
                            variant.save()
                            updated_count += 1
                        except ProductVariant.DoesNotExist:
                            # If not found, create a new variant.
                            ProductVariant.objects.create(**variant_data)
                            created_count += 1
                    else:
                        # If no id is provided, update by unique variant_code or create.
                        variant, created = ProductVariant.objects.update_or_create(
                            variant_code=row['variant_code'],
                            defaults=variant_data
                        )
                        if created:
                            created_count += 1
                        else:
                            updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Import complete: {created_count} created, {updated_count} updated."
        ))
