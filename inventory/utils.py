import calendar
import math
import json

from collections import defaultdict
from datetime import date, datetime
from typing import List, Optional, Sequence, Dict, Any, Iterable
from decimal import Decimal

from dateutil.relativedelta import relativedelta
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
    ExpressionWrapper,
    FloatField,
    Case,
    When,
)
from django.db.models.functions import Coalesce


from .models import Sale, InventorySnapshot, Product, ProductVariant, OrderItem


# Create a mapping from size code to its order index.
SIZE_ORDER = {
    code: index for index, (code, label) in enumerate(ProductVariant.SIZE_CHOICES)
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


def calculate_size_order_mix(
    *,
    category: Optional[str] = None,
    months: int = 6,
    recency_weights: Optional[Sequence[float]] = None,
    today: date = None
) -> List[Dict[str, Any]]:
    """
    Returns an ordered list (XS → XXL) of dicts with:
      - size
      - avg_monthly (weighted)
      - ending_stock
      - sell_through
      - demand_score
      - ideal_pct  (sums to ~100)
    Filters all queries to the given `category` (type code).
    """

    # 0) Setup
    today = today or date.today()
    # uniform weights if none provided
    if recency_weights is None or len(recency_weights) != months:
        recency_weights = [1.0 / months] * months

    # 1) Base querysets, optionally filtered by category
    sale_qs = Sale.objects.filter(date__lte=today)
    snap_qs = InventorySnapshot.objects.filter(date__lte=today)
    if category and category != "all":
        sale_qs = sale_qs.filter(variant__product__type=category)
        snap_qs = snap_qs.filter(product_variant__product__type=category)

    # 2) Compute weighted total sales per size over past `months`
    weighted_sales: Dict[str, float] = defaultdict(float)
    for idx in range(months):
        weight = recency_weights[idx]
        month_start = today.replace(day=1) - relativedelta(months=idx)
        # end of that month:
        dim = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=dim)
        # sum sold per size in that slice
        monthly = (
            sale_qs.filter(date__gte=month_start, date__lte=month_end)
            .values(size=F("variant__size"))
            .annotate(qty=Sum("sold_quantity"))
        )
        for row in monthly:
            weighted_sales[row["size"]] += row["qty"] * weight

    # 3) Determine the last snapshot date (overall) and ending stock per size
    last_snap_date = snap_qs.order_by("-date").values_list("date", flat=True).first()
    ending_stock_map: Dict[str, int] = {}
    if last_snap_date:
        ending = (
            snap_qs.filter(date=last_snap_date)
            .values(size=F("product_variant__size"))
            .annotate(onhand=Sum("inventory_count"))
        )
        for row in ending:
            ending_stock_map[row["size"]] = row["onhand"]

    # 4) Compute metrics per size
    demand_scores: Dict[str, float] = {}
    for size, avg in weighted_sales.items():
        E = ending_stock_map.get(size, 0)
        S = avg
        # sell-through fraction
        R = 1.0 if (S + E) == 0 else (S / (S + E))
        score = S * R
        demand_scores[size] = score

    # 5) Normalize into percentages
    total_score = sum(demand_scores.values()) or 1.0
    ideal_pct = {
        size: (score / total_score) * 100 for size, score in demand_scores.items()
    }

    # 6) Build result in fixed XS→XXL order
    size_order = ["XS", "S", "M", "L", "XL", "XXL"]
    result = []
    for sz in size_order:
        result.append(
            {
                "size": sz,
                "avg_monthly": round(weighted_sales.get(sz, 0), 1),
                "ending_stock": ending_stock_map.get(sz, 0),
                "sell_through": round(
                    (
                        1.0
                        if (weighted_sales.get(sz, 0) + ending_stock_map.get(sz, 0))
                        == 0
                        else weighted_sales.get(sz, 0)
                        / (weighted_sales.get(sz, 0) + ending_stock_map.get(sz, 0))
                    ),
                    2,
                ),
                "demand_score": round(demand_scores.get(sz, 0), 1),
                "ideal_pct": round(ideal_pct.get(sz, 0), 1),
            }
        )
    return result


