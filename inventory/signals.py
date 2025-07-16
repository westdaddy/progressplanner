from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import InventorySnapshot, Sale, OrderItem

CACHE_KEYS = {
    'safe': 'safe_stock_{id}',
    'proj': 'variant_proj_{id}',
    'health': 'product_health_{id}',
}


def invalidate_product_cache(product_id):
    keys = [v.format(id=product_id) for v in CACHE_KEYS.values()]
    cache.delete_many(keys)


@receiver([post_save, post_delete], sender=InventorySnapshot)
def invalidate_inventory_cache(sender, instance, **kwargs):
    invalidate_product_cache(instance.product_variant.product_id)


@receiver([post_save, post_delete], sender=Sale)
def invalidate_sale_cache(sender, instance, **kwargs):
    invalidate_product_cache(instance.variant.product_id)


@receiver([post_save, post_delete], sender=OrderItem)
def invalidate_orderitem_cache(sender, instance, **kwargs):
    invalidate_product_cache(instance.product_variant.product_id)

