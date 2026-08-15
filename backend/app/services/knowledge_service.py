import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.config import settings
from app.db.session import rows_to_dicts
from app.services.auth_service import CurrentUser
from app.services.image_import_service import extract_text


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PDF_EXTENSIONS = {".pdf"}
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


def _safe_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).stem).strip("._") or "knowledge"
    digest = hashlib.sha1(f"{filename}-{datetime.now().isoformat()}".encode("utf-8")).hexdigest()[:10]
    return f"{stem}_{digest}{suffix}"


def _write_file(filename: str, content: bytes) -> Path:
    today = datetime.now().strftime("%Y%m%d")
    folder = settings.knowledge_root / today
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _safe_filename(filename)
    path.write_bytes(content)
    return path


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise ValueError("当前环境缺少 pypdf，无法解析 PDF，请安装后重试。") from exc

    from io import BytesIO

    reader = PdfReader(BytesIO(content))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n".join(page for page in pages if page)
    if not text.strip():
        raise ValueError("PDF 中未提取到文字，可能是扫描件，请上传图片或可复制文本的 PDF。")
    return text


def _extract_upload_text(file: UploadFile | None, file_content: bytes | None) -> tuple[str, str | None, str | None]:
    if file is None or not file.filename or not file_content:
        return "", None, None

    suffix = Path(file.filename).suffix.lower()
    file_path = _write_file(file.filename, file_content)

    if suffix in PDF_EXTENSIONS:
        return _extract_pdf_text(file_content), "pdf", str(file_path)
    if suffix in IMAGE_EXTENSIONS:
        text, error = extract_text(file_path)
        if error:
            raise ValueError(error)
        return text, "image", str(file_path)
    if suffix in {".txt", ".md"}:
        return file_content.decode("utf-8", errors="ignore"), "text", str(file_path)
    raise ValueError("仅支持上传 PDF、图片、txt 或 md 文件。")


def split_chunks(content: str) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", content).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - CHUNK_OVERLAP)
    return chunks


def create_knowledge_document(
    conn,
    user: CurrentUser,
    *,
    title: str,
    community_name: str | None,
    knowledge_type: str,
    content: str | None,
    file: UploadFile | None,
    file_content: bytes | None,
) -> dict[str, Any]:
    title = title.strip()
    knowledge_type = knowledge_type.strip() or "楼盘信息"
    community_name = (community_name or "").strip() or None
    typed_content = (content or "").strip()
    file_text, source_type, file_path = _extract_upload_text(file, file_content)
    merged_content = "\n\n".join(part for part in [typed_content, file_text.strip()] if part).strip()
    if not title:
        raise ValueError("请填写知识标题。")
    if not merged_content:
        raise ValueError("请填写文字内容，或上传可识别的 PDF/图片/文本文件。")

    scope_where = "city = ? AND COALESCE(community_name, '') = ? AND knowledge_type = ? AND status = 'active'"
    scope_params = (user.city, community_name or "", knowledge_type)
    latest = conn.execute(
        "SELECT MAX(version) AS version FROM knowledge_documents WHERE city = ? AND COALESCE(community_name, '') = ? AND knowledge_type = ?",
        scope_params,
    ).fetchone()
    version = int((latest["version"] if latest else 0) or 0) + 1

    old_rows = conn.execute(f"SELECT id FROM knowledge_documents WHERE {scope_where}", scope_params).fetchall()
    old_ids = [row["id"] for row in old_rows]
    if old_ids:
        placeholders = ",".join("?" for _ in old_ids)
        conn.execute(
            f"UPDATE knowledge_documents SET status = 'archived', archived_time = CURRENT_TIMESTAMP, modify_time = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            tuple(old_ids),
        )
        conn.execute(
            f"UPDATE knowledge_chunks SET status = 'archived' WHERE document_id IN ({placeholders})",
            tuple(old_ids),
        )

    cursor = conn.execute(
        """
        INSERT INTO knowledge_documents(
            title, content, city, tags, status, community_name, knowledge_type,
            source_type, source_file, file_path, uploader_user_id, version
        )
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            merged_content,
            user.city,
            ",".join(part for part in [community_name, knowledge_type] if part),
            community_name,
            knowledge_type,
            source_type or "text",
            file.filename if file else None,
            file_path,
            user.id,
            version,
        ),
    )
    document_id = int(cursor.lastrowid)

    chunks = split_chunks(merged_content)
    conn.executemany(
        """
        INSERT INTO knowledge_chunks(document_id, city, community_name, knowledge_type, chunk_index, content)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(document_id, user.city, community_name, knowledge_type, index, chunk) for index, chunk in enumerate(chunks)],
    )
    return {"id": document_id, "version": version, "chunks": len(chunks)}


def list_knowledge_documents(conn, user: CurrentUser) -> list[dict]:
    where_sql = "1 = 1"
    params: tuple = ()
    if "admin" not in user.role_codes:
        where_sql = "kd.status = 'active' AND kd.city = ?"
        params = (user.city,)
    rows = conn.execute(
        f"""
        SELECT kd.id, kd.title, kd.city, kd.community_name, kd.knowledge_type, kd.source_type,
               kd.source_file, kd.version, kd.status, kd.create_time, kd.modify_time,
               u.display_name AS uploader,
               SUBSTR(kd.content, 1, 240) AS summary
        FROM knowledge_documents kd
        LEFT JOIN users u ON u.id = kd.uploader_user_id
        WHERE {where_sql}
        ORDER BY kd.id DESC
        LIMIT 200
        """,
        params,
    ).fetchall()
    return rows_to_dicts(rows)


def archive_knowledge_document(conn, document_id: int) -> bool:
    cursor = conn.execute(
        """
        UPDATE knowledge_documents
        SET status = 'archived', archived_time = CURRENT_TIMESTAMP, modify_time = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'active'
        """,
        (document_id,),
    )
    conn.execute("UPDATE knowledge_chunks SET status = 'archived' WHERE document_id = ?", (document_id,))
    return cursor.rowcount > 0
