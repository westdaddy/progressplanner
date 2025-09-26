from django.contrib import admin
from .models import (
    Product,
    ProductVariant,
    Sale,
    InventorySnapshot,
    Order,
    OrderItem,
    Group,
    Series,
    RestockSetting,
    Referrer,
)

from datetime import datetime, timedelta, date
from django.utils.timezone import now
from django.urls import reverse
from django import forms
from django.contrib import messages
from django.contrib.admin.widgets import AdminDateWidget
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import path
from django.http import JsonResponse, HttpResponseRedirect
from django.db.models import Case, When, Value, IntegerField, Q
from django.utils.text import smart_split
from django.utils.translation import gettext_lazy as _
import logging

logger = logging.getLogger(__name__)
from django.utils.safestring import mark_safe
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME


class AssignReferrerForm(forms.Form):
    """Simple form to choose a Referrer for an admin action."""

    referrer = forms.ModelChoiceField(queryset=Referrer.objects.all(), required=True)
    _selected_action = forms.CharField(
        widget=forms.MultipleHiddenInput, required=False
    )


class SaleDateFilterForm(forms.Form):
    """Form that exposes a single date input for admin filtering."""

    date = forms.DateField(
        required=False,
        widget=AdminDateWidget(attrs={"placeholder": _("Select date")}),
        label=_("date"),
    )


class SaleDateEqualsFilter(admin.SimpleListFilter):
    """Simple list filter that matches sales that occur on a specific date."""

    title = _("date")
    parameter_name = "date"
    template = "admin/date_equals_filter.html"

    def __init__(self, request, params, model, model_admin):
        value = params.get(self.parameter_name)
        if value:
            self.form = SaleDateFilterForm(data={self.parameter_name: value})
        else:
            self.form = SaleDateFilterForm()
        super().__init__(request, params, model, model_admin)

    def has_output(self):
        return True

    def lookups(self, request, model_admin):
        return ()

    def queryset(self, request, queryset):
        if self.form.is_bound and self.form.is_valid():
            selected_date = self.form.cleaned_data.get(self.parameter_name)
            if selected_date:
                return queryset.filter(date=selected_date)
        return queryset

    def choices(self, changelist):
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": _("Clear"),
            "reset": True,
        }


def get_size_order_case(field_name="size"):
    """Return a Case expression ordering by size based on SIZE_CHOICES."""
    return Case(
        *[
            When(**{field_name: code}, then=Value(idx))
            for idx, (code, _label) in enumerate(ProductVariant.SIZE_CHOICES)
        ],
        default=Value(len(ProductVariant.SIZE_CHOICES)),
        output_field=IntegerField(),
    )



class ProductAdminForm(forms.ModelForm):
    """Form used for creating/editing Products with variant suggestions."""

    variant_sizes = forms.MultipleChoiceField(
        choices=ProductVariant.SIZE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select sizes to create variants for.",
    )

    class Meta:
        model = Product
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            existing = list(
                self.instance.variants.values_list("size", flat=True)
            )
            self.fields["variant_sizes"].initial = existing

    def save(self, commit=True):
        product = super().save(commit=commit)
        # store selected sizes for admin to create variants later
        self._pending_sizes = self.cleaned_data.get("variant_sizes", [])

        return product


class ProductVariantInline(admin.TabularInline):
    """Inline for editing variants directly on the Product page."""
    model = ProductVariant
    extra = 1
    fields = (
        "variant_code",
        "size",
        "gender",
        "primary_color",
        "secondary_color",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_size_order=get_size_order_case()).order_by(
            "_size_order",
            "variant_code",
        )




@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = (
        "product_id",
        "product_name",
        "retail_price",
        "restock_time",
        "type",
        "style",
        "age",
    )
    list_filter = ("groups", "series", "type", "style", "age")
    inlines = [ProductVariantInline]

    class Media:
        js = ("admin/js/product_admin.js",)

    def save_model(self, request, obj, form, change):
        """Create selected variants after saving the Product."""
        super().save_model(request, obj, form, change)
        sizes = getattr(form, "_pending_sizes", [])
        for size in sizes:
            code = f"{obj.product_id}-{size}"
            ProductVariant.objects.get_or_create(
                product=obj,
                variant_code=code,
                defaults={"size": size, "gender": "male"},
            )



@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "variant_code", "size", "gender")
    list_filter = ("product", "size", "gender")  # Add filters for easy management

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_size_order=get_size_order_case()).order_by(
            "_size_order",
            "variant_code",
        )



