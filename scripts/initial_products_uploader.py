import os
import django
import sys
import logging

# Set the path to the project root (where manage.py is located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Adjust if your settings module differs
django.setup()

import csv
from inventory.models import Product

logger = logging.getLogger(__name__)

# Define the path to your CSV file
CSV_FILE_PATH = 'data/initialdata/product_list.csv'

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
                logger.info("Created: %s (%s)", product.product_name, product.product_id)
            else:
                logger.info("Updated: %s (%s)", product.product_name, product.product_id)

if __name__ == "__main__":
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')  # Update with your project name
    django.setup()

    logging.basicConfig(level=logging.INFO)

    import_products()
    logger.info("Product import completed!")
