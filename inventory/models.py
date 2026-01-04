from datetime import date
from typing import Iterable, Optional

from django.db import models

# ---------------------------------------------------------------------------
# Choice constants shared by Product and ProductVariant
# ---------------------------------------------------------------------------

PRODUCT_STYLE_CHOICES = [
    ("gi", "Gi"),
    ("ng", "Nogi"),
    ("ap", "Apparel"),
    ("ac", "Accessories"),
]

PRODUCT_TYPE_CHOICES_BY_STYLE = {
    "gi": [
        ("gi", "Gi (full set)"),
        ("tr", "Trousers"),
        ("jk", "Jacket"),
        ("bt", "Belt"),
    ],
    "ng": [
        ("rg", "Rashguard"),
        ("dk", "Shorts"),
        ("ck", "Spats"),
    ],
    "ap": [
        ("te", "Tee"),
        ("ho", "Hoodie"),
        ("jg", "Joggers"),
        ("cn", "Crewneck"),
        ("br", "Bra"),
        ("jk", "Jacket"),
        ("bg", "Bag"),
    ],
    "ac": [
        ("bg", "Bag"),
        ("ft", "Finger Tape"),
        ("bo", "Bottle"),
    ],
}

PRODUCT_SUBTYPE_CHOICES_BY_TYPE = {
    "tr": [
        ("tw", "Twill"),
        ("rs", "Ripstop"),
    ],
    "rg": [
        ("ss", "Short Sleeve"),
        ("ls", "Long Sleeve"),
        ("rt", "Rolling Tee"),
    ],
    "dk": [
        ("bs", "Board Shorts"),
        ("dl", "Double Layer"),
        ("vt", "Vale Tudo"),
    ],
}


def _flatten_type_choices():
    seen = set()
    choices = []
    for style_code, _label in PRODUCT_STYLE_CHOICES:
        for code, label in PRODUCT_TYPE_CHOICES_BY_STYLE.get(style_code, []):
            if code in seen:
                continue
            seen.add(code)
            choices.append((code, label))
    return choices


def _build_type_to_styles_map():
    mapping: dict[str, set[str]] = {}
    for style_code, type_choices in PRODUCT_TYPE_CHOICES_BY_STYLE.items():
        for type_code, _label in type_choices:
            mapping.setdefault(type_code, set()).add(style_code)
    return mapping


PRODUCT_TYPE_CHOICES = _flatten_type_choices()
PRODUCT_TYPE_TO_STYLES = _build_type_to_styles_map()


def _flatten_subtype_choices():
    seen = set()
    choices = []
    for type_code, subtype_choices in PRODUCT_SUBTYPE_CHOICES_BY_TYPE.items():
        for code, label in subtype_choices:
            if code in seen:
                continue
            seen.add(code)
            choices.append((code, label))
    return choices


def _build_subtype_to_types_map():
    mapping: dict[str, set[str]] = {}
    for type_code, subtype_choices in PRODUCT_SUBTYPE_CHOICES_BY_TYPE.items():
        for subtype_code, _label in subtype_choices:
            mapping.setdefault(subtype_code, set()).add(type_code)
    return mapping


PRODUCT_SUBTYPE_CHOICES = _flatten_subtype_choices()
PRODUCT_SUBTYPE_TO_TYPES = _build_subtype_to_types_map()


def get_type_choices_for_styles(styles: Optional[Iterable[str]]):
    """Return type choices limited to the provided style codes."""

    if not styles:
        return PRODUCT_TYPE_CHOICES

    selected = []
    seen = set()
    for style_code in styles:
        for code, label in PRODUCT_TYPE_CHOICES_BY_STYLE.get(style_code, []):
            if code in seen:
                continue
            seen.add(code)
            selected.append((code, label))
    return selected


def get_subtype_choices_for_types(types: Optional[Iterable[str]]):
    """Return subtype choices limited to the provided type codes."""

    if not types:
        return PRODUCT_SUBTYPE_CHOICES

    selected = []
    seen = set()
    for type_code in types:
        for code, label in PRODUCT_SUBTYPE_CHOICES_BY_TYPE.get(type_code, []):
            if code in seen:
                continue
            seen.add(code)
            selected.append((code, label))
    return selected

PRODUCT_AGE_CHOICES = [
    ("adult", "Adult"),
    ("kids", "Kids"),
]

PRODUCT_GENDER_CHOICES = [
    ("male", "Male"),
    ("female", "Female"),
]


class Group(models.Model):
    """Top level product grouping."""

    name = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:
        return self.name


class Series(models.Model):
    """Collection of related products within a group."""

    name = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    product_id = models.CharField(max_length=50, unique=True)  # Text/number code
    product_name = models.CharField(max_length=200)  # Product name
    product_photo = models.ImageField(
        upload_to="product_photos/", blank=True, null=True
    )  # Optional product photo
    retail_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Recommended retail price.",
    )
    decommissioned = models.BooleanField(
        default=False, help_text="Select if this product is old and retired."
    )
    discounted = models.BooleanField(
        default=False, help_text="Check if this product is currently discounted."
    )
    restock_time = models.PositiveIntegerField(
        default=0,
        help_text="Number of months required to restock this product.",
    )
    type = models.CharField(
        max_length=20,
        choices=PRODUCT_TYPE_CHOICES,
        blank=True,
        null=True,
    )
    subtype = models.CharField(
        max_length=20,
        choices=PRODUCT_SUBTYPE_CHOICES,
        blank=True,
        null=True,
        help_text="More detailed subcategory (e.g. Short Sleeve Rashguard)",
    )
    style = models.CharField(
        max_length=20,
        choices=PRODUCT_STYLE_CHOICES,
        blank=True,
        null=True,
    )
    age = models.CharField(
        max_length=10,
        choices=PRODUCT_AGE_CHOICES,
        blank=True,
        null=True,
    )
    groups = models.ManyToManyField(
        Group,
        related_name="products",
        blank=True,
    )
    series = models.ManyToManyField(
        Series,
        related_name="products",
        blank=True,
    )

    def __str__(self):
        return f"({self.product_id}) {self.product_name}"

    class Meta:
        # Example: primary sort by name ascending,
        # then by creation date descending
        ordering = ["product_id"]


