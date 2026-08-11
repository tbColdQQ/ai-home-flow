import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import current_user
from app.db.session import get_connection, rows_to_dicts
from app.services.auth_service import CurrentUser
from app.services.order_service import create_order


router = APIRouter()


class CompleteTaskRequest(BaseModel):
    order: dict
    remark: str | None = None


@router.get("")
def list_tasks(status: str = "pending", user: CurrentUser = Depends(current_user)) -> list[dict]:
    with get_connection() as conn:
        if "admin" in user.role_codes:
            rows = conn.execute(
                "SELECT * FROM task_items WHERE status = ? ORDER BY create_time DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_items WHERE status = ? AND city = ? ORDER BY create_time DESC",
                (status, user.city),
            ).fetchall()
        return rows_to_dicts(rows)


@router.post("/{task_id}/complete")
def complete_task(task_id: int, body: CompleteTaskRequest, user: CurrentUser = Depends(current_user)) -> dict:
    if not set(user.role_codes).intersection({"store_manager", "admin"}):
        raise HTTPException(status_code=403, detail="无权处理待办")
    with get_connection() as conn:
        task = conn.execute("SELECT * FROM task_items WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            raise HTTPException(status_code=404, detail="待办不存在")
        if task["status"] != "pending":
            raise HTTPException(status_code=400, detail="待办已处理")

        order_data = dict(body.order)
        order_data.setdefault("city", task["city"])
        order_data.setdefault("source_type", task["source_type"])
        order_data.setdefault("source_id", task["source_id"])
        order_data.setdefault("review_status", "confirmed")
        order_data.setdefault("raw_payload_json", json.dumps(order_data, ensure_ascii=False))
        order_id = create_order(conn, order_data)

        conn.execute(
            """
            UPDATE task_items
            SET status = 'done', result_ref_type = 'order', result_ref_id = ?, finish_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (order_id, task_id),
        )
        if task["source_type"] == "image":
            conn.execute(
                "UPDATE source_images SET status = 'confirmed', related_order_id = ?, modify_time = CURRENT_TIMESTAMP WHERE id = ?",
                (order_id, task["source_id"]),
            )
        conn.execute(
            """
            INSERT INTO task_logs(task_id, action, operator_user_id, after_json, remark)
            VALUES (?, 'complete', ?, ?, ?)
            """,
            (task_id, user.id, json.dumps(order_data, ensure_ascii=False), body.remark),
        )
        conn.commit()
        return {"order_id": order_id}


@router.post("/{task_id}/ignore")
def ignore_task(task_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    if not set(user.role_codes).intersection({"store_manager", "admin"}):
        raise HTTPException(status_code=403, detail="无权处理待办")
    with get_connection() as conn:
        conn.execute("UPDATE task_items SET status = 'ignored', finish_time = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
        conn.execute(
            "INSERT INTO task_logs(task_id, action, operator_user_id) VALUES (?, 'ignore', ?)",
            (task_id, user.id),
        )
        conn.commit()
    return {"message": "ignored"}
