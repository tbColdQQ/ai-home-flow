from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import current_user
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
from app.services.duty_service import get_month_schedule, get_roster, set_assignment, set_roster


router = APIRouter()


class RosterRequest(BaseModel):
    user_ids: list[int]


class AssignmentRequest(BaseModel):
    duty_date: str
    user_id: int


def ensure_store_manager(user: CurrentUser) -> None:
    if "store_manager" not in user.role_codes:
        raise HTTPException(status_code=403, detail="只有店长可以维护值班")
    if user.store_id is None:
        raise HTTPException(status_code=400, detail="当前用户未绑定门店")


def _month_or_current(month: str | None) -> str:
    if not month:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"
    date.fromisoformat(f"{month}-01")
    return month


@router.get("/schedule")
def schedule(month: str | None = None, user: CurrentUser = Depends(current_user)) -> dict:
    if user.store_id is None:
        return {"month": _month_or_current(month), "store_id": None, "roster": [], "days": []}
    with get_connection() as conn:
        return get_month_schedule(conn, user.city, user.store_id, _month_or_current(month))


@router.get("/roster")
def roster(user: CurrentUser = Depends(current_user)) -> list[dict]:
    if user.store_id is None:
        return []
    with get_connection() as conn:
        return get_roster(conn, user.city, user.store_id)


@router.put("/roster")
def update_roster(body: RosterRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_store_manager(user)
    with get_connection() as conn:
        try:
            roster = set_roster(conn, user.city, user.store_id, body.user_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
        return {"roster": roster}


@router.put("/assignment")
def update_assignment(body: AssignmentRequest, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_store_manager(user)
    with get_connection() as conn:
        try:
            set_assignment(conn, user.city, user.store_id, body.duty_date, body.user_id, user.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
    return {"message": "updated"}
