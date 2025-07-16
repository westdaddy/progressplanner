from datetime import datetime, date, timedelta
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta
import json
from collections import defaultdict, namedtuple, OrderedDict
import calendar
import statistics
import math
from urllib.parse import urlencode
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)


from decimal import Decimal

from django.shortcuts import render, get_object_or_404
from django.db import models
from django.db.models import (
    Count,
    F,
    Q,
    Sum,
    Subquery,
    OuterRef,
    Value,
    IntegerField,
    DecimalField,
    Prefetch,
    FloatField,
    ExpressionWrapper,
    Avg,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.db.models.functions import TruncMonth

from .models import (
    Product,
    ProductVariant,
    InventorySnapshot,
    Sale,
    Order,
    OrderItem,
    Group,
    Series,
    PRODUCT_TYPE_CHOICES,
    PRODUCT_STYLE_CHOICES,
    PRODUCT_AGE_CHOICES,
)
from .utils import (
    calculate_size_order_mix,
    compute_safe_stock,
    SIZE_ORDER,
    compute_variant_projection,
    compute_sales_aggregates,
    get_product_sales_data,
    calculate_estimated_inventory_sales_value,
    calculate_on_paper_inventory_value,
    compute_inventory_health_scores,
    get_product_health_metrics,
    calculate_dynamic_product_score,
    compute_product_health,
    get_low_stock_products,
    get_restock_alerts,
    calculate_variant_sales_speed,
)


# used in 'home' view
CATEGORY_COLOR_MAP = {
    "gi": "#43a047",  # Green
    "rg": "#1e88e5",  # Blue
    "dk": "#fb8c00",  # Orange
    "other": "#9e9e9e",  # Grey
}


# — Helper to bucket types into our four categories —
def _simplify_type(type_code):
    tc = (type_code or "").lower()
    if tc == "gi":
        return "gi"
    elif "rashguard" in tc or "rg" in tc:
        return "rg"
    elif "shorts" in tc or tc == "dk":
        return "dk"
    return "other"


def home(request):
    # — Determining last month's date range —
    today = date.today()
    first_day_current = today.replace(day=1)
    last_day_previous = first_day_current - timedelta(days=1)
    first_day_previous = last_day_previous.replace(day=1)

    # — Sales for last month —
    sales_last_month = Sale.objects.filter(
        date__range=(first_day_previous, last_day_previous)
    )

    # — Aggregate item counts by category —
    category_totals = defaultdict(int)
    for sale in sales_last_month.select_related("variant__product"):
        if sale.variant:
            cat = _simplify_type(sale.variant.product.type)
            category_totals[cat] += sale.sold_quantity or 0

    # — Prepare ordered donut data —
    ordered_labels, ordered_values, ordered_colors = [], [], []
    for key, color in CATEGORY_COLOR_MAP.items():
        ordered_labels.append(key)
        ordered_values.append(category_totals.get(key, 0))
        ordered_colors.append(color)
    total_items_sold = sum(ordered_values)

    # — Build 12-month revenue line chart data —
    monthly_labels, monthly_sales, monthly_sales_last_year = [], [], []
    for i in range(12):
        this_month = (today - relativedelta(months=11 - i)).replace(day=1)
        next_month = this_month + relativedelta(months=1)

        rev = (
            Sale.objects.filter(date__gte=this_month, date__lt=next_month).aggregate(
                total=Sum("sold_value")
            )["total"]
            or 0
        )
        last_year_month = this_month - relativedelta(years=1)
        rev_last = (
            Sale.objects.filter(
                date__gte=last_year_month,
                date__lt=last_year_month + relativedelta(months=1),
            ).aggregate(total=Sum("sold_value"))["total"]
            or 0
        )

        monthly_labels.append(this_month.strftime("%b %Y"))
        monthly_sales.append(float(rev))
        monthly_sales_last_year.append(float(rev_last))

    last_month_name = first_day_previous.strftime("%B %Y")

    # — Summary card totals —
    total_sales = (
        sales_last_month.aggregate(total_sold_value=Sum("sold_value"))[
            "total_sold_value"
        ]
        or 0
    )
    total_returns = (
        sales_last_month.aggregate(total_return_value=Sum("return_value"))[
            "total_return_value"
        ]
        or 0
    )
    net_sales = total_sales - total_returns

    # — Inventory Overview Stats —
    latest_cost_qs = (
        OrderItem.objects.filter(
            product_variant=OuterRef("pk"), date_arrived__isnull=False
        )
        .order_by("-date_arrived")
        .values("item_cost_price")[:1]
    )

    avg_cost_qs = (
        OrderItem.objects.filter(product_variant=OuterRef("pk"))
        .values("product_variant")
        .annotate(avg_price=Avg("item_cost_price"))
        .values("avg_price")[:1]
    )

    variants = ProductVariant.objects.annotate(
        latest_inventory=Coalesce(
            Subquery(
                InventorySnapshot.objects.filter(product_variant=OuterRef("pk"))
                .order_by("-date")
                .values("inventory_count")[:1]
            ),
            Value(0),
        ),
        unit_cost=Coalesce(
            Subquery(latest_cost_qs),  # 1) real last-arrived cost
            Subquery(avg_cost_qs),  # 2) historical average cost
            ExpressionWrapper(
                F("product__retail_price")
                * Value(Decimal("0.5")),  # 3) half of retail price
                output_field=DecimalField(),
            ),
            Value(Decimal("0.00")),
        ),
    )

    inventory_count = variants.aggregate(total=Sum("latest_inventory"))["total"] or 0
    inventory_value = (
        variants.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("latest_inventory") * F("unit_cost"), output_field=DecimalField()
                )
            )
        )["total"]
        or 0
    )

    incoming = OrderItem.objects.filter(
        date_expected__gte=today, date_arrived__isnull=True
    )
    on_order_count = incoming.aggregate(total=Sum("quantity"))["total"] or 0
    on_order_value = (
        incoming.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("quantity") * F("item_cost_price"), output_field=DecimalField()
                )
            )
        )["total"]
        or 0
    )

    context = {
        # Summary cards
        "total_sales": total_sales,
        "total_returns": total_returns,
        "net_sales": net_sales,
        # Revenue chart data
        "last_month_name": last_month_name,
        "monthly_labels": json.dumps(monthly_labels),
        "monthly_sales": json.dumps(monthly_sales),
        "monthly_sales_last_year": json.dumps(monthly_sales_last_year),
        # Category donut data
        "total_items_sold": total_items_sold,
        "category_labels": json.dumps(ordered_labels),
        "category_values": json.dumps(ordered_values),
        "category_colors": json.dumps(ordered_colors),
        # Inventory overview
        "inventory_count": inventory_count,
        "inventory_value": inventory_value,
        "on_order_count": on_order_count,
        "on_order_value": on_order_value,
    }

    # Compute estimated sales‐value of stock
    est_sales_value = calculate_estimated_inventory_sales_value(
        variants, _simplify_type  # pass your bucket-func in
    )
    on_paper_value = calculate_on_paper_inventory_value(variants)

    context.update(
        {
            "estimated_inventory_sales_value": est_sales_value,
            "on_paper_value": on_paper_value,
        }
    )

    # Gather detailed restock alerts
    context["restock_alerts"] = get_restock_alerts()

    return render(request, "inventory/home.html", context)


