import calendar
import math
import json

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence, Dict, Any, Iterable
from decimal import Decimal, ROUND_HALF_UP

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
    Min,
)
from django.db.models.functions import Coalesce


from .models import (
    Sale,
    InventorySnapshot,
    Product,
    ProductVariant,
    OrderItem,
    Group,
    RestockSetting,
)


def _banded_score(value: Optional[Decimal], bands: list[Decimal]) -> int:
    """Return 2/1/0 based on where ``value`` sits against ascending bands."""

    if value is None:
        return 1

    if value <= bands[0]:
        return 2
    if value <= bands[1]:
        return 1
    return 0


def compute_product_confidence(
    *,
    months_to_sell_out: Optional[Decimal],
    sales_speed: Optional[Decimal],
    return_rate: Optional[Decimal],
    discount_pct: Optional[Decimal],
    margin_pct: Optional[Decimal],
    baselines: dict[str, Optional[Decimal]],
    is_core: bool,
    restock_lead_months: Optional[int],
    sales_volume: int,
    inventory_units: int,
    gift_rate: Optional[Decimal],
) -> dict[str, Any]:
    """Compute Low/Medium/High confidence plus advisories for a product.

    The scorer combines sell-through horizon (stock coverage), sales speed vs
    store average, returns rate, discounting, and gross margin. Each factor is
    converted to a 0–2 sub-score, then weighted differently for core vs
    seasonal products. Missing data yields a neutral sub-score (1) to avoid
    over-penalising sparse items.
    """

    avg_return = baselines.get("avg_return_rate")
    avg_discount = baselines.get("avg_discount_pct")
    avg_margin = baselines.get("avg_margin_pct")
    avg_sales_speed = baselines.get("avg_sales_speed")

    # Sell-through: faster is better. Core products are allowed deeper stock
    # coverage so they can avoid stock-outs, while seasonal/one-off items need
    # quicker sell-through. Core items with up to ~12 months of coverage should
    # still be rewarded so they can confidently maintain supply.
    if is_core:
        coverage_score = _banded_score(
            months_to_sell_out, [Decimal("12"), Decimal("18")]
        )
    else:
        coverage_score = _banded_score(
            months_to_sell_out, [Decimal("5"), Decimal("9")]
        )

    # Sales speed vs store average: higher than average is better.
    if sales_speed is None or avg_sales_speed in (None, Decimal("0")):
        sales_speed_score = 1
    else:
        fast = avg_sales_speed * Decimal("1.2")
        ok = avg_sales_speed * Decimal("0.8")
        if sales_speed >= fast:
            sales_speed_score = 2
        elif sales_speed >= ok:
            sales_speed_score = 1
        else:
            sales_speed_score = 0

    # Returns: lower than average is good
    if return_rate is None or avg_return in (None, Decimal("0")):
        return_score = 1
    else:
        threshold_low = avg_return * Decimal("0.9")
        threshold_high = avg_return * Decimal("1.1")
        return_score = _banded_score(return_rate, [threshold_low, threshold_high])

    # Discounting: lower than shop average is good. Treat "at or below average"
    # as the strongest signal so consistently full-price items are rewarded.
    if discount_pct is None or avg_discount is None:
        discount_score = 1
    else:
        at_or_better = avg_discount
        modestly_higher = avg_discount + Decimal("5")
        discount_score = _banded_score(discount_pct, [at_or_better, modestly_higher])

    # Margin: higher than average is good
    if margin_pct is None or avg_margin is None:
        margin_score = 1
    else:
        strong = avg_margin + Decimal("5")
        ok = avg_margin - Decimal("5")
        if margin_pct >= strong:
            margin_score = 2
        elif margin_pct >= ok:
            margin_score = 1
        else:
            margin_score = 0

    severe_signals: list[str] = []
    margin_advisory: Optional[str] = None

    if months_to_sell_out is not None and months_to_sell_out >= Decimal("15"):
        severe_signals.append("Projected to take well over a year to sell through.")

    if return_rate is not None and avg_return not in (None, Decimal("0")):
        if return_rate >= avg_return * Decimal("1.5"):
            severe_signals.append("Return rate is far above the store average.")

    if discount_pct is not None:
        if discount_pct >= Decimal("50"):
            severe_signals.append("Clearance-level discounting is required to sell this item.")
        elif avg_discount is not None and discount_pct >= avg_discount + Decimal("25"):
            severe_signals.append("Discounting is dramatically above the store average.")

    if margin_pct is not None and avg_margin is not None:
        margin_context = (
            " (margin may be impacted by gifted units)"
            if gift_rate is not None and gift_rate >= Decimal("0.1")
            else ""
        )
        if margin_pct <= avg_margin - Decimal("15"):
            severe_signals.append(
                f"Gross margin is substantially below the store average{margin_context}."
            )
        elif margin_pct < avg_margin - Decimal("5"):
            margin_advisory = f"Low gross margin versus store average{margin_context}."

    weights = (
        {
            "coverage": Decimal("0.25"),
            "sales_speed": Decimal("0.2"),
            "returns": Decimal("0.2"),
            "discount": Decimal("0.15"),
            "margin": Decimal("0.2"),
        }
        if is_core
        else {
            "coverage": Decimal("0.3"),
            "sales_speed": Decimal("0.25"),
            "returns": Decimal("0.15"),
            "discount": Decimal("0.2"),
            "margin": Decimal("0.1"),
        }
    )

    weighted_sum = (
        coverage_score * weights["coverage"]
        + sales_speed_score * weights["sales_speed"]
        + return_score * weights["returns"]
        + discount_score * weights["discount"]
        + margin_score * weights["margin"]
    )

    performance_bonus = Decimal("0")

    if coverage_score == 2 and discount_score == 2:
        performance_bonus += Decimal("0.1")

    if margin_score == 2:
        performance_bonus += Decimal("0.05")

    if sales_volume >= 50:
        performance_bonus += Decimal("0.05")

    weighted_sum = min(weighted_sum + performance_bonus, Decimal("2"))
    score_pct = (weighted_sum / 2) * 100

    if score_pct >= 67:
        level = "High"
    elif score_pct >= 40:
        level = "Medium"
    else:
        level = "Low"

    if severe_signals:
        level = "Low"
        score_pct = min(score_pct, 30)

    advisories: list[str] = []

    if months_to_sell_out is None:
        advisories.append("Not enough sales data to project sell-through.")

    if months_to_sell_out is not None:
        buffer_months = Decimal(str((restock_lead_months or 0) + 1))
        if is_core and months_to_sell_out <= buffer_months:
            advisories.append(
                "Restock warning: projected sell-out before restock buffer."
            )

        overstock_threshold = Decimal("12") if is_core else Decimal("9")
        if months_to_sell_out > overstock_threshold:
            months_display = months_to_sell_out.quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            if (
                sales_speed is not None
                and avg_sales_speed not in (None, Decimal("0"))
                and sales_speed >= avg_sales_speed
            ):
                advisories.append(
                    f"Stock coverage is high at ~{months_display} months—inventory is ahead of demand; consider slowing reorders or targeted promotion."
                )
            else:
                advisories.append(
                    f"Slow sell-through—projected to take ~{months_display} months to clear; consider promotion or markdown."
                )

        if months_to_sell_out < Decimal("3") and inventory_units < 5:
            advisories.append("Fast seller with low stock—prioritise replenishment.")

    advisories.extend(severe_signals)

    if (
        discount_pct is not None
        and avg_discount is not None
        and discount_pct > avg_discount + Decimal("3")
    ):
        advisories.append("Heavy discounting relative to store average.")

    if margin_advisory:
        advisories.append(margin_advisory)

    if sales_volume < 5:
        advisories.append("Low sales volume—confidence is provisional.")

    components = {
        "sell_through": coverage_score,
        "sales_speed": sales_speed_score,
        "returns": return_score,
        "discount": discount_score,
        "margin": margin_score,
    }

    return {
        "level": level,
        "score": round(score_pct, 1),
        "components": components,
        "advisories": advisories,
    }


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
    today: date = None,
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


