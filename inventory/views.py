from datetime import datetime, date, timedelta
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta
import json
from collections import defaultdict
import calendar

from decimal import Decimal

from django.shortcuts import render, get_object_or_404
from django.db import models
from django.db.models.functions import Coalesce
from django.db.models import Count, Sum, Max, F, Q, Subquery, OuterRef, Avg, Prefetch, ExpressionWrapper, DecimalField
from django.http import HttpResponse
from django.db.models.functions import TruncMonth

from .models import Product, ProductVariant, InventorySnapshot, Sale, Order, OrderItem




# Create a mapping from size code to its order index.
SIZE_ORDER = {code: index for index, (code, label) in enumerate(ProductVariant.SIZE_CHOICES)}




def home(request):
    # Determine last month's date range.
    today = date.today()
    first_day_current = today.replace(day=1)
    last_day_previous = first_day_current - timedelta(days=1)
    first_day_previous = last_day_previous.replace(day=1)

    # Filter sales from last month.
    sales_last_month = Sale.objects.filter(date__range=(first_day_previous, last_day_previous))

    # Calculate total sales value and total returns for last month.
    total_sales = sales_last_month.aggregate(total_sold_value=Sum('sold_value'))['total_sold_value'] or 0
    total_returns = sales_last_month.aggregate(total_return_value=Sum('return_value'))['total_return_value'] or 0

    # Get top ten sold variants by quantity.
    top_variants = (
        sales_last_month
        .values('variant')
        .annotate(
            total_quantity=Sum('sold_quantity'),
            total_sales=Sum('sold_value')
        )
        .order_by('-total_quantity')[:10]
    )

    # Extract variant IDs.
    variant_ids = [item['variant'] for item in top_variants]

    # Fetch the actual ProductVariant objects, including related Product.
    top_variants_qs = ProductVariant.objects.filter(id__in=variant_ids).select_related('product')

    # Build a list that merges the annotation data with the model object.
    top_products = []
    for item in top_variants_qs:
        data = next((tv for tv in top_variants if tv['variant'] == item.id), {})
        top_products.append({
            'product_variant': item,
            'total_quantity': data.get('total_quantity', 0),
            'total_sales': data.get('total_sales', 0),
        })

    # --- New code for monthly sales chart ---
    monthly_labels = []
    monthly_sales = []
    # Calculate for the last 12 months (oldest first).
    for i in range(12):
        month_date = (today - relativedelta(months=11 - i)).replace(day=1)
        next_month = month_date + relativedelta(months=1)
        monthly_total = Sale.objects.filter(date__gte=month_date, date__lt=next_month).aggregate(total=Sum('sold_value'))['total'] or 0
        monthly_labels.append(month_date.strftime('%b %Y'))
        # Convert the Decimal to float
        monthly_sales.append(float(monthly_total))

    context = {
        'total_sales': total_sales,
        'total_returns': total_returns,
        'top_products': top_products,
        'last_month_range': {
            'start': first_day_previous,
            'end': last_day_previous,
        },
        'monthly_labels': json.dumps(monthly_labels),
        'monthly_sales': json.dumps(monthly_sales),
    }
    return render(request, 'inventory/home.html', context)


