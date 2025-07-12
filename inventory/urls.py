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
    path('returns/', views.returns, name='returns'), 
]