# ---------------------------------------------------------------------------
# Sales Speed Helper
# ---------------------------------------------------------------------------

WEEKS_PER_MONTH = 365.25 / 12 / 7


def calculate_variant_sales_speed_details(
    variant: ProductVariant,
    *,
    weeks: int = 26,
    today: Optional[date] = None,
    fallback_weeks: int = 52,
) -> dict:
    """Return detailed sales speed info for ``variant``.

    Weeks where the variant had no stock are ignored. Returns a dict with
    ``speed`` (units per month), ``total_sold`` across counted periods, and
    ``periods`` (weeks) that contributed to the calculation.
    """

    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()

    week_start_today = today - timedelta(days=today.weekday())

    def _speed_for_window(window_weeks: int) -> dict:
        start_week = week_start_today - timedelta(weeks=window_weeks - 1)
        week_starts = [start_week + timedelta(weeks=i) for i in range(window_weeks)]

        # Gather events to track inventory over time
        events = []
        for snap in variant.snapshots.all():
            events.append((snap.date, "snapshot", snap.inventory_count))
        for sale in variant.sales.all():
            events.append((sale.date, "sale", sale.sold_quantity or 0))
        events.sort(key=lambda x: x[0])

        # Inventory level at end of each week
        inventory_by_week: Dict[date, Optional[int]] = {}
        idx = 0
        current_inv = 0
        seen_snapshot = False

        for ws in week_starts:
            we = ws + timedelta(days=6)
            while idx < len(events) and events[idx][0] <= we:
                dt, typ, qty = events[idx]
                if typ == "snapshot":
                    current_inv = qty
                    seen_snapshot = True
                else:
                    current_inv -= qty
                idx += 1
            inventory_by_week[ws] = max(current_inv, 0) if seen_snapshot else None

        # Sales totals per week
        sales_by_week: Dict[date, int] = defaultdict(int)
        for sale in variant.sales.all():
            ws = sale.date - timedelta(days=sale.date.weekday())
            if start_week <= ws <= week_start_today:
                sales_by_week[ws] += sale.sold_quantity or 0

        total = 0
        periods = 0
        for ws in week_starts:
            sold = sales_by_week.get(ws, 0)
            inv = inventory_by_week.get(ws)
            if inv is None:
                had_stock = sold > 0
            else:
                had_stock = inv > 0

            if sold or had_stock:
                periods += 1
                total += sold

        if periods == 0:
            return {"speed": 0.0, "total_sold": 0, "periods": 0}

        avg_weekly = total / periods
        return {
            "speed": avg_weekly * WEEKS_PER_MONTH,
            "total_sold": total,
            "periods": periods,
        }

    result = _speed_for_window(weeks)
    if result["speed"] == 0.0 and fallback_weeks and fallback_weeks > weeks:
        result = _speed_for_window(fallback_weeks)
    return result