def dashboard(request):
    today = date.today()
    # Calculate last month's date range.
    first_day_this_month = today.replace(day=1)
    last_day_previous = first_day_this_month - timedelta(days=1)
    first_day_last_month = last_day_previous.replace(day=1)

    # Calculate the last 3 full months range.
    first_day_last_3_months = (first_day_this_month - relativedelta(months=3)).replace(
        day=1
    )
    # Calculate the last 12 months range.
    one_year_ago = today - relativedelta(months=12)

    # 1. Aggregate sales by variant type for last month.
    sales_by_type_qs = (
        Sale.objects.filter(date__range=(first_day_last_month, last_day_previous))
        .values("variant__product__type")
        .annotate(total_sold=Sum("sold_quantity"))
    )
    sales_by_type = {
        item["variant__product__type"]: item["total_sold"] for item in sales_by_type_qs
    }

    # 2. Aggregate sales for the last 3 months.
    sales_3m_qs = (
        Sale.objects.filter(date__range=(first_day_last_3_months, last_day_previous))
        .values("variant__product__type")
        .annotate(total_sold=Sum("sold_quantity"))
    )
    sales_3m_by_type = {
        item["variant__product__type"]: item["total_sold"] for item in sales_3m_qs
    }

    # 3. Aggregate sales for the last 12 months.
    sales_12_qs = (
        Sale.objects.filter(date__gte=one_year_ago)
        .values("variant__product__type")
        .annotate(total_sold=Sum("sold_quantity"))
    )
    sales_12_by_type = {
        item["variant__product__type"]: item["total_sold"] for item in sales_12_qs
    }

    # 4. Annotate each ProductVariant with its latest inventory.
    latest_snapshot_subquery = (
        InventorySnapshot.objects.filter(product_variant=OuterRef("pk"))
        .order_by("-date")
        .values("inventory_count")[:1]
    )
    variants = ProductVariant.objects.annotate(
        latest_inventory=Coalesce(Subquery(latest_snapshot_subquery), 0)
    )

    # 5. Calculate current stock by type.
    stock_by_type_qs = variants.values("product__type").annotate(
        total_stock=Sum("latest_inventory")
    )
    stock_by_type = {
        item["product__type"]: item["total_stock"] for item in stock_by_type_qs
    }

    # 6. Aggregate items on order by variant type.
    orders_qs = (
        OrderItem.objects.filter(date_expected__gte=first_day_this_month)
        .values("product_variant__product__type")
        .annotate(total_order=Sum("quantity"))
    )
    orders_by_type = {
        item["product_variant__product__type"]: item["total_order"]
        for item in orders_qs
    }

    # 7. Define allowed categories.
    allowed = {
        "gi": "Gi",
        "rg": "Rashguard",
        "dk": "Shorts",
        "ck": "Spats",
        "bt": "Belts",
    }

    # Helper function: Build product breakdown for a given filter expression.
    def get_product_breakdown(filter_expr):
        qs = (
            ProductVariant.objects.annotate(
                latest_inventory=Coalesce(Subquery(latest_snapshot_subquery), 0)
            )
            .filter(filter_expr, sales__date__gte=first_day_last_3_months)
            .distinct()
        )
        products_dict = {}
        for variant in qs:
            key = variant.product_id
            if key not in products_dict:
                products_dict[key] = {
                    "product_id": key,
                    "product_name": variant.product.product_name,
                    "last_month_sales": 0,
                    "sales_3m": 0,
                    "current_stock": 0,
                }
            variant_last_month_sales = variant.sales.filter(
                date__range=(first_day_last_month, last_day_previous)
            ).aggregate(total=Coalesce(Sum("sold_quantity"), 0))["total"]
            variant_3m_sales = variant.sales.filter(
                date__range=(first_day_last_3_months, last_day_previous)
            ).aggregate(total=Coalesce(Sum("sold_quantity"), 0))["total"]
            products_dict[key]["last_month_sales"] += variant_last_month_sales
            products_dict[key]["sales_3m"] += variant_3m_sales
            products_dict[key]["current_stock"] += variant.latest_inventory
        products_list = []
        for prod in products_dict.values():
            if prod["last_month_sales"] > 0:
                products_list.append(
                    {
                        "product_id": prod["product_id"],
                        "product_name": prod["product_name"],
                        "last_month_sales": prod["last_month_sales"],
                        "avg_sales": prod["sales_3m"] / 3,
                        "current_stock": prod["current_stock"],
                    }
                )
        products_list.sort(key=lambda x: x["last_month_sales"], reverse=True)
        return products_list

    # 8. Build category data for allowed types.
    categories = []
    for type_code, label in allowed.items():
        lm_sales = sales_by_type.get(type_code, 0)
        total_12 = sales_12_by_type.get(type_code, 0)
        avg_12 = total_12 / 12.0
        total_3 = sales_3m_by_type.get(type_code, 0)
        avg_3 = total_3 / 3.0
        cat_stock = stock_by_type.get(type_code, 0)
        orders = orders_by_type.get(type_code, 0)
        products_list = get_product_breakdown(Q(type=type_code))
        categories.append(
            {
                "type_code": type_code,
                "label": label,
                "stock": cat_stock,
                "last_month_sales": lm_sales,
                "avg_sales_12": avg_12,
                "avg_sales_3": avg_3,
                "items_on_order": orders,
                "products": products_list,
            }
        )

    # 9. Build category data for "Others" (types not in allowed).
    others_sales_last = sum(
        sales for key, sales in sales_by_type.items() if key not in allowed
    )
    others_sales_12 = sum(
        sales for key, sales in sales_12_by_type.items() if key not in allowed
    )
    others_avg_12 = others_sales_12 / 12.0
    others_sales_3 = sum(
        sales for key, sales in sales_3m_by_type.items() if key not in allowed
    )
    others_avg_3 = others_sales_3 / 3.0
    others_stock = sum(
        stock for key, stock in stock_by_type.items() if key not in allowed
    )
    others_orders = sum(
        orders for key, orders in orders_by_type.items() if key not in allowed
    )
    categories.append(
        {
            "type_code": "others",
            "label": "Others",
            "stock": others_stock,
            "last_month_sales": others_sales_last,
            "avg_sales_12": others_avg_12,
            "avg_sales_3": others_avg_3,
            "items_on_order": others_orders,
            "products": get_product_breakdown(~Q(type__in=list(allowed.keys()))),
        }
    )

    # --- PREVIOUS CODE (Charts, Top-Selling, etc.) ---
    # Normalize today to first of month for chart projections.
    chart_today = datetime.today().replace(day=1)
    next_12_months = [chart_today + relativedelta(months=i) for i in range(13)]

    # Stock Projection Chart Data
    stock_chart_data = {
        "months": [month.strftime("%b %Y") for month in next_12_months],
        "variant_lines": [],
    }
    historic_sales_data = {}
    for v in ProductVariant.objects.all():
        snapshot = (
            InventorySnapshot.objects.filter(product_variant=v)
            .order_by("-date")
            .values("inventory_count")
            .first()
        )
        current_stock = snapshot["inventory_count"] if snapshot else 0
        sales_speed = calculate_variant_sales_speed(v)
        order_items = v.order_items.filter(date_expected__gte=chart_today).values(
            "date_expected", "quantity"
        )
        restocks = {}
        for item in order_items:
            restock_month = item["date_expected"].replace(day=1)
            restocks[restock_month] = restocks.get(restock_month, 0) + item["quantity"]
        stock_levels = [current_stock]
        for i in range(1, 13):
            projected = stock_levels[-1] - sales_speed
            month = (chart_today + relativedelta(months=i)).date()
            if month in restocks:
                projected += restocks[month]
            stock_levels.append(max(projected, 0))
        stock_chart_data["variant_lines"].append(
            {
                "variant_name": v.variant_code,
                "stock_levels": stock_levels,
            }
        )

        sales = (
            v.sales.filter(date__gte=one_year_ago)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_quantity=Sum("sold_quantity"))
            .order_by("month")
        )
        for sale in sales:
            m = sale["month"].strftime("%Y-%m")
            if m not in historic_sales_data:
                historic_sales_data[m] = {}
            historic_sales_data[m][v.variant_code] = sale["total_quantity"]

    sorted_months = sorted(historic_sales_data.keys())
    historic_chart_data = {"months": sorted_months, "datasets": []}
    for v in ProductVariant.objects.all():
        variant_sales = [
            historic_sales_data.get(m, {}).get(v.variant_code, 0) for m in sorted_months
        ]
        historic_chart_data["datasets"].append(
            {
                "label": v.variant_code,
                "data": variant_sales,
            }
        )

    # Top-Selling Analysis (80/20)
    top_selling_variants = ProductVariant.objects.annotate(
        total_sales=Sum("sales__sold_quantity", filter=Q(sales__date__gte=one_year_ago))
    ).order_by("-total_sales")
    total_sales_all_variants = sum(v.total_sales or 0 for v in top_selling_variants)
    cumulative_sales = 0
    top_80_percent_variants = []
    for v in top_selling_variants:
        cumulative_sales += v.total_sales or 0
        top_80_percent_variants.append(v)
        if cumulative_sales >= 0.8 * total_sales_all_variants:
            break

    top_selling_sizes = (
        ProductVariant.objects.filter(size__isnull=False)
        .values("size")
        .annotate(
            total_sales=Sum(
                "sales__sold_quantity", filter=Q(sales__date__gte=one_year_ago)
            )
        )
        .order_by("-total_sales")
    )
    total_sales_sizes = sum((s["total_sales"] or 0) for s in top_selling_sizes)
    top_selling_sizes = [
        {
            "size": s["size"],
            "total_sales": s["total_sales"] or 0,
            "percentage": (
                round(((s["total_sales"] or 0) / total_sales_sizes) * 100, 2)
                if total_sales_sizes > 0
                else 0
            ),
        }
        for s in top_selling_sizes
    ]

    top_selling_colors = (
        ProductVariant.objects.filter(primary_color__isnull=False)
        .values("primary_color")
        .annotate(
            total_sales=Sum(
                "sales__sold_quantity", filter=Q(sales__date__gte=one_year_ago)
            )
        )
        .order_by("-total_sales")
    )

    context = {
        "categories": categories,
        "labels": json.dumps([month.strftime("%b %Y") for month in next_12_months]),
        "stock_levels": json.dumps(
            [
                sum(variant_stock["stock_levels"])
                for variant_stock in stock_chart_data["variant_lines"]
            ]
        ),
        "stacked_bar_data": json.dumps(
            {
                "labels": [month.strftime("%b %Y") for month in next_12_months],
                "datasets": [],  # (Assume you fill this in similarly if needed)
            }
        ),
        "projected_stock_levels": json.dumps(stock_chart_data),
        "historic_chart_data": json.dumps(historic_chart_data),
        "top_selling_variants": top_80_percent_variants,
        "top_selling_sizes": top_selling_sizes,
        "top_selling_colors": top_selling_colors,
    }

    return render(request, "inventory/dashboard.html", context)


