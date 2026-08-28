import json
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.api.deps import current_user
from app.core.config import settings
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
from app.services.image_import_service import IMAGE_EXTENSIONS, extract_order_from_image
from app.services.knowledge_service import archive_knowledge_document, create_knowledge_document, list_knowledge_documents
from app.services.rag_service import normalize_community_name, retrieve_context
from app.services.qa_service import answer_question, answer_question_stream


router = APIRouter()


def _safe_query_image_name(filename: str) -> str:
    raw_name = Path(filename or "").name
    suffix = Path(raw_name).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式：{suffix or '未知'}")
    stem = Path(raw_name).stem.strip() or "query"
    safe_stem = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", stem)[:80].strip("._") or "query"
    return f"{safe_stem}_{uuid.uuid4().hex[:8]}{suffix}"


def _query_image_deals(conn, city: str, parsed: dict) -> list[dict]:
    residential = parsed.get("residential")
    maintainor = parsed.get("maintainor") or parsed.get("CA")
    acreage = parsed.get("acreage")
    where = ["city = ?", "COALESCE(status, 'normal') = 'normal'"]
    params: list = [city]
    if residential:
        where.append("residential LIKE ?")
        params.append(f"%{residential}%")
    if maintainor:
        where.append("(maintainor LIKE ? OR CA LIKE ? OR agent LIKE ?)")
        params.extend([f"%{maintainor}%", f"%{maintainor}%", f"%{maintainor}%"])
    if acreage:
        where.append("acreage BETWEEN ? AND ?")
        params.extend([float(acreage) - 5, float(acreage) + 5])
    rows = conn.execute(
        f"""
        SELECT ID, signing_date, residential, room_number, acreage, price,
               ROUND(price / NULLIF(acreage, 0), 2) AS unit_price,
               agent, store, maintainor, CA
        FROM orders
        WHERE {' AND '.join(where)}
        ORDER BY signing_date DESC
        LIMIT 20
        """,
        tuple(params),
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def _image_answer(parsed: dict, deals: list[dict], sources: list[dict]) -> str:
    name = parsed.get("residential") or "图片中的小区"
    parts = [f"已识别到小区：{name}。"]
    if parsed.get("acreage"):
        parts.append(f"面积约 {parsed['acreage']} 平。")
    if parsed.get("maintainor"):
        parts.append(f"维护人：{parsed['maintainor']}。")
    if parsed.get("price"):
        parts.append(f"图片价格字段约 {parsed['price']} 元。")
    if deals:
        parts.append(f"按小区、面积和人员信息匹配到 {len(deals)} 条近期成交记录。")
    else:
        parts.append("暂未匹配到对应成交记录。")
    if sources:
        parts.append(f"知识库命中 {len(sources)} 条小区/政策资料，可展开查看来源。")
    return "\n".join(parts)


class AskRequest(BaseModel):
    question: str
    session_id: int | None = None
    mode: str = "auto"


@router.post("/ask")
def ask(body: AskRequest, user: CurrentUser = Depends(current_user)) -> dict:
    with get_connection() as conn:
        result = answer_question(conn, body.question, user.city, body.mode, user.id, body.session_id)
        session_id = body.session_id
        if session_id is None:
            cursor = conn.execute(
                "INSERT INTO chat_sessions(user_id, title) VALUES (?, ?)",
                (user.id, body.question[:40]),
            )
            session_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO chat_messages(session_id, user_id, role, content, result_json)
            VALUES (?, ?, 'user', ?, ?)
            """,
            (session_id, user.id, body.question, json.dumps(result, ensure_ascii=False)),
        )
        conn.execute(
            """
            INSERT INTO chat_messages(session_id, user_id, role, content, result_json)
            VALUES (?, ?, 'assistant', ?, ?)
            """,
            (session_id, user.id, result["answer"], json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
        result["session_id"] = session_id
        return result


def _save_chat_message_pair(conn, user: CurrentUser, question: str, result: dict, session_id: int | None) -> int:
    if session_id is None:
        cursor = conn.execute(
            "INSERT INTO chat_sessions(user_id, title) VALUES (?, ?)",
            (user.id, question[:40]),
        )
        session_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO chat_messages(session_id, user_id, role, content, result_json)
        VALUES (?, ?, 'user', ?, ?)
        """,
        (session_id, user.id, question, json.dumps(result, ensure_ascii=False)),
    )
    conn.execute(
        """
        INSERT INTO chat_messages(session_id, user_id, role, content, result_json)
        VALUES (?, ?, 'assistant', ?, ?)
        """,
        (session_id, user.id, result["answer"], json.dumps(result, ensure_ascii=False)),
    )
    conn.commit()
    return session_id