def calculate_variant_sales_speed(
    variant: ProductVariant,
    *,
    weeks: int = 26,
    today: Optional[date] = None,
    fallback_weeks: int = 52,
) -> float:
    """Return the average monthly sales speed of ``variant``.

    The speed is calculated using weekly periods for accuracy. Weeks where the
    variant had no stock are ignored. ``weeks`` defaults to 26 (roughly six
    months). If no sales are found within ``weeks`` and ``fallback_weeks`` is
    greater, the window is automatically expanded up to ``fallback_weeks``.
    The returned value is expressed in units sold per month.
    """

    return calculate_variant_sales_speed_details(
        variant, weeks=weeks, today=today, fallback_weeks=fallback_weeks
    )["speed"]


def calculate_sales_speed_for_variants(
    variants,
    *,
    weeks: int = 26,
    today: Optional[date] = None,
    weight: str = "sales",
) -> float:
    """Return a unified sales speed for a group of variants.

    ``weight`` controls aggregation:
      - "sales": weight by total units sold while in stock (default).
      - "equal": simple mean of variant speeds.
    """

    today = today or date.today()
    details = []
    for variant in variants:
        detail = calculate_variant_sales_speed_details(
            variant, weeks=weeks, today=today
        )
        details.append(detail)

    if not details:
        return 0.0

    if weight == "equal":
        speeds = [d["speed"] for d in details]
        return sum(speeds) / len(speeds) if speeds else 0.0

    weighted_total = 0.0
    weight_sum = 0.0
    for detail in details:
        weight_value = detail["total_sold"]
        if weight_value:
            weighted_total += detail["speed"] * weight_value
            weight_sum += weight_value

    if weight_sum > 0:
        return weighted_total / weight_sum

    speeds = [d["speed"] for d in details]
    return sum(speeds) / len(speeds) if speeds else 0.0


