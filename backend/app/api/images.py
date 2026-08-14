from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import current_user
from app.services.auth_service import CurrentUser
from app.services.image_import_service import scan_images


router = APIRouter()


class ScanImagesRequest(BaseModel):
    business_date: str


@router.post("/scan")
def scan(body: ScanImagesRequest, user: CurrentUser = Depends(current_user)) -> dict:
    if not {"store_manager", "admin"}.intersection(user.role_codes):
        raise HTTPException(status_code=403, detail="无权扫描图片")
    return scan_images(city=user.city, business_date=body.business_date)
