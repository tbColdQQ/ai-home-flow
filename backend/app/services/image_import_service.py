import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.session import get_connection
from app.services.order_service import create_order
from app.services.parser_service import parse_order_text


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MERGE_ORDER_FIELDS = {
    "agent",
    "store",
    "maintainor",
    "maintainor_store",
    "CA",
    "brand",
    "signing_date",
    "area",
    "street",
    "source_type",
    "source_id",
    "source_file",
    "raw_payload_json",
}
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


def _upsert_pending_task(conn, source_id: int | None, city: str, store: str | None, payload_json: str | None, reason: str) -> None:
    task = conn.execute(
        """
        SELECT id
        FROM task_items
        WHERE source_type = 'image'
          AND source_id IS ?
          AND status = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    if task:
        conn.execute(
            """
            UPDATE task_items
            SET title = '成交图片识别待确认',
                city = ?,
                store = ?,
                payload_json = ?,
                reason = ?
            WHERE id = ?
            """,
            (city, store, payload_json, reason, task["id"]),
        )
        return

    conn.execute(
        """
        INSERT INTO task_items(
            task_type, title, city, store, source_type, source_id,
            assignee_role, payload_json, reason
        )
        VALUES ('ocr_order_confirm', '成交图片识别待确认', ?, ?, 'image', ?, 'store_manager', ?, ?)
        """,
        (city, store, source_id, payload_json, reason),
    )


def _mark_source_tasks_done(conn, source_id: int, order_id: int) -> None:
    conn.execute(
        """
        UPDATE task_items
        SET status = 'done',
            result_ref_type = 'order',
            result_ref_id = ?,
            finish_time = CURRENT_TIMESTAMP
        WHERE source_type = 'image'
          AND source_id = ?
          AND status = 'pending'
        """,
        (order_id, source_id),
    )


def _apply_community_fields(conn, data: dict) -> None:
    if not data.get("residential") or not data.get("city"):
        return
    community = conn.execute(
        """
        SELECT area, street
        FROM communities
        WHERE name = ?
          AND COALESCE(city, ?) = ?
        ORDER BY id
        LIMIT 1
        """,
        (data["residential"], data["city"], data["city"]),
    ).fetchone()
    if not community:
        return
    data.setdefault("area", community["area"])
    data.setdefault("street", community["street"])


def _find_matching_order(conn, data: dict) -> dict | None:
    required = ["city", "residential", "acreage", "price"]
    if any(data.get(field) in (None, "") for field in required):
        return None
    row = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE city = ?
          AND residential = ?
          AND ABS(COALESCE(acreage, 0) - ?) < 0.001
          AND ABS(COALESCE(price, 0) - ?) < 0.001
          AND COALESCE(status, 'normal') = 'normal'
        ORDER BY
          CASE WHEN signing_date = ? THEN 0 ELSE 1 END,
          CASE WHEN source_type = 'image' THEN 0 ELSE 1 END,
          ID DESC
        LIMIT 1
        """,
        (
            data["city"],
            data["residential"],
            data["acreage"],
            data["price"],
            data.get("signing_date"),
        ),
    ).fetchone()
    return dict(row) if row else None


def _merge_order_payload(existing: dict, data: dict, source_id: int, image_path: Path, parsed_json: str) -> dict:
    payload: dict[str, Any] = {}
    for field in MERGE_ORDER_FIELDS:
        value = data.get(field)
        if field == "source_type":
            value = "image"
        if field == "source_id":
            value = existing.get("source_id") or source_id
        if field == "source_file":
            value = existing.get("source_file") or str(image_path)
        if field == "raw_payload_json":
            value = parsed_json
        if value not in (None, "") and (field in {"raw_payload_json"} or not existing.get(field)):
            payload[field] = value
    payload["modify_time"] = "CURRENT_TIMESTAMP"
    return payload


def _update_order_from_image(conn, order_id: int, payload: dict) -> None:
    if not payload:
        return
    special_current_timestamp = payload.pop("modify_time", None)
    assignments = [f"{field} = ?" for field in payload]
    params = list(payload.values())
    if special_current_timestamp:
        assignments.append("modify_time = CURRENT_TIMESTAMP")
    if not assignments:
        return
    params.append(order_id)
    conn.execute(f"UPDATE orders SET {', '.join(assignments)} WHERE ID = ?", tuple(params))


def _insert_source_image(
    conn,
    city: str,
    business_date: str,
    path: Path,
    digest: str,
    ocr_text: str,
    status: str,
    parsed_json: str | None = None,
    confidence_json: str | None = None,
    error_message: str | None = None,
    related_order_id: int | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO source_images(
            city, business_date, file_path, file_name, file_hash,
            ocr_text, parsed_result_json, confidence_json, status, error_message, related_order_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            related_order_id,
        ),
    )
    return int(cursor.lastrowid)