def product_list(request):
    # ─── Filter flags ───────────────────────────────────────────────────────────
    show_retired = request.GET.get("show_retired", "false").lower() == "true"
    type_filter = request.GET.get("type_filter", None)
    style_filter = request.GET.get("style_filter", None)
    age_filter = request.GET.get("age_filter", None)
    group_filters = [gid.strip() for gid in request.GET.getlist("group_filter") if gid]
    series_filters = [sid.strip() for sid in request.GET.getlist("series_filter") if sid]
    zero_inventory = request.GET.get("zero_inventory", "false").lower() == "true"

    # ─── Date ranges ────────────────────────────────────────────────────────────
    today = now().date()
    last_12_months = today - timedelta(days=365)
    last_30_days = today - timedelta(days=30)

    # ─── Annotate each variant with its latest snapshot ─────────────────────────
    latest_snapshot = (
        InventorySnapshot.objects.filter(product_variant=OuterRef("pk"))
        .order_by("-date")
        .values("inventory_count")[:1]
    )

    variants_qs = ProductVariant.objects.annotate(
        latest_inventory=Coalesce(Subquery(latest_snapshot), 0)
    )

    # ─── Build product queryset ─────────────────────────────────────────────────
    products_qs = (
        Product.objects.all()
        .prefetch_related(
            Prefetch(
                "variants", queryset=variants_qs, to_attr="variants_with_inventory"
            )
        )
        .annotate(variant_count=Count("variants", distinct=True))
    )

    if type_filter:
        products_qs = products_qs.filter(type=type_filter)

    if style_filter:
        products_qs = products_qs.filter(style=style_filter)

    if age_filter:
        products_qs = products_qs.filter(age=age_filter)

    if group_filters:
        products_qs = products_qs.filter(groups__id__in=group_filters).distinct()

    if series_filters:
        products_qs = products_qs.filter(series__id__in=series_filters).distinct()

    if not show_retired:
        products_qs = products_qs.filter(decommissioned=False)

    products = list(products_qs)

    # ─── Compute per‐product stats ───────────────────────────────────────────────
    SIZE_ORDER = {
        code: idx for idx, (code, _) in enumerate(ProductVariant.SIZE_CHOICES)
    }

    for product in products:
        # sort variants by size
        product.variants_with_inventory.sort(key=lambda v: SIZE_ORDER.get(v.size, 9999))

        # total inventory
        product.total_inventory = sum(
            v.latest_inventory for v in product.variants_with_inventory
        )

        # sales aggregates
        total_sales = 0
        total_sales_value = Decimal("0.00")
        sales_12 = 0
        sales_30 = 0

        for v in product.variants_with_inventory:
            total_sales += v.sales.aggregate(total=Coalesce(Sum("sold_quantity"), 0))[
                "total"
            ]
            total_sales_value += v.sales.aggregate(
                total=Coalesce(Sum("sold_value"), Decimal("0.00"))
            )["total"]
            sales_12 += v.sales.filter(date__gte=last_12_months).aggregate(
                total=Coalesce(Sum("sold_quantity"), 0)
            )["total"]
            sales_30 += v.sales.filter(date__gte=last_30_days).aggregate(
                total=Coalesce(Sum("sold_quantity"), 0)
            )["total"]

        product.total_sales = total_sales
        product.total_sales_value = total_sales_value
        product.sales_last_12_months = sales_12
        product.sales_last_30_days = sales_30
        product.sales_speed_12_months = sales_12 / 12 if sales_12 else 0
        product.sales_speed_30_days = sales_30

        # last order info
        last_item = (
            OrderItem.objects.filter(product_variant__product=product)
            .order_by("-order__order_date")
            .first()
        )

        if last_item:
            order_items = OrderItem.objects.filter(
                product_variant__product=product, order=last_item.order
            )
            cost = order_items.aggregate(
                total_cost=Coalesce(
                    Sum(
                        ExpressionWrapper(
                            F("item_cost_price") * F("quantity"),
                            output_field=DecimalField(),
                        )
                    ),
                    Decimal("0.00"),
                )
            )["total_cost"] or Decimal("0.00")
            product.last_order_cost = cost

            delivered = all(i.date_arrived for i in order_items)
            if delivered:
                product.last_order_date = order_items.first().date_arrived
                product.last_order_label = "Last Order"
            else:
                product.last_order_date = None
                product.last_order_label = "On Order"

            product.last_order_qty = order_items.aggregate(
                total=Coalesce(Sum("quantity"), 0)
            )["total"]
        else:
            product.last_order_cost = Decimal("0.00")
            product.last_order_date = None
            product.last_order_qty = 0
            product.last_order_label = ""

        product.profit = product.total_sales_value - product.last_order_cost

    # ───  Apply zero‐inventory filter if requested ──────────────────────────────
    if zero_inventory:
        products = [p for p in products if p.total_inventory == 0]

    # ─── Prepare context & render ───────────────────────────────────────────────
    view_mode = request.GET.get("view_mode", "card").strip()


    params = []
    if show_retired:
        params.append(("show_retired", "true"))
    if type_filter:
        params.append(("type_filter", type_filter))
    if style_filter:
        params.append(("style_filter", style_filter))
    if age_filter:
        params.append(("age_filter", age_filter))
    for gid in group_filters:
        params.append(("group_filter", gid))
    for sid in series_filters:
        params.append(("series_filter", sid))
    if zero_inventory:
        params.append(("zero_inventory", "true"))

    list_query = urlencode(params + [("view_mode", "list")])
    card_query = urlencode(params + [("view_mode", "card")])

    context = {
        "products": products,
        "show_retired": show_retired,
        "type_filter": type_filter,
        "style_filter": style_filter,
        "age_filter": age_filter,
        "group_filters": group_filters,
        "series_filters": series_filters,
        "zero_inventory": zero_inventory,
        "type_choices": PRODUCT_TYPE_CHOICES,
        "style_choices": PRODUCT_STYLE_CHOICES,
        "age_choices": PRODUCT_AGE_CHOICES,
        "group_choices": Group.objects.all(),
        "series_choices": Series.objects.all(),
        "view_mode": view_mode,
        "list_query": list_query,
        "card_query": card_query,
    }

    # optional groupings (discounted/current/on‐order)
    STYLE_ORDER = {"gi": 0, "ng": 1, "ap": 2, "ac": 3}

    def _style_key(prod):
        return STYLE_ORDER.get(prod.style, 99)

    discounted_products = sorted(
        [p for p in products if getattr(p, "discounted", False)], key=_style_key
    )
    current_products = sorted(
        [
            p
            for p in products
            if not getattr(p, "discounted", False)
            and not getattr(p, "decommissioned", False)
            and p.total_inventory > 0
        ],
        key=_style_key,
    )
    on_order_products = sorted(
        [
            p
            for p in products
            if p.last_order_label == "On Order"
            and p.last_order_qty
            and p.total_inventory == 0
        ],
        key=_style_key,
    )

    context.update(
        {
            "discounted_products": discounted_products,
            "current_products": current_products,
            "on_order_products": on_order_products,
            "discounted_count": len(discounted_products),
            "current_count": len(current_products),
            "on_order_count": len(on_order_products),
            "discounted_stock": sum(p.total_inventory for p in discounted_products),
            "current_stock": sum(p.total_inventory for p in current_products),
            "on_order_stock": sum(p.last_order_qty or 0 for p in on_order_products),
        }
    )

    return render(request, "inventory/product_list.html", context)


