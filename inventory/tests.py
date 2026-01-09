from datetime import date, timedelta, datetime
from decimal import Decimal
import json
import os
import tempfile
from io import BytesIO

from unittest.mock import patch
from dateutil.relativedelta import relativedelta
from django.contrib.admin.sites import AdminSite
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile

from PIL import Image

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
from .admin import SaleAdmin, SaleDateEqualsFilter
from .utils import (
    get_low_stock_products,
    get_restock_alerts,
    calculate_variant_sales_speed,
    get_category_speed_stats,
)
from .views import (
    PRODUCT_CANVAS_MAX_DIMENSION,
    DEFAULT_PRODUCT_IMAGE,
    _build_product_list_context,
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


class ProductConfidenceAdvisoryTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_core_key_sizes_out_of_stock_are_consolidated(self):
        product = Product.objects.create(
            product_id="P-KEYS",
            product_name="Core Nogi",
            style="ng",
            restock_time=2,
        )

        for size in ["S", "M", "L"]:
            variant = ProductVariant.objects.create(
                product=product,
                variant_code=f"VAR-{size}",
                primary_color="#000000",
                size=size,
            )
            InventorySnapshot.objects.create(
                product_variant=variant, date=date.today(), inventory_count=0
            )

        request = self.factory.get("/inventory/products/")
        context = _build_product_list_context(request)

        product_entry = next(
            p for p in context["products"] if getattr(p, "product_id", None) == "P-KEYS"
        )
        advisories = getattr(product_entry, "confidence_advisories", [])
        out_of_stock_advisories = [
            note for note in advisories if "out of stock" in note.lower()
        ]

        self.assertEqual(len(out_of_stock_advisories), 1)
        self.assertIn("S/M/L", out_of_stock_advisories[0])


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


class ProductAdminGroupActionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        from inventory.admin import ProductAdmin

        self.admin = ProductAdmin(Product, admin_site=AdminSite())
        self.group_a = Group.objects.create(name="Group A")
        self.group_b = Group.objects.create(name="Group B")
        self.product_one = Product.objects.create(
            product_id="G1", product_name="Group Product 1"
        )
        self.product_two = Product.objects.create(
            product_id="G2", product_name="Group Product 2"
        )
        self.product_one.groups.add(self.group_a)
        self.product_two.groups.add(self.group_a)

        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )

    def _prepare_request(self, data):
        request = self.factory.post("/admin/inventory/product/", data)
        request.user = self.user
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)
        return request

    def test_assign_group_prompts_for_confirmation(self):
        data = {
            "action": "assign_group",
            ACTION_CHECKBOX_NAME: [str(self.product_one.pk)],
        }
        request = self._prepare_request(data)
        queryset = Product.objects.filter(pk=self.product_one.pk)

        response = self.admin.assign_group(request, queryset)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Assign group", response.content.decode())

    def test_assign_group_updates_selected_products(self):
        selected_ids = [str(self.product_one.pk), str(self.product_two.pk)]
        data = {
            "action": "assign_group",
            "apply": "1",
            "group": str(self.group_b.pk),
            ACTION_CHECKBOX_NAME: selected_ids,
            "_selected_action": selected_ids,
        }
        request = self._prepare_request(data)
        queryset = Product.objects.filter(pk__in=selected_ids)

        response = self.admin.assign_group(request, queryset)

        self.assertEqual(response.status_code, 302)
        self.product_one.refresh_from_db()
        self.product_two.refresh_from_db()
        self.assertEqual(list(self.product_one.groups.all()), [self.group_b])
        self.assertEqual(list(self.product_two.groups.all()), [self.group_b])

    def test_mark_no_restock_updates_selected_products(self):
        selected_ids = [str(self.product_one.pk), str(self.product_two.pk)]
        data = {
            "action": "mark_no_restock",
            ACTION_CHECKBOX_NAME: selected_ids,
        }
        request = self._prepare_request(data)
        queryset = Product.objects.filter(pk__in=selected_ids)

        response = self.admin.mark_no_restock(request, queryset)

        self.assertIsNone(response)
        self.product_one.refresh_from_db()
        self.product_two.refresh_from_db()
        self.assertTrue(self.product_one.no_restock)
        self.assertTrue(self.product_two.no_restock)


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


class SalesBucketDetailViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="SB1", product_name="Sales Bucket Product", retail_price=Decimal("100.00")
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            variant_code="SB1-1",
            primary_color="#000000",
        )

    def test_full_order_displayed_for_bucket(self):
        bucket_sale = Sale.objects.create(
            order_number="ORDER-1",
            date=date(2024, 4, 5),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("0.00"),
        )
        other_sale = Sale.objects.create(
            order_number="ORDER-1",
            date=date(2024, 4, 5),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("100.00"),
        )

        response = self.client.get(
            reverse("sales_bucket_detail", args=["gifted"]),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        orders = response.context["orders"]
        self.assertEqual(len(orders), 1)

        order = orders[0]
        self.assertEqual(order["order_number"], "ORDER-1")
        self.assertEqual(order["total_value"], Decimal("100.00"))
        self.assertEqual(len(order["items"]), 2)

        bucket_items = [item for item in order["items"] if item["is_bucket_item"]]
        non_bucket_items = [item for item in order["items"] if not item["is_bucket_item"]]

        self.assertEqual(len(bucket_items), 1)
        self.assertEqual(len(non_bucket_items), 1)
        self.assertEqual(bucket_items[0]["sale"].pk, bucket_sale.pk)
        self.assertEqual(non_bucket_items[0]["sale"].pk, other_sale.pk)
        self.assertEqual(bucket_items[0]["discount_percentage"], Decimal("100.00"))
        self.assertEqual(non_bucket_items[0]["discount_percentage"], Decimal("0.00"))

        bucket_totals = response.context["bucket_totals"]
        self.assertEqual(bucket_totals["items_count"], 1)
        self.assertEqual(bucket_totals["retail_value"], Decimal("100.00"))
        self.assertEqual(bucket_totals["actual_value"], Decimal("0.00"))

    def test_returned_items_include_return_details(self):
        Sale.objects.create(
            order_number="ORDER-RETURN",
            date=date(2024, 4, 4),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("100.00"),
        )
        returned_sale = Sale.objects.create(
            order_number="ORDER-RETURN",
            date=date(2024, 4, 6),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("0.00"),
            return_quantity=1,
            return_value=Decimal("100.00"),
        )

        response = self.client.get(
            reverse("sales_bucket_detail", args=["full_price"]),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        orders = response.context["orders"]
        self.assertEqual(len(orders), 1)

        order = orders[0]
        self.assertEqual(order["order_number"], "ORDER-RETURN")
        self.assertEqual(order["returns_value"], Decimal("100.00"))

        returned_item = next(
            item for item in order["items"] if item["sale"].pk == returned_sale.pk
        )
        self.assertTrue(returned_item["returned"])
        self.assertEqual(returned_item["return_quantity"], 1)
        self.assertEqual(returned_item["return_value"], Decimal("100.00"))
        self.assertEqual(returned_item["discount_percentage"], Decimal("100.00"))


    def test_refunded_sale_without_quantity_highlighted(self):
        refund_sale = Sale.objects.create(
            order_number="ORDER-REFUND",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("0.00"),
            return_quantity=0,
            return_value=Decimal("100.00"),
        )

        response = self.client.get(
            reverse("sales_bucket_detail", args=["full_price"]),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        orders = response.context["orders"]
        self.assertEqual(len(orders), 1)

        order = orders[0]
        refund_item = order["items"][0]

        self.assertTrue(refund_item["returned"])
        self.assertEqual(refund_item["sale"].pk, refund_sale.pk)
        self.assertEqual(refund_item["return_quantity"], 0)
        self.assertEqual(refund_item["return_value"], Decimal("100.00"))
        self.assertEqual(refund_item["discount_percentage"], Decimal("100.00"))


class SalesReferrersViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="RF1",
            product_name="Referrer Product",
            retail_price=Decimal("80.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            variant_code="RF1-1",
            primary_color="#000000",
        )
        self.alpha = Referrer.objects.create(name="Alpha")
        self.beta = Referrer.objects.create(name="Beta")

    def test_lists_sales_with_referrers_in_range(self):
        Sale.objects.create(
            order_number="REF-100",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("120.00"),
            referrer=self.alpha,
        )
        Sale.objects.create(
            order_number="REF-100",
            date=date(2024, 4, 12),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("30.00"),
            return_quantity=1,
            return_value=Decimal("30.00"),
            referrer=self.alpha,
        )
        # Outside requested range
        Sale.objects.create(
            order_number="OLD-REF",
            date=date(2024, 3, 5),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("40.00"),
            referrer=self.beta,
        )

        response = self.client.get(
            reverse("sales_referrers"),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_sales_data"])
        self.assertEqual(response.context["orders_count"], 1)

        summary = response.context["summary"]
        self.assertEqual(summary["items_count"], 3)
        self.assertEqual(summary["actual_value"], Decimal("150.00"))
        self.assertEqual(summary["returns_value"], Decimal("30.00"))
        self.assertEqual(summary["retail_value"], Decimal("240.00"))
        self.assertEqual(summary["referrer_count"], 1)

        orders = response.context["orders"]
        self.assertEqual(len(orders), 1)
        order = orders[0]
        self.assertEqual(order["order_number"], "REF-100")
        self.assertEqual(order["total_value"], Decimal("150.00"))
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual(len(order["referrers"]), 1)
        self.assertEqual(order["referrers"][0], self.alpha)

    def test_filtering_by_specific_referrer(self):
        Sale.objects.create(
            order_number="ALPHA-1",
            date=date(2024, 4, 6),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("50.00"),
            referrer=self.alpha,
        )
        Sale.objects.create(
            order_number="BETA-1",
            date=date(2024, 4, 7),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("70.00"),
            referrer=self.beta,
        )

        response = self.client.get(
            reverse("sales_referrers"),
            {
                "start_date": "2024-04-01",
                "end_date": "2024-04-30",
                "referrer": str(self.beta.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["orders_count"], 1)
        self.assertEqual(response.context["selected_referrer"], self.beta)
        self.assertEqual(response.context["summary"]["referrer_count"], 1)
        self.assertEqual(response.context["summary"]["items_count"], 2)

        orders = response.context["orders"]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["order_number"], "BETA-1")
        self.assertEqual(orders[0]["referrers"], [self.beta])


class ReferrersOverviewViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="RO1",
            product_name="Referrer Overview Product",
            retail_price=Decimal("120.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            variant_code="RO1-1",
            primary_color="#000000",
        )
        self.alpha = Referrer.objects.create(name="Alpha")
        self.beta = Referrer.objects.create(name="Beta")

    def test_referrers_sorted_with_totals(self):
        Sale.objects.create(
            order_number="ALPHA-100",
            date=date(2024, 4, 5),
            variant=self.variant,
            sold_quantity=3,
            sold_value=Decimal("300.00"),
            referrer=self.alpha,
        )
        Sale.objects.create(
            order_number="ALPHA-100",
            date=date(2024, 4, 6),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("50.00"),
            return_quantity=1,
            return_value=Decimal("50.00"),
            referrer=self.alpha,
        )

        Sale.objects.create(
            order_number="BETA-200",
            date=date(2024, 4, 7),
            variant=self.variant,
            sold_quantity=5,
            sold_value=Decimal("0.00"),
            referrer=self.beta,
        )
        Sale.objects.create(
            order_number="BETA-201",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("100.00"),
            return_value=Decimal("20.00"),
            referrer=self.beta,
        )

        response = self.client.get(
            reverse("referrers_overview"),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_sales_data"])

        rows = response.context["referrer_rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["referrer"] for row in rows], [self.alpha, self.beta])

        alpha_row = rows[0]
        beta_row = rows[1]

        self.assertEqual(alpha_row["total_orders"], 1)
        self.assertEqual(alpha_row["total_items"], 4)
        self.assertEqual(alpha_row["total_sales"], Decimal("300.00"))
        self.assertEqual(alpha_row["total_gifted"], 0)

        self.assertEqual(beta_row["total_orders"], 2)
        self.assertEqual(beta_row["total_items"], 7)
        self.assertEqual(beta_row["total_sales"], Decimal("80.00"))
        self.assertEqual(beta_row["total_gifted"], 5)

        totals = response.context["totals"]
        self.assertEqual(totals["orders"], 3)
        self.assertEqual(totals["items"], 11)
        self.assertEqual(totals["gifted"], 5)
        self.assertEqual(totals["sales"], Decimal("380.00"))
        self.assertEqual(totals["with_sales"], 2)

    def test_default_date_range_last_month(self):
        Sale.objects.create(
            order_number="ALPHA-APR",
            date=date(2024, 4, 15),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("160.00"),
            referrer=self.alpha,
        )
        # Should be excluded by default date range
        Sale.objects.create(
            order_number="ALPHA-MAY",
            date=date(2024, 5, 2),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("80.00"),
            referrer=self.alpha,
        )

        with patch("inventory.views.now") as mock_now:
            mock_now.return_value = timezone.make_aware(datetime(2024, 5, 15))
            response = self.client.get(reverse("referrers_overview"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["start_date"], date(2024, 4, 1))
        self.assertEqual(response.context["end_date"], date(2024, 4, 30))

        rows = response.context["referrer_rows"]
        self.assertEqual(rows[0]["total_items"], 2)
        self.assertEqual(rows[0]["total_sales"], Decimal("160.00"))
class ReferrerDetailViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            product_id="RD1",
            product_name="Referrer Detail Product",
            retail_price=Decimal("100.00"),
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            variant_code="RD1-1",
            primary_color="#000000",
        )
        self.primary_referrer = Referrer.objects.create(name="Primary")
        self.secondary_referrer = Referrer.objects.create(name="Secondary")

    def test_orders_and_stats_for_referrer(self):
        order = Order.objects.create(order_date=date(2024, 3, 20))
        OrderItem.objects.create(
            order=order,
            product_variant=self.variant,
            quantity=10,
            item_cost_price=Decimal("30.00"),
            date_expected=date(2024, 3, 1),
            date_arrived=date(2024, 3, 5),
        )

        Sale.objects.create(
            order_number="ORD-1",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("150.00"),
            referrer=self.primary_referrer,
        )
        Sale.objects.create(
            order_number="ORD-1",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("0.00"),
            referrer=self.primary_referrer,
        )
        Sale.objects.create(
            order_number="ORD-1",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("100.00"),
            referrer=self.secondary_referrer,
        )
        Sale.objects.create(
            order_number="ORD-1",
            date=date(2024, 4, 10),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("100.00"),
        )
        Sale.objects.create(
            order_number="ORD-2",
            date=date(2024, 4, 12),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("90.00"),
            referrer=self.primary_referrer,
        )

        response = self.client.get(
            reverse("referrer_detail", args=[self.primary_referrer.pk]),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["has_sales_data"])

        summary = response.context["summary"]
        self.assertEqual(summary["items_count"], 4)
        self.assertEqual(summary["retail_value"], Decimal("400.00"))
        self.assertEqual(summary["actual_value"], Decimal("240.00"))
        self.assertEqual(summary["returns_value"], Decimal("0"))

        stats = response.context["stats"]
        self.assertEqual(stats["free_items"], 1)
        self.assertEqual(stats["direct_discount_items"], 2)
        self.assertEqual(stats["referred_items"], 1)

        financials = response.context["financials"]
        self.assertEqual(financials["total_sales"], Decimal("240.00"))
        self.assertEqual(financials["returns"], Decimal("0"))
        self.assertEqual(financials["cost_of_goods_sold"], Decimal("90.00"))
        self.assertEqual(financials["freebies_cost"], Decimal("30.00"))
        self.assertEqual(financials["paid_value"], Decimal("240.00"))
        self.assertEqual(financials["paid_quantity"], 3)
        self.assertEqual(financials["freebie_value"], Decimal("0.00"))
        self.assertEqual(financials["freebie_quantity"], 1)
        self.assertEqual(financials["commission"], Decimal("75.00"))
        self.assertEqual(financials["net_profit"], Decimal("45.00"))


        orders = response.context["orders"]
        self.assertEqual(len(orders), 2)
        order_numbers = {order["order_number"] for order in orders}
        self.assertIn("ORD-1", order_numbers)
        self.assertIn("ORD-2", order_numbers)

        order_one = next(order for order in orders if order["order_number"] == "ORD-1")
        self.assertEqual(len(order_one["items"]), 4)
        highlighted_count = sum(1 for item in order_one["items"] if item["is_referrer_item"])
        self.assertEqual(highlighted_count, 2)
        other_ref_item = next(
            item
            for item in order_one["items"]
            if item["sale"].referrer == self.secondary_referrer
        )
        self.assertFalse(other_ref_item["is_referrer_item"])
        no_ref_item = next(
            item for item in order_one["items"] if item["sale"].referrer is None
        )
        self.assertFalse(no_ref_item["is_referrer_item"])

    def test_financials_include_returns_in_paid_value(self):
        order = Order.objects.create(order_date=date(2024, 3, 20))
        OrderItem.objects.create(
            order=order,
            product_variant=self.variant,
            quantity=5,
            item_cost_price=Decimal("30.00"),
            date_expected=date(2024, 3, 1),
            date_arrived=date(2024, 3, 5),
        )

        Sale.objects.create(
            order_number="RET-1",
            date=date(2024, 4, 15),
            variant=self.variant,
            sold_quantity=2,
            sold_value=Decimal("200.00"),
            return_quantity=1,
            return_value=Decimal("100.00"),
            referrer=self.primary_referrer,
        )

        response = self.client.get(
            reverse("referrer_detail", args=[self.primary_referrer.pk]),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)

        financials = response.context["financials"]
        self.assertEqual(financials["total_sales"], Decimal("200.00"))
        self.assertEqual(financials["returns"], Decimal("100.00"))
        self.assertEqual(financials["paid_value"], Decimal("100.00"))
        self.assertEqual(financials["cost_of_goods_sold"], Decimal("30.00"))
        self.assertEqual(financials["freebies_cost"], Decimal("0"))
        self.assertEqual(financials["net_profit"], Decimal("70.00"))

    def test_referrer_detail_handles_empty_range(self):
        Sale.objects.create(
            order_number="ORD-OLD",
            date=date(2024, 3, 10),
            variant=self.variant,
            sold_quantity=1,
            sold_value=Decimal("90.00"),
            referrer=self.primary_referrer,
        )

        response = self.client.get(
            reverse("referrer_detail", args=[self.primary_referrer.pk]),
            {"start_date": "2024-04-01", "end_date": "2024-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["has_sales_data"])
        self.assertEqual(response.context["summary"]["items_count"], 0)
        self.assertEqual(response.context["stats"], {
            "free_items": 0,
            "direct_discount_items": 0,
            "referred_items": 0,
        })


class SaleAdminDateFilterTests(TestCase):
    def setUp(self):
        self.admin_site = AdminSite()
        self.sale_admin = SaleAdmin(Sale, self.admin_site)
        self.factory = RequestFactory()

        product = Product.objects.create(product_id="P200", product_name="Prod200")
        variant = ProductVariant.objects.create(
            product=product,
            variant_code="VAR200",
            primary_color="#000000",
        )

        self.matching_sale = Sale.objects.create(
            order_number="ORDER-200",
            date=date(2024, 6, 1),
            variant=variant,
            sold_quantity=1,
            sold_value=Decimal("15.00"),
        )
        self.other_sale = Sale.objects.create(
            order_number="ORDER-201",
            date=date(2024, 6, 2),
            variant=variant,
            sold_quantity=1,
            sold_value=Decimal("18.00"),
        )

    def test_list_filter_includes_date_picker(self):
        self.assertEqual(self.sale_admin.list_filter[0], SaleDateEqualsFilter)
        self.assertNotIn("variant", self.sale_admin.list_filter)

    def test_queryset_filters_by_selected_date(self):
        params = {"date": self.matching_sale.date.isoformat()}
        request = self.factory.get("/admin/inventory/sale/", params)
        date_filter = SaleDateEqualsFilter(request, params, Sale, self.sale_admin)

        filtered_queryset = date_filter.queryset(request, Sale.objects.all())

        self.assertEqual(list(filtered_queryset), [self.matching_sale])


class SaleAdminSearchTests(TestCase):
    def setUp(self):
        self.admin_site = AdminSite()
        self.sale_admin = SaleAdmin(Sale, self.admin_site)
        self.factory = RequestFactory()

        product = Product.objects.create(product_id="P100", product_name="Prod100")
        variant = ProductVariant.objects.create(
            product=product,
            variant_code="VAR100",
            primary_color="#000000",
        )

        self.sale_one = Sale.objects.create(
            order_number="ORDER-001",
            date=date.today(),
            variant=variant,
            sold_quantity=1,
            sold_value=Decimal("10.00"),
        )
        self.sale_two = Sale.objects.create(
            order_number="ORDER-002",
            date=date.today(),
            variant=variant,
            sold_quantity=1,
            sold_value=Decimal("12.00"),
        )

    def test_search_multiple_order_numbers_returns_all_matches(self):
        search_term = f"{self.sale_one.order_number} {self.sale_two.order_number}"
        request = self.factory.get("/admin/inventory/sale/", {"q": search_term})

        queryset, use_distinct = self.sale_admin.get_search_results(
            request,
            Sale.objects.all(),
            search_term,
        )

        self.assertFalse(use_distinct)
        self.assertCountEqual(list(queryset), [self.sale_one, self.sale_two])


class SaleAdminAssignReferrerActionTests(TestCase):
    def setUp(self):
        self.admin_site = AdminSite()
        self.sale_admin = SaleAdmin(Sale, self.admin_site)
        self.factory = RequestFactory()

        product = Product.objects.create(product_id="P100", product_name="Prod100")
        variant = ProductVariant.objects.create(
            product=product,
            variant_code="VAR100",
            primary_color="#000000",
        )

        self.sale_one = Sale.objects.create(
            order_number="ORDER-001",
            date=date.today(),
            variant=variant,
            sold_quantity=1,
            sold_value=Decimal("10.00"),
        )
        self.sale_two = Sale.objects.create(
            order_number="ORDER-002",
            date=date.today(),
            variant=variant,
            sold_quantity=1,
            sold_value=Decimal("12.00"),
        )
        self.referrer = Referrer.objects.create(name="Affiliate")

        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )

    def _prepare_request(self, data):
        request = self.factory.post("/admin/inventory/sale/", data)
        request.user = self.user
        # Attach a session and message storage so the admin action can use them.
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)
        return request

    def test_assign_referrer_prompts_for_confirmation(self):
        data = {
            "action": "assign_referrer",
            ACTION_CHECKBOX_NAME: [str(self.sale_one.pk)],
        }
        request = self._prepare_request(data)
        queryset = Sale.objects.filter(pk=self.sale_one.pk)

        response = self.sale_admin.assign_referrer(request, queryset)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Assign referrer", response.content.decode())

    def test_assign_referrer_updates_selected_sales(self):
        selected_ids = [str(self.sale_one.pk), str(self.sale_two.pk)]
        data = {
            "action": "assign_referrer",
            "apply": "1",
            "referrer": str(self.referrer.pk),
            ACTION_CHECKBOX_NAME: selected_ids,
            "_selected_action": selected_ids,
        }
        request = self._prepare_request(data)
        queryset = Sale.objects.filter(pk__in=selected_ids)

        response = self.sale_admin.assign_referrer(request, queryset)

        self.assertEqual(response.status_code, 302)
        self.sale_one.refresh_from_db()
        self.sale_two.refresh_from_db()
        self.assertEqual(self.sale_one.referrer, self.referrer)
        self.assertEqual(self.sale_two.referrer, self.referrer)


class ProductCanvasLayoutTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)

    def _create_product(self, code="001"):
        return Product.objects.create(
            product_id=f"PC{code}", product_name=f"Product {code}"
        )

    def test_get_returns_empty_layout_when_file_missing(self):
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            self._create_product()
            response = self.client.get(reverse("product_canvas_layout"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"layout": {}})

    def test_post_persists_filtered_layout(self):
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            product_a = self._create_product("A")
            product_b = self._create_product("B")
            product_c = self._create_product("C")

            url = reverse("product_canvas_layout")
            payload = {
                "layout": {
                    str(product_a.pk): {
                        "left": 12.5,
                        "top": 34,
                        "scaleX": 1.2,
                        "scaleY": 1.25,
                    },
                    str(product_b.pk): {
                        "left": "50",
                        "top": "60",
                        "scaleX": "1.5",
                        "scaleY": None,
                    },
                    str(product_c.pk): {
                        "left": 70,
                        "top": 80,
                        "scaleX": 0,
                        "scaleY": 0,
                    },
                    "unknown": {
                        "left": 1,
                        "top": 2,
                        "scaleX": 1,
                        "scaleY": 1,
                    },
                }
            }

            response = self.client.post(
                url, data=json.dumps(payload), content_type="application/json"
            )
            self.assertEqual(response.status_code, 200)

            saved_layout = response.json().get("layout")
            self.assertIn(str(product_a.pk), saved_layout)
            self.assertIn(str(product_b.pk), saved_layout)
            self.assertNotIn(str(product_c.pk), saved_layout)
            self.assertNotIn("unknown", saved_layout)

            self.assertEqual(saved_layout[str(product_a.pk)]["left"], 12.5)
            self.assertEqual(saved_layout[str(product_a.pk)]["scaleY"], 1.25)
            self.assertEqual(saved_layout[str(product_b.pk)]["left"], 50)
            self.assertAlmostEqual(saved_layout[str(product_b.pk)]["scaleX"], 1.5)
            self.assertAlmostEqual(
                saved_layout[str(product_b.pk)]["scaleY"],
                saved_layout[str(product_b.pk)]["scaleX"],
            )

            # Confirm persisted to disk and filtered output on GET
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"layout": saved_layout})

    def test_post_rejects_invalid_payload(self):
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            self._create_product("Z")
            url = reverse("product_canvas_layout")
            response = self.client.post(
                url, data=json.dumps({"layout": []}), content_type="application/json"
            )

        self.assertEqual(response.status_code, 400)


class ProductCanvasImageTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)

    def _image_bytes(self, size=(640, 480), color=(200, 50, 50)):
        image = Image.new("RGB", size, color)
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        return buffer.getvalue()

    def _upload(self, name="photo.jpg", size=(640, 480)):
        return SimpleUploadedFile(name, self._image_bytes(size=size), content_type="image/jpeg")

    def test_product_canvas_image_resizes_large_photos(self):
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            product = Product.objects.create(
                product_id="PX1",
                product_name="Canvas Product",
                product_photo=self._upload(size=(1200, 900)),
            )

            response = self.client.get(reverse("product_canvas_image", args=[product.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")

        with Image.open(BytesIO(response.content)) as img:
            self.assertEqual(img.size, (PRODUCT_CANVAS_MAX_DIMENSION, PRODUCT_CANVAS_MAX_DIMENSION))

    def test_product_canvas_image_upscales_small_square_photos(self):
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            product = Product.objects.create(
                product_id="PX1B",
                product_name="Small Photo",
                product_photo=self._upload(size=(320, 320)),
            )

            response = self.client.get(reverse("product_canvas_image", args=[product.pk]))

        self.assertEqual(response.status_code, 200)

        with Image.open(BytesIO(response.content)) as img:
            self.assertEqual(img.size, (PRODUCT_CANVAS_MAX_DIMENSION, PRODUCT_CANVAS_MAX_DIMENSION))
            top_left = img.getpixel((0, 0))
            self.assertTrue(all(channel < 250 for channel in top_left))

    def test_product_canvas_image_uses_default_when_missing_photo(self):
        with override_settings(MEDIA_ROOT=self.media_dir.name):
            default_path = os.path.join(self.media_dir.name, DEFAULT_PRODUCT_IMAGE)
            os.makedirs(os.path.dirname(default_path), exist_ok=True)
            with open(default_path, "wb") as handle:
                handle.write(self._image_bytes(size=(300, 300), color=(20, 20, 20)))

            product = Product.objects.create(
                product_id="PX2",
                product_name="No Photo Product",
            )

            response = self.client.get(reverse("product_canvas_image", args=[product.pk]))

        self.assertEqual(response.status_code, 200)
        with Image.open(BytesIO(response.content)) as img:
            self.assertEqual(img.size, (PRODUCT_CANVAS_MAX_DIMENSION, PRODUCT_CANVAS_MAX_DIMENSION))
