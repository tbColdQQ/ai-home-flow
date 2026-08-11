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


def list_orders(
    conn: sqlite3.Connection,
    city: str,
    start_date: str | None = None,
    end_date: str | None = None,
    residential: str | None = None,
    store: str | None = None,
    agent: str | None = None,
    limit: int = 50,
) -> list[dict]:
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
    if store:
        clauses.append("store LIKE ?")
        params.append(f"%{store}%")
    if agent:
        clauses.append("agent LIKE ?")
        params.append(f"%{agent}%")
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT *
        FROM orders
        WHERE {' AND '.join(clauses)}
        ORDER BY signing_date DESC, ID DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return rows_to_dicts(rows)


def today_iso() -> str:
    return date.today().isoformat()

