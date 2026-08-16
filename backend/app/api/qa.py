import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.api.deps import current_user
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
from app.services.knowledge_service import archive_knowledge_document, create_knowledge_document, list_knowledge_documents
from app.services.qa_service import answer_question, answer_question_stream


router = APIRouter()


class AskRequest(BaseModel):
    question: str
    session_id: int | None = None


@router.post("/ask")
def ask(body: AskRequest, user: CurrentUser = Depends(current_user)) -> dict:
    with get_connection() as conn:
        result = answer_question(conn, body.question, user.city)
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
                for event in answer_question_stream(conn, body.question, user.city):
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/knowledge")
async def upload_knowledge(
    title: str = Form(...),
    knowledge_type: str = Form("楼盘信息"),
    community_name: str | None = Form(None),
    content: str | None = Form(None),
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
