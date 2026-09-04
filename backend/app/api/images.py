import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import current_user
from app.core.config import settings
from app.services.auth_service import CurrentUser
from app.services.image_import_service import IMAGE_EXTENSIONS, scan_images


router = APIRouter()
MAX_IMAGE_UPLOAD_FILES = 10


class ScanImagesRequest(BaseModel):
    business_date: str


def _ensure_image_permission(user: CurrentUser) -> None:
    if not {"store_manager", "admin", "clerk_admin"}.intersection(user.role_codes):
        raise HTTPException(status_code=403, detail="无权操作成交图片")


def _validate_business_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        raise HTTPException(status_code=400, detail="图片日期格式必须为 yyyy-mm-dd")
    return value


def _safe_image_name(filename: str) -> str:
    raw_name = Path(filename or "").name
    suffix = Path(raw_name).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式：{suffix or '未知'}")
    stem = Path(raw_name).stem.strip() or "image"
    safe_stem = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", stem)[:80].strip("._") or "image"
    return f"{safe_stem}{suffix}"


@router.post("/scan")
def scan(body: ScanImagesRequest, user: CurrentUser = Depends(current_user)) -> dict:
    _ensure_image_permission(user)
    return scan_images(city=user.city, business_date=_validate_business_date(body.business_date))


@router.post("/upload")
async def upload_images(
    business_date: str = Form(...),
    scan_after_upload: bool = Form(False),
    files: list[UploadFile] = File(...),
    user: CurrentUser = Depends(current_user),
) -> dict:
    _ensure_image_permission(user)
    business_date = _validate_business_date(business_date)
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的图片")
    if len(files) > MAX_IMAGE_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"最多只能上传 {MAX_IMAGE_UPLOAD_FILES} 张图片")

    target_dir = settings.image_root / user.city / business_date
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    saved_paths = []
    for file in files:
        safe_name = _safe_image_name(file.filename or "")
        target_path = target_dir / safe_name
        if target_path.exists():
            target_path = target_dir / f"{Path(safe_name).stem}_{uuid.uuid4().hex[:8]}{Path(safe_name).suffix}"
        try:
            with target_path.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
        finally:
            await file.close()
        saved_files.append(target_path.name)
        saved_paths.append(target_path)

    result = {
        "city": user.city,
        "business_date": business_date,
        "target_dir": str(target_dir),
        "uploaded": len(saved_files),
        "files": saved_files,
    }
    if scan_after_upload:
        result["scan"] = scan_images(city=user.city, business_date=business_date, only_paths=saved_paths)
    return result
