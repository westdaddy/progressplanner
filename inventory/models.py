from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from django.db import models
from django.core.exceptions import ValidationError

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
    no_restock = models.BooleanField(
        default=False,
        help_text="Exclude this product from reorder recommendations.",
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
    CATEGORY_OTHER = "other"
    CATEGORY_GYM_CODE = "gym_code"
    CATEGORY_WHOLESALE = "wholesale"
    CATEGORY_CHOICES = [
        (CATEGORY_OTHER, "Other"),
        (CATEGORY_GYM_CODE, "Gym code"),
        (CATEGORY_WHOLESALE, "Wholesale"),
    ]

    name = models.CharField(max_length=255, unique=True)
    category = models.CharField(
        max_length=32,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_OTHER,
        db_index=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Discount(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=255, unique=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DiscountChipSetting(models.Model):
    """Singleton-ish settings for discount chip color mapping."""

    palette = models.JSONField(default=list, blank=True)
    discount_color_map = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Discount Chip Setting"
        verbose_name_plural = "Settings"

    def save(self, *args, **kwargs):
        if not self.palette:
            self.palette = [
                "#1E88E5",
                "#43A047",
                "#FB8C00",
                "#8E24AA",
                "#E53935",
                "#00897B",
                "#5E35B1",
                "#3949AB",
                "#6D4C41",
                "#039BE5",
                "#7CB342",
                "#F4511E",
                "#546E7A",
                "#C2185B",
                "#FDD835",
            ]
        super().save(*args, **kwargs)

    def __str__(self):
        return "Discount chip colors"


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
    list_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    seller_note = models.TextField(blank=True, null=True)
    coupon_name_raw = models.CharField(max_length=255, blank=True, null=True)
    discounts = models.ManyToManyField(
        Discount,
        blank=True,
        related_name="sales",
    )
    product_short_name = models.CharField(max_length=255, blank=True, null=True)
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
    manual_discount_locked = models.BooleanField(
        default=False,
        help_text="Keep existing sale pricing when assigning/changing referrer discount rules.",
    )

    REFERRER_DISCOUNT_RULES = {
        Referrer.CATEGORY_GYM_CODE: {
            "default_percent": Decimal("10"),
            "minimum_percent": Decimal("10"),
            "enforce_exact_default": True,
        },
        Referrer.CATEGORY_WHOLESALE: {
            "default_percent": Decimal("25"),
            "minimum_percent": Decimal("25"),
            "enforce_exact_default": False,
        },
    }

    def __str__(self):
        return (
            f"Sale {self.sale_id} - Variant {self.variant.variant_code} on {self.date}"
        )

    def calculate_discount_percentage(self) -> Optional[Decimal]:
        sold_quantity = self.sold_quantity or 0
        if sold_quantity <= 0:
            return None

        retail_price = self.variant.product.retail_price or Decimal("0")
        if retail_price <= 0:
            return None

        actual_total = self.sold_value or Decimal("0")
        actual_unit_price = actual_total / sold_quantity
        discount_percentage = ((retail_price - actual_unit_price) / retail_price) * Decimal("100")
        return discount_percentage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def get_referrer_discount_rule(self, referrer: Optional["Referrer"] = None) -> Optional[dict]:
        active_referrer = referrer if referrer is not None else self.referrer
        if not active_referrer:
            return None
        return self.REFERRER_DISCOUNT_RULES.get(active_referrer.category)

    def apply_referrer_discount_policy(
        self,
        *,
        referrer: Optional["Referrer"] = None,
        clear_referrer: bool = False,
        manual_discount_locked: Optional[bool] = None,
        save: bool = True,
    ) -> bool:
        if manual_discount_locked is not None:
            self.manual_discount_locked = bool(manual_discount_locked)
        if clear_referrer:
            self.referrer = None
        elif referrer is not None:
            self.referrer = referrer

        if self.manual_discount_locked:
            if save:
                self.full_clean()
                self.save(update_fields=["referrer", "manual_discount_locked"])
            return False

        rule = self.get_referrer_discount_rule()
        if not rule:
            if save:
                self.full_clean()
                self.save(update_fields=["referrer", "manual_discount_locked"])
            return False

        sold_quantity = self.sold_quantity or 0
        retail_price = self.variant.product.retail_price or Decimal("0")
        if sold_quantity <= 0 or retail_price <= 0:
            if save:
                self.full_clean()
                self.save(update_fields=["referrer", "manual_discount_locked"])
            return False

        current_discount = self.calculate_discount_percentage() or Decimal("0")
        default_percent = rule["default_percent"]
        minimum_percent = rule["minimum_percent"]
        if rule.get("enforce_exact_default"):
            target_discount = default_percent
        else:
            target_discount = max(current_discount, default_percent, minimum_percent)

        multiplier = (Decimal("100") - target_discount) / Decimal("100")
        target_total = (retail_price * sold_quantity * multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        updated = (self.sold_value != target_total) or (referrer is not None)
        self.sold_value = target_total
        if save:
            self.full_clean()
            self.save(update_fields=["referrer", "sold_value", "manual_discount_locked"])
        return updated

    def clean(self):
        super().clean()
        if not self.referrer or self.manual_discount_locked:
            return

        rule = self.get_referrer_discount_rule()
        if not rule:
            return

        discount_percentage = self.calculate_discount_percentage()
        if discount_percentage is None:
            return

        minimum = rule["minimum_percent"]
        if discount_percentage < minimum:
            raise ValidationError(
                {"sold_value": f"{self.referrer.get_category_display()} referrer requires at least {minimum}% discount."}
            )

        if rule.get("enforce_exact_default"):
            default_percent = rule["default_percent"]
            if discount_percentage != default_percent:
                raise ValidationError(
                    {"sold_value": f"{self.referrer.get_category_display()} referrer requires exactly {default_percent}% discount unless manually locked."}
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
        on_delete=models.SET_NULL,
        related_name="order_items",
        verbose_name="Related Order",
        blank=True,
        null=True,
    )

    def __str__(self):
        if self.order_id:
            return f"{self.quantity} x {self.product_variant} (Order {self.order.id})"
        return f"{self.quantity} x {self.product_variant} (Unassigned)"

class RestockSetting(models.Model):
    """Configuration of groups considered for restock checks."""
    groups = models.ManyToManyField(Group, blank=True, related_name="restock_settings")

    def __str__(self):
        return "Restock Setting"
