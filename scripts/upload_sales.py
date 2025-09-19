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
from datetime import datetime, date
from django.db import transaction
from inventory.models import Sale, ProductVariant

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
#  CSV/XLSX filename and optional "test" flag
# ----------------------------------------------------------------
if len(sys.argv) < 2:
    logger.info("Usage: python upload_sales.py <filename> [test] [diff]")
    sys.exit(1)

file_path = sys.argv[1]
flags = {arg.lower() for arg in sys.argv[2:]}
test_mode = "test" in flags
diff_mode = "diff" in flags

# Load the file
if file_path.endswith('.csv'):
    df = pd.read_csv(file_path)
else:
    df = pd.read_excel(file_path)

def _serialize_row(row_series):
    return {
        key: (None if pd.isnull(value) else value)
        for key, value in row_series.items()
    }


def _serialize_sale_fields(
    *,
    order_number,
    order_date,
    variant,
    variant_code,
    sold_quantity,
    sold_value,
    return_quantity,
    return_value,
):
    """Return only the fields required to create a Sale manually."""

    if isinstance(order_date, (datetime, date)):
        date_value = order_date.isoformat()
    else:
        date_value = order_date

    payload = {
        "order_number": order_number,
        "date": date_value,
        "variant_code": variant_code,
        "sold_quantity": sold_quantity,
        "sold_value": sold_value,
        "return_quantity": return_quantity,
        "return_value": return_value,
    }

    if variant is not None:
        payload["variant_id"] = variant.id

    return payload



def _parse_order_date(raw_value):
    if pd.isnull(raw_value):
        return None

    if isinstance(raw_value, datetime):
        return raw_value.date()

    if isinstance(raw_value, date):
        return raw_value

    if hasattr(raw_value, "to_pydatetime"):
        return raw_value.to_pydatetime().date()

    if isinstance(raw_value, str):
        date_formats = [
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d",
            "%Y-%m-%d",
        ]
        for fmt in date_formats:
            try:
                return datetime.strptime(raw_value, fmt).date()
            except ValueError:
                continue

    raise ValueError(f"Unrecognized date format: {raw_value!r}")



@transaction.atomic
def upload_sales(test=False, diff=False):
    errors = []
    failed_rows = []
    diff_missing_rows = []

    savepoint = transaction.savepoint()
    should_save = not test and not diff

    try:
        for index, row in df.iterrows():
            try:
                # ---- parse fields from each row ----
                order_number   = str(row['内部订单号']) if not pd.isnull(row['内部订单号']) else None
                order_date     = _parse_order_date(row['订单日期'])
                variant_code   = str(row['商品编码']) if not pd.isnull(row['商品编码']) else None
                sold_quantity  = int(row['销售数量']) if not pd.isnull(row['销售数量']) else 0
                sold_value     = float(row['实发金额'])   if not pd.isnull(row['实发金额'])   else 0.00
                return_quantity= int(row['实退数量'])   if not pd.isnull(row['实退数量']) else 0
                return_value   = float(row['退货金额'])   if not pd.isnull(row['退货金额'])   else 0.00

                # ---- look up the variant ----
                variant = ProductVariant.objects.filter(variant_code=variant_code).first()
                if not variant:
                    msg = f"No ProductVariant for code {variant_code} (row {index})"
                    errors.append(msg)
                    failed_rows.append((index, msg, _serialize_row(row)))
                    continue

                # ---- create the Sale record ----
                if should_save:
                    Sale.objects.create(
                        order_number   = order_number,
                        date           = order_date,
                        variant        = variant,
                        sold_quantity  = sold_quantity,
                        return_quantity= return_quantity,
                        sold_value     = sold_value,
                        return_value   = return_value,
                    )

                if diff and order_number and order_date and variant:
                    exists = Sale.objects.filter(
                        order_number=order_number,
                        date=order_date,
                        variant=variant,
                    ).exists()
                    if not exists:
                        diff_missing_rows.append(
                            (
                                index,
                                _serialize_sale_fields(
                                    order_number=order_number,
                                    order_date=order_date,
                                    variant=variant,
                                    variant_code=variant_code,
                                    sold_quantity=sold_quantity,
                                    sold_value=sold_value,
                                    return_quantity=return_quantity,
                                    return_value=return_value,
                                ),
                            )
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
                failed_rows.append((index, msg, _serialize_row(row)))
                logger.error(msg)

        # rollback if in test mode
        if test:
            logger.info("\nTEST MODE – rolling back all changes.")
            transaction.savepoint_rollback(savepoint)

    except Exception as e:
        logger.error("Critical error: %s", e)
        transaction.savepoint_rollback(savepoint)

    if failed_rows:
        logger.info("\nRows that were not uploaded:")
        for row_index, reason, row_contents in failed_rows:
            logger.info("Row %s failed: %s", row_index, reason)
            logger.info("Row %s data: %s", row_index, row_contents)

    if diff:
        if diff_missing_rows:
            logger.info("\nSpreadsheet rows missing from the database:")
            for row_index, row_contents in diff_missing_rows:
                logger.info("Row %s missing: %s", row_index, row_contents)
        else:
            logger.info("\nAll spreadsheet rows already exist in the database.")


    return errors

if __name__ == "__main__":
    # ensure Django env is set (again) if necessary
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventory.settings')  # or your settings
    django.setup()

    logging.basicConfig(level=logging.INFO)
    errors = upload_sales(test=test_mode, diff=diff_mode)
    logger.info("\nProcessing completed!")
    if errors:
        logger.info("The following errors were encountered:")
        for err in errors:
            logger.info(" - %s", err)
