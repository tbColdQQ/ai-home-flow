import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import current_user
from app.db.session import get_connection
from app.services.auth_service import CurrentUser
from app.services.qa_service import answer_question


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

