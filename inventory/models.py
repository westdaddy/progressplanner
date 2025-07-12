from django.db import models
from datetime import date


class Product(models.Model):
    product_id = models.CharField(max_length=50, unique=True)  # Text/number code
    product_name = models.CharField(max_length=200)  # Product name
    product_photo = models.ImageField(upload_to='product_photos/', blank=True, null=True)  # Optional product photo
    retail_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Recommended retail price."
    )
    decommissioned = models.BooleanField(
        default=False,
        help_text="Select if this product is old and retired."
    )
    discounted = models.BooleanField(
        default=False,
        help_text="Check if this product is currently discounted."
    )

    def __str__(self):
        return f"({self.product_id}) {self.product_name}"

    class Meta:
        # Example: primary sort by name ascending,
        # then by creation date descending
        ordering = ['product_id']




class ProductVariant(models.Model):
    SIZE_CHOICES = [
        ('XXS', 'Extra-Extra-Small'),
        ('XS', 'Extra-Small'),
        ('S', 'Small'),
        ('M', 'Medium'),
        ('L', 'Large'),
        ('XL', 'Extra Large'),
        ('XXL', 'Extra-Extra Large'),
        ('A0', 'A0'),
        ('A1', 'A1'),
        ('A1L', 'A1L'),
        ('A2', 'A2'),
        ('A2L', 'A2L'),
        ('A3', 'A3'),
        ('A3L', 'A3L'),
        ('A4', 'A4'),
        ('F0', 'F0'),
        ('F1', 'F1'),
        ('F2', 'F2'),
        ('F3', 'F3'),
        ('F4', 'F4'),
        ('M000', 'M000'),
        ('M00', 'M00'),
        ('M0', 'M0'),
        ('M1', 'M1'),
        ('M2', 'M2'),
        ('M3', 'M3'),
        ('M4', 'M4'),
    ]

    TYPE_CHOICES = [
        ('gi', 'Gi'),
        ('rg', 'Rashguard'),
        ('dk', 'Shorts'),
        ('ck', 'Spats'),
        ('bt', 'Belt'),
        ('te', 'Tee'),
        ('cn', 'Crewneck'),
        ('ho', 'Hoodie'),
        ('bo', 'Bottle'),
        ('tr', 'Trousers'),
        ('ft', 'Finger Tape'),
        ('br', 'Bra'),
        ('bg', 'Bag'),
        ('jk', 'Jacket'),
    ]

    STYLE_CHOICES = [
        ('ap', 'Apparel'),
        ('ac', 'Accessories'),
        ('gi', 'Gi'),
        ('ng', 'Nogi'),
    ]

    AGE_CHOICES = [
        ('adult', 'Adult'),
        ('kids', 'Kids'),
    ]

    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
    ]

    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='variants')
    variant_code = models.CharField(max_length=50, unique=True)  # Text/number code
    primary_color = models.CharField(max_length=7)  # Hex code (e.g., #FFFFFF)
    secondary_color = models.CharField(max_length=7, blank=True, null=True)  # Optional hex code
    size = models.CharField(max_length=4, choices=SIZE_CHOICES, blank=True, null=True)  # Optional size
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, blank=True, null=True)  # Optional type
    style = models.CharField(max_length=20, choices=STYLE_CHOICES, blank=True, null=True)  # Optional style
    age = models.CharField(max_length=10, choices=AGE_CHOICES, blank=True, null=True)  # Optional age
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)  # Optional gender

    def __str__(self):
        return f"{self.product.product_name} - {self.variant_code}"

    class Meta:
        ordering = ['-variant_code']


class Sale(models.Model):
    sale_id = models.AutoField(primary_key=True)
    order_number  = models.CharField(max_length=50, db_index=True) # the 内部订单号
    date = models.DateField()
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='sales')
    sold_quantity = models.IntegerField()
    return_quantity = models.IntegerField(blank=True, null=True)
    sold_value = models.DecimalField(max_digits=10, decimal_places=2)
    return_value = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

    def __str__(self):
        return f"Sale {self.sale_id} - Variant {self.variant.variant_code} on {self.date}"


class InventorySnapshot(models.Model):
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='snapshots')
    date = models.DateField()
    inventory_count = models.IntegerField()

    def __str__(self):
        return f"Snapshot for {self.product_variant.variant_code} on {self.date}"



class Order(models.Model):
    order_date = models.DateField(default=date.today, verbose_name="Order Date")
    invoice_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Invoice ID")
    invoice = models.FileField(upload_to='invoices/', blank=True, null=True, verbose_name="Invoice File")

    def __str__(self):
        return f"{self.invoice_id} - {self.order_date}"

    class Meta:
        # Example: primary sort by name ascending,
        # then by creation date descending
        ordering = ['-order_date']


class OrderItem(models.Model):
    product_variant = models.ForeignKey('inventory.ProductVariant', on_delete=models.CASCADE, related_name='order_items', verbose_name="Product Variant")
    quantity = models.PositiveIntegerField(verbose_name="Quantity Ordered")
    item_cost_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Cost Price (CNY)")
    date_expected = models.DateField(verbose_name="Expected Arrival Date")
    date_arrived = models.DateField(blank=True, null=True, verbose_name="Actual Arrival Date")
    actual_quantity = models.PositiveIntegerField(blank=True, null=True, verbose_name="Actual Quantity Arrived")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='order_items', verbose_name="Related Order")

    def __str__(self):
        return f"{self.quantity} x {self.product_variant} (Order {self.order.id})"