def dashboard(request):
    today = date.today()
    # Calculate last month's date range.
    first_day_this_month = today.replace(day=1)
    last_day_previous = first_day_this_month - timedelta(days=1)
    first_day_last_month = last_day_previous.replace(day=1)

    # Calculate the last 3 full months range.
    first_day_last_3_months = (first_day_this_month - relativedelta(months=3)).replace(day=1)
    # Calculate the last 12 months range.
    one_year_ago = today - relativedelta(months=12)

    # 1. Aggregate sales by variant type for last month.
    sales_by_type_qs = Sale.objects.filter(
        date__range=(first_day_last_month, last_day_previous)
    ).values('variant__type').annotate(total_sold=Sum('sold_quantity'))
    sales_by_type = {item['variant__type']: item['total_sold'] for item in sales_by_type_qs}

    # 2. Aggregate sales for the last 3 months.
    sales_3m_qs = Sale.objects.filter(
        date__range=(first_day_last_3_months, last_day_previous)
    ).values('variant__type').annotate(total_sold=Sum('sold_quantity'))
    sales_3m_by_type = {item['variant__type']: item['total_sold'] for item in sales_3m_qs}

    # 3. Aggregate sales for the last 12 months.
    sales_12_qs = Sale.objects.filter(
        date__gte=one_year_ago
    ).values('variant__type').annotate(total_sold=Sum('sold_quantity'))
    sales_12_by_type = {item['variant__type']: item['total_sold'] for item in sales_12_qs}

    # 4. Annotate each ProductVariant with its latest inventory.
    latest_snapshot_subquery = InventorySnapshot.objects.filter(
        product_variant=OuterRef('pk')
    ).order_by('-date').values('inventory_count')[:1]
    variants = ProductVariant.objects.annotate(
        latest_inventory=Coalesce(Subquery(latest_snapshot_subquery), 0)
    )

    # 5. Calculate current stock by type.
    stock_by_type_qs = variants.values('type').annotate(total_stock=Sum('latest_inventory'))
    stock_by_type = {item['type']: item['total_stock'] for item in stock_by_type_qs}

    # 6. Aggregate items on order by variant type.
    orders_qs = OrderItem.objects.filter(
        date_expected__gte=first_day_this_month
    ).values('product_variant__type').annotate(total_order=Sum('quantity'))
    orders_by_type = {item['product_variant__type']: item['total_order'] for item in orders_qs}

    # 7. Define allowed categories.
    allowed = {
       'gi': 'Gi',
       'rg': 'Rashguard',
       'dk': 'Shorts',
       'ck': 'Spats',
       'bt': 'Belts',
    }

    # Helper function: Build product breakdown for a given filter expression.
    def get_product_breakdown(filter_expr):
        qs = ProductVariant.objects.annotate(
            latest_inventory=Coalesce(Subquery(latest_snapshot_subquery), 0)
        ).filter(filter_expr, sales__date__gte=first_day_last_3_months).distinct()
        products_dict = {}
        for variant in qs:
            key = variant.product_id
            if key not in products_dict:
                products_dict[key] = {
                    'product_id': key,
                    'product_name': variant.product.product_name,
                    'last_month_sales': 0,
                    'sales_3m': 0,
                    'current_stock': 0,
                }
            variant_last_month_sales = variant.sales.filter(
                date__range=(first_day_last_month, last_day_previous)
            ).aggregate(total=Coalesce(Sum('sold_quantity'), 0))['total']
            variant_3m_sales = variant.sales.filter(
                date__range=(first_day_last_3_months, last_day_previous)
            ).aggregate(total=Coalesce(Sum('sold_quantity'), 0))['total']
            products_dict[key]['last_month_sales'] += variant_last_month_sales
            products_dict[key]['sales_3m'] += variant_3m_sales
            products_dict[key]['current_stock'] += variant.latest_inventory
        products_list = []
        for prod in products_dict.values():
            if prod['last_month_sales'] > 0:
                products_list.append({
                    'product_id': prod['product_id'],
                    'product_name': prod['product_name'],
                    'last_month_sales': prod['last_month_sales'],
                    'avg_sales': prod['sales_3m'] / 3,
                    'current_stock': prod['current_stock'],
                })
        products_list.sort(key=lambda x: x['last_month_sales'], reverse=True)
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
        categories.append({
            'type_code': type_code,
            'label': label,
            'stock': cat_stock,
            'last_month_sales': lm_sales,
            'avg_sales_12': avg_12,
            'avg_sales_3': avg_3,
            'items_on_order': orders,
            'products': products_list,
        })

    # 9. Build category data for "Others" (types not in allowed).
    others_sales_last = sum(sales for key, sales in sales_by_type.items() if key not in allowed)
    others_sales_12 = sum(sales for key, sales in sales_12_by_type.items() if key not in allowed)
    others_avg_12 = others_sales_12 / 12.0
    others_sales_3 = sum(sales for key, sales in sales_3m_by_type.items() if key not in allowed)
    others_avg_3 = others_sales_3 / 3.0
    others_stock = sum(stock for key, stock in stock_by_type.items() if key not in allowed)
    others_orders = sum(orders for key, orders in orders_by_type.items() if key not in allowed)
    categories.append({
        'type_code': 'others',
        'label': 'Others',
        'stock': others_stock,
        'last_month_sales': others_sales_last,
        'avg_sales_12': others_avg_12,
        'avg_sales_3': others_avg_3,
        'items_on_order': others_orders,
        'products': get_product_breakdown(~Q(type__in=list(allowed.keys()))),
    })

    # --- PREVIOUS CODE (Charts, Top-Selling, etc.) ---
    # Normalize today to first of month for chart projections.
    chart_today = datetime.today().replace(day=1)
    next_12_months = [chart_today + relativedelta(months=i) for i in range(13)]

    # Stock Projection Chart Data
    stock_chart_data = {
        'months': [month.strftime('%b %Y') for month in next_12_months],
        'variant_lines': []
    }
    historic_sales_data = {}
    for v in ProductVariant.objects.all():
        snapshot = InventorySnapshot.objects.filter(product_variant=v).order_by('-date').values('inventory_count').first()
        current_stock = snapshot['inventory_count'] if snapshot else 0
        six_months_ago = datetime.today() - relativedelta(months=6)
        total_sales_last_6 = v.sales.filter(date__gte=six_months_ago).aggregate(total_sold=Sum('sold_quantity'))['total_sold'] or 0
        sales_speed = total_sales_last_6 / 6
        order_items = v.order_items.filter(date_expected__gte=chart_today).values('date_expected', 'quantity')
        restocks = {}
        for item in order_items:
            restock_month = item['date_expected'].replace(day=1)
            restocks[restock_month] = restocks.get(restock_month, 0) + item['quantity']
        stock_levels = [current_stock]
        for i in range(1, 13):
            projected = stock_levels[-1] - sales_speed
            month = (chart_today + relativedelta(months=i)).date()
            if month in restocks:
                projected += restocks[month]
            stock_levels.append(max(projected, 0))
        stock_chart_data['variant_lines'].append({
            'variant_name': v.variant_code,
            'stock_levels': stock_levels,
        })

        sales = v.sales.filter(date__gte=one_year_ago).annotate(month=TruncMonth('date')).values('month').annotate(total_quantity=Sum('sold_quantity')).order_by('month')
        for sale in sales:
            m = sale['month'].strftime('%Y-%m')
            if m not in historic_sales_data:
                historic_sales_data[m] = {}
            historic_sales_data[m][v.variant_code] = sale['total_quantity']

    sorted_months = sorted(historic_sales_data.keys())
    historic_chart_data = {
        'months': sorted_months,
        'datasets': []
    }
    for v in ProductVariant.objects.all():
        variant_sales = [historic_sales_data.get(m, {}).get(v.variant_code, 0) for m in sorted_months]
        historic_chart_data['datasets'].append({
            'label': v.variant_code,
            'data': variant_sales,
        })

    # Top-Selling Analysis (80/20)
    top_selling_variants = ProductVariant.objects.annotate(
        total_sales=Sum('sales__sold_quantity', filter=Q(sales__date__gte=one_year_ago))
    ).order_by('-total_sales')
    total_sales_all_variants = sum(v.total_sales or 0 for v in top_selling_variants)
    cumulative_sales = 0
    top_80_percent_variants = []
    for v in top_selling_variants:
        cumulative_sales += v.total_sales or 0
        top_80_percent_variants.append(v)
        if cumulative_sales >= 0.8 * total_sales_all_variants:
            break

    top_selling_sizes = ProductVariant.objects.filter(size__isnull=False).values('size').annotate(
        total_sales=Sum('sales__sold_quantity', filter=Q(sales__date__gte=one_year_ago))
    ).order_by('-total_sales')
    total_sales_sizes = sum((s['total_sales'] or 0) for s in top_selling_sizes)
    top_selling_sizes = [
        {
            'size': s['size'],
            'total_sales': s['total_sales'] or 0,
            'percentage': round(((s['total_sales'] or 0) / total_sales_sizes) * 100, 2) if total_sales_sizes > 0 else 0
        }
        for s in top_selling_sizes
    ]

    top_selling_colors = ProductVariant.objects.filter(primary_color__isnull=False).values('primary_color').annotate(
        total_sales=Sum('sales__sold_quantity', filter=Q(sales__date__gte=one_year_ago))
    ).order_by('-total_sales')

    context = {
        'categories': categories,
        'labels': json.dumps([month.strftime('%b %Y') for month in next_12_months]),
        'stock_levels': json.dumps([sum(variant_stock['stock_levels']) for variant_stock in stock_chart_data['variant_lines']]),
        'stacked_bar_data': json.dumps({
            'labels': [month.strftime('%b %Y') for month in next_12_months],
            'datasets': []  # (Assume you fill this in similarly if needed)
        }),
        'projected_stock_levels': json.dumps(stock_chart_data),
        'historic_chart_data': json.dumps(historic_chart_data),
        'top_selling_variants': top_80_percent_variants,
        'top_selling_sizes': top_selling_sizes,
        'top_selling_colors': top_selling_colors,
    }

    return render(request, 'inventory/dashboard.html', context)






