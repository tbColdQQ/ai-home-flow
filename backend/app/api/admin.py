import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_user
from app.db.session import get_connection, rows_to_dicts
from app.services.auth_service import CurrentUser, hash_password


router = APIRouter()
STORE_MANAGER_ROLE_CODES = {"clerk", "rental_clerk"}
STORE_MANAGER_FORBIDDEN_ROLE_CODES = {"admin", "store_manager", "rental_agent"}


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


def _is_store_managed_user(conn, target_user_id: int, store_id: int | None) -> bool:
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
        HAVING SUM(CASE WHEN r.code IN ('clerk', 'rental_clerk') THEN 1 ELSE 0 END) > 0
           AND SUM(CASE WHEN r.code IN ('admin', 'store_manager', 'rental_agent') THEN 1 ELSE 0 END) = 0
        """,
        (target_user_id, store_id),
    ).fetchone()
    return row is not None


def _role_codes_from_csv(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _ensure_store_manager_role_scope(role_codes: list[str]) -> list[str]:
    normalized = [code for code in dict.fromkeys(role_codes) if code]
    if not normalized:
        normalized = ["clerk"]
    if not set(normalized).issubset(STORE_MANAGER_ROLE_CODES):
        raise HTTPException(status_code=403, detail="店长只能分配店员或租赁店员角色")
    return normalized


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
        visible = []
        for item in result:
            role_codes = _role_codes_from_csv(item.get("role_codes"))
            if role_codes.intersection(STORE_MANAGER_ROLE_CODES) and not role_codes.intersection(STORE_MANAGER_FORBIDDEN_ROLE_CODES):
                visible.append(item)
        return visible


@router.post("/users")
def create_user(body: CreateUserRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_user_manager(user)
    with get_connection() as conn:
        city_id = body.city_id
        store_id = body.store_id
        role_codes = body.role_codes
        if "admin" not in user.role_codes:
            if user.store_id is None:
                raise HTTPException(status_code=400, detail="当前店长未绑定门店")
            role_codes = _ensure_store_manager_role_scope(role_codes)
            store_id = user.store_id
            store = conn.execute("SELECT city_id FROM stores WHERE id = ? AND status != 'deleted'", (store_id,)).fetchone()
            if store is None:
                raise HTTPException(status_code=400, detail="当前门店不存在")
            city_id = store["city_id"]
        elif city_id is None:
            city = conn.execute("SELECT id FROM cities ORDER BY id LIMIT 1").fetchone()
            city_id = city["id"] if city else None
        cursor = conn.execute(
            """
            INSERT INTO users(username, display_name, password_hash, city_id, store_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (body.username, body.display_name, hash_password(body.password), city_id, store_id),
        )
        user_id = int(cursor.lastrowid)
        for code in role_codes:
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
        if "admin" not in user.role_codes and not _is_store_managed_user(conn, user_id, user.store_id):
            raise HTTPException(status_code=403, detail="店长只能重置所在门店店员或租赁店员的密码")
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
    ensure_user_manager(user)
    where_sql = ""
    params: tuple = ()
    if "admin" not in user.role_codes:
        where_sql = "WHERE r.code IN (?, ?)"
        params = tuple(sorted(STORE_MANAGER_ROLE_CODES))
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT r.*, GROUP_CONCAT(p.code) AS permission_codes
            FROM roles r
            LEFT JOIN role_permissions rp ON rp.role_id = r.id
            LEFT JOIN permissions p ON p.id = rp.permission_id
            {where_sql}
            GROUP BY r.id
            ORDER BY r.id
            """,
            params,
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
    ensure_user_manager(user)
    where_sql = "s.status != 'deleted'"
    params: tuple = ()
    if "admin" not in user.role_codes:
        where_sql += " AND s.id = ?"
        params = (user.store_id,)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT s.*, c.name AS city
            FROM stores s
            LEFT JOIN cities c ON c.id = s.city_id
            WHERE {where_sql}
            ORDER BY s.id
            """,
            params,
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
