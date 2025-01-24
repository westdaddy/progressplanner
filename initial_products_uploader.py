import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Replace 'myproject' with your project's name

import django
django.setup()


import csv
from inventory.models import Product

# Define the path to your CSV file
CSV_FILE_PATH = 'initialdata/product_list.csv'

def import_products():
    with open(CSV_FILE_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            # Create or update product
            product, created = Product.objects.update_or_create(
                product_id=row['product_id'],
                defaults={
                    'product_name': row['product_name'],
                }
            )

            if created:
                print(f"Created: {product.product_name} ({product.product_id})")
            else:
                print(f"Updated: {product.product_name} ({product.product_id})")

if __name__ == "__main__":
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')  # Update with your project name
    django.setup()

    import_products()
    print("Product import completed!")
