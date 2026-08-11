from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.services.auth_service import CurrentUser
from app.services.image_import_service import scan_images


router = APIRouter()


@router.post("/scan")
def scan(user: CurrentUser = Depends(current_user)) -> dict:
    if not set(user.role_codes).intersection({"store_manager", "admin"}):
        return {"error": "无权扫描图片"}
    return scan_images()

