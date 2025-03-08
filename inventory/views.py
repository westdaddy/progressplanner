from datetime import datetime, date, timedelta
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta
import json
from collections import defaultdict
import calendar

from django.shortcuts import render, get_object_or_404
from django.db import models
from django.db.models import Count, Sum, Max, F, Q, Subquery, OuterRef, Avg, Prefetch
from django.http import HttpResponse
from django.db.models.functions import TruncMonth

from .models import Product, ProductVariant, InventorySnapshot, Sale, Order, OrderItem




# Create a mapping from size code to its order index.
SIZE_ORDER = {code: index for index, (code, label) in enumerate(ProductVariant.SIZE_CHOICES)}




def home(request):
    # Determine the first and last day of last month.
    today = date.today()
    first_day_current = today.replace(day=1)
    last_day_previous = first_day_current - timedelta(days=1)
    first_day_previous = last_day_previous.replace(day=1)

    # Filter sales from last month.
    sales_last_month = Sale.objects.filter(date__range=(first_day_previous, last_day_previous))

    # Calculate total sales value and total returns for last month.
    total_sales = sales_last_month.aggregate(total_sold_value=Sum('sold_value'))['total_sold_value'] or 0
    total_returns = sales_last_month.aggregate(total_return_value=Sum('return_value'))['total_return_value'] or 0

    # Get top ten sold products by summing sold quantity for each product.
    top_products = sales_last_month.values(
        'variant__product__product_id',
        'variant__product__product_name'
    ).annotate(
        total_quantity=Sum('sold_quantity'),
        total_sales=Sum('sold_value')
    ).order_by('-total_quantity')[:10]


    context = {
        'total_sales': total_sales,
        'total_returns': total_returns,
        'top_products': top_products,
        'last_month_range': {
            'start': first_day_previous,
            'end': last_day_previous,
        }
    }
    return render(request, 'inventory/home.html', context)

def dashboard(request):
    today = datetime.today().replace(day=1)  # Normalize to first of the month
    next_12_months = [today + relativedelta(months=i) for i in range(13)]  # Current + next 12 months

    # Fetch the latest inventory snapshot for each variant
    latest_snapshot_subquery = InventorySnapshot.objects.filter(
        product_variant=models.OuterRef('pk')
    ).order_by('-date').values('inventory_count')[:1]

    # Fetch product variants with latest stock level
    variants = ProductVariant.objects.annotate(latest_inventory=models.Subquery(latest_snapshot_subquery))

    # Calculate sales speed per variant (average over last 6 months)
    six_months_ago = today - relativedelta(months=6)
    sales_speed_per_variant = {
        variant.id: (
            variant.sales.filter(date__gte=six_months_ago)
            .aggregate(total_sales=Sum('sold_quantity'))['total_sales'] or 0
        ) / 6  # Average sales per month
        for variant in variants
    }

    # Fetch expected restocks (OrderItem) per month
    future_orders = OrderItem.objects.filter(date_expected__gte=today).values('date_expected', 'product_variant', 'quantity')

    restock_schedule = {}
    for order in future_orders:
        restock_month = order['date_expected'].replace(day=1)  # Normalize to first of the month
        restock_schedule.setdefault(restock_month, {}).setdefault(order['product_variant'], 0)
        restock_schedule[restock_month][order['product_variant']] += order['quantity']

    # Initialize stock projections categorized by style
    projected_stock_levels = {month.strftime('%b %Y'): {} for month in next_12_months}
    styles = ['nogi', 'gi', 'apparel', 'accessories']
    style_stock_levels = {month.strftime('%b %Y'): {style: 0 for style in styles} for month in next_12_months}

    for variant in variants:
        stock = variant.latest_inventory or 0  # Start with the latest inventory count
        sales_speed = sales_speed_per_variant.get(variant.id, 0)  # Default sales speed to 0 if no sales data
        variant_style = variant.style if variant.style in styles else 'accessories'  # Default unknown styles to 'accessories'

        for month in next_12_months:
            month_str = month.strftime('%b %Y')
            stock -= sales_speed  # Decrease stock by projected sales

            # Add restocks if applicable
            normalized_month = month.date()  # Ensure month is in datetime.date format
            if normalized_month in restock_schedule:
                restock_amount = restock_schedule[normalized_month].get(variant.id, 0)
                if restock_amount > 0:
                    stock += restock_amount

            projected_stock_levels[month_str][variant.variant_code] = max(stock, 0)  # Ensure stock doesn't go negative
            style_stock_levels[month_str][variant_style] += max(stock, 0)  # Categorized stock by style

    # Convert projected stock levels into data for the graph
    chart_labels = list(projected_stock_levels.keys())
    total_stock_data = [
        sum(variant_stock.values()) for variant_stock in projected_stock_levels.values()
    ]

    # Prepare dataset for stacked bar chart
    stacked_bar_data = {
        'labels': chart_labels,
        'datasets': [
            {'label': style, 'data': [style_stock_levels[month][style] for month in chart_labels]}
            for style in styles
        ]
    }

    context = {
        'labels': json.dumps(chart_labels),
        'stock_levels': json.dumps(total_stock_data),
        'stacked_bar_data': json.dumps(stacked_bar_data),
        'projected_stock_levels': json.dumps(projected_stock_levels),  # Convert dict to JSON to prevent None errors
    }
    return render(request, 'inventory/dashboard.html', context)


