import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.migrations import migrate
from app.services.auth_service import ensure_initial_admin


if __name__ == "__main__":
    migrate()
    password = ensure_initial_admin()
    print("home-flow database initialized")
    if password:
        print(f"initial admin: admin")
        print(f"initial password: {password}")
