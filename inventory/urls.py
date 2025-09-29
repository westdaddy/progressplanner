from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('products/', views.product_list, name='product_list'),
    path('inventory-snapshots/', views.inventory_snapshots, name='inventory_snapshots'),
    path('products/<int:product_id>/', views.product_detail, name='product_detail'),  # New route
    path('orders/', views.order_list, name='order_list'),  # Order List View
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
