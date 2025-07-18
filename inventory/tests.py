from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.test import TestCase, RequestFactory

from .models import (
    Product,
    ProductVariant,
    InventorySnapshot,
    Sale,
    Order,
    OrderItem,
    Group,
    RestockSetting,
)
from django.urls import reverse
from .utils import (
    get_low_stock_products,
    get_restock_alerts,
    calculate_variant_sales_speed,
    get_category_speed_stats,
)


class LowStockProductsTests(TestCase):
    def setUp(self):
        self.core_group = Group.objects.create(name="core")
        self.other_group = Group.objects.create(name="other")
        restock = RestockSetting.objects.create()
        restock.groups.add(self.core_group)

        self.product1 = Product.objects.create(product_id="P1", product_name="Prod1")
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

        self.product2 = Product.objects.create(product_id="P2", product_name="Prod2")
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
        self.product3 = Product.objects.create(product_id="P3", product_name="Prod3")
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
        self.product4 = Product.objects.create(product_id="P4", product_name="Prod4")
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

    def test_restock_alerts(self):
        alerts = get_restock_alerts()
        products = [a["product"] for a in alerts]
        self.assertIn(self.product1, products)
        self.assertIn(self.product3, products)
        self.assertNotIn(self.product2, products)
        self.assertNotIn(self.product4, products)
        self.assertNotIn(self.product5, products)

    def test_restock_alert_levels(self):
        product = Product.objects.create(product_id="P6", product_name="Prod6")
        product.groups.add(self.core_group)

        variants = []
        # Two variants completely out of stock
        for code in ["V6A", "V6B"]:
            v = ProductVariant.objects.create(
                product=product, variant_code=code, primary_color="#000000"
            )
            InventorySnapshot.objects.create(
                product_variant=v, date=date.today(), inventory_count=0
            )
            Sale.objects.create(
                order_number=code, date=date.today(), variant=v, sold_quantity=1, sold_value=10
            )
            variants.append(v)

        # One low-stock variant
        v_low = ProductVariant.objects.create(
            product=product, variant_code="V6C", primary_color="#000000"
        )
        InventorySnapshot.objects.create(
            product_variant=v_low, date=date.today(), inventory_count=1
        )
        Sale.objects.create(
            order_number="V6C", date=date.today(), variant=v_low, sold_quantity=1, sold_value=10
        )
        variants.append(v_low)

        # Two healthy variants
        for code in ["V6D", "V6E"]:
            v = ProductVariant.objects.create(
                product=product, variant_code=code, primary_color="#000000"
            )
            InventorySnapshot.objects.create(
                product_variant=v, date=date.today(), inventory_count=20
            )
            Sale.objects.create(
                order_number=code, date=date.today(), variant=v, sold_quantity=1, sold_value=10
            )
            variants.append(v)

        alerts = get_restock_alerts()
        alert_map = {a["product"]: a for a in alerts}

        self.assertEqual(alert_map[self.product1]["alert_type"], "normal")
        self.assertEqual(alert_map[product]["alert_type"], "urgent")


class LastOrderQtyTests(TestCase):
    def test_last_order_ignores_undelivered(self):
        product = Product.objects.create(product_id="P10", product_name="Prod10")
        variant = ProductVariant.objects.create(
            product=product, variant_code="V10", primary_color="#000000"
        )

        delivered_order = Order.objects.create(
            order_date=date.today() - relativedelta(months=2)
        )
        OrderItem.objects.create(
            product_variant=variant,
            order=delivered_order,
            quantity=5,
            item_cost_price=1.0,
            date_expected=date.today() - relativedelta(months=2, days=-10),
            date_arrived=delivered_order.order_date,
        )

        open_order = Order.objects.create(
            order_date=date.today() - relativedelta(months=1)
        )
        OrderItem.objects.create(
            product_variant=variant,
            order=open_order,
            quantity=9,
            item_cost_price=1.0,
            date_expected=date.today(),
        )

        url = reverse("product_detail", args=[product.id])
        response = self.client.get(url)
        rows = response.context["safe_stock_data"]
        self.assertEqual(rows[0]["last_order_qty"], 5)
        self.assertEqual(rows[0]["last_order_date"], delivered_order.order_date)


class VariantSalesSpeedTests(TestCase):
    def test_fallback_window_extends_to_year(self):
        today = date.today()
        product = Product.objects.create(product_id="P20", product_name="Prod20")
        variant = ProductVariant.objects.create(
            product=product, variant_code="V20", primary_color="#000000"
        )

        sale_date = today - timedelta(weeks=30)
        InventorySnapshot.objects.create(
            product_variant=variant,
            date=sale_date - timedelta(days=1),
            inventory_count=2,
        )
        Sale.objects.create(
            order_number="O20",
            date=sale_date,
            variant=variant,
            sold_quantity=2,
            sold_value=20,
        )

        InventorySnapshot.objects.create(
            product_variant=variant, date=today, inventory_count=0
        )

        no_fallback = calculate_variant_sales_speed(
            variant, today=today, fallback_weeks=26
        )
        with_fallback = calculate_variant_sales_speed(variant, today=today)

        self.assertEqual(no_fallback, 0.0)
        self.assertGreater(with_fallback, 0.0)


