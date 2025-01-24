from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.product_list, name='product_list'),
    path('inventory-snapshots/', views.inventory_snapshots, name='inventory_snapshots'),
    path('products/<int:product_id>/', views.product_detail, name='product_detail'),  # New route
]