def product_detail(request, product_id):
    """
    Render the product detail page.
    Delegates safe stock, variant projection, and sales aggregation to helpers.
    """
    # Fetch product
    product = get_object_or_404(Product, id=product_id)

    # Annotate variants with latest inventory snapshot
    latest_snapshot_sq = (
        InventorySnapshot.objects.filter(product_variant=OuterRef("pk"))
        .order_by("-date")
        .values("inventory_count")[:1]
    )
    variants = (
        ProductVariant.objects.filter(product=product)
        .annotate(
            latest_inventory=Coalesce(
                Subquery(latest_snapshot_sq), Value(0), output_field=IntegerField()
            )
        )
        .prefetch_related("sales", "snapshots", "order_items")
    )

    cache_ttl = 60 * 60  # 1 hour

    # Compute all data via helpers with caching
    safe_stock_key = f"safe_stock_{product_id}"
    safe_stock = cache.get(safe_stock_key)
    if safe_stock is None:
        safe_stock = compute_safe_stock(variants)
        cache.set(safe_stock_key, safe_stock, cache_ttl)

    threshold_value = safe_stock["product_safe_summary"]["avg_speed"] * 2

    variant_proj_key = f"variant_proj_{product_id}"
    variant_proj = cache.get(variant_proj_key)
    if variant_proj is None:
        variant_proj = compute_variant_projection(variants)
        cache.set(variant_proj_key, variant_proj, cache_ttl)

    sales_data = get_product_sales_data(product)

    health_key = f"product_health_{product_id}"
    health = cache.get(health_key)
    if health is None:
        health = compute_product_health(product, variants, _simplify_type)
        cache.set(health_key, health, cache_ttl)

    # ——— ACTUAL DATA FOR INVENTORY CHART ————————
    today = datetime.today().date()
    twelve_months_ago = today - relativedelta(months=12)
    snaps = (
        InventorySnapshot.objects.filter(
            product_variant__product=product, date__gte=twelve_months_ago
        )
        .values("date")
        .annotate(total=Sum("inventory_count"))
        .order_by("date")
    )

    # Format for Chart.js time-series
    actual_data = [
        {"x": row["date"].isoformat(), "y": row["total"]} for row in snaps
    ]

    # Suppose `safe_stock['safe_stock_data']` is a list of dicts from compute_safe_stock
    # each with 'variant_code', 'current_stock', and 'avg_speed'.
    initial = {
        row["variant_code"]: row["current_stock"]
        for row in safe_stock["safe_stock_data"]
    }
    speeds = {
        row["variant_code"]: row["avg_speed"] for row in safe_stock["safe_stock_data"]
    }

    if snaps:
        last_snapshot_date = snaps.last()["date"]
    else:
        # fallback to the start of the 12-month window
        last_snapshot_date = twelve_months_ago

    # Preload all future-order quantities per variant per month using a
    # single grouped query instead of iterating over OrderItems
    future_orders = defaultdict(lambda: defaultdict(int))
    future_qs = (
        OrderItem.objects.filter(
            product_variant__product=product, date_expected__gt=last_snapshot_date
        )
        .annotate(month=TruncMonth("date_expected"))
        .values("product_variant__variant_code", "month")
        .annotate(total_qty=Sum("quantity"))
    )
    for row in future_qs:
        month = row["month"]
        future_orders[month][row["product_variant__variant_code"]] += row["total_qty"]

    # Now simulate month-by-month
    cursor = last_snapshot_date.replace(day=1)
    forecast_data = [{"x": cursor.isoformat(), "y": sum(initial.values())}]

    for i in range(1, 13):
        cursor = cursor + relativedelta(months=1)
        # subtract sales
        for code, speed in speeds.items():
            if initial[code] > 0:
                initial[code] = max(initial[code] - speed, 0)
        # add any restocks arriving that month
        for code, qty in future_orders.get(cursor, {}).items():
            initial[code] = initial.get(code, 0) + qty
        # record total
        running = sum(initial.values())
        forecast_data.append({"x": cursor.isoformat(), "y": running})

    # — Fetch and group all OrderItems for this product —
    all_items = (
        OrderItem.objects.filter(product_variant__product=product)
        .select_related("order")
        .order_by("-order__order_date")
    )
    orders_map = defaultdict(list)
    for item in all_items:
        orders_map[item.order.id].append(item)

    # — Current on-hand inventory across all variants —
    current_inventory = sum(v.latest_inventory for v in variants)

    # — Lifetime sales totals for this product —
    lifetime = Sale.objects.filter(variant__product=product).aggregate(
        sold_qty=Coalesce(Sum("sold_quantity"), 0),
        sold_val=Coalesce(Sum("sold_value"), Decimal("0.00")),
    )
    lifetime_sold_qty = lifetime["sold_qty"]
    lifetime_sold_val = lifetime["sold_val"]

    # — Lifetime cost of every order you’ve placed —
    total_order_cost = sum(i.quantity * i.item_cost_price for i in all_items)
    lifetime_profit = lifetime_sold_val - total_order_cost

    # — Build per-order rows (only date/qty/cost here) —
    prev_orders = []
    for items in orders_map.values():
        ord = items[0].order
        qty_ord = sum(i.quantity for i in items)
        delivered = [i for i in items if i.date_arrived]
        qty_del = sum(i.quantity for i in delivered)
        cost_val = sum(i.quantity * i.item_cost_price for i in items)
        date_ord = ord.order_date
        date_deliv = max((i.date_arrived for i in delivered), default=None)

        prev_orders.append(
            {
                "date_ordered": date_ord,
                "date_delivered": date_deliv,
                "qty_ordered": qty_ord,
                "qty_delivered": qty_del,
                "cost_value": cost_val,
            }
        )

    prev_orders.sort(key=lambda x: x["date_ordered"], reverse=True)

    # Consolidate context in one dictionary so each key appears only once
    context = {
        "product": product,
        **safe_stock,
        **variant_proj,
        **sales_data,
        "actual_data": json.dumps(actual_data),
        "forecast_data": json.dumps(forecast_data),
        "threshold_value": json.dumps(threshold_value),
        "health": health,
        "prev_orders": prev_orders,
        "lifetime_sold_qty": lifetime_sold_qty,
        "lifetime_sold_val": lifetime_sold_val,
        "total_order_cost": total_order_cost,
        "lifetime_profit": lifetime_profit,
        "current_inventory": current_inventory,
    }

    return render(request, "inventory/product_detail.html", context)


