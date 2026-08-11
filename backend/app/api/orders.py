from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
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
