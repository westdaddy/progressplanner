import logging
import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import django
import pandas as pd
from django.db import transaction

# ----------------------------------------------------------------
#  Configure Django settings
# ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "progressplanner.settings")
django.setup()

from inventory.models import ProductVariant, Sale  # noqa: E402  (import after setup)

logger = logging.getLogger(__name__)


def _load_dataframe(file_path: str) -> pd.DataFrame:
    """Load a spreadsheet (CSV or XLSX) into a DataFrame."""
    if file_path.lower().endswith(".csv"):
        return pd.read_csv(file_path)
    return pd.read_excel(file_path)


def _parse_order_date(raw_value) -> date:
    """Normalise spreadsheet date values to a python ``date``."""
    if pd.isnull(raw_value):
        return None

    if isinstance(raw_value, date):
        # datetime is also an instance of date, but includes time
        return raw_value if not isinstance(raw_value, datetime) else raw_value.date()

    try:
        return pd.to_datetime(raw_value).date()
    except Exception as exc:  # pragma: no cover - defensive logging
        raise ValueError(f"Could not parse order date '{raw_value}': {exc}") from exc


def _parse_int(value) -> int:
    if pd.isnull(value):
        return 0
    try:
        return int(value)
    except ValueError:
        return int(float(value))


def _parse_decimal(value) -> Decimal:
    if pd.isnull(value):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value '{value}': {exc}") from exc


@transaction.atomic
def upload_updated_sales(file_path: str, test: bool = False):
    df = _load_dataframe(file_path)

    errors = []
    stats = {
        "processed": 0,
        "updated": 0,
        "skipped_no_change": 0,
        "skipped_no_match": 0,
    }

    savepoint = transaction.savepoint()

    try:
        for index, row in df.iterrows():
            stats["processed"] += 1

            try:
                order_number_raw = row.get("内部订单号")
                order_number = (
                    str(order_number_raw).strip()
                    if not pd.isnull(order_number_raw)
                    else None
                )
                variant_code_raw = row.get("商品编码")
                variant_code = (
                    str(variant_code_raw).strip()
                    if not pd.isnull(variant_code_raw)
                    else None
                )
                order_date = _parse_order_date(row.get("订单日期"))

                if not order_number or not variant_code or not order_date:
                    errors.append(
                        f"Missing identifying data in row {index}: "
                        f"order_number={order_number}, variant_code={variant_code}, order_date={order_date}"
                    )
                    continue

                try:
                    variant = ProductVariant.objects.get(variant_code=variant_code)
                except ProductVariant.DoesNotExist:
                    errors.append(
                        f"Row {index}: No ProductVariant found for code {variant_code}"
                    )
                    continue

                sale = (
                    Sale.objects.filter(
                        order_number=order_number,
                        date=order_date,
                        variant=variant,
                    )
                    .select_for_update()
                    .first()
                )

                if sale is None:
                    stats["skipped_no_match"] += 1
                    logger.info(
                        "Skipping row %s: no existing sale for order %s, variant %s on %s",
                        index,
                        order_number,
                        variant_code,
                        order_date,
                    )
                    continue

                new_return_qty = _parse_int(row.get("实退数量"))
                new_return_value = _parse_decimal(row.get("退货金额"))

                existing_qty = sale.return_quantity or 0
                existing_value = sale.return_value if sale.return_value is not None else Decimal("0")

                update_fields = []

                if existing_qty != new_return_qty:
                    sale.return_quantity = new_return_qty
                    update_fields.append("return_quantity")

                if existing_value != new_return_value:
                    sale.return_value = new_return_value
                    update_fields.append("return_value")

                if update_fields:
                    sale.save(update_fields=update_fields)
                    stats["updated"] += 1
                    logger.info(
                        "Updated sale %s (Order %s / Variant %s / %s): %s",
                        sale.pk,
                        order_number,
                        variant_code,
                        order_date,
                        ", ".join(update_fields),
                    )
                else:
                    stats["skipped_no_change"] += 1

            except Exception as exc:  # capture row-specific errors
                error_message = f"Error on row {index}: {exc}"
                errors.append(error_message)
                logger.error(error_message)

        if test:
            logger.info("\nTEST MODE – rolling back all changes.")
            transaction.savepoint_rollback(savepoint)

    except Exception as exc:
        logger.error("Critical error: %s", exc)
        transaction.savepoint_rollback(savepoint)
        raise

    return errors, stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        logger.info("Usage: python upload_updated_sales.py <filename> [test]")
        sys.exit(1)

    input_path = sys.argv[1]
    test_mode = len(sys.argv) > 2 and sys.argv[2].lower() == "test"

    errors, stats = upload_updated_sales(input_path, test=test_mode)

    logger.info(
        "\nProcessed %(processed)s rows, %(updated)s updates, %(skipped_no_match)s without matches, "
        "%(skipped_no_change)s without changes.",
        stats,
    )

    if errors:
        logger.info("Errors encountered during upload:")
        for message in errors:
            logger.info(" - %s", message)
