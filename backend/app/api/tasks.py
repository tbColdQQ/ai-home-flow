import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import current_user
from app.db.session import get_connection, rows_to_dicts
from app.services.auth_service import CurrentUser
from app.services.lease_task_service import (
    add_lease_followup,
    generate_lease_expiry_tasks,
    suppress_lease_task,
    task_has_followup,
)
from app.services.image_import_service import confirm_image_task_order
from app.services.order_service import create_order


router = APIRouter()


class CompleteTaskRequest(BaseModel):
    order: dict
    remark: str | None = None


class UpdateTaskRequest(BaseModel):
    order: dict
    remark: str | None = None


class LeaseFollowupRequest(BaseModel):
    content: str


def ensure_image_task_handler(user: CurrentUser) -> None:
    if not {"store_manager", "admin", "clerk_admin"}.intersection(user.role_codes):
        raise HTTPException(status_code=403, detail="无权处理成交图片待办")


def _task_select_sql() -> str:
    return """
        SELECT t.*, si.file_path, si.file_name, si.ocr_text, si.business_date,
               lp.community_name, lp.address, lp.lease_expire_date,
               au.store_id AS assignee_store_id,
               ts.id AS task_store_id,
               au.display_name AS assignee_name,
               hu.id AS handler_user_id,
               hu.display_name AS handler_name,
               COUNT(lf.id) AS followup_count
        FROM task_items t
        LEFT JOIN source_images si ON si.id = t.source_id AND t.source_type = 'image'
        LEFT JOIN lease_properties lp ON lp.id = t.source_id AND t.source_type = 'lease'
        LEFT JOIN users au ON au.id = t.assignee_user_id
        LEFT JOIN cities tc ON tc.name = t.city
        LEFT JOIN stores ts ON ts.city_id = tc.id AND ts.name = t.store
        LEFT JOIN lease_task_followups lf ON lf.task_id = t.id
        LEFT JOIN task_logs hlog ON hlog.id = (
            SELECT tl.id
            FROM task_logs tl
            WHERE tl.task_id = t.id
              AND tl.action IN ('complete', 'acknowledge')
            ORDER BY tl.create_time DESC, tl.id DESC
            LIMIT 1
        )
        LEFT JOIN users hu ON hu.id = hlog.operator_user_id
    """


def _load_task(conn, task_id: int) -> dict:
    task = conn.execute(
        _task_select_sql()
        + """
        WHERE t.id = ?
        GROUP BY t.id
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    return dict(task)


def ensure_task_access(task: dict, user: CurrentUser) -> None:
    if "admin" in user.role_codes:
        return
    if "store_manager" in user.role_codes and task.get("assignee_store_id") == user.store_id:
        return
    if "store_manager" in user.role_codes and task.get("task_store_id") == user.store_id:
        return
    if task.get("assignee_user_id") == user.id:
        return
    if task.get("task_type") != "lease_expiry" and task.get("city") == user.city and "store_manager" in user.role_codes:
        return
    raise HTTPException(status_code=403, detail="无权查看或处理该待办")


def ensure_task_delete_access(task: dict, user: CurrentUser) -> None:
    if "store_manager" in user.role_codes and task.get("assignee_store_id") == user.store_id:
        return
    if "store_manager" in user.role_codes and task.get("task_store_id") == user.store_id:
        return
    if task.get("assignee_user_id") == user.id:
        return
    raise HTTPException(status_code=403, detail="只能删除自己负责的待办，店长可以删除本店待办")


@router.get("")
def list_tasks(status: str = "pending", user: CurrentUser = Depends(current_user)) -> list[dict]:
    with get_connection() as conn:
        generate_lease_expiry_tasks(conn, user.city if "admin" not in user.role_codes else None)
        base_sql = _task_select_sql()
        if "admin" in user.role_codes:
            rows = conn.execute(
                base_sql
                + """
                WHERE t.status = ?
                GROUP BY t.id
                ORDER BY t.create_time DESC
                """,
                (status,),
            ).fetchall()
        elif "store_manager" in user.role_codes:
            rows = conn.execute(
                base_sql
                + """
                WHERE t.status = ?
                  AND (
                    au.store_id = ?
                    OR (t.task_type != 'lease_expiry' AND t.city = ?)
                  )
                GROUP BY t.id
                ORDER BY t.create_time DESC
                """,
                (status, user.store_id, user.city),
            ).fetchall()
        else:
            rows = conn.execute(
                base_sql
                + """
                WHERE t.status = ?
                  AND t.assignee_user_id = ?
                GROUP BY t.id
                ORDER BY t.create_time DESC
                """,
                (status, user.id),
            ).fetchall()
        return rows_to_dicts(rows)


@router.put("/{task_id}")
def update_task(task_id: int, body: UpdateTaskRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_image_task_handler(user)
    with get_connection() as conn:
        task = _load_task(conn, task_id)
        ensure_task_access(task, user)
        if task["status"] != "pending":
            raise HTTPException(status_code=400, detail="只能修改待处理任务")
        if task.get("task_type") == "lease_expiry":
            raise HTTPException(status_code=400, detail="租赁待办请使用回访、已知悉或不再提示")

        order_data = dict(body.order)
        order_data.setdefault("city", task["city"])
        order_data.setdefault("signing_date", task.get("business_date"))
        payload_json = json.dumps(order_data, ensure_ascii=False)
        conn.execute(
            """
            UPDATE task_items
            SET payload_json = ?,
                store = ?,
                reason = ?
            WHERE id = ?
            """,
            (payload_json, order_data.get("store"), body.remark or task.get("reason"), task_id),
        )
        if task["source_type"] == "image":
            conn.execute(
                """
                UPDATE source_images
                SET parsed_result_json = ?,
                    modify_time = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (payload_json, task["source_id"]),
            )
        conn.execute(
            """
            INSERT INTO task_logs(task_id, action, operator_user_id, after_json, remark)
            VALUES (?, 'update', ?, ?, ?)
            """,
            (task_id, user.id, payload_json, body.remark),
        )
        conn.commit()
    return {"message": "updated"}