def compute_safe_stock(variants):
    """
    Compute safe stock data and product-level summary for a list of variants.
    Returns (safe_stock_data, product_safe_summary).
    """
    safe_stock_data = []
    # Determine date thresholds
    today = datetime.today()
    current_month = today.replace(day=1)
    twelve_months_ago = current_month - relativedelta(months=12)
    six_months_ago = current_month - relativedelta(months=6)
    three_months_ago = current_month - relativedelta(months=3)

    for v in variants:
        current = v.latest_inventory
        sold_12 = v.sales.filter(date__gte=twelve_months_ago).aggregate(
            total=Coalesce(Sum("sold_quantity"), Value(0), output_field=IntegerField())
        )["total"]
        sold_6 = v.sales.filter(date__gte=six_months_ago).aggregate(
            total=Coalesce(Sum("sold_quantity"), Value(0), output_field=IntegerField())
        )["total"]
        sold_3 = v.sales.filter(date__gte=three_months_ago).aggregate(
            total=Coalesce(Sum("sold_quantity"), Value(0), output_field=IntegerField())
        )["total"]

        avg_12 = sold_12 / 12.0
        avg_6 = sold_6 / 6.0
        avg_3 = sold_3 / 3.0
        avg_speed = (avg_12 + avg_6 + avg_3) / 3.0

        min_threshold = avg_12 * 2
        ideal_level = avg_12 * 6
        restock_qty = ideal_level  # requirement for 6 months

        if avg_3 > avg_speed:
            trend = "up"
        elif avg_3 < avg_speed:
            trend = "down"
        else:
            trend = "flat"

        safe_stock_data.append(
            {
                "variant_code": v.variant_code,
                "variant_size": v.size,
                "current_stock": current,
                "avg_speed": round(avg_speed, 1),
                "min_threshold": math.ceil(min_threshold),
                "restock_qty": math.ceil(restock_qty),
                "trend": trend,
            }
        )

    # Sort by size order
    safe_stock_data.sort(key=lambda x: SIZE_ORDER.get(x["variant_size"], 9999))

    # Product-level summary (exclude zero-speed variants)
    filtered = [r for r in safe_stock_data if r["avg_speed"] > 0]
    product_safe_summary = {
        "total_current_stock": sum(r["current_stock"] for r in filtered),
        "avg_speed": round(sum(r["avg_speed"] for r in filtered), 1) if filtered else 0,
        "total_restock_needed": math.ceil(sum(r["restock_qty"] for r in filtered)),
    }

    return {
        "safe_stock_data": safe_stock_data,
        "product_safe_summary": product_safe_summary,
    }


def compute_variant_projection(variants):
    """
    Compute variant-level stock projection data for Chart.js.
    Returns dict with key 'stock_chart_data' (a JSON string).
    """
    # 1) Define your date boundaries here
    today = datetime.today()
    current_month = today.replace(day=1)
    six_months_ago = current_month - relativedelta(months=6)

    # 2) Build your 12-month projection exactly as on inventory page
    next_12 = [current_month + relativedelta(months=i) for i in range(13)]
    stock_chart_data = {
        "months": [m.strftime("%Y-%m") for m in next_12],
        "variant_lines": [],
    }
    for v in variants:
        curr = v.latest_inventory
        sold_6 = v.sales.filter(date__gte=six_months_ago).aggregate(
            total=Coalesce(Sum("sold_quantity"), Value(0), output_field=IntegerField())
        )["total"]
        speed = sold_6 / 6.0

        # collect future restocks
        restocks = {}
        for oi in v.order_items.filter(date_expected__gte=current_month):
            mon = oi.date_expected.replace(day=1)
            restocks[mon] = restocks.get(mon, 0) + oi.quantity

        # simulate month-by-month
        levels = [curr]
        for j in range(1, 13):
            lvl = levels[-1] - speed
            dt = (current_month + relativedelta(months=j)).date()
            lvl += restocks.get(dt, 0)
            levels.append(max(lvl, 0))

        stock_chart_data["variant_lines"].append(
            {
                "variant_name": v.variant_code,
                "stock_levels": levels,
            }
        )

    return {
        "stock_chart_data": json.dumps(stock_chart_data),
    }


