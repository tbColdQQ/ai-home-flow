import re

from app.db.session import rows_to_dicts


def _keywords(question: str) -> list[str]:
    segments = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", question)
    keywords: list[str] = []
    for segment in segments:
        if segment not in keywords:
            keywords.append(segment)
        if len(segment) > 8:
            for size in (4, 3, 2):
                for index in range(0, len(segment) - size + 1):
                    token = segment[index : index + size]
                    if token not in keywords:
                        keywords.append(token)
                    if len(keywords) >= 12:
                        return keywords
    return keywords[:12]


def retrieve_context(conn, question: str, city: str, limit: int = 5) -> list[dict]:
    keywords = _keywords(question)
    if not keywords:
        return []

    clauses = ["kd.status = 'active'", "kc.status = 'active'", "(kd.city IS NULL OR kd.city = ?)"]
    params: list[str] = [city]
    like_clauses = []
    for keyword in keywords:
        like_clauses.append("(kd.title LIKE ? OR kc.content LIKE ? OR kd.tags LIKE ? OR kd.community_name LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    clauses.append("(" + " OR ".join(like_clauses) + ")")
    params.append(str(limit))
    rows = conn.execute(
        f"""
        SELECT kd.id, kd.title, kc.content, kd.tags, kd.community_name, kd.knowledge_type,
               kd.source_type, kd.source_file, kd.version, kd.create_time
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        WHERE {' AND '.join(clauses)}
        ORDER BY kd.create_time DESC, kc.chunk_index ASC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return rows_to_dicts(rows)