def product_list(request):
    # Get filter parameters from the request.
    # Now using "show_retired" - default is false, i.e. retired products are hidden.
    show_retired = request.GET.get('show_retired', 'false').lower() == 'true'
    type_filter = request.GET.get('type_filter', None)

    # Define date ranges.
    today = now().date()
    first_day_current = today.replace(day=1)
    last_12_months = today - timedelta(days=365)
    last_30_days = today - timedelta(days=30)

    # Subquery to fetch the latest inventory snapshot for each variant.
    latest_snapshot = InventorySnapshot.objects.filter(
        product_variant=OuterRef('pk')
    ).order_by('-date').values('inventory_count')[:1]

    # Build a queryset of variants annotated with their latest inventory.
    variants_with_inventory_qs = ProductVariant.objects.annotate(
        latest_inventory=Coalesce(Subquery(latest_snapshot), 0)
    )

    # Fetch all products with a prefetch of variants_with_inventory.
    products_qs = Product.objects.all().prefetch_related(
        Prefetch('variants', queryset=variants_with_inventory_qs, to_attr='variants_with_inventory')
    ).annotate(
        variant_count=Count('variants', distinct=True)
    )

    # Filter by type if provided.
    if type_filter:
        products_qs = products_qs.filter(variants__type=type_filter).distinct()

    # Filter out retired products unless show_retired is True.
    if not show_retired:
        products_qs = products_qs.filter(decommissioned=False)

    # Force evaluation.
    products = list(products_qs)

    # Create a mapping for ordering sizes (using SIZE_CHOICES).
    SIZE_ORDER = {code: index for index, (code, label) in enumerate(ProductVariant.SIZE_CHOICES)}

    # Process each product.
    for product in products:
        if hasattr(product, 'variants_with_inventory'):
            product.variants_with_inventory.sort(
                key=lambda variant: SIZE_ORDER.get(variant.size, 9999)
            )
        # Compute total inventory by summing latest_inventory.
        product.total_inventory = sum(v.latest_inventory for v in product.variants_with_inventory)

        # Compute per-variant sales aggregates and sum them.
        total_sales = 0
        total_sales_value = Decimal('0.00')
        sales_last_12 = 0
        sales_last_30 = 0
        for variant in product.variants_with_inventory:
            variant_sales = variant.sales.aggregate(
                total=Coalesce(Sum('sold_quantity'), 0)
            )['total']
            total_sales += variant_sales

            variant_sales_value = variant.sales.aggregate(
                total=Coalesce(Sum('sold_value'), Decimal('0.00'))
            )['total']
            total_sales_value += variant_sales_value

            sales_12 = variant.sales.filter(
                date__gte=last_12_months
            ).aggregate(total=Coalesce(Sum('sold_quantity'), 0))['total']
            sales_last_12 += sales_12

            sales_30 = variant.sales.filter(
                date__gte=last_30_days
            ).aggregate(total=Coalesce(Sum('sold_quantity'), 0))['total']
            sales_last_30 += sales_30

        product.total_sales = total_sales
        product.total_sales_value = total_sales_value
        product.sales_last_12_months = sales_last_12
        product.sales_last_30_days = sales_last_30
        product.sales_speed_12_months = product.sales_last_12_months / 12 if product.sales_last_12_months else 0
        product.sales_speed_30_days = product.sales_last_30_days if product.sales_last_30_days else 0

        # --- Compute last order info for each product ---
        last_order_item = OrderItem.objects.filter(
            product_variant__product=product
        ).order_by('-order__order_date').first()
        if last_order_item:
            last_order = last_order_item.order
            order_items = OrderItem.objects.filter(
                product_variant__product=product,
                order=last_order
            )
            # Calculate cost: quantity * item_cost_price for each order item.
            from django.db.models import F, ExpressionWrapper, DecimalField
            order_cost = order_items.aggregate(
                total_cost=Coalesce(
                    Sum(ExpressionWrapper(F('item_cost_price') * F('quantity'), output_field=DecimalField())),
                    Decimal('0.00')
                )
            )['total_cost'] or Decimal('0.00')
            product.last_order_cost = order_cost

            delivered = all(item.date_arrived is not None for item in order_items)
            if delivered:
                product.last_order_date = order_items.first().date_arrived
                product.last_order_qty = order_items.aggregate(total=Coalesce(Sum('quantity'), 0))['total'] or 0
                product.last_order_label = "Last Order"
            else:
                product.last_order_date = None
                product.last_order_qty = order_items.aggregate(total=Coalesce(Sum('quantity'), 0))['total'] or 0
                product.last_order_label = "On Order"
        else:
            product.last_order_date = None
            product.last_order_qty = 0
            product.last_order_label = ""
            product.last_order_cost = Decimal('0.00')

        # --- Calculate profit as total sales value minus last order cost ---
        product.profit = product.total_sales_value - product.last_order_cost

    context = {
        'products': products,
        'show_retired': show_retired,
        'type_filter': type_filter,
        'type_choices': ProductVariant.TYPE_CHOICES,
    }
    return render(request, 'inventory/product_list.html', context)