def compute_sales_aggregates(product):
    """
    Compute sales aggregates and price info for a product.
    Returns dict with 'avg_sale_price', 'total_sold_qty', 'total_sold_value', 'retail_price'.
    """
    variants = ProductVariant.objects.filter(product=product)
    sale_agg = Sale.objects.filter(variant__in=variants).aggregate(
        total_qty=Coalesce(Sum("sold_quantity"), Value(0), output_field=IntegerField()),
        total_val=Coalesce(Sum("sold_value"), Value(0), output_field=DecimalField()),
    )
    avg_sale_price = (
        round(sale_agg["total_val"] / sale_agg["total_qty"], 2)
        if sale_agg["total_qty"]
        else 0
    )

    # Ensure retail_price is numeric
    from decimal import Decimal

    retail_price = (
        product.retail_price if product.retail_price is not None else Decimal("0.00")
    )

    # Calculate discount percentage safely
    if retail_price > 0:
        discount_pct = round(
            (retail_price - Decimal(avg_sale_price)) / retail_price * 100, 0
        )
    else:
        discount_pct = 0

    return {
        "avg_sale_price": avg_sale_price,
        "total_sold_qty": sale_agg["total_qty"],
        "total_sold_value": sale_agg["total_val"],
        "retail_price": retail_price,
        "discount_pct": discount_pct,
    }


