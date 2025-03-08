# inventory/templatetags/inventory_extras.py
from django import template

register = template.Library()

@register.filter
def to_int(value):
    """
    Converts a value to an integer. Returns 0 on failure.
    """
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0
