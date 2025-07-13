import os
import django
import sys
import logging

# ----------------------------------------------------------------
#  Adjust these paths/settings to point at your project correctly
# ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # <-- your settings module
django.setup()

import pandas as pd
from datetime import datetime
from django.db import transaction
from inventory.models import Sale, ProductVariant

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
#  CSV/XLSX filename and optional "test" flag
# ----------------------------------------------------------------
if len(sys.argv) < 2:
    logger.info("Usage: python upload_sales.py <filename> [test]")
    sys.exit(1)

file_path = sys.argv[1]
test_mode = len(sys.argv) > 2 and sys.argv[2].lower() == 'test'

# Load the file
if file_path.endswith('.csv'):
    df = pd.read_csv(file_path)
else:
    df = pd.read_excel(file_path)

@transaction.atomic
def upload_sales(test=False):
    errors = []
    savepoint = transaction.savepoint()

    try:
        for index, row in df.iterrows():
            try:
                # ---- parse fields from each row ----
                order_number   = str(row['内部订单号']) if not pd.isnull(row['内部订单号']) else None
                order_date     = datetime.strptime(row['订单日期'], '%Y/%m/%d %H:%M:%S') \
                                     if not pd.isnull(row['订单日期']) else None
                variant_code   = str(row['商品编码']) if not pd.isnull(row['商品编码']) else None
                sold_quantity  = int(row['销售数量']) if not pd.isnull(row['销售数量']) else 0
                sold_value     = float(row['实发金额'])   if not pd.isnull(row['实发金额'])   else 0.00
                return_quantity= int(row['实退数量'])   if not pd.isnull(row['实退数量']) else 0
                return_value   = float(row['退货金额'])   if not pd.isnull(row['退货金额'])   else 0.00

                # ---- look up the variant ----
                variant = ProductVariant.objects.filter(variant_code=variant_code).first()
                if not variant:
                    errors.append(f"No ProductVariant for code {variant_code} (row {index})")
                    continue

                # ---- create the Sale record ----
                if not test:
                    Sale.objects.create(
                        order_number   = order_number,
                        date           = order_date,
                        variant        = variant,
                        sold_quantity  = sold_quantity,
                        return_quantity= return_quantity,
                        sold_value     = sold_value,
                        return_value   = return_value,
                    )

                logger.info(
                    "Processed Order#%s, Variant %s on %s",
                    order_number,
                    variant_code,
                    order_date,
                )

            except Exception as e:
                msg = f"Error on row {index}: {e}"
                errors.append(msg)
                logger.error(msg)

        # rollback if in test mode
        if test:
            logger.info("\nTEST MODE – rolling back all changes.")
            transaction.savepoint_rollback(savepoint)

    except Exception as e:
        logger.error("Critical error: %s", e)
        transaction.savepoint_rollback(savepoint)

    return errors

if __name__ == "__main__":
    # ensure Django env is set (again) if necessary
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventory.settings')  # or your settings
    django.setup()

    logging.basicConfig(level=logging.INFO)
    errors = upload_sales(test=test_mode)
    logger.info("\nUpload completed!")
    if errors:
        logger.info("The following errors were encountered:")
        for err in errors:
            logger.info(" - %s", err)
