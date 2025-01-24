from django.shortcuts import render
from django.db.models import Count, Sum, Max, F, Subquery, OuterRef
from django.http import HttpResponse
from .models import Product, ProductVariant, InventorySnapshot

def home(request):
    context = {}
    return render(request, 'inventory/home.html', context)


def product_list(request):
    # Subquery to fetch the latest inventory snapshot for each variant
    latest_snapshot = InventorySnapshot.objects.filter(
        product_variant=OuterRef('pk')
    ).order_by('-date').values('inventory_count')[:1]

    # Annotate variants with their latest inventory count
    variants_with_inventory = ProductVariant.objects.annotate(
        latest_inventory=Subquery(latest_snapshot)
    )

    # Annotate products with aggregated data
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

    # Calculate items with zero inventory (products where all variants have zero inventory)
    products_with_zero_inventory = [
        product for product in products if all(
            (variant.latest_inventory or 0) == 0
            for variant in variants_with_inventory.filter(product=product)
        )
    ]

    # Summary metrics
    latest_snapshot_date = InventorySnapshot.objects.aggregate(latest_date=Max('date'))['latest_date']
    total_inventory = sum(product.total_inventory for product in products)
    total_zero_inventory_items = len(products_with_zero_inventory)

    context = {
        'products': products,
        'summary': {
            'latest_snapshot_date': latest_snapshot_date,
            'total_products': products.count(),
            'total_inventory': total_inventory,
            'total_zero_inventory_items': total_zero_inventory_items,
        },
    }
    return render(request, 'inventory/product_list.html', context)




def inventory_snapshots(request):
    # Aggregate inventory levels for each snapshot date
    snapshots = (
        InventorySnapshot.objects.values('date')
        .annotate(total_inventory=Sum('inventory_count'))
        .order_by('-date')
    )

    context = {'snapshots': snapshots}
    return render(request, 'inventory/inventory_snapshots.html', context)