class CategorySpeedStatsTests(TestCase):
    def test_category_and_size_average_speed(self):
        today = date.today()
        product1 = Product.objects.create(product_id="P30", product_name="Prod30", type="rg")
        product2 = Product.objects.create(product_id="P31", product_name="Prod31", type="rg")

        v1 = ProductVariant.objects.create(product=product1, variant_code="V30S", primary_color="#000000", size="S")
        v2 = ProductVariant.objects.create(product=product2, variant_code="V31S", primary_color="#000000", size="S")

        InventorySnapshot.objects.create(product_variant=v1, date=today - timedelta(weeks=4), inventory_count=10)
        InventorySnapshot.objects.create(product_variant=v1, date=today, inventory_count=6)
        InventorySnapshot.objects.create(product_variant=v2, date=today - timedelta(weeks=4), inventory_count=10)
        InventorySnapshot.objects.create(product_variant=v2, date=today, inventory_count=8)

        for i in range(4):
            Sale.objects.create(order_number=f"O1{i}", date=today - timedelta(weeks=i), variant=v1, sold_quantity=1, sold_value=10)
        for i in range(2):
            Sale.objects.create(order_number=f"O2{i}", date=today - timedelta(weeks=i), variant=v2, sold_quantity=1, sold_value=10)

        stats = get_category_speed_stats("rg", weeks=4, today=today)

        self.assertIn("overall_avg", stats)
        self.assertIn("size_avgs", stats)
        self.assertIn("S", stats["size_avgs"])
        self.assertGreater(stats["overall_avg"], 0)
        self.assertGreater(stats["size_avgs"]["S"], 0)


class ProductAdminFormTests(TestCase):
    def test_admin_creates_variants_on_save(self):
        from inventory.admin import ProductAdminForm, ProductAdmin
        from django.contrib.admin.sites import AdminSite


        form_data = {
            "product_id": "PG123",
            "product_name": "Prod",
            "type": "rg",
            "restock_time": 0,
            "variant_sizes": ["XS", "M"],
        }
        form = ProductAdminForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

        # Simulate admin workflow
        product = form.save(commit=False)
        admin = ProductAdmin(Product, admin_site=AdminSite())
        admin.save_model(request=None, obj=product, form=form, change=False)


        variants = product.variants.all()
        self.assertEqual(variants.count(), 2)
        codes = set(variants.values_list("variant_code", flat=True))
        self.assertEqual(codes, {"PG123-XS", "PG123-M"})
        genders = set(variants.values_list("gender", flat=True))
        self.assertEqual(genders, {"male"})

    def test_product_admin_includes_variant_inline(self):
        from inventory.admin import ProductAdmin, ProductVariantInline
        from django.contrib.admin.sites import AdminSite

        admin = ProductAdmin(Product, admin_site=AdminSite())
        self.assertIn(ProductVariantInline, admin.inlines)


class ProductVariantOrderingTests(TestCase):
    def test_admin_orders_variants_by_size(self):
        from inventory.admin import ProductVariantAdmin
        from django.contrib.admin.sites import AdminSite

        product = Product.objects.create(product_id="PV1", product_name="Prod1")
        sizes = ["M", "S", "L"]
        for s in sizes:
            ProductVariant.objects.create(
                product=product,
                variant_code=f"V{s}",
                size=s,
                primary_color="#000000",
            )

        admin = ProductVariantAdmin(ProductVariant, admin_site=AdminSite())
        request = RequestFactory().get("/")
        ordered = list(admin.get_queryset(request).values_list("size", flat=True))
        expected_order = [code for code, _ in ProductVariant.SIZE_CHOICES if code in sizes]
        self.assertEqual(ordered, expected_order)

    def test_add_products_form_orders_variants_by_size(self):
        from inventory.admin import AddProductsForm

        product = Product.objects.create(product_id="PF1", product_name="Prod2")
        ProductVariant.objects.create(
            product=product,
            variant_code="PFS",
            size="S",
            primary_color="#000000",
        )
        ProductVariant.objects.create(
            product=product,
            variant_code="PFM",
            size="M",
            primary_color="#000000",
        )

        form = AddProductsForm()
        ordered = list(form.fields["product_variants"].queryset.values_list("size", flat=True))
        expected_order = [code for code, _ in ProductVariant.SIZE_CHOICES if code in ["S", "M"]]
        self.assertEqual(ordered, expected_order)


class OrderItemInlineTests(TestCase):
    def test_inline_queryset_orders_by_product_and_size(self):
        from inventory.admin import OrderItemInline
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from django.contrib.auth.models import User

        prod_a = Product.objects.create(product_id="PA", product_name="Aprod")
        prod_b = Product.objects.create(product_id="PB", product_name="Bprod")

        var_a_s = ProductVariant.objects.create(
            product=prod_a,
            variant_code="AS",
            size="S",
            primary_color="#000000",
        )
        var_a_m = ProductVariant.objects.create(
            product=prod_a,
            variant_code="AM",
            size="M",
            primary_color="#000000",
        )
        var_b_s = ProductVariant.objects.create(
            product=prod_b,
            variant_code="BS",
            size="S",
            primary_color="#000000",
        )

        order = Order.objects.create(invoice_id="INV1", order_date=date.today())
        OrderItem.objects.create(
            order=order,
            product_variant=var_a_m,
            quantity=1,
            item_cost_price=0,
            date_expected=date.today(),
        )
        OrderItem.objects.create(
            order=order,
            product_variant=var_a_s,
            quantity=1,
            item_cost_price=0,
            date_expected=date.today(),
        )
        OrderItem.objects.create(
            order=order,
            product_variant=var_b_s,
            quantity=1,
            item_cost_price=0,
            date_expected=date.today(),
        )

        inline = OrderItemInline(OrderItem, admin_site=AdminSite())
        request = RequestFactory().get("/")
        request.user = User.objects.create_superuser("admin", "a@example.com", "p")
        items = list(inline.get_queryset(request))
        sizes = [item.product_variant.size for item in items]
        products = [item.product_variant.product.product_name for item in items]

        self.assertEqual(products, ["Aprod", "Aprod", "Bprod"])
        self.assertEqual(sizes, ["S", "M", "S"])
