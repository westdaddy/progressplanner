import os
import django
import sys
import logging

# ----------------------------------------------------------------
#  Adjust these paths/settings to point at your project correctly
# ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'progressplanner.settings')  # <-- your settings module
django.setup()


from django.db import transaction
from inventory.models import Sale

logger = logging.getLogger(__name__)

def delete_all_sales(dry_run=True):
    """
    If dry_run is True, just print how many would be deleted.
    Otherwise, delete all Sale records.
    """
    total = Sale.objects.count()
    logger.info("Found %s Sale records.", total)
    if dry_run:
        logger.info("Dry run mode – no records have been deleted.")
    else:
        with transaction.atomic():
            deleted, _ = Sale.objects.all().delete()
        logger.info("Deleted %s Sale records.", deleted)

if __name__ == "__main__":
    # Pass "go" as first arg to actually delete
    go = len(sys.argv) > 1 and sys.argv[1].lower() == "go"
    logging.basicConfig(level=logging.INFO)
    delete_all_sales(dry_run=not go)
    if not go:
        logger.info("\nTo really delete, run:\n    python delete_sales.py go")
