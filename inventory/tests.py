from datetime import date
from django.test import TestCase

from .models import Product, ProductVariant, InventorySnapshot, Sale
from .utils import get_low_stock_products


class LowStockProductsTests(TestCase):
    def setUp(self):
        self.product1 = Product.objects.create(
            product_id="P1", product_name="Prod1"
        )
        self.variant1 = ProductVariant.objects.create(
            product=self.product1,
            variant_code="V1",
            primary_color="#000000",
        )
        InventorySnapshot.objects.create(
            product_variant=self.variant1,
            date=date.today(),
            inventory_count=5,
        )
        for m in range(6):
            Sale.objects.create(
                order_number=f"O{m}",
                date=date.today(),
                variant=self.variant1,
                sold_quantity=2,
                sold_value=100,
            )

        self.product2 = Product.objects.create(
            product_id="P2", product_name="Prod2"
        )
        self.variant2 = ProductVariant.objects.create(
            product=self.product2,
            variant_code="V2",
            primary_color="#000000",
        )
        InventorySnapshot.objects.create(
            product_variant=self.variant2,
            date=date.today(),
            inventory_count=50,
        )
        for m in range(6):
            Sale.objects.create(
                order_number=f"O2-{m}",
                date=date.today(),
                variant=self.variant2,
                sold_quantity=1,
                sold_value=50,
            )

    def test_low_stock_variants(self):
        qs = ProductVariant.objects.all()
        low = list(get_low_stock_products(qs))
        self.assertIn(self.variant1, low)
        self.assertNotIn(self.variant2, low)

    def test_low_stock_products(self):
        qs = Product.objects.all()
        low = list(get_low_stock_products(qs))
        self.assertIn(self.product1, low)
        self.assertNotIn(self.product2, low)
