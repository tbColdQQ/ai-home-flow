import json
import sqlite3
from datetime import date, datetime
from typing import Any

from app.db.session import rows_to_dicts
from app.services.auth_service import CurrentUser


REMINDER_DAYS = {60, 30, 15, 7}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _lease_payload(lease: dict[str, Any], days_left: int) -> dict[str, Any]:
    keys = [
        "id",
        "city",
        "community_name",
        "address",
        "acreage",
        "price",
        "rental_type",
        "recorder",
        "maintainor",
        "agent",
        "lease_expire_date",
        "owner_phone",
        "customer_phone",
    ]
    payload = {key: lease.get(key) for key in keys}
    payload["days_left"] = days_left
    return payload


def _find_rental_agent(conn: sqlite3.Connection, lease: dict[str, Any]) -> sqlite3.Row | None:
    names = [lease.get("agent"), lease.get("maintainor"), lease.get("recorder"), lease.get("creator")]
    for name in [item for item in names if item]:
        row = conn.execute(
            """
            SELECT u.id, u.store_id
            FROM users u
            JOIN user_roles ur ON ur.user_id = u.id
            JOIN roles r ON r.id = ur.role_id
            LEFT JOIN cities c ON c.id = u.city_id
            WHERE u.status = 'active'
              AND r.code = 'rental_agent'
              AND COALESCE(c.name, ?) = ?
              AND (u.username = ? OR u.display_name = ?)
            LIMIT 1
            """,
            (lease.get("city"), lease.get("city"), name, name),
        ).fetchone()
        if row:
            return row
    return conn.execute(
        """
        SELECT u.id, u.store_id
        FROM users u
        JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id
        LEFT JOIN cities c ON c.id = u.city_id
        WHERE u.status = 'active'
          AND r.code = 'rental_agent'
          AND COALESCE(c.name, ?) = ?
        ORDER BY u.id
        LIMIT 1
        """,
        (lease.get("city"), lease.get("city")),
    ).fetchone()


def generate_lease_expiry_tasks(conn: sqlite3.Connection, city: str | None = None, today: date | None = None) -> int:
    current = today or date.today()
    params: list[Any] = []
    city_filter = ""
    if city:
        city_filter = "AND city = ?"
        params.append(city)
    leases = rows_to_dicts(
        conn.execute(
            f"""
            SELECT *
            FROM lease_properties
            WHERE status != 'deleted'
              AND lease_expire_date IS NOT NULL
              {city_filter}
            """,
            tuple(params),
        ).fetchall()
    )

    created = 0
    for lease in leases:
        expire_date = _parse_date(lease.get("lease_expire_date"))
        if not expire_date:
            continue
        days_left = (expire_date - current).days
        if days_left not in REMINDER_DAYS:
            continue
        lease_id = lease["id"]
        suppressed = conn.execute(
            "SELECT 1 FROM lease_reminder_suppressions WHERE lease_id = ?",
            (lease_id,),
        ).fetchone()
        if suppressed:
            continue
        pending = conn.execute(
            """
            SELECT 1
            FROM task_items
            WHERE task_type = 'lease_expiry'
              AND source_type = 'lease'
              AND source_id = ?
              AND status = 'pending'
            LIMIT 1
            """,
            (lease_id,),
        ).fetchone()
        if pending:
            continue

        assignee = _find_rental_agent(conn, lease)
        if not assignee:
            continue
        payload = _lease_payload(lease, days_left)
        title = f"{lease.get('community_name') or '租赁房源'}租期还有{days_left}天到期"
        reason = f"租期到期日：{lease.get('lease_expire_date')}，剩余 {days_left} 天"
        conn.execute(
            """
            INSERT INTO task_items(
                task_type, title, city, store, source_type, source_id,
                assignee_role, assignee_user_id, status, priority, payload_json, reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                "lease_expiry",
                title,
                lease.get("city"),
                str(assignee["store_id"]) if assignee["store_id"] is not None else None,
                "lease",
                lease_id,
                "rental_agent",
                assignee["id"],
                1,
                json.dumps(payload, ensure_ascii=False),
                reason,
            ),
        )
        created += 1
    if created:
        conn.commit()
    return created


def task_has_followup(conn: sqlite3.Connection, task_id: int) -> bool:
    return conn.execute("SELECT 1 FROM lease_task_followups WHERE task_id = ? LIMIT 1", (task_id,)).fetchone() is not None


def add_lease_followup(conn: sqlite3.Connection, task: dict[str, Any], user: CurrentUser, content: str) -> None:
    text = content.strip()
    if not text:
        raise ValueError("回访内容不能为空")
    conn.execute(
        """
        INSERT INTO lease_task_followups(task_id, lease_id, operator_user_id, content)
        VALUES (?, ?, ?, ?)
        """,
        (task["id"], task["source_id"], user.id, text),
    )
    conn.execute(
        "INSERT INTO task_logs(task_id, action, operator_user_id, remark) VALUES (?, 'lease_followup', ?, ?)",
        (task["id"], user.id, text),
    )


def acknowledge_lease_task(conn: sqlite3.Connection, task: dict[str, Any], user: CurrentUser) -> None:
    conn.execute(
        "UPDATE task_items SET status = 'done', finish_time = CURRENT_TIMESTAMP WHERE id = ?",
        (task["id"],),
    )
    conn.execute(
        "INSERT INTO task_logs(task_id, action, operator_user_id) VALUES (?, 'acknowledge', ?)",
        (task["id"], user.id),
    )


def suppress_lease_task(conn: sqlite3.Connection, task: dict[str, Any], user: CurrentUser) -> None:
    if not task_has_followup(conn, task["id"]):
        raise ValueError("已有回访记录后才能不再提示")
    conn.execute(
        """
        INSERT OR IGNORE INTO lease_reminder_suppressions(lease_id, task_id, operator_user_id, reason)
        VALUES (?, ?, ?, ?)
        """,
        (task["source_id"], task["id"], user.id, "用户选择不再提示"),
    )
    conn.execute(
        "UPDATE task_items SET status = 'ignored', finish_time = CURRENT_TIMESTAMP WHERE id = ?",
        (task["id"],),
    )
    conn.execute(
        "INSERT INTO task_logs(task_id, action, operator_user_id) VALUES (?, 'suppress', ?)",
        (task["id"], user.id),
    )
