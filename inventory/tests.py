from datetime import date
from dateutil.relativedelta import relativedelta
from django.test import TestCase

from .models import (
    Product,
    ProductVariant,
    InventorySnapshot,
    Sale,
    Group,
    RestockSetting,
)
from .utils import get_low_stock_products


class LowStockProductsTests(TestCase):
    def setUp(self):
        self.core_group = Group.objects.create(name="core")
        self.other_group = Group.objects.create(name="other")
        restock = RestockSetting.objects.create()
        restock.groups.add(self.core_group)
        
        self.product1 = Product.objects.create(
            product_id="P1", product_name="Prod1"
        )
        self.product1.groups.add(self.core_group)
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
        self.product2.groups.add(self.core_group)
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

        # Variant that sold out quickly then restocked recently
        self.product3 = Product.objects.create(
            product_id="P3", product_name="Prod3"
        )
        self.product3.groups.add(self.core_group)

        self.variant3 = ProductVariant.objects.create(
            product=self.product3,
            variant_code="V3",
            primary_color="#000000",
        )
        six_months_ago = date.today().replace(day=1) - relativedelta(months=6)
        InventorySnapshot.objects.create(
            product_variant=self.variant3,
            date=six_months_ago,
            inventory_count=10,
        )
        # sold everything five months ago
        Sale.objects.create(
            order_number="O3", 
            date=six_months_ago + relativedelta(months=1),
            variant=self.variant3,
            sold_quantity=10,
            sold_value=200,
        )
        # restocked at current month with 5 on hand
        InventorySnapshot.objects.create(
            product_variant=self.variant3,
            date=date.today(),
            inventory_count=5,
        )

        # Low stock product not in core group
        self.product4 = Product.objects.create(
            product_id="P4", product_name="Prod4"
        )
        self.product4.groups.add(self.other_group)
        self.variant4 = ProductVariant.objects.create(
            product=self.product4,
            variant_code="V4",
            primary_color="#000000",
        )
        InventorySnapshot.objects.create(
            product_variant=self.variant4,
            date=date.today(),
            inventory_count=2,
        )
        Sale.objects.create(
            order_number="O4",
            date=date.today(),
            variant=self.variant4,
            sold_quantity=5,
            sold_value=60,
        )

        # Decommissioned product should be ignored even if low stock
        self.product5 = Product.objects.create(
            product_id="P5", product_name="Prod5", decommissioned=True
        )
        self.product5.groups.add(self.core_group)
        self.variant5 = ProductVariant.objects.create(
            product=self.product5,
            variant_code="V5",
            primary_color="#000000",
        )
        InventorySnapshot.objects.create(
            product_variant=self.variant5,
            date=date.today(),
            inventory_count=1,
        )
        Sale.objects.create(
            order_number="O5",
            date=date.today(),
            variant=self.variant5,
            sold_quantity=3,
            sold_value=30,
        )

    def test_low_stock_variants(self):
        qs = ProductVariant.objects.all()
        low = list(get_low_stock_products(qs))

        self.assertIn(self.variant1, low)
        self.assertIn(self.variant3, low)
        self.assertNotIn(self.variant2, low)
        self.assertNotIn(self.variant4, low)
        self.assertNotIn(self.variant5, low)

    def test_low_stock_products(self):
        qs = Product.objects.all()
        low = list(get_low_stock_products(qs))
        self.assertIn(self.product1, low)
        self.assertIn(self.product3, low)
        self.assertNotIn(self.product2, low)
        self.assertNotIn(self.product4, low)
        self.assertNotIn(self.product5, low)