@router.post("/ask-stream")
def ask_stream(body: AskRequest, user: CurrentUser = Depends(current_user)) -> StreamingResponse:
    def event_stream():
        with get_connection() as conn:
            try:
                for event in answer_question_stream(conn, body.question, user.city, body.mode, user.id, body.session_id):
                    if event["type"] == "final":
                        result = event["result"]
                        result["session_id"] = _save_chat_message_pair(conn, user, body.question, result, body.session_id)
                        event = {"type": "final", "result": result}
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except Exception as exc:
                yield json.dumps({"type": "error", "content": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/ask-image-stream")
async def ask_image_stream(
    file: UploadFile = File(...),
    question: str | None = Form(None),
    user: CurrentUser = Depends(current_user),
) -> StreamingResponse:
    safe_name = _safe_query_image_name(file.filename or "")
    target_dir = settings.image_root / user.city / "h5_query" / date.today().isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name
    try:
        with target_path.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
    finally:
        await file.close()

    def event_stream():
        with get_connection() as conn:
            try:
                yield json.dumps({"type": "status", "content": "正在识别图片文字..."}, ensure_ascii=False) + "\n"
                ocr_text, error, parsed_data, confidence, reasons, ocr_provider = extract_order_from_image(
                    target_path, user.city, date.today().isoformat()
                )
                if error:
                    yield json.dumps({"type": "error", "content": error}, ensure_ascii=False) + "\n"
                    return
                normalized = normalize_community_name(conn, user.city, parsed_data.get("residential"))
                if normalized.get("name"):
                    parsed_data["residential"] = normalized["name"]
                image_payload = {
                    "file_name": file.filename,
                    "ocr_text": ocr_text,
                    "parsed": parsed_data,
                    "confidence": confidence,
                    "reasons": reasons,
                    "ocr_provider": ocr_provider,
                    "community_normalization": normalized,
                    "saved_path": str(target_path),
                }
                yield json.dumps({"type": "image_ocr", "content": image_payload}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "status", "content": "正在查询成交数据..."}, ensure_ascii=False) + "\n"
                deals = _query_image_deals(conn, user.city, parsed_data)
                yield json.dumps({"type": "deal_result", "content": {"rows": deals, "total": len(deals)}}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "status", "content": "正在检索知识库..."}, ensure_ascii=False) + "\n"
                source_question = " ".join(
                    part
                    for part in [parsed_data.get("residential"), "小区 情况 政策 楼盘 配套", question or ""]
                    if part
                )
                sources = retrieve_context(
                    conn,
                    source_question or ocr_text[:200],
                    user.city,
                    entities={"community_name": parsed_data.get("residential"), "community_name_raw": parsed_data.get("residential")},
                )
                if sources:
                    yield json.dumps({"type": "sources", "content": sources}, ensure_ascii=False) + "\n"
                answer = _image_answer(parsed_data, deals, sources)
                for line in answer.splitlines(True):
                    yield json.dumps({"type": "delta", "content": line}, ensure_ascii=False) + "\n"
                result = {
                    "answer": answer,
                    "answer_source": "local_image_query",
                    "intent": "image_query",
                    "status": "completed",
                    "image_query": image_payload,
                    "deal_result": {"rows": deals, "total": len(deals)},
                    "data": deals,
                    "rag_context": sources,
                    "sources": sources,
                }
                yield json.dumps({"type": "final", "result": result}, ensure_ascii=False) + "\n"
            except Exception as exc:
                yield json.dumps({"type": "error", "content": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/knowledge")
async def upload_knowledge(
    title: str = Form(...),
    knowledge_type: str = Form("楼盘信息"),
    community_name: str | None = Form(None),
    content: str | None = Form(None),
    source_url: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(current_user),
) -> dict:
    file_content = await file.read() if file else None
    with get_connection() as conn:
        try:
            result = create_knowledge_document(
                conn,
                user,
                title=title,
                community_name=community_name,
                knowledge_type=knowledge_type,
                content=content,
                source_url=source_url,
                file=file,
                file_content=file_content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
        return result


@router.get("/knowledge")
def list_knowledge(user: CurrentUser = Depends(current_user)) -> list[dict]:
    with get_connection() as conn:
        return list_knowledge_documents(conn, user)


@router.delete("/knowledge/{document_id}")
def delete_knowledge(document_id: int, user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    if "admin" not in user.role_codes:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    with get_connection() as conn:
        if not archive_knowledge_document(conn, document_id):
            raise HTTPException(status_code=404, detail="知识不存在")
        conn.commit()
    return {"message": "deleted"}
