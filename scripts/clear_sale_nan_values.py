import logging
import os
import sys

import django
from django.db import transaction

# ----------------------------------------------------------------
#  Configure Django settings
# ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "progressplanner.settings")
django.setup()

from inventory.models import Sale  # noqa: E402

logger = logging.getLogger(__name__)
PLACEHOLDER_VALUES = {"nan", "none", "null", "nat"}


def _normalize_string(value):
    if value is None:
        return None

    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()

    if not text:
        return None

    if text.lower() in PLACEHOLDER_VALUES:
        return None

    return text


@transaction.atomic
def clear_sale_nan_values(test: bool = False):
    savepoint = transaction.savepoint()

    sales_updated = 0
    fields_cleared = {
        "coupon_name_raw": 0,
        "seller_note": 0,
        "product_short_name": 0,
    }

    for sale in Sale.objects.all().only(
        "sale_id", "coupon_name_raw", "seller_note", "product_short_name"
    ).iterator():
        update_fields = []

        for field_name in fields_cleared.keys():
            raw_value = getattr(sale, field_name)
            normalized = _normalize_string(raw_value)
            if raw_value is not None and normalized is None:
                setattr(sale, field_name, None)
                update_fields.append(field_name)
                fields_cleared[field_name] += 1

        if update_fields:
            sale.save(update_fields=update_fields)
            sales_updated += 1

    if test:
        logger.info("TEST MODE – rolling back all changes.")
        transaction.savepoint_rollback(savepoint)

    return {
        "sales_updated": sales_updated,
        **fields_cleared,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    flags = {arg.lower() for arg in sys.argv[1:]}
    test_mode = "test" in flags

    stats = clear_sale_nan_values(test=test_mode)

    logger.info(
        "Updated %(sales_updated)s sales. Cleared coupon_name_raw=%(coupon_name_raw)s, "
        "seller_note=%(seller_note)s, product_short_name=%(product_short_name)s.",
        stats,
    )
