import os
import django
import sys

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

# ----------------------------------------------------------------
#  CSV/XLSX filename and optional "test" flag
# ----------------------------------------------------------------
if len(sys.argv) < 2:
    print("Usage: python upload_sales.py <filename> [test]")
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

                print(f"Processed Order#{order_number}, Variant {variant_code} on {order_date}")

            except Exception as e:
                msg = f"Error on row {index}: {e}"
                errors.append(msg)
                print(msg)

        # rollback if in test mode
        if test:
            print("\nTEST MODE – rolling back all changes.")
            transaction.savepoint_rollback(savepoint)

    except Exception as e:
        print(f"Critical error: {e}")
        transaction.savepoint_rollback(savepoint)

    return errors

if __name__ == "__main__":
    # ensure Django env is set (again) if necessary
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventory.settings')  # or your settings
    django.setup()

    errors = upload_sales(test=test_mode)
    print("\nUpload completed!")
    if errors:
        print("The following errors were encountered:")
        for err in errors:
            print(f" - {err}")
