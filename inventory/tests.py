from datetime import date, timedelta, datetime
from decimal import Decimal

from unittest.mock import patch
from dateutil.relativedelta import relativedelta
from django.test import TestCase, RequestFactory
from django.utils import timezone

from .models import (
    Product,
    ProductVariant,
    InventorySnapshot,
    Sale,
    Order,
    OrderItem,
    Group,
    RestockSetting,
    Referrer,
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


class SalesDataInventoryTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="P100", product_name="Prod100", retail_price=10
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, variant_code="V100", primary_color="#000000"
        )

    def test_snapshot_warning_when_far_from_month_end(self):
        InventorySnapshot.objects.create(
            product_variant=self.variant,
            date=date(2024, 3, 25),
            inventory_count=10,
        )
        url = reverse("sales_data")
        res = self.client.get(url, {"year": 2024, "month": 3})
        data = res.json()
        self.assertEqual(data["inventory_count"], 10)
        self.assertTrue(data["snapshot_warning"])
        self.assertEqual(data["snapshot_date"], "2024-03-25")

    def test_on_order_calculation(self):
        # snapshot near month end to avoid warning
        InventorySnapshot.objects.create(
            product_variant=self.variant,
            date=date(2024, 4, 1),
            inventory_count=8,
        )
        order1 = Order.objects.create(order_date=date(2024, 3, 10))
        OrderItem.objects.create(
            order=order1,
            product_variant=self.variant,
            quantity=5,
            item_cost_price=1,
            date_expected=date(2024, 3, 20),
            date_arrived=date(2024, 4, 5),
        )
        order2 = Order.objects.create(order_date=date(2024, 3, 5))
        OrderItem.objects.create(
            order=order2,
            product_variant=self.variant,
            quantity=3,
            item_cost_price=1,
            date_expected=date(2024, 3, 15),
            date_arrived=date(2024, 3, 20),
        )
        url = reverse("sales_data")
        res = self.client.get(url, {"year": 2024, "month": 3})
        data = res.json()
        self.assertEqual(data["on_order_count"], 5)
        self.assertFalse(data["snapshot_warning"])
        self.assertEqual(data["snapshot_date"], "2024-04-01")


class SalesViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="SP1", product_name="Sales Product", retail_price=10
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            variant_code="SP1-V1",
            primary_color="#000000",
        )

    def test_default_last_month_range_and_metrics(self):
        # Sales in April 2024
        Sale.objects.create(
            order_number="A100",
            date=date(2024, 4, 5),
            variant=self.variant,
            sold_quantity=3,
            return_quantity=1,
            sold_value=100,
            return_value=30,
        )
        Sale.objects.create(
            order_number="A100",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=2,
            sold_value=70,
        )
        Sale.objects.create(
            order_number="B200",
            date=date(2024, 4, 20),
            variant=self.variant,
            sold_quantity=5,
            return_quantity=2,
            sold_value=120,
            return_value=40,
        )
        # Outside the default range
        Sale.objects.create(
            order_number="C300",
            date=date(2024, 3, 15),
            variant=self.variant,
            sold_quantity=4,
            sold_value=50,
        )

        with patch("inventory.views.now") as mock_now:
            mock_now.return_value = timezone.make_aware(datetime(2024, 5, 15))
            response = self.client.get(reverse("sales"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], date(2024, 4, 1))
        self.assertEqual(response.context["end_date"], date(2024, 4, 30))
        self.assertEqual(response.context["orders_count"], 2)
        self.assertEqual(response.context["items_count"], 7)
        self.assertEqual(response.context["gross_sales_value"], Decimal("290"))
        self.assertEqual(response.context["net_sales_value"], Decimal("220"))
        self.assertTrue(response.context["has_sales_data"])

    def test_custom_range_filters_sales(self):
        Sale.objects.create(
            order_number="X1",
            date=date(2024, 1, 5),
            variant=self.variant,
            sold_quantity=4,
            sold_value=80,
        )
        Sale.objects.create(
            order_number="X2",
            date=date(2024, 2, 10),
            variant=self.variant,
            sold_quantity=6,
            return_quantity=1,
            sold_value=90,
            return_value=15,
        )
        Sale.objects.create(
            order_number="X3",
            date=date(2024, 3, 1),
            variant=self.variant,
            sold_quantity=8,
            sold_value=110,
        )

        with patch("inventory.views.now") as mock_now:
            mock_now.return_value = timezone.make_aware(datetime(2024, 4, 10))
            response = self.client.get(
                reverse("sales"),
                {"start_date": "2024-02-28", "end_date": "2024-02-01"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], date(2024, 2, 1))
        self.assertEqual(response.context["end_date"], date(2024, 2, 28))
        self.assertEqual(response.context["orders_count"], 1)
        self.assertEqual(response.context["items_count"], 5)
        self.assertEqual(response.context["gross_sales_value"], Decimal("90"))
        self.assertEqual(response.context["net_sales_value"], Decimal("75"))
        self.assertTrue(response.context["has_sales_data"])

    def test_price_breakdown_categorises_sales(self):
        self.product.retail_price = Decimal("100")
        self.product.save(update_fields=["retail_price"])

        Sale.objects.create(
            order_number="F001",
            date=date(2024, 4, 2),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("100.00"),
        )
        Sale.objects.create(
            order_number="S001",
            date=date(2024, 4, 5),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("192.00"),
        )
        Sale.objects.create(
            order_number="D001",
            date=date(2024, 4, 12),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("90.00"),
        )
        Sale.objects.create(
            order_number="W001",
            date=date(2024, 4, 18),
            variant=self.variant,
            sold_quantity=4,
            sold_value=Decimal("300.00"),
        )
        Sale.objects.create(
            order_number="G001",
            date=date(2024, 4, 25),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("0.00"),
        )
        # Returned sale should be excluded from breakdown counts
        Sale.objects.create(
            order_number="R001",
            date=date(2024, 4, 27),
            variant=self.variant,
            sold_quantity=2,
            return_quantity=1,
            sold_value=Decimal("150.00"),
        )

        with patch("inventory.views.now") as mock_now:
            mock_now.return_value = timezone.make_aware(datetime(2024, 5, 15))
            response = self.client.get(reverse("sales"))

        self.assertEqual(response.status_code, 200)

        breakdown = response.context["price_breakdown"]
        breakdown_by_label = {entry["label"]: entry for entry in breakdown}

        self.assertEqual(breakdown_by_label["Full price"]["items_count"], 1)
        self.assertEqual(breakdown_by_label["Full price"]["retail_value"], Decimal("100"))
        self.assertEqual(
            breakdown_by_label["Full price"]["actual_value"], Decimal("100")
        )
        self.assertEqual(
            breakdown_by_label["Full price"]["actual_percentage"], Decimal("14.66")
        )

        self.assertEqual(breakdown_by_label["Small discount"]["items_count"], 2)
        self.assertEqual(
            breakdown_by_label["Small discount"]["retail_value"], Decimal("200")
        )
        self.assertEqual(
            breakdown_by_label["Small discount"]["actual_value"], Decimal("192")
        )
        self.assertEqual(
            breakdown_by_label["Small discount"]["actual_percentage"],
            Decimal("28.15"),
        )

        self.assertEqual(breakdown_by_label["Discount"]["items_count"], 1)
        self.assertEqual(
            breakdown_by_label["Discount"]["retail_value"], Decimal("100")
        )
        self.assertEqual(
            breakdown_by_label["Discount"]["actual_value"], Decimal("90")
        )
        self.assertEqual(
            breakdown_by_label["Discount"]["actual_percentage"], Decimal("13.20")
        )

        self.assertEqual(breakdown_by_label["Wholesale"]["items_count"], 4)
        self.assertEqual(
            breakdown_by_label["Wholesale"]["retail_value"], Decimal("400")
        )
        self.assertEqual(
            breakdown_by_label["Wholesale"]["actual_value"], Decimal("300")
        )
        self.assertEqual(
            breakdown_by_label["Wholesale"]["actual_percentage"], Decimal("43.99")
        )

        self.assertEqual(breakdown_by_label["Gifted"]["items_count"], 1)
        self.assertEqual(
            breakdown_by_label["Gifted"]["retail_value"], Decimal("100")
        )
        self.assertEqual(
            breakdown_by_label["Gifted"]["actual_value"], Decimal("0")
        )
        self.assertEqual(
            breakdown_by_label["Gifted"]["actual_percentage"], Decimal("0.00")
        )

        self.assertEqual(response.context["pricing_total_items"], 9)
        self.assertEqual(
            response.context["pricing_total_retail_value"], Decimal("900")
        )
        self.assertEqual(
            response.context["pricing_total_actual_value"], Decimal("682")
        )

    def test_refunded_sales_not_categorised_as_gifted(self):
        self.product.retail_price = Decimal("100")
        self.product.save(update_fields=["retail_price"])

        Sale.objects.create(
            order_number="R100",
            date=date(2024, 4, 15),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("0.00"),
            return_quantity=0,
            return_value=Decimal("100.00"),
        )

        with patch("inventory.views.now") as mock_now:
            mock_now.return_value = timezone.make_aware(datetime(2024, 5, 15))
            response = self.client.get(reverse("sales"))

        self.assertEqual(response.status_code, 200)
        breakdown = response.context["price_breakdown"]
        breakdown_by_label = {entry["label"]: entry for entry in breakdown}

        self.assertEqual(breakdown_by_label["Gifted"]["items_count"], 0)
        self.assertEqual(breakdown_by_label["Full price"]["items_count"], 1)

    def test_assign_order_referrer_updates_all_sales(self):
        referrer = Referrer.objects.create(name="Coach Nova")
        sale_one = Sale.objects.create(
            order_number="REF100",
            date=date(2024, 4, 5),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("10.00"),
        )
        sale_two = Sale.objects.create(
            order_number="REF100",
            date=date(2024, 4, 6),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("20.00"),
        )
        other_sale = Sale.objects.create(
            order_number="OTHER",
            date=date(2024, 4, 6),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("10.00"),
        )

        redirect_with_dates = self.client.post(
            reverse("assign_order_referrer", args=["full_price"]),
            {
                "order_number": "REF100",
                "referrer_id": str(referrer.id),
                "date_querystring": "start_date=2024-04-01&end_date=2024-04-30",
            },
        )

        expected_redirect = (
            f"{reverse('sales_bucket_detail', args=['full_price'])}?"
            "start_date=2024-04-01&end_date=2024-04-30"
        )
        self.assertEqual(redirect_with_dates.status_code, 302)
        self.assertEqual(redirect_with_dates["Location"], expected_redirect)

        sale_one.refresh_from_db()
        sale_two.refresh_from_db()
        other_sale.refresh_from_db()

        self.assertEqual(sale_one.referrer, referrer)
        self.assertEqual(sale_two.referrer, referrer)
        self.assertIsNone(other_sale.referrer)

        redirect_clear = self.client.post(
            reverse("assign_order_referrer", args=["full_price"]),
            {
                "order_number": "REF100",
                "referrer_id": "",
            },
        )
        self.assertEqual(
            redirect_clear["Location"],
            reverse("sales_bucket_detail", args=["full_price"]),
        )

        sale_one.refresh_from_db()
        sale_two.refresh_from_db()

        self.assertIsNone(sale_one.referrer)
        self.assertIsNone(sale_two.referrer)

