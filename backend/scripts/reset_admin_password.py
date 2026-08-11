import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.migrations import migrate
from app.services.auth_service import reset_admin_password


if __name__ == "__main__":
    migrate()
    print(f"admin password reset: {reset_admin_password()}")
