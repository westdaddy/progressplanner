from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.product_list, name='product_list'),
    path('products/filtered/', views.product_filtered, name='product_filtered'),
    path('products/type/<str:type_code>/', views.product_type_list, name='product_type_list'),
    path('products/style/<str:style_code>/', views.product_style_list, name='product_style_list'),
    path('products/group/<int:group_id>/', views.product_group_list, name='product_group_list'),
    path('products/series/<int:series_id>/', views.product_series_list, name='product_series_list'),
    path('products/canvas/', views.product_canvas, name='product_canvas'),
    path('products/canvas/layout/', views.product_canvas_layout, name='product_canvas_layout'),
    path('products/canvas/image/<int:product_id>/', views.product_canvas_image, name='product_canvas_image'),
    path('inventory-snapshots/', views.inventory_snapshots, name='inventory_snapshots'),
    path('products/<int:product_id>/', views.product_detail, name='product_detail'),  # New route
    path('orders/', views.order_list, name='order_list'),  # Order List View
    path('orders/search/', views.order_product_search, name='order_product_search'),
    path('orders/items/create/', views.order_item_create, name='order_item_create'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),  # Order Detail View
    path('sales/', views.sales, name='sales'),
    path('sales/referrers/', views.sales_referrers, name='sales_referrers'),
    path('sales/referrers/overview/', views.referrers_overview, name='referrers_overview'),
    path('sales/referrers/<int:referrer_id>/', views.referrer_detail, name='referrer_detail'),
    path('sales/price-group/<str:bucket_key>/', views.sales_bucket_detail, name='sales_bucket_detail'),
    path(
        'sales/price-group/<str:bucket_key>/assign-referrer/',
        views.assign_order_referrer,
        name='assign_order_referrer',
    ),
    path('returns/', views.returns, name='returns'),
    path('sales-data/', views.sales_data, name='sales_data'),
]
