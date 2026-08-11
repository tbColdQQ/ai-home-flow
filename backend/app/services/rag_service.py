from app.db.session import rows_to_dicts


def retrieve_context(conn, question: str, city: str, limit: int = 3) -> list[dict]:
    keywords = [word for word in question.replace("?", " ").replace("\uff1f", " ").split() if len(word) >= 2]
    if not keywords:
        return []

    clauses = ["status = 'active'", "(city IS NULL OR city = ?)"]
    params: list[str] = [city]
    like_clauses = []
    for keyword in keywords[:5]:
        like_clauses.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    clauses.append("(" + " OR ".join(like_clauses) + ")")
    params.append(str(limit))
    rows = conn.execute(
        f"""
        SELECT id, title, content, tags
        FROM knowledge_documents
        WHERE {' AND '.join(clauses)}
        ORDER BY id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return rows_to_dicts(rows)