def get_variant_speed_map(variants, *, weeks=26, today=None):
    """Return a {variant_id: speed} map for the given variants."""
    today = today or date.today()
    return {
        v.id: calculate_variant_sales_speed(v, weeks=weeks, today=today)
        for v in variants
    }


def get_category_speed_stats(
    type_code: str, *, weeks: int = 26, today: Optional[date] = None
):
    """Return average sales speed info for a product type.

    Parameters
    ----------
    type_code : str
        The ``Product.type`` code to filter variants by.
    weeks : int
        Number of weeks to consider when calculating variant speeds.
    today : date, optional
        Anchor date for calculations. Defaults to ``date.today()``.

    Returns
    -------
    dict
        ``{"overall_avg": float, "size_avgs": {size: float}}``
        where speeds are expressed in units per month.
    """

    if not type_code:
        return {"overall_avg": 0.0, "size_avgs": {}}

    today = today or date.today()
    variants = ProductVariant.objects.filter(product__type=type_code).prefetch_related(
        "sales", "snapshots"
    )

    speed_map = get_variant_speed_map(variants, weeks=weeks, today=today)

    size_buckets: Dict[Optional[str], list[float]] = defaultdict(list)
    for v in variants:
        size_buckets[v.size].append(speed_map.get(v.id, 0.0))

    size_avgs = {
        sz: round(sum(vals) / len(vals), 1) for sz, vals in size_buckets.items() if vals
    }

    speeds = list(speed_map.values())
    overall = round(sum(speeds) / len(speeds), 1) if speeds else 0.0

    # sort size averages alphabetically for stable output
    size_avgs = dict(sorted(size_avgs.items(), key=lambda x: x[0] or ""))

    return {"overall_avg": overall, "size_avgs": size_avgs}


def compute_safe_stock(variants, speed_map=None):
    """
    Compute safe stock data and product-level summary for a list of variants.
    Each variant entry includes current stock, sales speed, restock quantity,
    ideal six-month stock level, and units currently on order (undelivered).
    Returns a dict with keys ``safe_stock_data`` and ``product_safe_summary``.
    """
    safe_stock_data = []
    today = datetime.today().date()

    for v in variants:
        current = v.latest_inventory
        avg_speed = (
            speed_map.get(v.id)
            if speed_map is not None
            else calculate_variant_sales_speed(v, today=today)
        )
        recent_speed = calculate_variant_sales_speed(v, weeks=13, today=today)

        min_threshold = avg_speed * 2
        ideal_level = avg_speed * 6
        restock_wait = getattr(v.product, "restock_time", 0)
        stock_at_restock = max(0, math.ceil(current - restock_wait * avg_speed))
        restock_qty = max(math.ceil(ideal_level - stock_at_restock), 0)
        six_month_stock = math.ceil(ideal_level)
        on_order_qty = v.order_items.filter(date_arrived__isnull=True).aggregate(
            total=Coalesce(Sum("quantity"), 0)
        )["total"]

        months_left = (current / avg_speed) if avg_speed > 0 else None

        if current == 0:
            status = "red"
        elif months_left is not None and months_left <= 3:
            status = "orange"
        else:
            status = "green"

        if recent_speed > avg_speed:
            trend = "up"
        elif recent_speed < avg_speed:
            trend = "down"
        else:
            trend = "flat"

        safe_stock_data.append(
            {
                "variant_code": v.variant_code,
                "variant_size": v.size,
                "current_stock": current,
                "stock_at_restock": stock_at_restock,
                "avg_speed": round(avg_speed, 1),
                "min_threshold": math.ceil(min_threshold),
                "restock_qty": restock_qty,
                "six_month_stock": six_month_stock,
                "on_order_qty": on_order_qty,
                "months_left": months_left,
                "stock_status": status,
                "trend": trend,
            }
        )

    # Sort by size order
    safe_stock_data.sort(key=lambda x: SIZE_ORDER.get(x["variant_size"], 9999))

    # Product-level summary (exclude zero-speed variants)
    filtered = [r for r in safe_stock_data if r["avg_speed"] > 0]
    product_safe_summary = {
        "total_current_stock": sum(r["current_stock"] for r in safe_stock_data),
        "total_stock_at_restock": sum(r["stock_at_restock"] for r in safe_stock_data),
        "avg_speed": round(sum(r["avg_speed"] for r in filtered), 1) if filtered else 0,
        "total_restock_needed": sum(r["restock_qty"] for r in filtered),
        "total_six_month_stock": sum(r["six_month_stock"] for r in filtered),
        "total_on_order_qty": sum(r["on_order_qty"] for r in safe_stock_data),
    }

    return {
        "safe_stock_data": safe_stock_data,
        "product_safe_summary": product_safe_summary,
    }


