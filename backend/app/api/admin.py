from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_user
from app.db.session import get_connection, rows_to_dicts
from app.services.auth_service import CurrentUser, hash_password


router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    display_name: str
    password: str
    city_id: int | None = None
    store_id: int | None = None
    role_codes: list[str] = Field(default_factory=lambda: ["clerk"])


class UpdateUserRolesRequest(BaseModel):
    role_codes: list[str]


def ensure_admin(user: CurrentUser) -> None:
    if "admin" not in user.role_codes:
        raise HTTPException(status_code=403, detail="\u9700\u8981\u7ba1\u7406\u5458\u6743\u9650")


@router.get("/overview")
def overview(user: CurrentUser = Depends(current_user)) -> dict:
    ensure_admin(user)
    with get_connection() as conn:
        return {
            "users": conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"],
            "roles": conn.execute("SELECT COUNT(*) AS total FROM roles").fetchone()["total"],
            "permissions": conn.execute("SELECT COUNT(*) AS total FROM permissions").fetchone()["total"],
            "orders": conn.execute("SELECT COUNT(*) AS total FROM orders").fetchone()["total"],
            "pending_tasks": conn.execute("SELECT COUNT(*) AS total FROM task_items WHERE status = 'pending'").fetchone()["total"],
        }


@router.get("/users")
def list_users(user: CurrentUser = Depends(current_user)) -> list[dict]:
    ensure_admin(user)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.status, c.name AS city, s.name AS store,
                   GROUP_CONCAT(r.code) AS role_codes,
                   GROUP_CONCAT(r.name) AS role_names
            FROM users u
            LEFT JOIN cities c ON c.id = u.city_id
            LEFT JOIN stores s ON s.id = u.store_id
            LEFT JOIN user_roles ur ON ur.user_id = u.id
            LEFT JOIN roles r ON r.id = ur.role_id
            GROUP BY u.id
            ORDER BY u.id DESC
            """
        ).fetchall()
        return rows_to_dicts(rows)


@router.post("/users")
def create_user(body: CreateUserRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_admin(user)
    with get_connection() as conn:
        city_id = body.city_id
        if city_id is None:
            city = conn.execute("SELECT id FROM cities ORDER BY id LIMIT 1").fetchone()
            city_id = city["id"] if city else None
        cursor = conn.execute(
            """
            INSERT INTO users(username, display_name, password_hash, city_id, store_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (body.username, body.display_name, hash_password(body.password), city_id, body.store_id),
        )
        user_id = int(cursor.lastrowid)
        for code in body.role_codes:
            role = conn.execute("SELECT id FROM roles WHERE code = ?", (code,)).fetchone()
            if role:
                conn.execute("INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)", (user_id, role["id"]))
        conn.commit()
        return {"id": user_id}


@router.put("/users/{user_id}/roles")
def update_user_roles(user_id: int, body: UpdateUserRolesRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    with get_connection() as conn:
        exists = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="\u7528\u6237\u4e0d\u5b58\u5728")
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for code in body.role_codes:
            role = conn.execute("SELECT id FROM roles WHERE code = ?", (code,)).fetchone()
            if role:
                conn.execute("INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)", (user_id, role["id"]))
        conn.commit()
    return {"message": "updated"}


@router.get("/roles")
def list_roles(user: CurrentUser = Depends(current_user)) -> list[dict]:
    ensure_admin(user)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*, GROUP_CONCAT(p.code) AS permission_codes
            FROM roles r
            LEFT JOIN role_permissions rp ON rp.role_id = r.id
            LEFT JOIN permissions p ON p.id = rp.permission_id
            GROUP BY r.id
            ORDER BY r.id
            """
        ).fetchall()
        return rows_to_dicts(rows)


@router.get("/permissions")
def list_permissions(user: CurrentUser = Depends(current_user)) -> list[dict]:
    ensure_admin(user)
    with get_connection() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM permissions ORDER BY id").fetchall())


@router.get("/cities")
def list_cities(user: CurrentUser = Depends(current_user)) -> list[dict]:
    ensure_admin(user)
    with get_connection() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM cities ORDER BY id").fetchall())


@router.get("/stores")
def list_stores(user: CurrentUser = Depends(current_user)) -> list[dict]:
    ensure_admin(user)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT s.*, c.name AS city
            FROM stores s
            LEFT JOIN cities c ON c.id = s.city_id
            ORDER BY s.id
            """
        ).fetchall()
        return rows_to_dicts(rows)
