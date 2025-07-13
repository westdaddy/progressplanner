import os
import django
import sys
import logging

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

logger = logging.getLogger(__name__)

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

    snapshot_date = datetime.strptime(match.group(1), "%Y_%m_%d").date()
    logger.info("Snapshot date extracted: %s", snapshot_date)

    # Load the Excel file
    df = pd.read_excel(file_path)

    # Extract variant codes from the file
    file_variant_codes = set()
    for index, row in df.iterrows():
        variant_code = str(row['商品编码']) if not pd.isnull(row['商品编码']) else None
        inventory_count = int(row['实际库存数']) if not pd.isnull(row['实际库存数']) else None

        if not variant_code or inventory_count is None:
            logger.warning(
                "Skipping row %s: Missing variant code or inventory count.", index
            )
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
                    logger.warning(
                        "Skipping row %s: Missing variant code or inventory count.",
                        index,
                    )
                    continue

                # Find the corresponding product variant
                product_variant = ProductVariant.objects.filter(variant_code=variant_code).first()
                if not product_variant:
                    logger.warning(
                        "Skipping row %s: No matching ProductVariant found for variant_code %s.",
                        index,
                        variant_code,
                    )
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
                    logger.info(
                        "%s snapshot: %s - %s - %s units.",
                        "TEST MODE: Would update" if test else "Updated",
                        variant_code,
                        snapshot_date,
                        inventory_count,
                    )
                else:
                    # Create new snapshot
                    if not test:
                        InventorySnapshot.objects.create(
                            product_variant=product_variant,
                            date=snapshot_date,
                            inventory_count=inventory_count,
                        )
                    logger.info(
                        "%s snapshot: %s - %s - %s units.",
                        "TEST MODE: Would create" if test else "Created",
                        variant_code,
                        snapshot_date,
                        inventory_count,
                    )

            except Exception as e:
                logger.error("Error processing row %s: %s", index, e)

        # Process variants not in the file
        all_variant_codes = set(ProductVariant.objects.values_list('variant_code', flat=True))
        missing_variant_codes = all_variant_codes - file_variant_codes

        for variant_code in missing_variant_codes:
            try:
                product_variant = ProductVariant.objects.filter(variant_code=variant_code).first()
                if not product_variant:
                    logger.warning(
                        "Skipping missing variant %s: No matching ProductVariant found.",
                        variant_code,
                    )
                    continue

                # Create snapshot with 0 inventory count
                if not test:
                    InventorySnapshot.objects.create(
                        product_variant=product_variant,
                        date=snapshot_date,
                        inventory_count=0,
                    )
                logger.info(
                    "%s snapshot: %s - %s - 0 units.",
                    "TEST MODE: Would create" if test else "Created",
                    variant_code,
                    snapshot_date,
                )

            except Exception as e:
                logger.error(
                    "Error processing missing variant %s: %s", variant_code, e
                )

        # Rollback changes in test mode
        if test:
            logger.info("\nTEST MODE: Rolling back transaction...")
            transaction.savepoint_rollback(savepoint)

    except Exception as e:
        logger.error("Critical error: %s", e)
        transaction.savepoint_rollback(savepoint)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.info("Usage: python upload_inventory_snapshot.py <file.xlsx> [test]")
        sys.exit(1)

    file_path = sys.argv[1]
    test_mode = len(sys.argv) > 2 and sys.argv[2].lower() == 'test'
    logging.basicConfig(level=logging.INFO)
    import_inventory_snapshot(file_path, test=test_mode)

    if test_mode:
        logger.info("TEST MODE: No changes have been committed.")
    else:
        logger.info("Inventory snapshot upload completed!")