def compute_variant_projection(variants, speed_map=None):
    """Compute variant-level stock projection data including history."""

    today_dt = date.today()
    current_month = today_dt.replace(day=1)

    # Determine start month based on earliest sale (minus one month) but not
    # showing more than 12 months of history
    first_sale = (
        Sale.objects.filter(variant__in=variants)
        .aggregate(first=Min("date"))
        .get("first")
    )
    if first_sale:
        start_month = (first_sale - relativedelta(months=1)).replace(day=1)
    else:
        start_month = current_month

    last_year_month = current_month - relativedelta(months=12)
    if start_month < last_year_month:
        start_month = last_year_month

    end_month = current_month + relativedelta(months=12)
    month_count = (
        (end_month.year - start_month.year) * 12 + end_month.month - start_month.month
    )
    months = [start_month + relativedelta(months=i) for i in range(month_count + 1)]

    stock_chart_data = {
        "months": [m.strftime("%Y-%m") for m in months],
        "variant_lines": [],
    }

    for v in variants:
        speed = (
            speed_map.get(v.id)
            if speed_map is not None
            else calculate_variant_sales_speed(v, today=current_month)
        )

        sales_by_month = defaultdict(int)
        for s in v.sales.all():
            mon = s.date.replace(day=1)
            sales_by_month[mon] += s.sold_quantity or 0

        restocks = defaultdict(int)
        # Prefetched order_items may exclude delivered ones, so fetch all
        for oi in OrderItem.objects.filter(product_variant=v):

            if oi.date_arrived:
                mon = oi.date_arrived.replace(day=1)
                qty = (
                    oi.actual_quantity
                    if oi.actual_quantity is not None
                    else oi.quantity
                )
                restocks[mon] += qty
            elif oi.date_expected:
                mon = oi.date_expected.replace(day=1)
                restocks[mon] += oi.quantity

        snap = (
            v.snapshots.filter(date__lte=start_month)
            .order_by("-date")
            .values("inventory_count")
            .first()
        )
        stock = snap["inventory_count"] if snap else 0

        levels = []
        current = stock
        for m in months:
            current += restocks.get(m, 0)
            if m <= current_month:
                current -= sales_by_month.get(m, 0)
            else:
                current -= speed
            current = max(round(current), 0)
            levels.append(current)

        stock_chart_data["variant_lines"].append(
            {"variant_name": v.variant_code, "stock_levels": levels}
        )

    return {"stock_chart_data": json.dumps(stock_chart_data)}


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


def compute_product_health(product, variants, simplify_type, speed_map=None):
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