def product_detail(request, product_id):
    # Fetch the product by ID
    product = get_object_or_404(Product, id=product_id)

    # Define the date ranges:
    today = datetime.today()
    current_month = today.replace(day=1)  # Start of current month
    next_12_months = [current_month + relativedelta(months=i) for i in range(13)]
    one_year_ago = today - relativedelta(months=12)
    three_months_ago = today - relativedelta(months=3)
    first_day_current = today.replace(day=1)
    last_day_previous = first_day_current - timedelta(days=1)
    first_day_previous = last_day_previous.replace(day=1)

    # Cache all variants and annotate them with latest inventory in one step.
    latest_snapshot_subquery = InventorySnapshot.objects.filter(
        product_variant=OuterRef('pk')
    ).order_by('-date').values('inventory_count')[:1]
    variants = product.variants.annotate(
        latest_inventory=Coalesce(Subquery(latest_snapshot_subquery), 0)
    )

    # --- Overall Product Aggregates ---
    total_sold_12 = Sale.objects.filter(
        variant__in=variants, date__gte=one_year_ago
    ).aggregate(total=Sum('sold_quantity'))['total'] or 0
    avg_sold_12 = total_sold_12 / 12.0
    total_sold_3 = Sale.objects.filter(
        variant__in=variants, date__gte=three_months_ago
    ).aggregate(total=Sum('sold_quantity'))['total'] or 0
    avg_sold_3 = total_sold_3 / 3.0
    items_in_stock = variants.aggregate(total_stock=Sum('latest_inventory'))['total_stock'] or 0
    # IMPORTANT: Check the filter on "items_on_order".
    # If orders from earlier this month should not count, consider using date_expected__gt=today.date()
    items_on_order = OrderItem.objects.filter(
        product_variant__in=variants, date_expected__gte=current_month
    ).aggregate(total=Sum('quantity'))['total'] or 0

    aggregates = {
         'total_sold_12': total_sold_12,
         'avg_sold_12': avg_sold_12,
         'avg_sold_3': avg_sold_3,
         'items_in_stock': items_in_stock,
         'items_on_order': items_on_order,
    }

    # --- Chart Data for Stock Projection and Historic Sales ---
    stock_chart_data = {
        'months': [month.strftime('%Y-%m') for month in next_12_months],
        'variant_lines': []
    }
    historic_sales_data = {}
    for v in variants:
        # For each variant, get current stock from its latest snapshot (already annotated)
        current_stock = v.latest_inventory

        six_months_ago = today - relativedelta(months=6)
        total_sales_last_6 = v.sales.filter(date__gte=six_months_ago).aggregate(total_sold=Sum('sold_quantity'))['total_sold'] or 0
        sales_speed = total_sales_last_6 / 6  # units per month

        order_items = v.order_items.filter(date_expected__gte=current_month).values('date_expected', 'quantity')
        restocks = {}
        for item in order_items:
            restock_month = item['date_expected'].replace(day=1)
            restocks[restock_month] = restocks.get(restock_month, 0) + item['quantity']

        stock_levels = [current_stock]
        for i in range(1, 13):
            projected = stock_levels[-1] - sales_speed
            month = (current_month + relativedelta(months=i)).date()
            if month in restocks:
                projected += restocks[month]
            stock_levels.append(max(projected, 0))
        stock_chart_data['variant_lines'].append({
            'variant_name': v.variant_code,
            'stock_levels': stock_levels,
        })

        sales = v.sales.filter(date__gte=one_year_ago).annotate(month=TruncMonth('date')).values('month').annotate(total_quantity=Sum('sold_quantity')).order_by('month')
        for sale in sales:
            m = sale['month'].strftime('%Y-%m')
            if m not in historic_sales_data:
                historic_sales_data[m] = {}
            historic_sales_data[m][v.variant_code] = sale['total_quantity']

    sorted_months = sorted(historic_sales_data.keys())
    historic_chart_data = {
        'months': sorted_months,
        'datasets': []
    }
    for v in variants:
        variant_sales = [historic_sales_data.get(m, {}).get(v.variant_code, 0) for m in sorted_months]
        historic_chart_data['datasets'].append({
            'label': v.variant_code,
            'data': variant_sales,
        })

    # --- Top-Selling Analysis (unchanged) ---
    top_selling_variants = product.variants.annotate(
        total_sales=Sum('sales__sold_quantity', filter=Q(sales__date__gte=one_year_ago))
    ).order_by('-total_sales')
    total_sales_all_variants = sum(v.total_sales or 0 for v in top_selling_variants)
    cumulative_sales = 0
    top_80_percent_variants = []
    for v in top_selling_variants:
        cumulative_sales += v.total_sales or 0
        top_80_percent_variants.append(v)
        if cumulative_sales >= 0.8 * total_sales_all_variants:
            break

    top_selling_sizes = product.variants.filter(size__isnull=False).values('size').annotate(
        total_sales=Sum('sales__sold_quantity', filter=Q(sales__date__gte=one_year_ago))
    ).order_by('-total_sales')
    total_sales_sizes = sum((s['total_sales'] or 0) for s in top_selling_sizes)
    top_selling_sizes = [
        {
            'size': s['size'],
            'total_sales': s['total_sales'] or 0,
            'percentage': round(((s['total_sales'] or 0) / total_sales_sizes) * 100, 2) if total_sales_sizes > 0 else 0
        }
        for s in top_selling_sizes
    ]

    top_selling_colors = product.variants.filter(primary_color__isnull=False).values('primary_color').annotate(
        total_sales=Sum('sales__sold_quantity', filter=Q(sales__date__gte=one_year_ago))
    ).order_by('-total_sales')

    # --- Granular Variant Detail: Per-Variant Aggregates ---
    # For each variant, calculate the five metrics:
    # 1. Items sold (last 12 months)
    # 2. Average sold per month (last 12 months)
    # 3. Average sold per month (last 3 months)
    # 4. Items in stock now (latest_inventory)
    # 5. Items on order (with date_expected >= current_month)
    # Define a subquery that calculates the total order quantity for each variant
    order_items_subquery = OrderItem.objects.filter(
        product_variant=OuterRef('pk'),
        date_expected__gte=current_month
    ).values('product_variant').annotate(
        total_ordered=Sum('quantity')
    ).values('total_ordered')

    # Now annotate each variant with the five metrics using the subquery for items_on_order
    variants_detail = product.variants.annotate(
        latest_inventory=Coalesce(Subquery(latest_snapshot_subquery), 0),
        total_sold_12=Coalesce(Sum('sales__sold_quantity', filter=Q(sales__date__gte=one_year_ago)), 0),
        total_sold_3=Coalesce(Sum('sales__sold_quantity', filter=Q(sales__date__gte=three_months_ago)), 0),
        items_on_order=Coalesce(Subquery(order_items_subquery), 0)
    ).annotate(
        avg_sold_12=ExpressionWrapper(F('total_sold_12') / 12.0, output_field=DecimalField()),
        avg_sold_3=ExpressionWrapper(F('total_sold_3') / 3.0, output_field=DecimalField())
    )

    context = {
        'product': product,
        'aggregates': aggregates,
        'stock_chart_data': json.dumps(stock_chart_data),
        'historic_chart_data': json.dumps(historic_chart_data),
        'top_selling_variants': top_80_percent_variants,
        'top_selling_sizes': top_selling_sizes,
        'top_selling_colors': top_selling_colors,
        'variants_detail': variants_detail,
    }

    return render(request, 'inventory/product_detail.html', context)





