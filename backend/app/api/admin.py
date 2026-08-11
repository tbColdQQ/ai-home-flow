import secrets

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


class StoreRequest(BaseModel):
    city_id: int
    name: str
    area: str | None = None
    street: str | None = None
    status: str = "active"


class RoleRequest(BaseModel):
    code: str
    name: str
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)


class PermissionRequest(BaseModel):
    code: str
    name: str
    permission_type: str = "api"
    description: str | None = None


def ensure_admin(user: CurrentUser) -> None:
    if "admin" not in user.role_codes:
        raise HTTPException(status_code=403, detail="需要管理员权限")


def ensure_user_manager(user: CurrentUser) -> None:
    if not {"admin", "store_manager"}.intersection(user.role_codes):
        raise HTTPException(status_code=403, detail="需要用户管理权限")


def _is_store_clerk(conn, target_user_id: int, store_id: int | None) -> bool:
    if store_id is None:
        return False
    row = conn.execute(
        """
        SELECT u.id
        FROM users u
        JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id
        WHERE u.id = ?
          AND u.store_id = ?
          AND u.status = 'active'
        GROUP BY u.id
        HAVING SUM(CASE WHEN r.code = 'clerk' THEN 1 ELSE 0 END) > 0
           AND SUM(CASE WHEN r.code IN ('admin', 'store_manager') THEN 1 ELSE 0 END) = 0
        """,
        (target_user_id, store_id),
    ).fetchone()
    return row is not None


def _replace_role_permissions(conn, role_id: int, permission_codes: list[str]) -> None:
    conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
    for code in permission_codes:
        permission = conn.execute("SELECT id FROM permissions WHERE code = ?", (code,)).fetchone()
        if permission:
            conn.execute(
                "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?)",
                (role_id, permission["id"]),
            )


@router.get("/overview")
def overview(user: CurrentUser = Depends(current_user)) -> dict:
    ensure_admin(user)
    with get_connection() as conn:
        return {
            "users": conn.execute("SELECT COUNT(*) AS total FROM users WHERE status = 'active'").fetchone()["total"],
            "roles": conn.execute("SELECT COUNT(*) AS total FROM roles").fetchone()["total"],
            "permissions": conn.execute("SELECT COUNT(*) AS total FROM permissions").fetchone()["total"],
            "orders": conn.execute("SELECT COUNT(*) AS total FROM orders WHERE COALESCE(status, 'normal') = 'normal'").fetchone()["total"],
            "pending_tasks": conn.execute("SELECT COUNT(*) AS total FROM task_items WHERE status = 'pending'").fetchone()["total"],
        }