def order_list(request):
    # Fetch orders and prefetch related items for efficiency
    orders = (
        Order.objects.all()
        .prefetch_related("order_items")
        .annotate(
            total_value=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("order_items__item_cost_price")
                        * F("order_items__quantity"),
                        output_field=DecimalField(),
                    )
                ),
                Decimal("0.00"),
            )
        )
        .order_by("-order_date")
    )

    # — Build calendar_data for upcoming four months —
    today = date.today()
    first_day_current = today.replace(day=1)
    start_month = first_day_current + relativedelta(months=1)
    calendar_data = []
    for i in range(4):
        month_start = start_month + relativedelta(months=i)
        month_end = month_start + relativedelta(months=1)
        month_label = month_start.strftime("%B %Y")

        incoming_qs = OrderItem.objects.filter(
            date_expected__gte=month_start, date_expected__lt=month_end
        ).select_related("product_variant__product")

        prod_map = {}
        for oi in incoming_qs:
            prod = oi.product_variant.product
            if prod.id not in prod_map:
                prod_map[prod.id] = {"product": prod, "quantity": 0}
            prod_map[prod.id]["quantity"] += oi.quantity

        calendar_data.append(
            {
                "month_label": month_label,
                "events": list(prod_map.values()),
            }
        )

    context = {
        "orders": orders,
        "calendar_data": calendar_data,
    }
    return render(request, "inventory/order_list.html", context)


