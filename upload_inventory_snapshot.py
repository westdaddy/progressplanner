import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Replace 'inventory.settings' with your settings module
django.setup()

import sys
import pandas as pd
from datetime import datetime
from django.db import transaction
from inventory.models import InventorySnapshot, ProductVariant

'''
This script uploads inventory snapshots from two .xlsx files.

Usage:
    python upload_inventory.py <file1.xlsx> <file2.xlsx> [test]
'''

if len(sys.argv) < 3:
    print("Usage: python upload_inventory.py <file1.xlsx> <file2.xlsx> [test]")
    sys.exit(1)

file1_path = sys.argv[1]
file2_path = sys.argv[2]
test_mode = len(sys.argv) > 3 and sys.argv[3].lower() == 'test'

def import_inventory_snapshot(file_path, test=False):
    # Load the Excel file
    df = pd.read_excel(file_path)

    # Start a transaction savepoint
    savepoint = transaction.savepoint()

    try:
        # Iterate over rows and create/update snapshots
        for index, row in df.iterrows():
            try:
                variant_code = str(row['商品编码']) if not pd.isnull(row['商品编码']) else None
                inventory_count = int(row['实际库存数']) if not pd.isnull(row['实际库存数']) else None
                snapshot_date = datetime.strptime(row['日期'], '%Y-%m-%d').date() if '日期' in row else datetime.today().date()

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

        # Rollback changes in test mode
        if test:
            print("\nTEST MODE: Rolling back transaction...")
            transaction.savepoint_rollback(savepoint)

    except Exception as e:
        print(f"Critical error: {e}")
        transaction.savepoint_rollback(savepoint)

if __name__ == "__main__":
    import django
    import os

    # Set up Django environment
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventory.settings')  # Update with your settings module
    django.setup()

    print(f"Processing file: {file1_path}")
    import_inventory_snapshot(file1_path, test=test_mode)

    print(f"Processing file: {file2_path}")
    import_inventory_snapshot(file2_path, test=test_mode)

    if test_mode:
        print("TEST MODE: No changes have been committed.")
    else:
        print("Inventory snapshot upload completed!")
