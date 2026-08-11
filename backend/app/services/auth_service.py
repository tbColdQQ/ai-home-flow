import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import settings
from app.db.session import get_connection


SESSION_HOURS = 12


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    city: str
    role_codes: list[str]
    store_id: int | None = None


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    parts = password_hash.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    iterations = int(parts[1])
    salt = bytes.fromhex(parts[2])
    expected = bytes.fromhex(parts[3])
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(actual, expected)


def ensure_initial_admin() -> str | None:
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        if existing is not None:
            return None

        city = conn.execute("SELECT id FROM cities WHERE name = ?", (settings.default_city,)).fetchone()
        city_id = city["id"]
        default_store = "\u9ed8\u8ba4\u95e8\u5e97"
        conn.execute(
            "INSERT OR IGNORE INTO stores(city_id, name) VALUES (?, ?)",
            (city_id, default_store),
        )
        store = conn.execute(
            "SELECT id FROM stores WHERE city_id = ? AND name = ?",
            (city_id, default_store),
        ).fetchone()

        password = secrets.token_urlsafe(12)
        cursor = conn.execute(
            """
            INSERT INTO users(username, display_name, password_hash, city_id, store_id)
            VALUES ('admin', ?, ?, ?, ?)
            """,
            ("\u7cfb\u7edf\u7ba1\u7406\u5458", hash_password(password), city_id, store["id"]),
        )
        role = conn.execute("SELECT id FROM roles WHERE code = 'admin'").fetchone()
        conn.execute(
            "INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)",
            (int(cursor.lastrowid), role["id"]),
        )
        conn.commit()
        return password


def reset_admin_password() -> str:
    password = secrets.token_urlsafe(12)
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = 'admin'",
            (hash_password(password),),
        )
        conn.execute(
            "UPDATE auth_sessions SET revoked = 1 WHERE user_id = (SELECT id FROM users WHERE username = 'admin')"
        )
        conn.commit()
    return password


def get_user(username: str) -> CurrentUser | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.store_id, COALESCE(c.name, ?) AS city
            FROM users u
            LEFT JOIN cities c ON c.id = u.city_id
            WHERE u.username = ? AND u.status = 'active'
            """,
            (settings.default_city, username),
        ).fetchone()
        if row is None:
            return None
        roles = conn.execute(
            """
            SELECT r.code
            FROM roles r
            JOIN user_roles ur ON ur.role_id = r.id
            WHERE ur.user_id = ?
            """,
            (row["id"],),
        ).fetchall()
        return CurrentUser(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            city=row["city"],
            role_codes=[role["code"] for role in roles],
            store_id=row["store_id"],
        )


def authenticate(username: str, password: str) -> CurrentUser | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ? AND status = 'active'",
            (username,),
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
    return get_user(username)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expire_time = (datetime.now() + timedelta(hours=SESSION_HOURS)).isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO auth_sessions(token, user_id, expire_time) VALUES (?, ?, ?)",
            (token, user_id, expire_time),
        )
        conn.commit()
    return token


def get_user_by_token(token: str) -> CurrentUser | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.username
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
              AND s.revoked = 0
              AND datetime(s.expire_time) > datetime('now')
              AND u.status = 'active'
            """,
            (token,),
        ).fetchone()
    return get_user(row["username"]) if row else None


def revoke_session(token: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE auth_sessions SET revoked = 1 WHERE token = ?", (token,))
        conn.commit()


def user_to_dict(user: CurrentUser, token: str | None = None) -> dict:
    payload = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "city": user.city,
        "roles": user.role_codes,
        "store_id": user.store_id,
    }
    if token:
        payload["token"] = token
    return payload