def order_detail(request, order_id):
    # Fetch the order and its items in one hit
    order = get_object_or_404(Order, id=order_id)
    order_items = order.order_items.select_related("product_variant__product")

    # Group items by product, track per‐product totals
    grouped_items = {}
    for item in order_items:
        product = item.product_variant.product
        if product not in grouped_items:
            grouped_items[product] = {
                "items": [],
                "total_quantity": 0,
                "total_value": Decimal("0.00"),
            }
        grouped_items[product]["items"].append(item)
        grouped_items[product]["total_quantity"] += item.quantity
        grouped_items[product]["total_value"] += item.item_cost_price * item.quantity

    # Overall totals
    aggregates = order_items.aggregate(
        total_value=Coalesce(
            Sum(
                ExpressionWrapper(
                    F("item_cost_price") * F("quantity"),
                    output_field=DecimalField(),
                )
            ),
            Decimal("0.00"),
        ),
        total_items=Coalesce(Sum("quantity"), 0),
    )
    total_value = aggregates["total_value"]
    total_items = aggregates["total_items"]

    context = {
        "order": order,
        "grouped_items": grouped_items,
        "total_value": total_value,
        "total_items": total_items,
    }
    return render(request, "inventory/order_detail.html", context)


# a small helper to keep (date, change) pairs
Event = namedtuple("Event", ["date", "delta"])


