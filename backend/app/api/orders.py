from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import current_user
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
from app.services.excel_import_service import import_orders_from_excel
from app.services.order_service import cancel_order, get_order, list_orders, update_order


router = APIRouter()


class UpdateOrderRequest(BaseModel):
    area: str | None = None
    street: str | None = None
    residential: str | None = None
    room_number: str | None = None
    acreage: float | None = None
    list_price: float | None = None
    price: float | None = None
    agent: str | None = None
    store: str | None = None
    signing_date: str | None = None
    CA: str | None = None
    maintainor: str | None = None
    parking: int | None = None
    remark: str | None = None
    location: str | None = None
    brand: str | None = None
    review_status: str | None = None


def ensure_order_editor(user: CurrentUser) -> None:
    if not {"admin", "store_manager"}.intersection(user.role_codes):
        raise HTTPException(status_code=403, detail="只有店长和管理员可以修改或删除成交数据")


@router.get("")
def orders(
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
    user: CurrentUser = Depends(current_user),
):
    with get_connection() as conn:
        return list_orders(
            conn=conn,
            city=user.city,
            start_date=start_date,
            end_date=end_date,
            residential=residential,
            agent=agent,
            area=area,
            acreage_min=acreage_min,
            acreage_max=acreage_max,
            price_min=price_min,
            price_max=price_max,
            page=page,
            page_size=page_size,
        )


@router.post("/import-excel")
async def import_excel(file: UploadFile = File(...), user: CurrentUser = Depends(current_user)) -> dict:
    if "admin" not in user.role_codes:
        raise HTTPException(status_code=403, detail="只有管理员可以导入成交数据")
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")
    content = await file.read()
    with get_connection() as conn:
        return import_orders_from_excel(conn, content, file.filename, user.username)


@router.get("/{order_id}")
def order_detail(order_id: int, user: CurrentUser = Depends(current_user)) -> dict:
    with get_connection() as conn:
        order = get_order(conn, user.city, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="成交记录不存在")
        return order


@router.put("/{order_id}")
def edit_order(order_id: int, body: UpdateOrderRequest, user: CurrentUser = Depends(current_user)) -> dict:
    ensure_order_editor(user)
    with get_connection() as conn:
        order = update_order(conn, user.city, order_id, body.model_dump(exclude_unset=True), user.username)
        if order is None:
            raise HTTPException(status_code=404, detail="成交记录不存在")
        conn.commit()
        return order


@router.delete("/{order_id}")
def delete_order(order_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    ensure_order_editor(user)
    with get_connection() as conn:
        if not cancel_order(conn, user.city, order_id, user.username):
            raise HTTPException(status_code=404, detail="成交记录不存在")
        conn.commit()
    return {"message": "deleted"}