class ProductVariant(models.Model):
    SIZE_CHOICES = [
        ("XXS", "Extra-Extra-Small"),
        ("XS", "Extra-Small"),
        ("S", "Small"),
        ("M", "Medium"),
        ("L", "Large"),
        ("XL", "Extra Large"),
        ("XXL", "Extra-Extra Large"),
        ("A0", "A0"),
        ("A1", "A1"),
        ("A1L", "A1L"),
        ("A2", "A2"),
        ("A2L", "A2L"),
        ("A3", "A3"),
        ("A3L", "A3L"),
        ("A4", "A4"),
        ("F0", "F0"),
        ("F1", "F1"),
        ("F2", "F2"),
        ("F3", "F3"),
        ("F4", "F4"),
        ("M000", "M000"),
        ("M00", "M00"),
        ("M0", "M0"),
        ("M1", "M1"),
        ("M2", "M2"),
        ("M3", "M3"),
        ("M4", "M4"),
    ]

    TYPE_CHOICES = PRODUCT_TYPE_CHOICES
    STYLE_CHOICES = PRODUCT_STYLE_CHOICES
    AGE_CHOICES = PRODUCT_AGE_CHOICES
    GENDER_CHOICES = PRODUCT_GENDER_CHOICES

    product = models.ForeignKey(
        "Product", on_delete=models.CASCADE, related_name="variants"
    )
    variant_code = models.CharField(max_length=50, unique=True)  # Text/number code
    primary_color = models.CharField(max_length=7)  # Hex code (e.g., #FFFFFF)
    secondary_color = models.CharField(
        max_length=7, blank=True, null=True
    )  # Optional hex code
    size = models.CharField(
        max_length=4, choices=SIZE_CHOICES, blank=True, null=True
    )  # Optional size
    gender = models.CharField(
        max_length=10, choices=GENDER_CHOICES, blank=True, null=True
    )  # Optional gender

    def __str__(self):
        return f"{self.product.product_name} - {self.variant_code}"

    class Meta:
        ordering = ["-variant_code"]


class Referrer(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Sale(models.Model):
    sale_id = models.AutoField(primary_key=True)
    order_number = models.CharField(max_length=50, db_index=True)  # the 内部订单号
    date = models.DateField(db_index=True)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="sales"
    )
    sold_quantity = models.IntegerField()
    return_quantity = models.IntegerField(blank=True, null=True)
    sold_value = models.DecimalField(max_digits=10, decimal_places=2)
    return_value = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    referrer = models.ForeignKey(
        Referrer,
        on_delete=models.SET_NULL,
        related_name="sales",
        blank=True,
        null=True,
    )

    def __str__(self):
        return (
            f"Sale {self.sale_id} - Variant {self.variant.variant_code} on {self.date}"
        )


class InventorySnapshot(models.Model):
    product_variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="snapshots"
    )
    date = models.DateField(db_index=True)
    inventory_count = models.IntegerField()

    def __str__(self):
        return f"Snapshot for {self.product_variant.variant_code} on {self.date}"


class Order(models.Model):
    order_date = models.DateField(default=date.today, verbose_name="Order Date")
    invoice_id = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Invoice ID"
    )
    invoice = models.FileField(
        upload_to="invoices/", blank=True, null=True, verbose_name="Invoice File"
    )

    def __str__(self):
        return f"{self.invoice_id} - {self.order_date}"

    class Meta:
        # Example: primary sort by name ascending,
        # then by creation date descending
        ordering = ["-order_date"]


class OrderItem(models.Model):
    product_variant = models.ForeignKey(
        "inventory.ProductVariant",
        on_delete=models.CASCADE,
        related_name="order_items",
        verbose_name="Product Variant",
    )
    quantity = models.PositiveIntegerField(verbose_name="Quantity Ordered")
    item_cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Cost Price (CNY)"
    )
    date_expected = models.DateField(verbose_name="Expected Arrival Date", db_index=True)
    date_arrived = models.DateField(
        blank=True, null=True, verbose_name="Actual Arrival Date", db_index=True
    )
    actual_quantity = models.PositiveIntegerField(
        blank=True, null=True, verbose_name="Actual Quantity Arrived"
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="order_items",
        verbose_name="Related Order",
    )

    def __str__(self):
        return f"{self.quantity} x {self.product_variant} (Order {self.order.id})"

class RestockSetting(models.Model):
    """Configuration of groups considered for restock checks."""
    groups = models.ManyToManyField(Group, blank=True, related_name="restock_settings")

    def __str__(self):
        return "Restock Setting"