@router.get("/users")
def list_users(user: CurrentUser = Depends(current_user)) -> list[dict]:
    ensure_user_manager(user)
    where_sql = "u.status = 'active'"
    params: tuple = ()
    if "admin" not in user.role_codes:
        where_sql += " AND u.store_id = ?"
        params = (user.store_id,)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT u.id, u.username, u.display_name, u.status, u.city_id, u.store_id,
                   c.name AS city, s.name AS store,
                   GROUP_CONCAT(r.code) AS role_codes,
                   GROUP_CONCAT(r.name) AS role_names
            FROM users u
            LEFT JOIN cities c ON c.id = u.city_id
            LEFT JOIN stores s ON s.id = u.store_id
            LEFT JOIN user_roles ur ON ur.user_id = u.id
            LEFT JOIN roles r ON r.id = ur.role_id
            WHERE {where_sql}
            GROUP BY u.id
            ORDER BY u.id DESC
            """,
            params,
        ).fetchall()
        result = rows_to_dicts(rows)
        if "admin" in user.role_codes:
            return result
        return [item for item in result if item.get("role_codes") == "clerk"]


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
        exists = conn.execute("SELECT id FROM users WHERE id = ? AND status = 'active'", (user_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for code in body.role_codes:
            role = conn.execute("SELECT id FROM roles WHERE code = ?", (code,)).fetchone()
            if role:
                conn.execute("INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)", (user_id, role["id"]))
        conn.commit()
    return {"message": "updated"}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录用户")
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET status = 'deleted', modify_time = CURRENT_TIMESTAMP WHERE id = ? AND status = 'active'",
            (user_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute("UPDATE auth_sessions SET revoked = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    return {"message": "deleted"}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_user_manager(user)
    with get_connection() as conn:
        exists = conn.execute("SELECT id FROM users WHERE id = ? AND status = 'active'", (user_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        if "admin" not in user.role_codes and not _is_store_clerk(conn, user_id, user.store_id):
            raise HTTPException(status_code=403, detail="店长只能重置所在门店店员的密码")
        password = secrets.token_urlsafe(10)
        conn.execute(
            "UPDATE users SET password_hash = ?, modify_time = CURRENT_TIMESTAMP WHERE id = ?",
            (hash_password(password), user_id),
        )
        conn.execute("UPDATE auth_sessions SET revoked = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    return {"password": password}


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


@router.post("/roles")
def create_role(body: RoleRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_admin(user)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO roles(code, name, description) VALUES (?, ?, ?)",
            (body.code, body.name, body.description),
        )
        role_id = int(cursor.lastrowid)
        _replace_role_permissions(conn, role_id, body.permission_codes)
        conn.commit()
        return {"id": role_id}


@router.put("/roles/{role_id}")
def update_role(role_id: int, body: RoleRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE roles SET code = ?, name = ?, description = ? WHERE id = ?",
            (body.code, body.name, body.description, role_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="角色不存在")
        _replace_role_permissions(conn, role_id, body.permission_codes)
        conn.commit()
    return {"message": "updated"}


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    with get_connection() as conn:
        used = conn.execute("SELECT 1 FROM user_roles WHERE role_id = ? LIMIT 1", (role_id,)).fetchone()
        if used:
            raise HTTPException(status_code=400, detail="角色已分配给用户，不能删除")
        exists = conn.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="角色不存在")
        conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        conn.commit()
    return {"message": "deleted"}


@router.get("/permissions")
def list_permissions(user: CurrentUser = Depends(current_user)) -> list[dict]:
    ensure_admin(user)
    with get_connection() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM permissions ORDER BY id").fetchall())


@router.post("/permissions")
def create_permission(body: PermissionRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_admin(user)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO permissions(code, name, permission_type, description) VALUES (?, ?, ?, ?)",
            (body.code, body.name, body.permission_type, body.description),
        )
        conn.commit()
        return {"id": int(cursor.lastrowid)}


@router.put("/permissions/{permission_id}")
def update_permission(permission_id: int, body: PermissionRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE permissions SET code = ?, name = ?, permission_type = ?, description = ? WHERE id = ?",
            (body.code, body.name, body.permission_type, body.description, permission_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="权限不存在")
        conn.commit()
    return {"message": "updated"}


@router.delete("/permissions/{permission_id}")
def delete_permission(permission_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    with get_connection() as conn:
        used = conn.execute("SELECT 1 FROM role_permissions WHERE permission_id = ? LIMIT 1", (permission_id,)).fetchone()
        if used:
            raise HTTPException(status_code=400, detail="权限已分配给角色，不能删除")
        cursor = conn.execute("DELETE FROM permissions WHERE id = ?", (permission_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="权限不存在")
        conn.commit()
    return {"message": "deleted"}


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
            WHERE s.status != 'deleted'
            ORDER BY s.id
            """
        ).fetchall()
        return rows_to_dicts(rows)


@router.post("/stores")
def create_store(body: StoreRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_admin(user)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO stores(city_id, name, area, street, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (body.city_id, body.name, body.area, body.street, body.status),
        )
        conn.commit()
        return {"id": int(cursor.lastrowid)}


@router.put("/stores/{store_id}")
def update_store(store_id: int, body: StoreRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE stores
            SET city_id = ?, name = ?, area = ?, street = ?, status = ?, modify_time = CURRENT_TIMESTAMP
            WHERE id = ? AND status != 'deleted'
            """,
            (body.city_id, body.name, body.area, body.street, body.status, store_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="门店不存在")
        conn.commit()
    return {"message": "updated"}


@router.delete("/stores/{store_id}")
def delete_store(store_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_admin(user)
    with get_connection() as conn:
        used = conn.execute("SELECT 1 FROM users WHERE store_id = ? AND status = 'active' LIMIT 1", (store_id,)).fetchone()
        if used:
            raise HTTPException(status_code=400, detail="门店下还有 active 用户，不能删除")
        cursor = conn.execute(
            "UPDATE stores SET status = 'deleted', modify_time = CURRENT_TIMESTAMP WHERE id = ? AND status != 'deleted'",
            (store_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="门店不存在")
        conn.commit()
    return {"message": "deleted"}
