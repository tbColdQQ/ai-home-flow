import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.session import get_connection
from app.services.order_service import create_order
from app.services.parser_service import parse_order_text


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_rapid_ocr: Any | None = None


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_text_from_sidecar(path: Path) -> tuple[str, str | None]:
    sidecar = path.with_suffix(".txt")
    if not sidecar.exists():
        return "", "未找到同名 txt 识别文件"
    try:
        text = sidecar.read_text(encoding="utf-8").strip()
    except Exception as exc:
        return "", f"读取同名 txt 失败：{exc}"
    if not text:
        return "", "同名 txt 识别文件为空"
    return text, None


def _extract_text_with_rapidocr(path: Path) -> tuple[str, str | None]:
    global _rapid_ocr
    try:
        from rapidocr import RapidOCR  # type: ignore
    except Exception:
        return "", "未安装 RapidOCR 组件"

    try:
        if _rapid_ocr is None:
            _rapid_ocr = RapidOCR()
        result = _rapid_ocr(path)
    except Exception as exc:
        return "", f"RapidOCR 识别失败：{exc}"

    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if txts is None and isinstance(result, (list, tuple)):
        txts = []
        scores = []
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                txts.append(str(item[1]))
                scores.append(float(item[2]) if len(item) >= 3 else 1.0)

    lines = []
    for index, text in enumerate(txts or []):
        score = 1.0
        if scores is not None and index < len(scores):
            score = float(scores[index])
        clean_text = str(text).strip()
        if clean_text and score >= settings.ocr_min_score:
            lines.append(clean_text)

    if not lines:
        return "", "RapidOCR 未识别到有效文字"
    return "\n".join(lines), None


def _extract_text_with_tesseract(path: Path) -> tuple[str, str | None]:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return "", "未安装 Tesseract OCR Python 组件"

    try:
        text = pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng").strip()
    except Exception as exc:
        return "", f"Tesseract OCR 识别失败：{exc}"
    if not text:
        return "", "Tesseract OCR 未识别到有效文字"
    return text, None


def extract_text(path: Path) -> tuple[str, str | None]:
    text, error = _extract_text_from_sidecar(path)
    if error is None:
        return text, None

    errors = [error]
    providers = {
        "rapidocr": [_extract_text_with_rapidocr, _extract_text_with_tesseract],
        "tesseract": [_extract_text_with_tesseract, _extract_text_with_rapidocr],
        "sidecar": [],
    }.get(settings.ocr_provider, [_extract_text_with_rapidocr, _extract_text_with_tesseract])

    for provider in providers:
        text, error = provider(path)
        if error is None:
            return text, None
        errors.append(error)

    return "", "；".join(errors)


def _insert_source_image(
    city: str,
    business_date: str,
    path: Path,
    digest: str,
    ocr_text: str,
    status: str,
    parsed_json: str | None = None,
    confidence_json: str | None = None,
    error_message: str | None = None,
) -> int | None:
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO source_images(
                    city, business_date, file_path, file_name, file_hash,
                    ocr_text, parsed_result_json, confidence_json, status, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    city,
                    business_date,
                    str(path),
                    path.name,
                    digest,
                    ocr_text,
                    parsed_json,
                    confidence_json,
                    status,
                    error_message,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        except Exception:
            return None


def _has_duplicate_order(conn, data: dict) -> bool:
    row = conn.execute(
        """
        SELECT ID
        FROM orders
        WHERE city = ?
          AND signing_date = ?
          AND residential = ?
          AND ABS(COALESCE(acreage, 0) - ?) < 0.001
          AND ABS(COALESCE(price, 0) - ?) < 0.001
          AND COALESCE(status, 'normal') = 'normal'
        LIMIT 1
        """,
        (
            data.get("city"),
            data.get("signing_date"),
            data.get("residential"),
            data.get("acreage") or 0,
            data.get("price") or 0,
        ),
    ).fetchone()
    return row is not None


def scan_images(root: Path | None = None) -> dict:
    root = root or settings.image_root
    root.mkdir(parents=True, exist_ok=True)
    result = {"scanned": 0, "confirmed": 0, "pending": 0, "skipped": 0, "failed": 0}

    for image_path in root.rglob("*"):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        result["scanned"] += 1
        parts = image_path.relative_to(root).parts
        if len(parts) < 3:
            digest = file_hash(image_path)
            _insert_source_image("", "", image_path, digest, "", "failed", error_message="图片目录必须为：城市/日期/图片")
            result["failed"] += 1
            continue

        city, business_date = parts[0], parts[1]
        digest = file_hash(image_path)
        with get_connection() as conn:
            exists = conn.execute("SELECT id FROM source_images WHERE file_hash = ?", (digest,)).fetchone()
        if exists:
            result["skipped"] += 1
            continue

        ocr_text, error = extract_text(image_path)
        if error:
            source_id = _insert_source_image(city, business_date, image_path, digest, ocr_text, "pending", error_message=error)
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO task_items(task_type, title, city, source_type, source_id, assignee_role, reason)
                    VALUES ('ocr_order_confirm', '成交图片识别待确认', ?, 'image', ?, 'store_manager', ?)
                    """,
                    (city, source_id, error),
                )
                conn.commit()
            result["pending"] += 1
            continue

        parsed = parse_order_text(ocr_text, city, business_date)
        parsed_json = json.dumps(parsed.data, ensure_ascii=False)
        confidence_json = json.dumps(parsed.confidence, ensure_ascii=False)

        with get_connection() as conn:
            duplicate = _has_duplicate_order(conn, parsed.data) if not parsed.needs_review else False
            if duplicate:
                parsed.reasons.append("疑似重复成交记录")

            if parsed.needs_review:
                cursor = conn.execute(
                    """
                    INSERT INTO source_images(
                        city, business_date, file_path, file_name, file_hash,
                        ocr_text, parsed_result_json, confidence_json, status, error_message
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        city,
                        business_date,
                        str(image_path),
                        image_path.name,
                        digest,
                        ocr_text,
                        parsed_json,
                        confidence_json,
                        ";".join(parsed.reasons),
                    ),
                )
                source_id = int(cursor.lastrowid)
                conn.execute(
                    """
                    INSERT INTO task_items(
                        task_type, title, city, store, source_type, source_id,
                        assignee_role, payload_json, reason
                    )
                    VALUES ('ocr_order_confirm', '成交图片识别待确认', ?, ?, 'image', ?, 'store_manager', ?, ?)
                    """,
                    (city, parsed.data.get("store"), source_id, parsed_json, ";".join(parsed.reasons)),
                )
                conn.commit()
                result["pending"] += 1
            else:
                parsed.data.update(
                    {
                        "source_type": "image",
                        "source_file": str(image_path),
                        "raw_payload_json": parsed_json,
                    }
                )
                order_id = create_order(conn, parsed.data)
                cursor = conn.execute(
                    """
                    INSERT INTO source_images(
                        city, business_date, file_path, file_name, file_hash,
                        ocr_text, parsed_result_json, confidence_json, status, related_order_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
                    """,
                    (
                        city,
                        business_date,
                        str(image_path),
                        image_path.name,
                        digest,
                        ocr_text,
                        parsed_json,
                        confidence_json,
                        order_id,
                    ),
                )
                source_id = int(cursor.lastrowid)
                conn.execute("UPDATE orders SET source_id = ? WHERE ID = ?", (source_id, order_id))
                conn.commit()
                result["confirmed"] += 1
    return result
