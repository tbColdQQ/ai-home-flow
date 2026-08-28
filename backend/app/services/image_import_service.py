import base64
import datetime as dt
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.request
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


ORDER_MATCH_FIELDS = ("city", "residential", "acreage", "price")
COMPLEMENTARY_ORDER_FIELDS = (
    "agent",
    "store",
    "maintainor",
    "maintainor_store",
    "CA",
    "brand",
    "signing_date",
    "report_type",
)
OCR_FILL_FIELDS = (
    "residential",
    "price",
    "acreage",
    "signing_date",
    "agent",
    "store",
    "maintainor",
    "maintainor_store",
    "CA",
    "brand",
    "report_type",
)


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
    except Exception as exc:
        return "", f"未安装 RapidOCR 组件或依赖加载失败：{exc}"

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
    except Exception as exc:
        return "", f"未安装 Tesseract OCR Python 组件或依赖加载失败：{exc}"

    try:
        text = pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng").strip()
    except Exception as exc:
        return "", f"Tesseract OCR 识别失败：{exc}"
    if not text:
        return "", "Tesseract OCR 未识别到有效文字"
    return text, None


def _tencent_ocr_configured() -> bool:
    return bool(settings.tencent_ocr_secret_id and settings.tencent_ocr_secret_key)


def _tc3_sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _extract_text_with_tencent_ocr(path: Path) -> tuple[str, str | None]:
    if not _tencent_ocr_configured():
        return "", "Tencent OCR credentials are not configured"

    endpoint = "ocr.tencentcloudapi.com"
    service = "ocr"
    version = "2018-11-19"
    action = settings.tencent_ocr_action
    region = settings.tencent_ocr_region
    timestamp = int(time.time())
    date = dt.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")

    try:
        image_base64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        payload = json.dumps({"ImageBase64": image_base64}, separators=(",", ":"))
    except Exception as exc:
        return "", f"Tencent OCR image read failed: {exc}"

    canonical_headers = (
        f"content-type:application/json; charset=utf-8\n"
        f"host:{endpoint}\n"
        f"x-tc-action:{action.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            "",
            canonical_headers,
            signed_headers,
            hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        ]
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _tc3_sign(("TC3" + settings.tencent_ocr_secret_key).encode("utf-8"), date)
    secret_service = _tc3_sign(secret_date, service)
    secret_signing = _tc3_sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={settings.tencent_ocr_secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": endpoint,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }
    request = urllib.request.Request(
        f"https://{endpoint}",
        data=payload.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.tencent_ocr_timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return "", f"Tencent OCR HTTP {exc.code}: {body[:300]}"
    except Exception as exc:
        return "", f"Tencent OCR failed: {exc}"

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return "", f"Tencent OCR response decode failed: {exc}"

    payload_response = data.get("Response") or {}
    api_error = payload_response.get("Error")
    if api_error:
        return "", f"Tencent OCR error: {api_error.get('Code')} {api_error.get('Message')}"

    lines = [
        str(item.get("DetectedText", "")).strip()
        for item in payload_response.get("TextDetections") or []
        if str(item.get("DetectedText", "")).strip()
    ]
    if not lines:
        return "", "Tencent OCR did not return detected text"
    return "\n".join(lines), None


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


def _compact_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _line_after_ocr_labels(lines: list[str], labels: list[str]) -> str | None:
    normalized_labels = sorted({_compact_text(label).strip(":：") for label in labels}, key=len, reverse=True)
    for index, line in enumerate(lines):
        compact_line = _compact_text(line)
        for label in normalized_labels:
            if compact_line == label:
                for next_line in lines[index + 1 :]:
                    value = next_line.strip().strip(":：").strip()
                    if value:
                        return value
            if compact_line.startswith(label):
                value = line[len(label) :].strip().strip(":：").strip()
                if value:
                    return value
    return None


def _number_from_ocr(value: str | None, unit_multiplier: bool = False) -> float | None:
    if not value:
        return None
    text = value.replace(",", "").replace("，", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    if unit_multiplier and "万" in text:
        return number * 10000
    return number


def _looks_like_store(value: str) -> bool:
    compact = _compact_text(value)
    return len(compact) >= 4 and (compact.endswith("店") or compact.endswith("门店"))


def _looks_like_person(value: str) -> bool:
    compact = _compact_text(value)
    if not 2 <= len(compact) <= 5:
        return False
    if re.search(r"\d|[A-Za-z]", compact):
        return False
    if re.search(r"(税务局|公安局|财政局|住建局|市场监管局|管理局|委员会|办事处|法院|检察院|医院|学校|银行|公司|集团)$", compact):
        return False
    if any(token in compact for token in ["贝壳", "德佑", "喜报", "贺报", "小区", "楼盘", "金额", "面积", "品牌", "今日", "累计", "签单", "房源"]):
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fa5·]+", compact))


def _looks_like_org_name(value: str | None) -> bool:
    return bool(value and re.search(r"(税务局|公安局|财政局|住建局|市场监管局|管理局|委员会|办事处|法院|检察院|医院|学校|银行|公司|集团)$", _compact_text(value)))


def _participant_and_store_from_ocr(lines: list[str], data: dict) -> tuple[str | None, str | None]:
    participant = None
    store = None
    skip_values = {
        _compact_text(data.get("residential")),
        _compact_text(data.get("CA")),
        _compact_text(data.get("brand")),
    }
    for line in lines:
        value = line.strip().strip(":：").strip()
        compact = _compact_text(value)
        if not compact or compact in skip_values:
            continue
        if any(token in compact for token in ["签约金额", "签约小区", "签约面积", "签约品牌", "签约CA", "维护楼盘", "成交价格", "房源面积", "维护人CA", "今日"]):
            continue
        if store is None and _looks_like_store(value):
            store = compact
            continue
        if participant is None and _looks_like_person(value):
            participant = compact
    return participant, store


def _enhance_parsed_data_from_ocr(data: dict, ocr_text: str) -> dict:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    compact = _compact_text(ocr_text)
    if data.get("report_type") in (None, "", "unknown"):
        if any(token in compact for token in ["房源售出", "贺报", "賀報"]):
            data["report_type"] = "agent_report"
        elif any(token in compact for token in ["签约金额", "签约小区", "签约面积", "签约CA", "喜报"]):
            data["report_type"] = "maintainor_report"
        elif any(token in compact for token in ["维护楼盘", "维护人CA"]):
            data["report_type"] = "agent_report"

    if not data.get("residential"):
        data["residential"] = _line_after_ocr_labels(lines, ["维护楼盘", "签约小区", "成交小区", "楼盘", "小区"])
    if not data.get("price"):
        data["price"] = _number_from_ocr(_line_after_ocr_labels(lines, ["成交价格", "签约金额", "成交价"]), unit_multiplier=True)
    if not data.get("acreage"):
        data["acreage"] = _number_from_ocr(_line_after_ocr_labels(lines, ["房源面积", "签约面积", "面积"]))
    if not data.get("CA"):
        data["CA"] = _line_after_ocr_labels(lines, ["维护人CA", "维护人 CA", "签约CA", "签约 CA", "CA"])
    if not data.get("brand"):
        data["brand"] = _line_after_ocr_labels(lines, ["签约品牌", "品牌"])

    participant, store = _participant_and_store_from_ocr(lines, data)
    if data.get("report_type") == "maintainor_report":
        if not data.get("maintainor"):
            data["maintainor"] = participant
        if not data.get("maintainor_store"):
            data["maintainor_store"] = store
    elif data.get("report_type") == "agent_report":
        if not data.get("agent"):
            data["agent"] = participant
        if not data.get("store"):
            data["store"] = store
    return data


def _review_reasons(data: dict) -> list[str]:
    reasons = []
    required = {
        "residential": "楼盘缺失",
        "price": "成交价格缺失或格式异常",
        "acreage": "房源面积缺失或格式异常",
        "signing_date": "成交日期缺失",
    }
    if data.get("report_type") == "agent_report":
        required["agent"] = "成交人缺失"
        required["store"] = "成交人门店缺失"
    elif data.get("report_type") == "maintainor_report":
        required["maintainor"] = "维护人缺失"
        required["maintainor_store"] = "维护人门店缺失"
    else:
        reasons.append("无法识别图片类型")
    for field, reason in required.items():
        if not data.get(field):
            reasons.append(reason)
    return reasons


def _merge_ocr_data(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    for field in OCR_FILL_FIELDS:
        if merged.get(field) in (None, "") and incoming.get(field) not in (None, ""):
            merged[field] = incoming[field]
    return merged


def _parse_ocr_order_text(ocr_text: str, city: str, business_date: str) -> tuple[dict, dict, list[str]]:
    parsed = parse_order_text(ocr_text, city, business_date)
    parsed_data = _enhance_parsed_data_from_ocr(dict(parsed.data), ocr_text)
    return parsed_data, dict(parsed.confidence), _review_reasons(parsed_data)


def extract_order_from_image(path: Path, city: str, business_date: str) -> tuple[str, str | None, dict, dict, list[str], str]:
    local_text, local_error = extract_text(path)
    if local_text:
        parsed_data, confidence, review_reasons = _parse_ocr_order_text(local_text, city, business_date)
    else:
        parsed_data, confidence, review_reasons = {}, {}, ["local OCR did not return text"]

    provider = "local"
    cloud_error = None
    should_try_cloud = bool(local_error or review_reasons)
    if should_try_cloud and _tencent_ocr_configured():
        cloud_text, cloud_error = _extract_text_with_tencent_ocr(path)
        if cloud_text:
            cloud_data, cloud_confidence, cloud_reasons = _parse_ocr_order_text(cloud_text, city, business_date)
            if local_text:
                merged_data = _merge_ocr_data(parsed_data, cloud_data)
                merged_reasons = _review_reasons(merged_data)
            else:
                merged_data = cloud_data
                merged_reasons = cloud_reasons

            cloud_filled_more = sum(1 for field in OCR_FILL_FIELDS if cloud_data.get(field)) > sum(
                1 for field in OCR_FILL_FIELDS if parsed_data.get(field)
            )
            if len(merged_reasons) < len(review_reasons) or (
                len(merged_reasons) == len(review_reasons) and cloud_filled_more
            ):
                parsed_data = merged_data
                confidence = {**confidence, **cloud_confidence}
                review_reasons = merged_reasons
                provider = "local+tencent"
                local_text = f"{local_text}\n\n[Tencent OCR]\n{cloud_text}".strip()
        elif not local_text and cloud_error:
            return "", f"{local_error or 'Local OCR failed'}; {cloud_error}", {}, {}, [], "local+tencent"

    if not local_text:
        return "", local_error or cloud_error or "OCR did not return text", {}, {}, [], provider
    return local_text, None, parsed_data, confidence, review_reasons, provider


def _same_order_identity(left: dict, right: dict) -> bool:
    if any(left.get(field) in (None, "") or right.get(field) in (None, "") for field in ORDER_MATCH_FIELDS):
        return False
    return (
        str(left.get("city")) == str(right.get("city"))
        and str(left.get("residential")) == str(right.get("residential"))
        and abs(float(left.get("acreage") or 0) - float(right.get("acreage") or 0)) < 0.001
        and abs(float(left.get("price") or 0) - float(right.get("price") or 0)) < 0.001
    )


def _merge_order_data(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    for field in COMPLEMENTARY_ORDER_FIELDS:
        if merged.get(field) in (None, "") and incoming.get(field) not in (None, ""):
            merged[field] = incoming[field]
    return merged


def _find_matching_pending_task(conn, city: str, payload: dict, source_id: int | None) -> dict | None:
    rows = conn.execute(
        """
        SELECT id, source_id, payload_json
        FROM task_items
        WHERE source_type = 'image'
          AND status = 'pending'
          AND city = ?
          AND source_id IS NOT ?
        ORDER BY id DESC
        LIMIT 200
        """,
        (city, source_id),
    ).fetchall()
    for row in rows:
        try:
            existing_payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if _same_order_identity(existing_payload, payload):
            return {"id": row["id"], "source_id": row["source_id"], "payload": existing_payload}
    return None


def _upsert_pending_task(conn, source_id: int | None, city: str, store: str | None, payload_json: str | None, reason: str) -> None:
    payload = None
    if payload_json:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            payload = None
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
    if not task and isinstance(payload, dict):
        task = _find_matching_pending_task(conn, city, payload, source_id)
        if task:
            payload = _merge_order_data(task["payload"], payload)
            payload_json = json.dumps(payload, ensure_ascii=False)
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


def mark_matching_image_tasks_done(conn, order_data: dict, order_id: int) -> None:
    rows = conn.execute(
        """
        SELECT id, payload_json
        FROM task_items
        WHERE source_type = 'image'
          AND status = 'pending'
          AND city = ?
        ORDER BY id DESC
        LIMIT 200
        """,
        (order_data.get("city"),),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if not _same_order_identity(payload, order_data):
            continue
        conn.execute(
            """
            UPDATE task_items
            SET status = 'done',
                result_ref_type = 'order',
                result_ref_id = ?,
                finish_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (order_id, row["id"]),
        )


def confirm_image_task_order(conn, task: dict, order_data: dict) -> int:
    parsed_json = json.dumps(order_data, ensure_ascii=False)
    image_path = Path(task.get("file_path") or task.get("source_file") or "")
    _apply_community_fields(conn, order_data)
    existing_order = _find_matching_order(conn, order_data)
    source_id = task.get("source_id")
    if existing_order:
        order_id = int(existing_order["ID"])
        payload = _merge_order_payload(existing_order, order_data, int(source_id or 0), image_path, parsed_json)
        _update_order_from_image(conn, order_id, payload)
    else:
        order_data.setdefault("source_type", task.get("source_type"))
        order_data.setdefault("source_id", source_id)
        if image_path:
            order_data.setdefault("source_file", str(image_path))
        order_data.setdefault("raw_payload_json", parsed_json)
        order_id = create_order(conn, order_data)

    if task.get("source_type") == "image" and source_id:
        conn.execute(
            """
            UPDATE source_images
            SET status = 'confirmed',
                related_order_id = ?,
                parsed_result_json = ?,
                error_message = NULL,
                modify_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (order_id, parsed_json, source_id),
        )
        mark_matching_image_tasks_done(conn, order_data, order_id)
    return order_id


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


def _source_has_active_order(conn, source_row) -> bool:
    if not source_row or not source_row["related_order_id"]:
        return False
    order = conn.execute(
        """
        SELECT ID
        FROM orders
        WHERE ID = ?
          AND COALESCE(status, 'normal') != 'cancel'
        LIMIT 1
        """,
        (source_row["related_order_id"],),
    ).fetchone()
    return order is not None


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
            continue
        if value not in (None, "") and (field in {"raw_payload_json"} or not existing.get(field)):
            payload[field] = value

    if data.get("report_type") == "agent_report":
        if data.get("agent") and (
            not existing.get("agent")
            or existing.get("agent") == existing.get("maintainor")
            or existing.get("agent") == data.get("maintainor")
            or _looks_like_org_name(existing.get("agent"))
            or (
                existing.get("source_type") == "image"
                and not existing.get("maintainor")
                and existing.get("store")
                and data.get("store")
                and existing.get("store") != data.get("store")
            )
            or (
                existing.get("source_type") == "image"
                and existing.get("maintainor") == data.get("agent")
            )
        ):
            payload["agent"] = data["agent"]
        if data.get("store") and (
            not existing.get("store")
            or existing.get("store") == existing.get("maintainor_store")
            or existing.get("store") == data.get("maintainor_store")
            or (
                existing.get("source_type") == "image"
                and not existing.get("maintainor_store")
                and existing.get("agent")
                and data.get("agent")
                and existing.get("agent") != data.get("agent")
            )
            or (
                existing.get("source_type") == "image"
                and existing.get("maintainor_store") == data.get("store")
            )
        ):
            payload["store"] = data["store"]

    if data.get("report_type") == "maintainor_report":
        if data.get("maintainor") and (
            not existing.get("maintainor")
            or existing.get("maintainor") == existing.get("agent")
            or existing.get("maintainor") == data.get("agent")
            or _looks_like_org_name(existing.get("maintainor"))
            or (
                existing.get("source_type") == "image"
                and existing.get("agent") == data.get("maintainor")
            )
        ):
            payload["maintainor"] = data["maintainor"]
        if data.get("maintainor_store") and (
            not existing.get("maintainor_store")
            or existing.get("maintainor_store") == existing.get("store")
            or existing.get("maintainor_store") == data.get("store")
            or (
                existing.get("source_type") == "image"
                and existing.get("store") == data.get("maintainor_store")
            )
        ):
            payload["maintainor_store"] = data["maintainor_store"]
    merged_snapshot = dict(existing)
    merged_snapshot.update({key: value for key, value in payload.items() if key != "modify_time"})
    for source_field in OCR_FILL_FIELDS:
        if data.get(source_field) not in (None, ""):
            merged_snapshot[source_field] = data[source_field]
    payload["raw_payload_json"] = json.dumps(merged_snapshot, ensure_ascii=False, default=str)
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


def scan_images(
    root: Path | None = None,
    city: str | None = None,
    business_date: str | None = None,
    only_paths: list[Path] | None = None,
) -> dict:
    root = root or settings.image_root
    root.mkdir(parents=True, exist_ok=True)
    result = {"scanned": 0, "confirmed": 0, "merged": 0, "pending": 0, "skipped": 0, "failed": 0, "details": []}
    scan_root = root
    fixed_city = city
    fixed_business_date = business_date
    scan_paths = only_paths
    if city and business_date:
        scan_root = root / city / business_date
        result["target_dir"] = str(scan_root)
        if not scan_root.exists():
            result["details"].append(
                {
                    "file_name": "",
                    "status": "missing_dir",
                    "message": "扫描目录不存在",
                    "target_dir": str(scan_root),
                }
            )
            return result

    if scan_paths is None:
        scan_paths = list(scan_root.rglob("*"))
    else:
        allowed_root = scan_root.resolve()
        scan_paths = [Path(path) for path in scan_paths if Path(path).resolve().parent == allowed_root]

    for image_path in scan_paths:
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        result["scanned"] += 1
        parts = image_path.relative_to(root).parts
        digest = file_hash(image_path)
        if fixed_city and fixed_business_date:
            city, business_date = fixed_city, fixed_business_date
        elif len(parts) >= 3:
            city, business_date = parts[0], parts[1]
        else:
            with get_connection() as conn:
                _insert_source_image(conn, "", "", image_path, digest, "", "failed", error_message="图片目录必须为：城市/日期/图片")
                conn.commit()
            result["failed"] += 1
            result["details"].append(
                {
                    "file_name": image_path.name,
                    "status": "failed",
                    "message": "图片目录必须为：城市/日期/图片",
                }
            )
            continue
        with get_connection() as conn:
            exists = conn.execute(
                "SELECT id, status, related_order_id, error_message FROM source_images WHERE file_hash = ?",
                (digest,),
            ).fetchone()
            can_skip_existing = bool(exists and exists["status"] in {"confirmed", "ignored"} and _source_has_active_order(conn, exists))
        existing_source_id = int(exists["id"]) if exists else None
        if can_skip_existing:
            result["skipped"] += 1
            result["details"].append(
                {
                    "file_name": image_path.name,
                    "status": "skipped",
                    "message": "图片已处理过，且成交记录仍有效，已跳过",
                    "source_id": existing_source_id,
                    "order_id": exists["related_order_id"],
                    "source_status": exists["status"],
                }
            )
            continue

        ocr_text, error, parsed_data, confidence, review_reasons, ocr_provider = extract_order_from_image(
            image_path, city, business_date
        )
        if error:
            with get_connection() as conn:
                source_id = _handle_pending_source(conn, existing_source_id, city, business_date, image_path, digest, ocr_text, None, None, error, None)
                conn.commit()
            result["pending"] += 1
            result["details"].append(
                {
                    "file_name": image_path.name,
                    "status": "pending",
                    "message": error,
                    "source_id": source_id,
                }
            )
            continue

        parsed_json = json.dumps(parsed_data, ensure_ascii=False)
        confidence_json = json.dumps({**confidence, "ocr_provider": ocr_provider}, ensure_ascii=False)
        task_store = parsed_data.get("store") or parsed_data.get("maintainor_store")

        with get_connection() as conn:
            if review_reasons:
                reason = ";".join(review_reasons)
                source_id = _handle_pending_source(conn, existing_source_id, city, business_date, image_path, digest, ocr_text, parsed_json, confidence_json, reason, task_store)
                conn.commit()
                result["pending"] += 1
                result["details"].append(
                    {
                        "file_name": image_path.name,
                        "status": "pending",
                        "message": reason,
                        "source_id": source_id,
                        "parsed": parsed_data,
                    }
                )
            else:
                before = _find_matching_order(conn, parsed_data)
                order_id = _confirm_parsed_image(conn, existing_source_id, city, business_date, image_path, digest, ocr_text, parsed_data, parsed_json, confidence_json)
                conn.commit()
                if before:
                    result["merged"] += 1
                    result["details"].append(
                        {
                            "file_name": image_path.name,
                            "status": "merged",
                            "message": "已匹配到现有成交记录并合并",
                            "order_id": order_id,
                            "parsed": parsed_data,
                        }
                    )
                else:
                    result["confirmed"] += 1
                    result["details"].append(
                        {
                            "file_name": image_path.name,
                            "status": "confirmed",
                            "message": "已新增成交记录",
                            "order_id": order_id,
                            "parsed": parsed_data,
                        }
                    )
    return result
