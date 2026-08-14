import calendar
import sqlite3
from datetime import date
from typing import Any

from app.db.session import rows_to_dicts


def _store_clerks(conn: sqlite3.Connection, city: str, store_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT u.id, u.username, u.display_name
        FROM users u
        JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id
        WHERE u.city_id = (SELECT id FROM cities WHERE name = ?)
          AND u.store_id = ?
          AND u.status = 'active'
          AND r.code = 'clerk'
        GROUP BY u.id
        ORDER BY u.id
        """,
        (city, store_id),
    ).fetchall()
    return rows_to_dicts(rows)


def get_roster(conn: sqlite3.Connection, city: str, store_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT u.id, u.username, u.display_name, dr.sort_order
        FROM duty_roster dr
        JOIN users u ON u.id = dr.user_id
        WHERE dr.city = ?
          AND dr.store_id = ?
          AND u.status = 'active'
        ORDER BY dr.sort_order, u.id
        """,
        (city, store_id),
    ).fetchall()
    roster = rows_to_dicts(rows)
    if roster:
        return roster
    return [{**user, "sort_order": index + 1} for index, user in enumerate(_store_clerks(conn, city, store_id))]


def set_roster(conn: sqlite3.Connection, city: str, store_id: int, user_ids: list[int]) -> list[dict[str, Any]]:
    allowed_ids = {user["id"] for user in _store_clerks(conn, city, store_id)}
    clean_user_ids = []
    for user_id in user_ids:
        if user_id not in allowed_ids:
            raise ValueError("只能选择本门店店员参与值班")
        if user_id not in clean_user_ids:
            clean_user_ids.append(user_id)

    conn.execute("DELETE FROM duty_roster WHERE city = ? AND store_id = ?", (city, store_id))
    for index, user_id in enumerate(clean_user_ids, start=1):
        conn.execute(
            """
            INSERT INTO duty_roster(city, store_id, user_id, sort_order, modify_time)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (city, store_id, user_id, index),
        )
    return get_roster(conn, city, store_id)


def set_assignment(conn: sqlite3.Connection, city: str, store_id: int, duty_date: str, user_id: int, modifier_user_id: int) -> None:
    allowed_ids = {user["id"] for user in _store_clerks(conn, city, store_id)}
    if user_id not in allowed_ids:
        raise ValueError("只能选择本门店店员值班")
    date.fromisoformat(duty_date)
    conn.execute(
        """
        INSERT INTO duty_overrides(city, store_id, duty_date, user_id, modifier_user_id, modify_time)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(city, store_id, duty_date) DO UPDATE SET
            user_id = excluded.user_id,
            modifier_user_id = excluded.modifier_user_id,
            modify_time = CURRENT_TIMESTAMP
        """,
        (city, store_id, duty_date, user_id, modifier_user_id),
    )


def get_month_schedule(conn: sqlite3.Connection, city: str, store_id: int, month: str) -> dict[str, Any]:
    year_text, month_text = month.split("-", 1)
    year = int(year_text)
    month_number = int(month_text)
    days_in_month = calendar.monthrange(year, month_number)[1]
    roster = get_roster(conn, city, store_id)
    roster_by_id = {user["id"]: user for user in roster}
    overrides = {
        row["duty_date"]: dict(row)
        for row in conn.execute(
            """
            SELECT o.duty_date, u.id AS user_id, u.username, u.display_name
            FROM duty_overrides o
            JOIN users u ON u.id = o.user_id
            WHERE o.city = ? AND o.store_id = ? AND o.duty_date >= ? AND o.duty_date < ?
            """,
            (city, store_id, f"{year:04d}-{month_number:02d}-01", f"{year + (month_number // 12):04d}-{(month_number % 12) + 1:02d}-01"),
        ).fetchall()
    }

    days = []
    for day in range(1, days_in_month + 1):
        duty_date = f"{year:04d}-{month_number:02d}-{day:02d}"
        assigned = None
        is_override = False
        if duty_date in overrides:
            assigned = overrides[duty_date]
            is_override = True
        elif roster:
            assigned = roster[(day - 1) % len(roster)]
        days.append(
            {
                "date": duty_date,
                "day": day,
                "weekday": date(year, month_number, day).weekday(),
                "user_id": assigned["user_id"] if assigned and "user_id" in assigned else assigned["id"] if assigned else None,
                "username": assigned.get("username") if assigned else None,
                "display_name": assigned.get("display_name") if assigned else None,
                "is_override": is_override,
            }
        )
    return {"month": month, "store_id": store_id, "roster": roster, "days": days}