@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        "sale_id",
        "date",
        "variant",
        "sold_quantity",
        "return_quantity",
        "sold_value",
        "return_value",
        "referrer",
    )
    list_filter = (SaleDateEqualsFilter, "referrer")
    search_fields = ("order_number",)
    actions = ["assign_referrer"]

    def get_search_results(self, request, queryset, search_term):
        tokens = [token.strip() for token in smart_split(search_term) if token.strip()]

        if len(tokens) <= 1:
            return super().get_search_results(request, queryset, search_term)

        order_query = Q()
        for token in tokens:
            order_query |= Q(order_number__iexact=token)

        queryset = queryset.filter(order_query)
        return queryset, False

    def assign_referrer(self, request, queryset):
        """Admin action to assign a single referrer to selected sales."""

        if "apply" in request.POST:
            form = AssignReferrerForm(request.POST)
            if form.is_valid():
                referrer = form.cleaned_data["referrer"]
                updated = queryset.update(referrer=referrer)
                self.message_user(
                    request,
                    f"Successfully assigned {referrer} to {updated} sale(s).",
                    messages.SUCCESS,
                )
                return HttpResponseRedirect(request.get_full_path())
        else:
            form = AssignReferrerForm(
                initial={
                    "_selected_action": request.POST.getlist(ACTION_CHECKBOX_NAME)
                }
            )

        context = {
            "title": "Assign referrer",
            "queryset": queryset,
            "form": form,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "opts": self.model._meta,
            "media": self.media + form.media,
            "action_name": "assign_referrer",
            "select_across": request.POST.get("select_across"),
        }

        return render(request, "admin/inventory/sale/assign_referrer.html", context)

    assign_referrer.short_description = "Assign referrer to selected sales"


@admin.register(InventorySnapshot)
class InventorySnapshotAdmin(admin.ModelAdmin):
    list_display = ("product_variant", "date", "inventory_count")
    list_filter = (
        "product_variant",
        "date",
        "inventory_count",
    )  # Add filters for easy management


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(RestockSetting)
class RestockSettingAdmin(admin.ModelAdmin):
    filter_horizontal = ("groups",)


@admin.register(Referrer)
class ReferrerAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product_variant",)  # Display as text rather than a dropdown
    fields = (
        "product_variant",
        "quantity",
        "item_cost_price",
        "date_expected",
        "date_arrived",
        "actual_quantity",
    )
    template = "admin/orderitem_inline_grouped.html"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return (
            queryset.select_related("product_variant", "product_variant__product")
            .annotate(_size_order=get_size_order_case("product_variant__size"))
            .order_by(
                "product_variant__product__product_name",
                "_size_order",
                "product_variant__variant_code",
            )
        )



@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_id",
        "order_date",
    )
    search_fields = ("id", "invoice_id")
    inlines = [OrderItemInline]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:order_id>/add_products/",
                self.admin_site.admin_view(self.add_products_view),
                name="order-add-products",
            ),
        ]
        return custom_urls + urls

    def add_products_view(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        if request.method == "POST":
            logger.debug("add_products_view POST called")
            form = AddProductsForm(request.POST)
            if form.is_valid():
                variants = form.cleaned_data["product_variants"]
                cost_price = form.cleaned_data["item_cost_price"]
                date_expected = form.cleaned_data["date_expected"]
                # Create an order item for each variant
                for variant in variants:
                    OrderItem.objects.create(
                        order=order,
                        product_variant=variant,
                        quantity=0,  # default quantity (editable later)
                        item_cost_price=cost_price,
                        date_expected=date_expected,
                    )
                self.message_user(
                    request, "Products added successfully.", messages.SUCCESS
                )
                return redirect(
                    reverse("admin:inventory_order_change", args=[order.id])
                )
        else:
            form = AddProductsForm()
        context = {
            "order": order,
            "form": form,
            "products": Product.objects.prefetch_related("variants").all(),
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
        }
        return render(request, "admin/add_products.html", context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        # Build the URL to our custom add_products view.
        extra_context["add_products_url"] = reverse(
            "admin:order-add-products", args=[object_id]
        )
        return super().change_view(
            request, object_id, form_url, extra_context=extra_context
        )


class AddProductsForm(forms.Form):
    product_variants = forms.ModelMultipleChoiceField(
        queryset=ProductVariant.objects.select_related("product"),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        help_text="Select the variants to add as order items.",
    )
    item_cost_price = forms.DecimalField(
        required=True,
        max_digits=10,
        decimal_places=2,
        initial=0,
        help_text="Set the cost price for each order item.",
    )
    date_expected = forms.DateField(
        required=True,
        initial=date.today,  # or you can set a calculated default
        help_text="Set the expected date for the order items.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_variants"].queryset = (
            ProductVariant.objects.select_related("product")
            .annotate(_size_order=get_size_order_case())
            .order_by("product__product_name", "_size_order", "variant_code")

        )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product_variant",
        "quantity",
        "item_cost_price",
        "date_expected",
        "date_arrived",
        "actual_quantity",
        "order",
    )
    search_fields = ("product_variant__variant_code", "order__id")
    list_filter = ("date_expected", "date_arrived")