# Groups used for restock checks
def _restock_groups():
    setting = RestockSetting.objects.first()
    if setting:
        return setting.groups.all()
    return Group.objects.filter(name="core")


def _annotate_variant_stock(variants, month_start=None):
    """Annotate variants with stock metrics.

    Adds ``latest_inventory``, ``avg_speed``, ``months_left`` and
    ``restock_to_6`` attributes to each variant. ``avg_speed`` is computed using
    :func:`calculate_variant_sales_speed`, which looks at the last six months of
    weekly data and ignores weeks with no stock. ``months_left`` is
    ``latest_inventory`` divided by ``avg_speed``. ``restock_to_6`` is the
    quantity required to reach six months of coverage based on ``avg_speed``.
    """

    month_start = month_start or date.today().replace(day=1)

    for v in variants:
        # Determine latest inventory count from snapshots
        latest_inv = 0
        latest_dt = None
        for snap in v.snapshots.all():
            if latest_dt is None or snap.date > latest_dt:
                latest_dt = snap.date
                latest_inv = snap.inventory_count
        v.latest_inventory = latest_inv

        avg_speed = calculate_variant_sales_speed(v)

        v.avg_speed = avg_speed
        v.months_left = (v.latest_inventory / avg_speed) if avg_speed > 0 else None
        target_level = avg_speed * 6
        v.restock_to_6 = max(math.ceil(target_level - v.latest_inventory), 0)

    return variants


def get_low_stock_products(queryset):
    """Return items with less than 3 months of stock remaining.

    This uses ``calculate_variant_sales_speed`` to determine each variant's
    monthly sales velocity (ignoring weeks with no stock). Variants with less
    than three months of stock remaining are returned.
    """

    today = date.today()

    groups = _restock_groups()

    if queryset.model == ProductVariant:
        variant_qs = queryset.filter(
            product__decommissioned=False, product__groups__in=groups
        ).distinct()
        return_products = False
    elif queryset.model == Product:
        product_qs = queryset.filter(
            decommissioned=False,
            groups__in=groups,
        ).distinct()
        variant_qs = ProductVariant.objects.filter(product__in=product_qs)
        return_products = True
    else:
        raise ValueError("Queryset must be for Product or ProductVariant")

    variants = list(
        variant_qs.select_related("product").prefetch_related("sales", "snapshots")
    )

    month_start = today.replace(day=1)
    _annotate_variant_stock(variants, month_start)

    low_variants = [
        v for v in variants if v.months_left is not None and v.months_left < 3
    ]

    if return_products:
        return list({v.product for v in low_variants})
    return low_variants


def get_restock_alerts():
    """Return detailed restock information for products needing attention.

    The result is a list of dictionaries with keys ``product``, ``variants`` and
    ``total_restock``. ``variants`` is a list of ``ProductVariant`` objects with
    ``months_left`` and ``restock_to_6`` attributes populated for all variants
    of the product.
    """

    groups = _restock_groups()

    product_qs = Product.objects.filter(
        decommissioned=False, groups__in=groups
    ).distinct()

    variant_qs = (
        ProductVariant.objects.filter(product__in=product_qs)
        .select_related("product")
        .prefetch_related("sales", "snapshots")
    )

    variants = list(variant_qs)
    if not variants:
        return []

    _annotate_variant_stock(variants)

    grouped = defaultdict(list)
    for v in variants:
        grouped[v.product].append(v)

    alerts = []
    for product, vars in grouped.items():
        total_variants = len(vars)
        low_count = sum(
            1 for v in vars if v.months_left is not None and v.months_left < 3
        )
        out_count = sum(1 for v in vars if v.latest_inventory <= 0)

        if out_count / total_variants > 0.2:
            level = "urgent"
        elif low_count / total_variants >= 0.5:
            level = "normal"
        else:
            continue

        total = sum(v.restock_to_6 for v in vars)
        alerts.append(
            {
                "product": product,
                "variants": vars,
                "total_restock": total,
                "alert_type": level,
            }
        )

    return alerts
