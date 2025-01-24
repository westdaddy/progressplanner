from datetime import datetime, timedelta
import json
from collections import defaultdict

from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Sum, Max, F, Subquery, OuterRef
from django.http import HttpResponse
from django.db.models.functions import TruncMonth

from .models import Product, ProductVariant, InventorySnapshot, Sale, Order, OrderItem




def home(request):
    context = {}
    return render(request, 'inventory/home.html', context)



def product_list(request):
    # Get the filter parameter from the request
    hide_zero_inventory = request.GET.get('hide_zero_inventory', 'false').lower() == 'true'

    # Subquery to fetch the latest inventory snapshot for each variant
    latest_snapshot = InventorySnapshot.objects.filter(
        product_variant=OuterRef('pk')
    ).order_by('-date').values('inventory_count')[:1]

    # Annotate variants with their latest inventory count
    variants_with_inventory = ProductVariant.objects.annotate(
        latest_inventory=Subquery(latest_snapshot)
    )

    # Fetch all products
    products = Product.objects.annotate(
        variant_count=Count('variants', distinct=True),
        total_sales=Sum('variants__sales__sold_quantity', default=0),
        total_sales_value=Sum('variants__sales__sold_value', default=0),
    )

    # Calculate total inventory for each product
    for product in products:
        product.total_inventory = sum(
            variant.latest_inventory or 0
            for variant in variants_with_inventory.filter(product=product)
        )

    # Apply filtering for zero inventory products
    if hide_zero_inventory:
        products = [product for product in products if product.total_inventory > 0]

    # Summary metrics
    latest_snapshot_date = InventorySnapshot.objects.aggregate(latest_date=Max('date'))['latest_date']
    total_inventory = sum(product.total_inventory for product in products)
    total_zero_inventory_items = len([
        product for product in products if product.total_inventory == 0
    ])

    context = {
        'products': products,
        'summary': {
            'latest_snapshot_date': latest_snapshot_date,
            'total_products': Product.objects.count(),
            'total_inventory': total_inventory,
            'total_zero_inventory_items': total_zero_inventory_items,
        },
        'hide_zero_inventory': hide_zero_inventory,
    }
    return render(request, 'inventory/product_list.html', context)




def product_detail(request, product_id):
    # Fetch the product by ID
    product = get_object_or_404(Product, id=product_id)

    # Get the date range parameter
    date_range = request.GET.get('range', '1y')  # Default to last 1 month
    today = datetime.today()
    if date_range == '3m':
        start_date = today - timedelta(days=90)
    elif date_range == '1y':
        start_date = today - timedelta(days=365)
    else:  # Default: 1 month
        start_date = today - timedelta(days=30)

    # Fetch sales data for this product, aggregated by month
    sales_data = (
        Sale.objects.filter(variant__product=product, date__gte=start_date)
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total_quantity=Sum('sold_quantity'))
        .order_by('month')
    )

    # Prepare data for the chart
    chart_data = {
        'months': [entry['month'].strftime('%Y-%m') for entry in sales_data],
        'quantities': [entry['total_quantity'] for entry in sales_data],
    }

    context = {
        'product': product,
        'chart_data': json.dumps(chart_data),  # Pass chart data as JSON
        'date_range': date_range,
    }
    return render(request, 'inventory/product_detail.html', context)


# Order List View
def order_list(request):
    orders = Order.objects.all()

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

    # Group items by product and include total quantity
    grouped_items = {}
    for item in order_items:
        product = item.product_variant.product
        if product not in grouped_items:
            grouped_items[product] = {'items': [], 'total_quantity': 0}
        grouped_items[product]['items'].append(item)
        grouped_items[product]['total_quantity'] += item.quantity

    # Calculate total order value
    total_value = sum(item.item_cost_price * item.quantity for item in order_items)

    context = {
        'order': order,
        'grouped_items': grouped_items,
        'total_value': total_value,
    }
    return render(request, 'inventory/order_detail.html', context)



def inventory_snapshots(request):
    # Aggregate inventory levels for each snapshot date
    snapshots = (
        InventorySnapshot.objects.values('date')
        .annotate(total_inventory=Sum('inventory_count'))
        .order_by('-date')
    )

    context = {'snapshots': snapshots}
    return render(request, 'inventory/inventory_snapshots.html', context)