def inventory_snapshots(request):
    today = now().date()

    # ——— Category filter setup —————————————————————————————————————————
    selected_type = request.GET.get("type", "all")
    # grab all available categories for the dropdown
    categories = (
        ProductVariant.objects.values_list("product__type", flat=True)
        .distinct()
        .order_by("product__type")
    )

    # base querysets
    snap_qs = InventorySnapshot.objects.filter(date__lte=today)
    sale_qs = Sale.objects.filter(date__lte=today)
    order_qs = OrderItem.objects.filter(date_arrived__isnull=True)

    if selected_type != "all":
        snap_qs = snap_qs.filter(product_variant__product__type=selected_type)
        sale_qs = sale_qs.filter(variant__product__type=selected_type)
        order_qs = order_qs.filter(product_variant__product__type=selected_type)

    # ——— 1) Build actual_data from snapshots ————————————————————————
    snaps = (
        snap_qs.values("date")
        .annotate(total=Sum("inventory_count"))
        .order_by("date")
    )

    actual_data = [
        {"x": row["date"].isoformat(), "y": row["total"]} for row in snaps
    ]

    # If no snapshots exist, ensure we still have arrays
    if not actual_data:
        last_snapshot_date = today.replace(day=1)
        last_inventory = 0
    else:
        last_snapshot_date = date.fromisoformat(actual_data[-1]["x"])
        last_inventory = actual_data[-1]["y"]

    # ——— 2) Compute average monthly sales over past 6 months ————————
    six_mo_ago = today - relativedelta(months=6)
    total_sold = (
        sale_qs.filter(date__gte=six_mo_ago).aggregate(total=Sum("sold_quantity"))[
            "total"
        ]
        or 0
    )
    avg_monthly = (total_sold / 6) if total_sold else 0

    # ——— 3) Build combined “events” dict keyed by date —————————————
    events = defaultdict(float)

    # 3a) Pro-rata drop from last_snapshot_date → 1st of next month
    dim = calendar.monthrange(last_snapshot_date.year, last_snapshot_date.month)[1]
    next1 = last_snapshot_date.replace(day=1) + relativedelta(months=1)
    days_to_n1 = (next1 - last_snapshot_date).days
    daily_rate = avg_monthly / dim if dim else 0
    events[next1] += -daily_rate * days_to_n1

    # 3b) Fixed –avg_monthly drop on each subsequent 1st for 12 months
    cursor = next1
    for _ in range(1, 13):
        cursor = cursor + relativedelta(months=1)
        mo = cursor.replace(day=1)
        events[mo] += -avg_monthly

    # 3c) Restock bumps on their exact date_expected
    for oi in order_qs.filter(date_expected__gt=last_snapshot_date):
        events[oi.date_expected] += oi.quantity

    # ——— 4) Turn events into a sorted forecast_data list ——————————
    forecast_data = [{"x": last_snapshot_date.isoformat(), "y": round(last_inventory)}]
    running = last_inventory

    for dt in sorted(events):
        running += events[dt]
        forecast_data.append({"x": dt.isoformat(), "y": round(max(running, 0))})

    # ———————— COMPUTATIONS FOR SIZES DATA —————————
    # ——— 1) Compute avg monthly sales per size ——————————————
    six_months_ago = today - relativedelta(months=6)
    sales_by_size = (
        sale_qs.filter(date__gte=six_months_ago)
        .values(size=F("variant__size"))
        .annotate(total_sold=Sum("sold_quantity"))
    )
    avg_monthly_by_size = {row["size"]: row["total_sold"] / 6 for row in sales_by_size}

    # ——— 2) Compute sell-through rate and demand score per size ————
    # need stock at last snapshot date
    stock_on_last = (
        snap_qs.filter(date=last_snapshot_date)
        .values(size=F("product_variant__size"))
        .annotate(current_stock=Sum("inventory_count"))
    )
    stock_map = {r["size"]: r["current_stock"] for r in stock_on_last}

    scores = {}
    for size, sold_avg in avg_monthly_by_size.items():
        S = sold_avg * 6  # total sold
        E = stock_map.get(size, 0)
        R = 1.0 if (S + E) == 0 else S / (S + E)
        scores[size] = S * R  # demand score

    # ——— 3) Determine high/low threshold ————————————————
    median_score = statistics.median(scores.values()) if scores else 0
    indicators = {
        size: ("High demand" if score >= median_score else "Low demand")
        for size, score in scores.items()
    }

    # ——— 4) Build the “ideal mix” percentages —————————————————
    total_avg = sum(avg_monthly_by_size.values()) or 1
    ideal_pct = {
        size: (avg_monthly_by_size[size] / total_avg) * 100
        for size in avg_monthly_by_size
    }

    # ——— 5) Prepare datasets for Chart.js ———————————————
    # assign a color per size (pick whatever you like)
    color_map = {
        "XS": "#ef9a9a",
        "S": "#f48fb1",
        "M": "#ce93d8",
        "L": "#90caf9",
        "XL": "#80deea",
        "XXL": "#b0bec5",
    }

    # ——— after computing avg_monthly_by_size, scores, etc. —————
    size_order = ["XS", "S", "M", "L", "XL", "XXL"]

    size_mix = calculate_size_order_mix(category=selected_type, months=6)
    logger.debug(size_mix)

    # ——— 5) Render template —————————————————————————————————————
    return render(
        request,
        "inventory/inventory_snapshots.html",
        {
            "categories": categories,
            "selected_type": selected_type,
            "actual_data": json.dumps(actual_data),
            "forecast_data": json.dumps(forecast_data),
            "size_mix": size_mix,
        },
    )


