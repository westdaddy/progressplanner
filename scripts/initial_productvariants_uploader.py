import os
import django
import sys
import csv
import logging

# ─── Bootstrapping Django ───────────────────────────────────────────────────────

# Set the path to the project root (where manage.py is located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set the Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "progressplanner.settings")
django.setup()


from inventory.models import Product, ProductVariant

logger = logging.getLogger(__name__)


# ─── Configuration ──────────────────────────────────────────────────────────────

# Path to your CSV file
CSV_FILE_PATH = "data/initialdata/variants_list.csv"

# Map color names to hex codes
COLOR_TO_HEX = {
    "white": "#FFFFFF",
    "black": "#000000",
    "blue": "#0000FF",
    "red": "#FF0000",
    "green": "#00FF00",
    "yellow": "#FFFF00",
    "grey": "#808080",
    "purple": "#800080",
    "lilac": "#C8A2C8",
}


def map_color_to_hex(color_name):
    """Map a human color name to a hex code, defaulting to white if unknown."""
    return COLOR_TO_HEX.get(color_name.lower(), "#FFFFFF")


# ─── Build “invert CHOICES” lookup maps ──────────────────────────────────────────


def make_choice_map(choices):
    """
    Given a list like [('gi','Gi'),('rg','Rashguard'),…],
    return a dict mapping both key and label (lowercased) → key.
    """
    m = {}
    for key, label in choices:
        m[key.lower()] = key
        m[label.lower()] = key
    return m


TYPE_MAP = make_choice_map(ProductVariant.TYPE_CHOICES)
STYLE_MAP = make_choice_map(ProductVariant.STYLE_CHOICES)
AGE_MAP = make_choice_map(ProductVariant.AGE_CHOICES)
GENDER_MAP = make_choice_map(ProductVariant.GENDER_CHOICES)
# handle your “mens” / “women” CSV oddities:
GENDER_MAP.update(
    {
        "mens": "male",
        "women": "female",
        "male": "male",
        "female": "female",
        "m": "male",
        "f": "female",
    }
)


def norm(map_, raw_value):
    """
    Normalize a raw CSV value to the choice-key via the given map,
    or return None if blank/unknown.
    """
    if not raw_value:
        return None
    return map_.get(raw_value.strip().lower())


# ─── Main import routine ────────────────────────────────────────────────────────


def import_variants():
    with open(CSV_FILE_PATH, newline="", encoding="latin1") as csvfile:
        reader = csv.DictReader(csvfile)
        logger.info("CSV columns detected: %s", reader.fieldnames)

        for row in reader:
            product = Product.objects.filter(product_id=row.get("product_code")).first()
            if not product:
                logger.warning(
                    "\u2192 SKIP: no Product with code '%s'", row.get("product_code")
                )
                continue

            # Color hex mapping
            pc = map_color_to_hex(row.get("primary_color", ""))
            sc = map_color_to_hex(row.get("secondary_color") or row.get("color", ""))

            # Size comes through as the code already (e.g. 'M0', 'L', etc.)
            size_code = row.get("size", "").strip() or None

            # Normalize the human labels into your choice-keys:
            type_code = norm(TYPE_MAP, row.get("type"))
            style_code = norm(STYLE_MAP, row.get("style"))
            age_code = norm(AGE_MAP, row.get("age"))
            gender_code = norm(GENDER_MAP, row.get("gender"))

            # update product-level attributes
            prod_updated = False
            for attr, val in [
                ("type", type_code),
                ("style", style_code),
                ("age", age_code),
            ]:
                if getattr(product, attr) != val:
                    setattr(product, attr, val)
                    prod_updated = True
            if prod_updated:
                product.save()

            variant, created = ProductVariant.objects.get_or_create(
                variant_code=row.get("variant_code"),
                defaults={
                    "product": product,
                    "primary_color": pc,
                    "secondary_color": sc,
                    "size": size_code,
                    "gender": gender_code,
                },
            )

            if created:
                logger.info("CREATED %s (gender=%s)", variant.variant_code, gender_code)
            else:
                updated = []
                for attr, newval in [
                    ("primary_color", pc),
                    ("secondary_color", sc),
                    ("size", size_code),
                    ("gender", gender_code),
                ]:
                    if getattr(variant, attr) != newval:
                        setattr(variant, attr, newval)
                        updated.append(attr)

                if updated:
                    variant.save()
                    logger.info("UPDATED %s: %s", variant.variant_code, ", ".join(updated))
                else:
                    logger.info("SKIPPED %s: no changes", variant.variant_code)


# ─── Run if invoked as a script ────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import_variants()
    logger.info("Variant import completed!")
