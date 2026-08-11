import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.migrations import migrate
from app.services.image_import_service import scan_images


if __name__ == "__main__":
    migrate()
    print(scan_images())
