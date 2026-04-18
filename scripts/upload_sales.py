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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db import transaction
from django.conf import settings
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


def _get_row_value(row, key):
    if key not in row:
        return None
    value = row[key]
    if pd.isnull(value):
        return None
    return value


def _to_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    return None


def _normalize_text(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    return " ".join(text.split())


def _classify_discount_reasons(coupon_name):
    normalized_coupon = _normalize_text(coupon_name)
    if not normalized_coupon:
        return []

    keyword_config = getattr(settings, "SALES_DISCOUNT_REASON_KEYWORDS", {})
    matched_reasons = []
    for reason, keywords in keyword_config.items():
        for keyword in keywords:
            normalized_keyword = _normalize_text(keyword)
            if normalized_keyword and normalized_keyword in normalized_coupon:
                matched_reasons.append(reason)
                break

    return sorted(set(matched_reasons))


def _calculate_discount_fields(list_price, sold_value, coupon_name):
    if list_price is None or sold_value is None:
        return None, False, [], False, None

    discount_amount = (list_price - sold_value).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    is_discounted = discount_amount > Decimal("0.01")
    reasons = []
    manual_discount_flag = False
    discount_notes = None

    if is_discounted:
        reasons = _classify_discount_reasons(coupon_name)

    return discount_amount, is_discounted, reasons, manual_discount_flag, discount_notes



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
                list_price = _to_decimal(_get_row_value(row, "基本售价"))
                sold_value_decimal = _to_decimal(sold_value)
                coupon_name_raw = _get_row_value(row, "优惠券名称")
                seller_note = _get_row_value(row, "卖家备注")
                product_short_name = _get_row_value(row, "商品简称")
                (
                    discount_amount,
                    is_discounted,
                    discount_reasons,
                    manual_discount_flag,
                    discount_notes,
                ) = _calculate_discount_fields(
                    list_price=list_price,
                    sold_value=sold_value_decimal,
                    coupon_name=coupon_name_raw,
                )

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
                        list_price     = list_price,
                        discount_amount= discount_amount,
                        is_discounted  = is_discounted,
                        discount_reasons= discount_reasons,
                        coupon_name_raw= str(coupon_name_raw) if coupon_name_raw is not None else None,
                        seller_note    = str(seller_note) if seller_note is not None else None,
                        product_short_name= str(product_short_name) if product_short_name is not None else None,
                        manual_discount_flag=manual_discount_flag,
                        discount_notes = discount_notes,
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
