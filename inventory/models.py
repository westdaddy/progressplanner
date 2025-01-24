from django.db import models

class Product(models.Model):
    product_id = models.CharField(max_length=50, unique=True)  # Text/number code
    product_name = models.CharField(max_length=200)  # Product name
    product_photo = models.ImageField(upload_to='product_photos/')  # Image field for product photo

    def __str__(self):
        return self.product_name




class ProductVariant(models.Model):
    SIZE_CHOICES = [
        ('XS', 'Extra-Extra-Small'),
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


class Sale(models.Model):
    sale_id = models.AutoField(primary_key=True)
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