def product_list(request):
    # Get filter parameters
    hide_zero_inventory = request.GET.get('hide_zero_inventory', 'false').lower() == 'true'
    type_filter = request.GET.get('type_filter', None)

    # Subquery to fetch the latest inventory snapshot for each variant
    latest_snapshot = InventorySnapshot.objects.filter(
        product_variant=OuterRef('pk')
    ).order_by('-date').values('inventory_count')[:1]

    # Build a queryset of variants annotated with their latest inventory.
    variants_with_inventory_qs = ProductVariant.objects.annotate(
        latest_inventory=Subquery(latest_snapshot)
    )

    # Time periods for sales speed calculation
    today = now().date()
    last_12_months = today - timedelta(days=365)
    last_30_days = today - timedelta(days=30)

    # Fetch all products with a prefetch of variants_with_inventory.
    products = Product.objects.all().prefetch_related(
        Prefetch('variants', queryset=variants_with_inventory_qs, to_attr='variants_with_inventory')
    ).annotate(
        variant_count=Count('variants', distinct=True),
        total_sales=Sum('variants__sales__sold_quantity', default=0),
        total_sales_value=Sum('variants__sales__sold_value', default=0),
        sales_last_12_months=Sum(
            'variants__sales__sold_quantity',
            filter=Q(variants__sales__date__gte=last_12_months),
            default=0
        ),
        sales_last_30_days=Sum(
            'variants__sales__sold_quantity',
            filter=Q(variants__sales__date__gte=last_30_days),
            default=0
        )
    )

    # Filter by type if provided.
    if type_filter:
        products = products.filter(variants__type=type_filter).distinct()

    # Create size order mapping
    SIZE_ORDER = {code: index for index, (code, label) in enumerate(ProductVariant.SIZE_CHOICES)}

    # Process each product
    for product in products:
        # Sort the variants using the defined order.
        if hasattr(product, 'variants_with_inventory'):
            product.variants_with_inventory.sort(
                key=lambda variant: SIZE_ORDER.get(variant.size, 9999)
            )

        product.total_inventory = sum(
            variant.latest_inventory or 0
            for variant in getattr(product, 'variants_with_inventory', [])
        )
        product.sales_speed_12_months = (
            product.sales_last_12_months / 12 if product.sales_last_12_months else 0
        )
        product.sales_speed_30_days = (
            product.sales_last_30_days if product.sales_last_30_days else 0
        )

    # Apply filtering for zero inventory products if requested.
    if hide_zero_inventory:
        products = [product for product in products if product.total_inventory > 0]

    # Summary metrics
    latest_snapshot_date = InventorySnapshot.objects.aggregate(latest_date=Max('date'))['latest_date']
    total_inventory = sum(product.total_inventory for product in products)
    total_zero_inventory_items = len([
        product for product in products if product.total_inventory == 0
    ])

    # Pass the TYPE_CHOICES to the context so the template can render the filter dropdown.
    type_choices = ProductVariant.TYPE_CHOICES

    context = {
        'products': products,
        'summary': {
            'latest_snapshot_date': latest_snapshot_date,
            'total_products': Product.objects.count(),
            'total_inventory': total_inventory,
            'total_zero_inventory_items': total_zero_inventory_items,
        },
        'hide_zero_inventory': hide_zero_inventory,
        'type_filter': type_filter,
        'type_choices': type_choices,
    }
    return render(request, 'inventory/product_list.html', context)




