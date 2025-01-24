from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Sum, Max, F, Subquery, OuterRef
from django.http import HttpResponse
from .models import Product, ProductVariant, InventorySnapshot

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

    context = {
        'product': product,
    }
    return render(request, 'inventory/product_detail.html', context)


def inventory_snapshots(request):
    # Aggregate inventory levels for each snapshot date
    snapshots = (
        InventorySnapshot.objects.values('date')
        .annotate(total_inventory=Sum('inventory_count'))
        .order_by('-date')
    )

    context = {'snapshots': snapshots}
    return render(request, 'inventory/inventory_snapshots.html', context)