def get_product_sales_data(
    product: Product, start_date: Optional[date] = None, end_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Returns sales & order metrics for a single product:
      - total_qty:     total units sold
      - total_value:   total revenue from those sales
      - avg_price:     total_value / total_qty (0 if none)
      - on_order_qty:  units currently on order (date_expected >= today)
      - discount_pct:  percent off retail_price vs avg_price
    """
    # 1) Sales aggregates
    qs = Sale.objects.filter(variant__product=product)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)

    agg = qs.aggregate(
        total_qty=Coalesce(Sum("sold_quantity"), Value(0), output_field=IntegerField()),
        total_value=Coalesce(Sum("sold_value"), Value(0), output_field=DecimalField()),
    )
    total_qty = agg["total_qty"]
    total_value = agg["total_value"]
    avg_price = (total_value / total_qty) if total_qty else Decimal("0.00")
    avg_price = round(avg_price, 2)

    # 2) On-order quantity
    today = date.today()
    on_order = OrderItem.objects.filter(
        product_variant__product=product, date_expected__gte=today
    ).aggregate(qty=Coalesce(Sum("quantity"), Value(0), output_field=IntegerField()))[
        "qty"
    ]

    # 3) Discount percentage
    retail = product.retail_price or Decimal("0.00")
    if retail > 0:
        discount_pct = round((retail - avg_price) / retail * 100, 0)
    else:
        discount_pct = 0

    return {
        "total_qty": total_qty,
        "total_value": total_value,
        "avg_price": avg_price,
        "on_order_qty": on_order,
        "discount_pct": discount_pct,
    }


def get_products_sales_data(
    products: Iterable[Product],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Batch version: returns a dict mapping product.id → its sales_data dict.
    """
    return {
        p.id: get_product_sales_data(p, start_date=start_date, end_date=end_date)
        for p in products
    }


def calculate_estimated_inventory_sales_value(variants, _simplify_type):
    """
    Given a queryset of ProductVariant annotated with `latest_inventory`,
    returns the Decimal total of (stock × avg selling price), where:
      - avg selling price per variant = total revenue / total qty sold
      - fallback is the avg price for the variant’s category
    `simplify_type` is your function to bucket a type_code into a category key.
    """
    # 1) Per‐variant stats
    stats = Sale.objects.values("variant").annotate(
        total_revenue=Sum("sold_value"), total_qty=Sum("sold_quantity")
    )
    avg_price_map = {
        s["variant"]: s["total_revenue"] / s["total_qty"]
        for s in stats
        if s["total_qty"]
    }

    # 2) Category‐level fallback
    cat_stats = (
        Sale.objects.select_related("variant__product")
        .annotate(cat=F("variant__product__type"))
        .values("cat")
        .annotate(total_revenue=Sum("sold_value"), total_qty=Sum("sold_quantity"))
    )
    category_avg = {
        _simplify_type(s["cat"]): s["total_revenue"] / s["total_qty"]
        for s in cat_stats
        if s["total_qty"]
    }

    # 3) Sum up
    total = Decimal("0")
    for v in variants:
        unit_avg = avg_price_map.get(v.id)
        if unit_avg is None:
            unit_avg = category_avg.get(_simplify_type(v.product.type), Decimal("0"))
        total += Decimal(v.latest_inventory) * Decimal(unit_avg)
    return total


def calculate_on_paper_inventory_value(variants):
    """
    Returns: Decimal total of (stock × product.retail_price), i.e.
    maximum theoretical value if sold at 100% retail.
    """
    agg = variants.aggregate(
        total=Sum(
            ExpressionWrapper(
                F("latest_inventory") * F("product__retail_price"),
                output_field=DecimalField(),
            )
        )
    )["total"]
    return agg or Decimal("0")


# Define your “core” sizes for each category
CORE_SIZES = {
    "gi": ["A1", "A2", "F1", "F2"],
    "ng": ["S", "M", "L"],  # nogi / rashguard / shorts share cores
    "rg": ["S", "M", "L"],
    "dk": ["S", "M", "L"],
}


def compute_inventory_health_scores(variants, _simplify_type):
    """
    Given a queryset of ProductVariant annotated with `latest_inventory`,
    returns a dict mapping variant.id → int health_score.

    Components of the score (higher is “healthier”):
      1) Sell‐through rate vs category avg (3 / 2 / 1 points)
      2) Core‐size in stock?             (2 or 0 points)
      3) Recency of last restock (months) (2 / 1 / 0 points)
      4) Time since first arrival (days)  (1 or 0 points)
    """
    today = date.today()
    six_months_ago = today - relativedelta(months=6)

    # 1) Total sold per variant over last 6m
    sold_qs = (
        Sale.objects.filter(variant__in=variants, date__gte=six_months_ago)
        .values("variant")
        .annotate(total_qty=Sum("sold_quantity"))
    )
    sold_map = {s["variant"]: s["total_qty"] for s in sold_qs}

    # 2) Build category‐level averages
    #    count how many variants in each category
    cat_counts = defaultdict(int)
    for v in variants:
        cat_counts[_simplify_type(v.product.type or "")] += 1

    #    sum sold by category
    cat_sold = defaultdict(int)
    for vid, qty in sold_map.items():
        # find that variant’s type
        try:
            v = next(x for x in variants if x.id == vid)
            cat = _simplify_type(v.product.type or "")
        except StopIteration:
            continue
        cat_sold[cat] += qty

    cat_avg = {
        cat: (cat_sold[cat] / cat_counts[cat])
        for cat in cat_counts
        if cat_counts[cat] > 0
    }

    # 3) Compute a score for each variant
    scores = {}
    for v in variants:
        vid = v.id
        cat = _simplify_type(v.product.type or "")

        # — Sell‐through rate relative score (3/2/1)
        sold = sold_map.get(vid, 0)
        avg_sold = cat_avg.get(cat, 1)
        rel_str = sold / avg_sold if avg_sold else 0
        if rel_str >= 1.2:
            str_score = 3
        elif rel_str >= 0.8:
            str_score = 2
        else:
            str_score = 1

        # — Core‐size availability (2 / 0)
        core_sizes = CORE_SIZES.get(cat, [])
        has_core = v.size in core_sizes and v.latest_inventory > 0
        core_score = 2 if has_core else 0

        # — Months since last restock (2 / 1 / 0)
        last_arrival = (
            OrderItem.objects.filter(product_variant=v, date_arrived__isnull=False)
            .order_by("-date_arrived")
            .values_list("date_arrived", flat=True)
            .first()
        )
        if last_arrival:
            months_since = (today.year - last_arrival.year) * 12 + (
                today.month - last_arrival.month
            )
        else:
            months_since = 13
        if months_since < 6:
            restock_score = 2
        elif months_since < 12:
            restock_score = 1
        else:
            restock_score = 0

        # — Days since first arrival (1 / 0)
        first_arrival = (
            OrderItem.objects.filter(product_variant=v, date_arrived__isnull=False)
            .order_by("date_arrived")
            .values_list("date_arrived", flat=True)
            .first()
        )
        days_in_stock = (today - first_arrival).days if first_arrival else 366
        days_score = 1 if days_in_stock < 365 else 0

        # — Total health score
        scores[vid] = str_score + core_score + restock_score + days_score

    return scores


def get_product_health_metrics(variants, _simplify_type):
    """
    Given a ProductVariant queryset annotated with `latest_inventory`:
      - returns a dict of metrics:
        - score            : overall weighted‐average health (1–8)
        - sales_score      : sell‐through sub‐score (1–3)
        - restock_count    : how many times we've restocked in the last year
        - months_since_restock : int months since last restock
        - days_in_stock    : days since first arrival
        - needs_restock    : True if months_since_restock > 6
    """
    today = date.today()
    one_year_ago = today - relativedelta(years=1)

    # 1) build the per‐variant health scores we already had
    raw_scores = compute_inventory_health_scores(variants, _simplify_type)

    # 2) weighted‐average overall score
    total_inv = sum(v.latest_inventory for v in variants)
    if total_inv:
        overall = (
            sum(raw_scores.get(v.id, 0) * v.latest_inventory for v in variants)
            / total_inv
        )
    else:
        overall = sum(raw_scores.values()) / len(raw_scores) if raw_scores else 0

    # 3) isolate the “sell‐through” sub‐score (1–3) for the whole product:
    #    average the individual variant sub‐scores weighted by inventory
    #    (we assume compute_inventory_health_scores gave 1–3 for the STR component)
    #    In our implementation, STR points are the first component, so we can
    #    re-run that logic here or decode them out of raw_scores—simplest is to
    #    call a thin wrapper:
    def calc_sales_subscore(v):
        # re‐compute just the STR portion for variant v
        # (you can also change compute_inventory_health_scores to return per‐component)
        # For brevity, let’s ask a mini‐helper:
        sold = (
            Sale.objects.filter(variant=v, date__gte=one_year_ago).aggregate(
                q=Sum("sold_quantity")
            )["q"]
            or 0
        )
        # category avg:
        cat_qs = Sale.objects.filter(
            variant__product__type=v.product.type, date__gte=one_year_ago
        ).aggregate(tot_rev=Sum("sold_value"), tot_qty=Sum("sold_quantity"))
        avg_sold = (cat_qs["tot_rev"] / cat_qs["tot_qty"]) if cat_qs["tot_qty"] else 1
        rel_str = sold / avg_sold if avg_sold else 0
        if rel_str >= 1.2:
            return 3
        if rel_str >= 0.8:
            return 2
        return 1

    sales_weighted = (
        sum(calc_sales_subscore(v) * v.latest_inventory for v in variants) / total_inv
        if total_inv
        else 0
    )

    # 4) restock stats
    arrivals = OrderItem.objects.filter(
        product_variant__in=variants,
        date_arrived__isnull=False,
        date_arrived__gte=one_year_ago,
    )
    restock_count = arrivals.count()
    last_arr = arrivals.order_by("-date_arrived").first()
    if last_arr:
        delta = relativedelta(today, last_arr.date_arrived)
        months_since = delta.years * 12 + delta.months
    else:
        months_since = 999

    # 5) time in stock
    first_arrival = (
        OrderItem.objects.filter(
            product_variant__in=variants, date_arrived__isnull=False
        )
        .order_by("date_arrived")
        .first()
    )
    days_in = (today - first_arrival.date_arrived).days if first_arrival else 999

    return {
        "score": float(round(overall, 1)),
        "sales_score": float(round(sales_weighted, 1)),
        "restock_count": restock_count,
        "months_since_restock": months_since,
        "days_in_stock": days_in,
        "needs_restock": months_since > 6,
    }


def calculate_dynamic_product_score(variants, simplify_type):
    """
    Given a queryset of ProductVariant annotated with `latest_inventory`,
    returns a float score (0–10) for the product overall.
    """
    today = date.today()
    six_mo_ago = today - relativedelta(months=6)

    # 1) Gather sold qty per variant (last 6 mo)
    sold_qs = (
        Sale.objects.filter(variant__in=variants, date__gte=six_mo_ago)
        .values("variant")
        .annotate(qty=Sum("sold_quantity"))
    )
    sold_map = {s["variant"]: s["qty"] for s in sold_qs}
    total_sold = sum(sold_map.values())

    # 2) Calculate total_available (stock + sold), as Decimal
    total_stock = sum(v.latest_inventory for v in variants)
    total_available = Decimal(total_stock) + Decimal(total_sold)

    # 3) Category-average sell-through rate (Decimal)
    if total_available > 0:
        avg_rate = Decimal(total_sold) / total_available
    else:
        avg_rate = Decimal("0")

    # first & last arrival dates
    arrivals = OrderItem.objects.filter(
        product_variant__in=variants, date_arrived__isnull=False
    ).order_by("date_arrived")
    if arrivals.exists():
        first_arr = arrivals.first().date_arrived
        last_arr = arrivals.last().date_arrived
    else:
        first_arr = last_arr = today

    days_in_market = (today - first_arr).days
    months_since_restock = (today.year - last_arr.year) * 12 + (
        today.month - last_arr.month
    )

    percent_remaining = (
        (Decimal(total_stock) / total_available)
        if total_available > 0
        else Decimal("1")
    )

    has_core = any(
        v.latest_inventory > 0
        and v.size in CORE_SIZES.get(simplify_type(v.product.type or ""), [])
        for v in variants
    )

    # 4) Start at 5
    score = Decimal("5")

    # — product-level sell rate vs avg_rate
    if total_available > 0:
        prod_rate = Decimal(total_sold) / total_available
    else:
        prod_rate = Decimal("0")

    if prod_rate >= avg_rate * Decimal("1.2"):
        score += 2
    elif prod_rate >= avg_rate * Decimal("0.8"):
        score += 1
    else:
        score -= 1

    # — core-stock bonus/penalty
    if has_core and days_in_market <= 180:
        score += 1
    if has_core and days_in_market > 180 and prod_rate < avg_rate * Decimal("0.8"):
        score -= 2

    # — percent remaining
    if percent_remaining <= Decimal("0.1"):
        score += 2
    elif percent_remaining >= Decimal("0.5") and not has_core:
        score -= 1

    # — restock recency
    if months_since_restock <= 1:
        score += 1
    if months_since_restock > 12:
        score -= 2

    # — cap
    score = max(Decimal("0"), min(score, Decimal("10")))

    return float(score)


CORE_SIZES = {
    "gi": ["A1", "A2", "F1", "F2"],
    "rg": ["S", "M", "L"],
    "dk": ["S", "M", "L"],
    "other": ["S", "M", "L"],
}


def normalize(value, best, worst):
    if best == worst:
        return 100
    pct = (value - worst) / (best - worst)
    return max(0, min(100, pct * 100))


def compute_product_health(product, variants, simplify_type):
    """
    Returns a dict of sub-scores and the overall 0–100 health index.
    `variants` must be annotated with .latest_inventory
    and have .size, .type, and .product__retail_price if you include margin.
    """
    today = date.today()
    # --- 1. SALES VELOCITY (last 3 mo) ---
    three_mo_ago = today - relativedelta(months=3)
    sold_qs = (
        Sale.objects.filter(variant__in=variants, date__gte=three_mo_ago)
        .values("variant")
        .annotate(q=Sum("sold_quantity"))
    )
    sold_map = {s["variant"]: s["q"] for s in sold_qs}
    total_sold = sum(sold_map.values())
    days = (today - three_mo_ago).days or 1
    avg_daily = total_sold / days
    # category avg daily
    cat_daily_map = {}
    cat_totals = {}
    for v in variants:
        cat = simplify_type(v.product.type)
        cat_totals.setdefault(cat, []).append(sold_map.get(v.id, 0))
    # flatten to average per variant, then per day
    cat_avg_daily = {
        cat: (sum(vals) / (len(vals) * days)) if vals else 0
        for cat, vals in cat_totals.items()
    }
    sv = normalize(
        avg_daily,
        best=2 * cat_avg_daily.get(simplify_type(variants[0].product.type), 1),
        worst=0,
    )

    # --- 2. SELL-THROUGH RATE (last 6 mo) ---
    six_mo_ago = today - relativedelta(months=6)
    sold6 = (
        Sale.objects.filter(variant__in=variants, date__gte=six_mo_ago).aggregate(
            s=Sum("sold_quantity")
        )["s"]
        or 0
    )
    # assume “available” = sold + current stock
    stock6 = sum(v.latest_inventory for v in variants)
    avail6 = sold6 + stock6 or 1
    strate = sold6 / avail6
    str_sc = normalize(strate, best=0.8, worst=0.2)

    # --- 3. STOCK COVERAGE DAYS ---
    cov_days = (stock6 / (sold6 / days * 2)) if sold6 else 90
    cd_sc = normalize(cov_days, best=14, worst=90)

    # --- 4. STOCK AGE (days since first arrival) ---
    arrivals = OrderItem.objects.filter(
        product_variant__in=variants, date_arrived__isnull=False
    ).order_by("date_arrived")
    first = arrivals.first().date_arrived if arrivals.exists() else today
    age = (today - first).days
    age_sc = normalize(age, best=0, worst=365)

    # --- 5. CORE VARIANT COVERAGE (%) ---
    core_sizes = CORE_SIZES.get(simplify_type(variants[0].product.type), [])
    core_in_stock = sum(
        1 for v in variants if v.size in core_sizes and v.latest_inventory > 0
    )
    core_pct = (core_in_stock / len(core_sizes)) if core_sizes else 0
    core_sc = normalize(core_pct, best=1, worst=0)

    # --- 6. RESTOCK FREQUENCY (last 12 mo) ---
    year_ago = today - relativedelta(months=12)
    restocks = (
        OrderItem.objects.filter(
            product_variant__in=variants, date_arrived__gte=year_ago
        )
        .values("date_arrived")
        .distinct()
        .count()
    )
    rs_sc = normalize(restocks, best=12, worst=0)

    # --- 7. RETURN RATE (last 6 mo) ---
    returned = (
        Sale.objects.filter(variant__in=variants, date__gte=six_mo_ago).aggregate(
            r=Sum("return_quantity")
        )["r"]
        or 0
    )
    rrate = returned / sold6 if sold6 else 0
    rr_sc = 100 - normalize(rrate, best=0, worst=0.3)

    # --- 8. MARGIN (%) optional ---
    # avg_sale_price = ...  # pull from your data
    # avg_cost_price = ...
    # margin_pct = (avg_sale_price - avg_cost_price) / avg_sale_price
    # m_sc = normalize(margin_pct, best=0.6, worst=0)

    # --- Weighted aggregate ---
    weights = {
        "sv": 0.25,
        "str": 0.20,
        "cd": 0.15,
        "age": 0.10,
        "core": 0.10,
        "rs": 0.10,
        "rr": 0.05,
        # 'm':    0.05,
    }
    overall = (
        sv * weights["sv"]
        + str_sc * weights["str"]
        + cd_sc * weights["cd"]
        + age_sc * weights["age"]
        + core_sc * weights["core"]
        + rs_sc * weights["rs"]
        + rr_sc * weights["rr"]
        # + m_sc * weights['m']
    )

    return {
        "subscores": {
            "sales_velocity": round(sv, 1),
            "sell_through": round(str_sc, 1),
            "coverage_days": round(cd_sc, 1),
            "stock_age": round(age_sc, 1),
            "core_coverage": round(core_sc, 1),
            "restocks": round(rs_sc, 1),
            "return_rate": round(rr_sc, 1),
            # 'margin': round(m_sc,1),
        },
        "overall_score": round(overall, 1),
    }


def get_low_stock_products(queryset):
    """Return items with less than 3 months of stock remaining."""

    today = date.today()
    six_months_ago = today - relativedelta(months=6)

    if queryset.model == ProductVariant:
        variant_qs = queryset
        return_products = False
    elif queryset.model == Product:
        variant_qs = ProductVariant.objects.filter(product__in=queryset)
        return_products = True
    else:
        raise ValueError("Queryset must be for Product or ProductVariant")

    latest_inv = (
        InventorySnapshot.objects.filter(product_variant=OuterRef("pk"))
        .order_by("-date")
        .values("inventory_count")[:1]
    )

    variant_qs = variant_qs.annotate(
        latest_inventory=Coalesce(Subquery(latest_inv), Value(0)),
        sold_6=Coalesce(
            Sum(
                "sales__sold_quantity",
                filter=Q(sales__date__gte=six_months_ago),
            ),
            Value(0),
            output_field=IntegerField(),
        ),
    ).annotate(
        avg_monthly_sales=ExpressionWrapper(
            F("sold_6") / Value(6.0), output_field=FloatField()
        )
    ).annotate(
        months_left=Case(
            When(
                avg_monthly_sales__gt=0,
                then=ExpressionWrapper(
                    F("latest_inventory") / F("avg_monthly_sales"),
                    output_field=FloatField(),
                ),
            ),
            default=Value(None),
            output_field=FloatField(),
        )
    )

    low_stock_variants = variant_qs.filter(
        avg_monthly_sales__gt=0, months_left__lt=3
    )

    if return_products:
        return queryset.filter(variants__in=low_stock_variants).distinct()
    return low_stock_variants
