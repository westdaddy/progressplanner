from django.contrib import admin
from .models import Product, ProductVariant, Sale, InventorySnapshot, Order, OrderItem

from datetime import datetime, timedelta, date
from django.utils.timezone import now
from django.urls import reverse
from django import forms
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import path
from django.http import JsonResponse
from django.utils.safestring import mark_safe
from django.contrib.admin.widgets import FilteredSelectMultiple



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
    extra = 0
    readonly_fields = ('product_variant',)  # Display as text rather than a dropdown
    fields = ('product_variant', 'quantity', 'item_cost_price', 'date_expected', 'date_arrived', 'actual_quantity')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('product_variant')



@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'order_date', 'invoice_id')
    search_fields = ('id', 'invoice_id')
    inlines = [OrderItemInline]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:order_id>/add_products/',
                self.admin_site.admin_view(self.add_products_view),
                name='order-add-products'
            ),
        ]
        return custom_urls + urls

    def add_products_view(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        if request.method == 'POST':
            form = AddProductsForm(request.POST)
            if form.is_valid():
                products = form.cleaned_data['products']
                cost_price = form.cleaned_data['item_cost_price']
                date_expected = form.cleaned_data['date_expected']
                product_variants = ProductVariant.objects.filter(product__in=products)
                # Create an order item for each variant
                for variant in product_variants:
                    OrderItem.objects.create(
                        order=order,
                        product_variant=variant,
                        quantity=0,            # default quantity (editable later)
                        item_cost_price=cost_price,
                        date_expected=date_expected,
                    )
                self.message_user(request, "Products added successfully.", messages.SUCCESS)
                return redirect(reverse('admin:inventory_order_change', args=[order.id]))
        else:
            form = AddProductsForm()
        context = {
            'order': order,
            'form': form,
            'opts': self.model._meta,
            'app_label': self.model._meta.app_label,
        }
        return render(request, 'admin/add_products.html', context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        # Build the URL to our custom add_products view.
        extra_context['add_products_url'] = reverse('admin:order-add-products', args=[object_id])
        return super().change_view(request, object_id, form_url, extra_context=extra_context)




class AddProductsForm(forms.Form):
    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.all(),
        widget=FilteredSelectMultiple("Products", is_stacked=False),
        required=True,
        help_text="Select one or more products to add their variants as order items."
    )
    item_cost_price = forms.DecimalField(
        required=True,
        max_digits=10,
        decimal_places=2,
        initial=0,
        help_text="Set the cost price for each order item."
    )
    date_expected = forms.DateField(
        required=True,
        initial=date.today,  # or you can set a calculated default
        help_text="Set the expected date for the order items."
    )

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'product_variant', 'quantity', 'item_cost_price', 'date_expected', 'date_arrived', 'actual_quantity', 'order')
    search_fields = ('product_variant__variant_code', 'order__id')
    list_filter = ('date_expected', 'date_arrived')
