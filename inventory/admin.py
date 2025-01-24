from django.contrib import admin
from .models import Product, ProductVariant, Sale, InventorySnapshot

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('product_id', 'product_name')  # Customize columns in the admin list view


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('product', 'variant_code', 'size', 'type', 'style', 'age', 'gender')
    list_filter = ('product', 'size', 'type', 'style', 'age', 'gender')  # Add filters for easy management

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('sale_id', 'date', 'variant', 'sold_quantity', 'return_quantity', 'sold_value', 'return_value')
    list_filter = ('sale_id', 'date', 'variant', 'sold_quantity', 'return_quantity', 'sold_value', 'return_value')  # Add filters for easy management


@admin.register(InventorySnapshot)
class InventorySnapshotAdmin(admin.ModelAdmin):
    list_display = ('product_variant', 'date', 'inventory_count')
    list_filter = ('product_variant', 'date', 'inventory_count')  # Add filters for easy management
