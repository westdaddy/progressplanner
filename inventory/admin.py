from django.contrib import admin
from .models import Product, ProductVariant, Sale, InventorySnapshot, Order, OrderItem

from datetime import datetime, timedelta
from django.utils.timezone import now

from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path
from django.http import JsonResponse
from django.utils.safestring import mark_safe


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




class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0  # Avoid empty rows unless variants exist
    min_num = 0  # Allow no variants initially
    fields = ('product_variant', 'quantity', 'item_cost_price', 'date_expected', 'date_arrived', 'actual_quantity')

    def get_queryset(self, request):
        """ Filter to show only OrderItems linked to the order being edited. """
        queryset = super().get_queryset(request)
        return queryset.select_related('product_variant')


class OrderAdminForm(forms.ModelForm):
    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.all(),
        widget=admin.widgets.FilteredSelectMultiple("Products", is_stacked=False),
        required=False,
        help_text="Select one or more products. Their variants will be added automatically."
    )

    class Meta:
        model = Order
        fields = '__all__'

    def save(self, commit=True):
        instance = super().save(commit=False)

        # If products are selected, fetch their variants and create OrderItems
        if self.cleaned_data['products']:
            product_variants = ProductVariant.objects.filter(product__in=self.cleaned_data['products'])
            instance.save()  # Save the Order before adding OrderItems

            # Create OrderItems for all variants of selected products, setting default quantity
            now = datetime.now()
            for variant in product_variants:
                OrderItem.objects.create(
                    order=instance,
                    product_variant=variant,
                    quantity=0,  # Prevent NULL constraint error
                    item_cost_price=0,  # Prevent NULL constraint error
                    date_expected=(now.replace(day=1) + timedelta(days=60))
                )

        if commit:
            instance.save()
        return instance





@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    list_display = ('id', 'order_date', 'invoice_id')
    search_fields = ('id', 'invoice_id')
    inlines = [OrderItemInline]

    class Media:
        js = ('admin/js/order_admin.js',)

    def get_urls(self):
        """ Add a custom URL for fetching product variants. """
        urls = super().get_urls()
        custom_urls = [
            path('get_variants_from_products/', self.admin_site.admin_view(self.get_variants_from_products))
        ]
        return custom_urls + urls

    def get_variants_from_products(self, request):
        """ API Endpoint: Returns a JSON response with variants from selected products. """
        product_ids = request.GET.get('product_ids', '').split(',')
        variants = ProductVariant.objects.filter(product_id__in=product_ids)

        variant_data = [{'id': v.id, 'variant_code': v.variant_code} for v in variants]
        return JsonResponse({'variants': variant_data})


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'product_variant', 'quantity', 'item_cost_price', 'date_expected', 'date_arrived', 'actual_quantity', 'order')
    search_fields = ('product_variant__variant_code', 'order__id')
    list_filter = ('date_expected', 'date_arrived')
