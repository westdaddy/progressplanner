import os
import django
import sys

# Set the path to the project root (where manage.py is located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # Adjust if your settings module differs
django.setup()

# Import the InventorySnapshot model
from inventory.models import InventorySnapshot

def delete_all_snapshots():
    confirm = input("Are you sure you want to delete all InventorySnapshot records? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Aborted.")
        return

    # Delete all snapshots
    deleted_count, _ = InventorySnapshot.objects.all().delete()
    print(f"Deleted {deleted_count} InventorySnapshot records.")

if __name__ == "__main__":
    delete_all_snapshots()