def returns(request):
    # ——————————————————————————————————————————————
    # 1) Last-12-months Sales vs Returns series
    # ——————————————————————————————————————————————
    today = date.today()
    labels, monthly_sales, monthly_returns = [], [], []

    for i in range(12):
        # compute the start and end of each month
        month_start = (today - relativedelta(months=11 - i)).replace(day=1)
        next_month = month_start + relativedelta(months=1)

        # aggregate sold_value and return_value
        sales_total = (
            Sale.objects.filter(date__gte=month_start, date__lt=next_month).aggregate(
                total=Sum("sold_value")
            )["total"]
            or 0
        )
        returns_total = (
            Sale.objects.filter(date__gte=month_start, date__lt=next_month).aggregate(
                total=Sum("return_value")
            )["total"]
            or 0
        )

        labels.append(month_start.strftime("%b %Y"))
        monthly_sales.append(float(sales_total))
        monthly_returns.append(float(returns_total))

    # ——————————————————————————————————————————————
    # 2) Per-Product return-rate calculations
    #    return_rate = total_return_quantity / total_sold_quantity
    # ——————————————————————————————————————————————
    product_stats = (
        Sale.objects.values("variant__product__id", "variant__product__product_name")
        .annotate(
            total_sold=Sum("sold_quantity"), total_returned=Sum("return_quantity")
        )
        .exclude(total_sold=0)  # avoid division by zero
        .annotate(
            return_rate=ExpressionWrapper(
                F("total_returned") * 1.0 / F("total_sold"), output_field=FloatField()
            )
        )
    )

    # overall average of those per-product rates
    avg_rate = product_stats.aggregate(avg=Avg("return_rate"))["avg"] or 0

    # top 10 products by return_rate
    top_ten = product_stats.order_by("-return_rate")[:10]

    # build list of dicts for the template
    top_products = [
        {
            "id": item["variant__product__id"],
            "name": item["variant__product__product_name"],
            "sold_qty": item["total_sold"],
            "returned_qty": item["total_returned"],
            "return_rate": round(item["return_rate"] * 100, 2),  # as %
        }
        for item in top_ten
    ]

    context = {
        # existing context
        "returns": Sale.objects.filter(return_quantity__gt=0)
        .select_related("variant__product")
        .order_by("-date"),
        "monthly_labels": json.dumps(labels),
        "monthly_sales": json.dumps(monthly_sales),
        "monthly_returns": json.dumps(monthly_returns),
        # new context for return-rate
        "average_return_rate": round(avg_rate * 100, 2),  # e.g. “3.45”
        "top_products": top_products,
    }

    return render(request, "inventory/returns.html", context)
