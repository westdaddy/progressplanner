import os
import django
import sys

# Set the path to the project root (where manage.py is located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Adjust if your settings module differs
django.setup()


import csv
from inventory.models import Product, ProductVariant

# Define the path to your CSV file
CSV_FILE_PATH = 'initialdata/variants_list.csv'

# Map color names to hex codes
COLOR_TO_HEX = {
    'white': '#FFFFFF',
    'black': '#000000',
    'blue': '#0000FF',
    'red': '#FF0000',
    'green': '#00FF00',
    'yellow': '#FFFF00',
    'grey': '#808080',
    'purple': '#800080',
    'lilac': '#C8A2C8',
}

def map_color_to_hex(color_name):
    """Map color names to hex codes, or return a default value."""
    return COLOR_TO_HEX.get(color_name.lower(), '#FFFFFF')  # Default to white

def import_variants():
    # Load the CSV file
    with open(CSV_FILE_PATH, newline='', encoding='latin1') as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            try:
                # Ensure the product exists
                product = Product.objects.filter(product_id=row['product_code']).first()
                if not product:
                    print(f"Skipping: Product with code '{row['product_code']}' not found.")
                    continue

                # Map colors to hex
                primary_color_hex = map_color_to_hex(row['primary_color'])
                secondary_color_hex = map_color_to_hex(row['color'])

                if not primary_color_hex:
                    print(f"Skipping row due to unknown primary color: {row}")
                    continue

                # Check for existing variant
                variant = ProductVariant.objects.filter(variant_code=row['variant_code']).first()

                if variant:
                    # Handle duplicate logic here
                    variant.primary_color = primary_color_hex or variant.primary_color
                    variant.secondary_color = secondary_color_hex or variant.secondary_color
                    # Update other fields...
                    variant.save()
                    print(f"Updated: Variant {variant.variant_code}")
                else:
                    # Create a new variant
                    ProductVariant.objects.create(
                        product=product,
                        variant_code=row['variant_code'],
                        primary_color=primary_color_hex,
                        secondary_color=secondary_color_hex,
                        size=row['size'] or None,
                        type=row['type'] or None,
                        style=row['style'] or None,
                        age=row['age'] or None,
                        gender=row['gender'] or None,
                    )
                    print(f"Created: Variant {row['variant_code']}")

            except Exception as e:
                print(f"Error processing row {row}: {e}")


if __name__ == "__main__":
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'inventory.settings')  # Update with your project name
    django.setup()

    import_variants()
    print("Variant import completed!")