def order_list(request):
    # Fetch orders, ordering them by date (most recent first)
    orders = Order.objects.all().order_by('-order_date')

    # Calculate total order value for each order
    for order in orders:
        order.total_value = sum(item.item_cost_price * item.quantity for item in order.order_items.all())

    context = {
        'orders': orders,
    }
    return render(request, 'inventory/order_list.html', context)




def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order_items = order.order_items.select_related('product_variant__product')  # Optimize queries

    # Group items by product and include total quantity and total value
    grouped_items = {}
    for item in order_items:
        product = item.product_variant.product
        if product not in grouped_items:
            grouped_items[product] = {'items': [], 'total_quantity': 0, 'total_value': 0}
        grouped_items[product]['items'].append(item)
        grouped_items[product]['total_quantity'] += item.quantity
        grouped_items[product]['total_value'] += item.item_cost_price * item.quantity

    # Calculate total order value
    total_value = sum(item.item_cost_price * item.quantity for item in order_items)

    context = {
        'order': order,
        'grouped_items': grouped_items,
        'total_value': total_value,
    }
    return render(request, 'inventory/order_detail.html', context)



def inventory_snapshots(request):
    # Get all snapshots for display, prefetching the related product_variant.
    snapshots_qs = InventorySnapshot.objects.select_related('product_variant').order_by('-date')

    # Use a dictionary to aggregate data by date.
    snapshots_by_date = defaultdict(lambda: {'total_inventory': 0, 'total_cost': 0, 'total_retail': 0})

    # Assuming you have some functions to get the unit cost and retail for a variant.
    def get_unit_cost(variant):
        # You may derive this from related OrderItems or other logic
        # For demonstration, we simply return a constant or computed value.
        return 100  # Replace with your logic

    def get_unit_retail(variant):
        # Similarly derive retail price.
        return 150  # Replace with your logic

    for snapshot in snapshots_qs:
        date_key = snapshot.date
        unit_cost = get_unit_cost(snapshot.product_variant)
        unit_retail = get_unit_retail(snapshot.product_variant)
        snapshots_by_date[date_key]['total_inventory'] += snapshot.inventory_count
        snapshots_by_date[date_key]['total_cost'] += snapshot.inventory_count * unit_cost
        snapshots_by_date[date_key]['total_retail'] += snapshot.inventory_count * unit_retail

    # Convert the dictionary into a sorted list
    snapshots = [
        {
            'date': date,
            'total_inventory': data['total_inventory'],
            'total_cost': data['total_cost'],
            'total_retail': data['total_retail'],
        }
        for date, data in snapshots_by_date.items()
    ]
    snapshots.sort(key=lambda x: x['date'], reverse=True)

    context = {'snapshots': snapshots}
    return render(request, 'inventory/inventory_snapshots.html', context)