def product_detail(request, product_id):
    # Fetch the product by ID
    product = get_object_or_404(Product, id=product_id)

    # Define the date range: current month + next 12 months
    today = datetime.today()
    current_month = today.replace(day=1)  # Start of the current month
    next_12_months = [current_month + relativedelta(months=i) for i in range(13)]

    # Fetch all variants of the product
    variants = product.variants.all()

    # Prepare chart data for stock projection
    stock_chart_data = {
        'months': [month.strftime('%Y-%m') for month in next_12_months],
        'variant_lines': []
    }

    # Prepare chart data for historic sales
    one_year_ago = today - relativedelta(months=12)
    historic_sales_data = {}

    for variant in variants:
        # Get the latest inventory snapshot value for the variant
        latest_snapshot = (
            variant.snapshots.order_by('-date').values('inventory_count').first()
        )
        current_stock = latest_snapshot['inventory_count'] if latest_snapshot else 0

        # Calculate sales speed for the last 3 months
        six_months_ago = today - relativedelta(months=6)
        total_sales_last_6_months = (
            variant.sales.filter(date__gte=six_months_ago)
            .aggregate(total_sold=Sum('sold_quantity'))['total_sold'] or 0
        )
        sales_speed_per_month = total_sales_last_6_months / 6  # Sales speed in units/month

        # Fetch expected restocks from OrderItem
        order_items = variant.order_items.filter(date_expected__gte=current_month).values('date_expected', 'quantity')

        # Create a dictionary of restocks by normalized month
        restocks = {}
        for item in order_items:
            restock_month = item['date_expected'].replace(day=1)
            restocks[restock_month] = restocks.get(restock_month, 0) + item['quantity']

        # Project stock levels for the next 12 months
        stock_levels = [current_stock]  # Start with the current stock
        for i in range(1, 13):
            projected_stock = stock_levels[-1] - sales_speed_per_month
            month = (current_month + relativedelta(months=i)).date()  # Convert to date object

            # Add restock if there is an order expected in this month
            if month in restocks:
                projected_stock += restocks[month]

            stock_levels.append(max(projected_stock, 0))  # Prevent negative stock

        # Add data for stock projection
        stock_chart_data['variant_lines'].append({
            'variant_name': variant.variant_code,
            'stock_levels': stock_levels,
        })

        # Fetch historic sales for the last 12 months
        sales = (
            variant.sales.filter(date__gte=one_year_ago)
            .annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total_quantity=Sum('sold_quantity'))
            .order_by('month')
        )

        for sale in sales:
            month = sale['month'].strftime('%Y-%m')
            if month not in historic_sales_data:
                historic_sales_data[month] = {}
            historic_sales_data[month][variant.variant_code] = sale['total_quantity']

    # Sort months in historic_sales_data
    sorted_months = sorted(historic_sales_data.keys())  # Chronological order
    historic_chart_data = {
        'months': sorted_months,
        'datasets': []
    }
    for variant in variants:
        variant_sales = [
            historic_sales_data.get(month, {}).get(variant.variant_code, 0)
            for month in sorted_months
        ]
        historic_chart_data['datasets'].append({
            'label': variant.variant_code,
            'data': variant_sales,
        })

    # Calculate total sales for each variant
    top_selling_variants = (
        variants.annotate(total_sales=Sum('sales__sold_quantity', filter=models.Q(sales__date__gte=one_year_ago)))
        .order_by('-total_sales')
    )

    # Perform 80-20 analysis
    total_sales_all_variants = sum(variant.total_sales or 0 for variant in top_selling_variants)
    cumulative_sales = 0
    top_80_percent_variants = []

    for variant in top_selling_variants:
        cumulative_sales += variant.total_sales or 0
        top_80_percent_variants.append(variant)
        if cumulative_sales >= 0.8 * total_sales_all_variants:
            break

    # Calculate top-selling sizes over the last 12 months
    top_selling_sizes = (
        variants.filter(size__isnull=False)  # Exclude variants without a size
        .values('size')  # Group by size
        .annotate(total_sales=Sum('sales__sold_quantity', filter=models.Q(sales__date__gte=one_year_ago)))
        .order_by('-total_sales')
    )

    # Calculate total sales across all sizes
    total_sales_sizes = sum((size['total_sales'] or 0) for size in top_selling_sizes)

    # Add percentage calculation with safe handling of None values
    top_selling_sizes = [
        {
            'size': size['size'],
            'total_sales': size['total_sales'] or 0,  # Ensure total_sales is at least 0
            'percentage': round(((size['total_sales'] or 0) / total_sales_sizes) * 100, 2) if total_sales_sizes > 0 else 0
        }
        for size in top_selling_sizes
    ]

    # Calculate top-selling colors over the last 12 months
    top_selling_colors = (
        variants.filter(primary_color__isnull=False)  # Exclude variants without a primary color
        .values('primary_color')  # Group by primary color
        .annotate(total_sales=Sum('sales__sold_quantity', filter=models.Q(sales__date__gte=one_year_ago)))
        .order_by('-total_sales')
    )

    context = {
        'product': product,
        'stock_chart_data': json.dumps(stock_chart_data),  # Pass stock chart data as JSON
        'historic_chart_data': json.dumps(historic_chart_data),  # Pass historic sales chart data as JSON
        'top_selling_variants': top_80_percent_variants,  # Pass the ordered list of top-selling variants
        'top_selling_sizes': top_selling_sizes,  # Pass the ordered list of top-selling sizes
        'top_selling_colors': top_selling_colors,  # Pass the ordered list of top-selling colors
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
