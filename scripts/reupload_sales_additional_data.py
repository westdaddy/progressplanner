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

from inventory.models import Discount, ProductVariant, Sale  # noqa: E402

logger = logging.getLogger(__name__)


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map normalized column names to actual DataFrame column labels."""
    resolved = {}
    for column in df.columns:
        normalized = str(column).strip().replace("\ufeff", "")
        if normalized not in resolved:
            resolved[normalized] = column
    return resolved


def _get_row_value(row, columns: dict[str, str], *aliases):
    for alias in aliases:
        real_key = columns.get(alias)
        if real_key is not None:
            return row.get(real_key)
    return None


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
        return raw_value if not isinstance(raw_value, datetime) else raw_value.date()

    try:
        return pd.to_datetime(raw_value).date()
    except Exception as exc:  # pragma: no cover - defensive logging
        raise ValueError(f"Could not parse order date '{raw_value}': {exc}") from exc


def _normalize_string(value):
    if pd.isnull(value):
        return None
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return None
    return text or None


def _parse_decimal_or_none(value):
    if pd.isnull(value):
        return None
    if isinstance(value, Decimal):
        return value

    text = str(value).strip().replace(",", "")
    if not text:
        return None

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value '{value}': {exc}") from exc


def _has_existing_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _parse_coupon_codes(coupon_name_raw):
    if coupon_name_raw is None:
        return []

    normalized_raw = str(coupon_name_raw).replace("；", ";")
    codes = []
    for raw_code in normalized_raw.split(";"):
        cleaned = raw_code.strip().strip('"').strip("'").strip()
        if cleaned:
            codes.append(cleaned)
    return codes


def _cleanup_coupon_name_raw_placeholders() -> int:
    cleaned_sales = []
    for sale in Sale.objects.exclude(coupon_name_raw__isnull=True).only("sale_id", "coupon_name_raw").iterator():
        if _normalize_string(sale.coupon_name_raw) is None:
            sale.coupon_name_raw = None
            cleaned_sales.append(sale)

    if cleaned_sales:
        Sale.objects.bulk_update(cleaned_sales, ["coupon_name_raw"])
    return len(cleaned_sales)


@transaction.atomic
def reupload_sales_additional_data(file_path: str, test: bool = False):
    df = _load_dataframe(file_path)
    columns = _resolve_columns(df)

    errors = []
    stats = {
        "processed": 0,
        "matched_sales": 0,
        "updated_sales": 0,
        "skipped_no_match": 0,
        "coupon_name_raw_cleaned": 0,
        "list_price_set": 0,
        "seller_note_set": 0,
        "coupon_name_raw_set": 0,
        "discounts_added": 0,
    }

    savepoint = transaction.savepoint()

    discount_by_code = {discount.code: discount for discount in Discount.objects.all()}

    try:
        # Cleanup pass required before processing new data:
        # remove legacy literal "nan" values from coupon_name_raw.
        cleaned_count = _cleanup_coupon_name_raw_placeholders()
        stats["coupon_name_raw_cleaned"] = cleaned_count

        for index, row in df.iterrows():
            stats["processed"] += 1

            try:
                order_number = _normalize_string(_get_row_value(row, columns, "内部订单号"))
                variant_code = _normalize_string(_get_row_value(row, columns, "商品编码"))
                order_date = _parse_order_date(_get_row_value(row, columns, "订单日期"))

                if not order_number or not variant_code or not order_date:
                    errors.append(
                        f"Missing identifying data in row {index}: "
                        f"order_number={order_number}, variant_code={variant_code}, order_date={order_date}"
                    )
                    continue

                try:
                    variant = ProductVariant.objects.get(variant_code=variant_code)
                except ProductVariant.DoesNotExist:
                    errors.append(f"Row {index}: No ProductVariant found for code {variant_code}")
                    continue

                sales = list(
                    Sale.objects.filter(
                        order_number=order_number,
                        date=order_date,
                        variant=variant,
                    ).select_for_update()
                )

                if not sales:
                    stats["skipped_no_match"] += 1
                    continue

                stats["matched_sales"] += len(sales)

                incoming_list_price = _parse_decimal_or_none(
                    _get_row_value(row, columns, "基本售价")
                )
                incoming_seller_note = _normalize_string(
                    _get_row_value(row, columns, "卖家备注")
                )
                incoming_coupon_raw_value = _get_row_value(row, columns, "优惠券名称")
                incoming_coupon_codes = _parse_coupon_codes(incoming_coupon_raw_value)
                incoming_coupon_name_raw = _normalize_string(incoming_coupon_raw_value)
                if incoming_coupon_name_raw is None and incoming_coupon_codes:
                    incoming_coupon_name_raw = ";".join(incoming_coupon_codes)

                matched_discounts = [
                    discount_by_code[code]
                    for code in incoming_coupon_codes
                    if code in discount_by_code
                ]

                for sale in sales:
                    update_fields = []

                    if not _has_existing_value(sale.list_price) and incoming_list_price is not None:
                        sale.list_price = incoming_list_price
                        update_fields.append("list_price")
                        stats["list_price_set"] += 1

                    if not _has_existing_value(sale.seller_note) and incoming_seller_note is not None:
                        sale.seller_note = incoming_seller_note
                        update_fields.append("seller_note")
                        stats["seller_note_set"] += 1

                    if (
                        not _has_existing_value(sale.coupon_name_raw)
                        and incoming_coupon_name_raw is not None
                    ):
                        sale.coupon_name_raw = incoming_coupon_name_raw
                        update_fields.append("coupon_name_raw")
                        stats["coupon_name_raw_set"] += 1

                    if update_fields:
                        sale.save(update_fields=update_fields)

                    sale_changed = bool(update_fields)

                    if matched_discounts:
                        existing_discount_ids = set(
                            sale.discounts.values_list("id", flat=True)
                        )
                        discounts_to_add = [
                            discount for discount in matched_discounts if discount.id not in existing_discount_ids
                        ]
                        if discounts_to_add:
                            sale.discounts.add(*discounts_to_add)
                            stats["discounts_added"] += len(discounts_to_add)
                            sale_changed = True

                    if sale_changed:
                        stats["updated_sales"] += 1

            except Exception as exc:
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
        logger.info("Usage: python reupload_sales_additional_data.py <filename> [test]")
        sys.exit(1)

    input_path = sys.argv[1]
    flags = {arg.lower() for arg in sys.argv[2:]}
    test_mode = "test" in flags

    errors, stats = reupload_sales_additional_data(input_path, test=test_mode)

    logger.info(
        "\nProcessed %(processed)s rows, matched %(matched_sales)s sales, updated %(updated_sales)s sales, "
        "%(skipped_no_match)s without matches.",
        stats,
    )
    logger.info(
        "Fields set: list_price=%(list_price_set)s, seller_note=%(seller_note_set)s, "
        "coupon_name_raw=%(coupon_name_raw_set)s. Discounts added=%(discounts_added)s. "
        "Pre-cleaned coupon_name_raw='nan': %(coupon_name_raw_cleaned)s.",
        stats,
    )

    if errors:
        logger.info("Errors encountered during upload:")
        for message in errors:
            logger.info(" - %s", message)
