from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import current_user
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
from app.services.excel_import_service import import_orders_from_excel
from app.services.order_service import list_orders


router = APIRouter()


@router.get("")
def orders(
    start_date: str | None = None,
    end_date: str | None = None,
    residential: str | None = None,
    store: str | None = None,
    agent: str | None = None,
    limit: int = 50,
    user: CurrentUser = Depends(current_user),
):
    with get_connection() as conn:
        return list_orders(conn, user.city, start_date, end_date, residential, store, agent, min(limit, 200))


@router.post("/import-excel")
async def import_excel(file: UploadFile = File(...), user: CurrentUser = Depends(current_user)) -> dict:
    if "admin" not in user.role_codes:
        raise HTTPException(status_code=403, detail="只有管理员可以导入成交数据")
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")
    content = await file.read()
    with get_connection() as conn:
        return import_orders_from_excel(conn, content, file.filename, user.username)