@router.post("/{task_id}/complete")
def complete_task(task_id: int, body: CompleteTaskRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_image_task_handler(user)
    with get_connection() as conn:
        task = _load_task(conn, task_id)
        ensure_task_access(task, user)
        if task["status"] != "pending":
            raise HTTPException(status_code=400, detail="待办已处理")
        if task.get("task_type") == "lease_expiry":
            raise HTTPException(status_code=400, detail="租赁待办请点击已知悉")

        order_data = dict(body.order)
        order_data.setdefault("city", task["city"])
        order_data.setdefault("signing_date", task.get("business_date"))
        order_data.setdefault("source_type", task["source_type"])
        order_data.setdefault("source_id", task["source_id"])
        order_data.setdefault("review_status", "confirmed")
        order_data.setdefault("raw_payload_json", json.dumps(order_data, ensure_ascii=False))
        if task["source_type"] == "image":
            order_id = confirm_image_task_order(conn, task, order_data)
        else:
            order_id = create_order(conn, order_data)

        conn.execute(
            """
            UPDATE task_items
            SET status = 'done', result_ref_type = 'order', result_ref_id = ?, finish_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (order_id, task_id),
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


@router.post("/{task_id}/acknowledge")
def acknowledge_task(task_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    with get_connection() as conn:
        task = _load_task(conn, task_id)
        ensure_task_access(task, user)
        if task["status"] != "pending":
            raise HTTPException(status_code=400, detail="待办已处理")
        if task.get("task_type") == "ocr_order_confirm":
            raise HTTPException(status_code=400, detail="成交图片待办请先修改并确认入库")
        conn.execute(
            "UPDATE task_items SET status = 'done', finish_time = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,),
        )
        conn.execute(
            "INSERT INTO task_logs(task_id, action, operator_user_id) VALUES (?, 'acknowledge', ?)",
            (task_id, user.id),
        )
        conn.commit()
    return {"message": "done"}


@router.post("/{task_id}/lease-followups")
def add_followup(task_id: int, body: LeaseFollowupRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    with get_connection() as conn:
        task = _load_task(conn, task_id)
        if task.get("task_type") != "lease_expiry" or task.get("source_type") != "lease":
            raise HTTPException(status_code=400, detail="不是租赁到期待办")
        if task.get("status") != "pending":
            raise HTTPException(status_code=400, detail="待办已处理")
        ensure_task_access(task, user)
        try:
            add_lease_followup(conn, task, user, body.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
    return {"message": "created"}


@router.post("/{task_id}/suppress")
def suppress_task(task_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    with get_connection() as conn:
        task = _load_task(conn, task_id)
        if task.get("task_type") != "lease_expiry" or task.get("source_type") != "lease":
            raise HTTPException(status_code=400, detail="不是租赁到期待办")
        if task.get("status") != "pending":
            raise HTTPException(status_code=400, detail="待办已处理")
        ensure_task_access(task, user)
        if not task_has_followup(conn, task_id):
            raise HTTPException(status_code=400, detail="已有回访记录后才能不再提示")
        suppress_lease_task(conn, task, user)
        conn.commit()
    return {"message": "suppressed"}


@router.delete("/{task_id}")
def delete_task(task_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    with get_connection() as conn:
        task = _load_task(conn, task_id)
        ensure_task_delete_access(task, user)
        if task.get("status") == "deleted":
            raise HTTPException(status_code=400, detail="待办已删除")
        action = "delete_done" if task.get("status") == "done" else "delete"
        conn.execute("UPDATE task_items SET status = 'deleted', finish_time = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
        conn.execute(
            "INSERT INTO task_logs(task_id, action, operator_user_id) VALUES (?, ?, ?)",
            (task_id, action, user.id),
        )
        conn.commit()
    return {"message": "deleted"}
