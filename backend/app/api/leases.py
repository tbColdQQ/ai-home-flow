from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import current_user
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
from app.services.lease_service import create_lease, delete_lease, get_lease, import_leases_from_excel, list_leases, update_lease


router = APIRouter()


class LeaseRequest(BaseModel):
    community_name: str | None = None
    address: str | None = None
    acreage: float | None = None
    price: float | None = None
    listing_date: str | None = None
    rental_type: str | None = None
    recorder: str | None = None
    maintainor: str | None = None
    has_key: int | None = None
    agent: str | None = None
    deal_date: str | None = None
    lease_expire_date: str | None = None
    cancel_time: str | None = None
    cancel_reason: str | None = None
    for_sale: int | None = None
    owner_phone: str | None = None
    customer_phone: str | None = None


def ensure_lease_manager(user: CurrentUser) -> None:
    if not {"admin", "store_manager", "rental_agent", "rental_clerk"}.intersection(user.role_codes):
        raise HTTPException(status_code=403, detail="需要租赁房源管理权限")


@router.get("")
def leases(
    community_name: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    sort_by: str = "lease_expire_date",
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 20,
    user: CurrentUser = Depends(current_user),
) -> dict:
    ensure_lease_manager(user)
    with get_connection() as conn:
        return list_leases(conn, user.city, community_name, price_min, price_max, sort_by, sort_order, page, page_size)


@router.post("")
def create(body: LeaseRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_lease_manager(user)
    with get_connection() as conn:
        lease_id = create_lease(conn, body.model_dump(exclude_unset=True), user.city, user.username)
        conn.commit()
        return {"id": lease_id}


@router.post("/import-excel")
async def import_excel(file: UploadFile = File(...), user: CurrentUser = Depends(current_user)) -> dict:
    ensure_lease_manager(user)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")
    content = await file.read()
    with get_connection() as conn:
        return import_leases_from_excel(conn, content, user.city, user.username)


@router.get("/{lease_id}")
def detail(lease_id: int, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_lease_manager(user)
    with get_connection() as conn:
        lease = get_lease(conn, lease_id, user.city)
        if lease is None:
            raise HTTPException(status_code=404, detail="租赁房源不存在")
        return lease


@router.put("/{lease_id}")
def update(lease_id: int, body: LeaseRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_lease_manager(user)
    with get_connection() as conn:
        lease = update_lease(conn, lease_id, body.model_dump(exclude_unset=True), user.city, user.username)
        if lease is None:
            raise HTTPException(status_code=404, detail="租赁房源不存在")
        conn.commit()
        return lease


@router.delete("/{lease_id}")
def delete(lease_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_lease_manager(user)
    with get_connection() as conn:
        if not delete_lease(conn, lease_id, user.city, user.username):
            raise HTTPException(status_code=404, detail="租赁房源不存在")
        conn.commit()
    return {"message": "deleted"}
