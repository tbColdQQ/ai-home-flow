import sqlite3
from datetime import date, datetime
from typing import Any

from app.db.session import rows_to_dicts


ORDER_FIELDS = {
    "city",
    "area",
    "street",
    "residential",
    "room_number",
    "acreage",
    "list_price",
    "price",
    "agent",
    "store",
    "signing_date",
    "CA",
    "creator",
    "modifier",
    "maintainor",
    "maintainor_store",
    "parking",
    "status",
    "remark",
    "location",
    "brand",
    "source_type",
    "source_id",
    "source_file",
    "review_status",
    "raw_payload_json",
}

ORDER_EDIT_FIELDS = {
    "area",
    "street",
    "residential",
    "room_number",
    "acreage",
    "list_price",
    "price",
    "agent",
    "store",
    "signing_date",
    "CA",
    "maintainor",
    "maintainor_store",
    "parking",
    "remark",
    "location",
    "brand",
    "review_status",
}


def create_order(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    payload = {k: v for k, v in data.items() if k in ORDER_FIELDS}
    payload.setdefault("status", "normal")
    payload.setdefault("review_status", "confirmed")
    payload.setdefault("create_time", now)
    payload.setdefault("modify_time", now)

    columns = ", ".join(payload.keys())
    placeholders = ", ".join(["?"] * len(payload))
    cursor = conn.execute(
        f"INSERT INTO orders({columns}) VALUES ({placeholders})",
        tuple(payload.values()),
    )
    return int(cursor.lastrowid)


def get_order(conn: sqlite3.Connection, city: str, order_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE ID = ?
          AND city = ?
          AND COALESCE(status, 'normal') = 'normal'
        """,
        (order_id, city),
    ).fetchone()
    return dict(row) if row else None


def update_order(conn: sqlite3.Connection, city: str, order_id: int, data: dict[str, Any], modifier: str) -> dict[str, Any] | None:
    payload = {key: value for key, value in data.items() if key in ORDER_EDIT_FIELDS}
    if not payload:
        return get_order(conn, city, order_id)

    payload["modifier"] = modifier
    payload["modify_time"] = datetime.now().isoformat(timespec="seconds")
    assignments = ", ".join([f"{key} = ?" for key in payload])
    params = list(payload.values()) + [order_id, city]
    cursor = conn.execute(
        f"""
        UPDATE orders
        SET {assignments}
        WHERE ID = ?
          AND city = ?
          AND COALESCE(status, 'normal') = 'normal'
        """,
        tuple(params),
    )
    if cursor.rowcount == 0:
        return None
    return get_order(conn, city, order_id)


def cancel_order(conn: sqlite3.Connection, city: str, order_id: int, modifier: str) -> bool:
    cursor = conn.execute(
        """
        UPDATE orders
        SET status = 'cancel',
            modifier = ?,
            modify_time = ?
        WHERE ID = ?
          AND city = ?
          AND COALESCE(status, 'normal') = 'normal'
        """,
        (modifier, datetime.now().isoformat(timespec="seconds"), order_id, city),
    )
    return cursor.rowcount > 0


def list_orders(
    conn: sqlite3.Connection,
    city: str,
    start_date: str | None = None,
    end_date: str | None = None,
    residential: str | None = None,
    agent: str | None = None,
    area: str | None = None,
    acreage_min: float | None = None,
    acreage_max: float | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    clauses = ["city = ?", "COALESCE(status, 'normal') = 'normal'"]
    params: list[Any] = [city]
    if start_date:
        clauses.append("signing_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("signing_date <= ?")
        params.append(end_date)
    if residential:
        clauses.append("residential LIKE ?")
        params.append(f"%{residential}%")
    if agent:
        clauses.append("agent LIKE ?")
        params.append(f"%{agent}%")
    if area:
        clauses.append("area LIKE ?")
        params.append(f"%{area}%")
    if acreage_min is not None:
        clauses.append("acreage >= ?")
        params.append(acreage_min)
    if acreage_max is not None:
        clauses.append("acreage <= ?")
        params.append(acreage_max)
    if price_min is not None:
        clauses.append("price >= ?")
        params.append(price_min)
    if price_max is not None:
        clauses.append("price <= ?")
        params.append(price_max)

    where_sql = " AND ".join(clauses)
    total = conn.execute(
        f"SELECT COUNT(*) AS total FROM orders WHERE {where_sql}",
        tuple(params),
    ).fetchone()["total"]

    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 10), 200)
    offset = (safe_page - 1) * safe_page_size
    rows = conn.execute(
        f"""
        SELECT *
        FROM orders
        WHERE {where_sql}
        ORDER BY signing_date DESC, ID DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [safe_page_size, offset]),
    ).fetchall()
    return {
        "items": rows_to_dicts(rows),
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
    }


def today_iso() -> str:
    return date.today().isoformat()