def _update_source_image(
    conn,
    source_id: int,
    city: str,
    business_date: str,
    path: Path,
    ocr_text: str,
    status: str,
    parsed_json: str | None,
    confidence_json: str | None,
    error_message: str | None,
    related_order_id: int | None = None,
) -> None:
    conn.execute(
        """
        UPDATE source_images
        SET city = ?,
            business_date = ?,
            file_path = ?,
            file_name = ?,
            ocr_text = ?,
            parsed_result_json = ?,
            confidence_json = ?,
            status = ?,
            error_message = ?,
            related_order_id = COALESCE(?, related_order_id),
            modify_time = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            city,
            business_date,
            str(path),
            path.name,
            ocr_text,
            parsed_json,
            confidence_json,
            status,
            error_message,
            related_order_id,
            source_id,
        ),
    )


def _handle_pending_source(
    conn,
    existing_source_id: int | None,
    city: str,
    business_date: str,
    image_path: Path,
    digest: str,
    ocr_text: str,
    parsed_json: str | None,
    confidence_json: str | None,
    reason: str,
    store: str | None,
) -> int:
    if existing_source_id:
        source_id = existing_source_id
        _update_source_image(conn, source_id, city, business_date, image_path, ocr_text, "pending", parsed_json, confidence_json, reason)
    else:
        source_id = _insert_source_image(
            conn,
            city,
            business_date,
            image_path,
            digest,
            ocr_text,
            "pending",
            parsed_json,
            confidence_json,
            reason,
        )
    _upsert_pending_task(conn, source_id, city, store, parsed_json, reason)
    return source_id


def _confirm_parsed_image(
    conn,
    existing_source_id: int | None,
    city: str,
    business_date: str,
    image_path: Path,
    digest: str,
    ocr_text: str,
    parsed_data: dict,
    parsed_json: str,
    confidence_json: str,
) -> int:
    _apply_community_fields(conn, parsed_data)
    existing_order = _find_matching_order(conn, parsed_data)

    if existing_order:
        order_id = int(existing_order["ID"])
        source_id = existing_source_id or _insert_source_image(
            conn,
            city,
            business_date,
            image_path,
            digest,
            ocr_text,
            "confirmed",
            parsed_json,
            confidence_json,
            related_order_id=order_id,
        )
        if existing_source_id:
            _update_source_image(conn, source_id, city, business_date, image_path, ocr_text, "confirmed", parsed_json, confidence_json, None, order_id)
        payload = _merge_order_payload(existing_order, parsed_data, source_id, image_path, parsed_json)
        _update_order_from_image(conn, order_id, payload)
    else:
        parsed_data.update(
            {
                "source_type": "image",
                "source_file": str(image_path),
                "raw_payload_json": parsed_json,
            }
        )
        order_id = create_order(conn, parsed_data)
        source_id = existing_source_id or _insert_source_image(
            conn,
            city,
            business_date,
            image_path,
            digest,
            ocr_text,
            "confirmed",
            parsed_json,
            confidence_json,
            related_order_id=order_id,
        )
        if existing_source_id:
            _update_source_image(conn, source_id, city, business_date, image_path, ocr_text, "confirmed", parsed_json, confidence_json, None, order_id)
        conn.execute("UPDATE orders SET source_id = COALESCE(source_id, ?) WHERE ID = ?", (source_id, order_id))

    _mark_source_tasks_done(conn, source_id, order_id)
    return order_id


def scan_images(root: Path | None = None) -> dict:
    root = root or settings.image_root
    root.mkdir(parents=True, exist_ok=True)
    result = {"scanned": 0, "confirmed": 0, "merged": 0, "pending": 0, "skipped": 0, "failed": 0}

    for image_path in root.rglob("*"):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        result["scanned"] += 1
        parts = image_path.relative_to(root).parts
        digest = file_hash(image_path)
        if len(parts) < 3:
            with get_connection() as conn:
                _insert_source_image(conn, "", "", image_path, digest, "", "failed", error_message="图片目录必须为：城市/日期/图片")
                conn.commit()
            result["failed"] += 1
            continue

        city, business_date = parts[0], parts[1]
        with get_connection() as conn:
            exists = conn.execute(
                "SELECT id, status, related_order_id FROM source_images WHERE file_hash = ?",
                (digest,),
            ).fetchone()
        existing_source_id = int(exists["id"]) if exists else None
        if exists and (exists["status"] in {"confirmed", "ignored"} or exists["related_order_id"]):
            result["skipped"] += 1
            continue

        ocr_text, error = extract_text(image_path)
        if error:
            with get_connection() as conn:
                _handle_pending_source(conn, existing_source_id, city, business_date, image_path, digest, ocr_text, None, None, error, None)
                conn.commit()
            result["pending"] += 1
            continue

        parsed = parse_order_text(ocr_text, city, business_date)
        parsed_json = json.dumps(parsed.data, ensure_ascii=False)
        confidence_json = json.dumps(parsed.confidence, ensure_ascii=False)
        task_store = parsed.data.get("store") or parsed.data.get("maintainor_store")

        with get_connection() as conn:
            if parsed.needs_review:
                reason = ";".join(parsed.reasons)
                _handle_pending_source(conn, existing_source_id, city, business_date, image_path, digest, ocr_text, parsed_json, confidence_json, reason, task_store)
                conn.commit()
                result["pending"] += 1
            else:
                before = _find_matching_order(conn, parsed.data)
                _confirm_parsed_image(conn, existing_source_id, city, business_date, image_path, digest, ocr_text, parsed.data, parsed_json, confidence_json)
                conn.commit()
                if before:
                    result["merged"] += 1
                else:
                    result["confirmed"] += 1
    return result
