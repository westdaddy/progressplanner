import os
import django
import sys

# Set the path to the project root (where manage.py is located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Adjust if your settings module differs
django.setup()

import re
import pandas as pd
from datetime import datetime
from django.db import transaction
from inventory.models import InventorySnapshot, ProductVariant

# Set up Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Adjust if your settings module differs
django.setup()

def import_inventory_snapshot(file_path, test=False):
    # Extract the snapshot date from the filename
    match = re.search(r'(\d{4}_\d{2}_\d{2})', file_path)
    if not match:
        raise ValueError(f"Invalid filename format. Expected YYYY_MM_DD in {file_path}")

    snapshot_date = datetime.strptime(match.group(1), '%Y_%m_%d').date()
    print(f"Snapshot date extracted: {snapshot_date}")

    # Load the Excel file
    df = pd.read_excel(file_path)

    # Extract variant codes from the file
    file_variant_codes = set()
    for index, row in df.iterrows():
        variant_code = str(row['商品编码']) if not pd.isnull(row['商品编码']) else None
        inventory_count = int(row['实际库存数']) if not pd.isnull(row['实际库存数']) else None

        if not variant_code or inventory_count is None:
            print(f"Skipping row {index}: Missing variant code or inventory count.")
            continue

        file_variant_codes.add(variant_code)

    # Start a transaction savepoint
    savepoint = transaction.savepoint()

    try:
        # Process inventory from the file
        for index, row in df.iterrows():
            try:
                variant_code = str(row['商品编码']) if not pd.isnull(row['商品编码']) else None
                inventory_count = int(row['实际库存数']) if not pd.isnull(row['实际库存数']) else None

                if not variant_code or inventory_count is None:
                    print(f"Skipping row {index}: Missing variant code or inventory count.")
                    continue

                # Find the corresponding product variant
                product_variant = ProductVariant.objects.filter(variant_code=variant_code).first()
                if not product_variant:
                    print(f"Skipping row {index}: No matching ProductVariant found for variant_code {variant_code}.")
                    continue

                # Check for an existing snapshot
                snapshot = InventorySnapshot.objects.filter(
                    product_variant=product_variant,
                    date=snapshot_date
                ).first()

                if snapshot:
                    # Update existing snapshot
                    snapshot.inventory_count = inventory_count
                    if not test:
                        snapshot.save()
                    print(f"{'TEST MODE: Would update' if test else 'Updated'} snapshot: {variant_code} - {snapshot_date} - {inventory_count} units.")
                else:
                    # Create new snapshot
                    if not test:
                        InventorySnapshot.objects.create(
                            product_variant=product_variant,
                            date=snapshot_date,
                            inventory_count=inventory_count,
                        )
                    print(f"{'TEST MODE: Would create' if test else 'Created'} snapshot: {variant_code} - {snapshot_date} - {inventory_count} units.")

            except Exception as e:
                print(f"Error processing row {index}: {e}")

        # Process variants not in the file
        all_variant_codes = set(ProductVariant.objects.values_list('variant_code', flat=True))
        missing_variant_codes = all_variant_codes - file_variant_codes

        for variant_code in missing_variant_codes:
            try:
                product_variant = ProductVariant.objects.filter(variant_code=variant_code).first()
                if not product_variant:
                    print(f"Skipping missing variant {variant_code}: No matching ProductVariant found.")
                    continue

                # Create snapshot with 0 inventory count
                if not test:
                    InventorySnapshot.objects.create(
                        product_variant=product_variant,
                        date=snapshot_date,
                        inventory_count=0,
                    )
                print(f"{'TEST MODE: Would create' if test else 'Created'} snapshot: {variant_code} - {snapshot_date} - 0 units.")

            except Exception as e:
                print(f"Error processing missing variant {variant_code}: {e}")

        # Rollback changes in test mode
        if test:
            print("\nTEST MODE: Rolling back transaction...")
            transaction.savepoint_rollback(savepoint)

    except Exception as e:
        print(f"Critical error: {e}")
        transaction.savepoint_rollback(savepoint)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_inventory_snapshot.py <file.xlsx> [test]")
        sys.exit(1)

    file_path = sys.argv[1]
    test_mode = len(sys.argv) > 2 and sys.argv[2].lower() == 'test'
    import_inventory_snapshot(file_path, test=test_mode)

    if test_mode:
        print("TEST MODE: No changes have been committed.")
    else:
        print("Inventory snapshot upload completed!")
