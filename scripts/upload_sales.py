import os
import django
import sys

# Set the path to the project root (where manage.py is located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Adjust if your settings module differs
django.setup()

import pandas as pd
from datetime import datetime
from django.db import transaction
from inventory.models import Sale, ProductVariant


'''
This script uploads sales data. It should have been exported from ERP under the
Reports tab. It should be exported and uploaded every month.

Usage:
    python upload_sales.py <filename> [test]
'''

if len(sys.argv) < 2:
    print("Usage: python upload_sales.py <filename> [test]")
    sys.exit(1)

file_path = sys.argv[1]
test_mode = len(sys.argv) > 2 and sys.argv[2].lower() == 'test'

# Load the file (CSV or Excel)
if file_path.endswith('.csv'):
    df = pd.read_csv(file_path)
else:
    df = pd.read_excel(file_path)

@transaction.atomic
def upload_sales(test=False):
    errors = []
    # Create a transaction savepoint
    savepoint = transaction.savepoint()

    try:
        for index, row in df.iterrows():
            try:
                # Parse the data from the file
                order_date = datetime.strptime(row['订单日期'], '%Y/%m/%d %H:%M:%S') if not pd.isnull(row['订单日期']) else None
                variant_code = str(row['商品编码']) if not pd.isnull(row['商品编码']) else None
                sold_quantity = int(row['销售数量']) if not pd.isnull(row['销售数量']) else 0
                sold_value = float(row['实发金额']) if not pd.isnull(row['实发金额']) else 0.00
                return_quantity = int(row['实退数量']) if not pd.isnull(row['实退数量']) else 0
                return_value = float(row['退货金额']) if not pd.isnull(row['退货金额']) else 0.00

                # Find the corresponding product variant
                variant = ProductVariant.objects.filter(variant_code=variant_code).first()
                if not variant:
                    errors.append(f"No matching ProductVariant found for variant_code: {variant_code}")
                    continue

                # Simulate or create the Sale record
                if not test:
                    Sale.objects.create(
                        date=order_date,
                        variant=variant,
                        sold_quantity=sold_quantity,
                        return_quantity=return_quantity,
                        sold_value=sold_value,
                        return_value=return_value
                    )


                print(f"Processed sale for variant {variant_code} on {order_date}.")

            except Exception as e:
                error_msg = f"Error processing row {index}: {e}"
                errors.append(error_msg)
                print(error_msg)

        if test:
            print("\nTEST MODE: No data was committed.")
            transaction.savepoint_rollback(savepoint)

    except Exception as e:
        print(f"Critical error: {e}")
        transaction.savepoint_rollback(savepoint)

    return errors


if __name__ == "__main__":
    import django
    import os

    # Set up Django environment
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventory.settings')  # Replace with your project settings module
    django.setup()

    errors = upload_sales(test=test_mode)
    print("\nUpload completed!")
    if errors:
        print("The following errors were encountered:")
        for error in errors:
            print(f"- {error}")
