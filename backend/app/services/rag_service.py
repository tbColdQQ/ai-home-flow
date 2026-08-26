import re
from difflib import SequenceMatcher
from typing import Any

from app.db.session import rows_to_dicts
from app.services.vector_service import query_knowledge


KNOWLEDGE_KEYWORDS = {
    "policy": ["政策", "规则", "资格", "限购", "贷款", "税费", "流程", "制度", "标准"],
    "community": ["小区", "楼盘", "学区", "配套", "交通", "物业", "优缺点", "怎么样", "情况"],
}
QUERY_STOP_TERMS = {"小区", "楼盘", "学区", "划分", "情况", "政策", "资料", "怎么", "怎么样", "的"}


def _keywords(question: str) -> list[str]:
    segments = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", question)
    keywords: list[str] = []
    for segment in segments:
        if segment not in keywords:
            keywords.append(segment)
        if len(segment) > 6:
            for size in (4, 3, 2):
                for index in range(0, len(segment) - size + 1):
                    token = segment[index : index + size]
                    if token not in keywords:
                        keywords.append(token)
                    if len(keywords) >= 40:
                        return keywords
    return keywords[:40]


def _important_terms(question: str) -> list[str]:
    terms: list[str] = []
    for segment in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", question):
        compact = segment
        for stop_term in QUERY_STOP_TERMS:
            compact = compact.replace(stop_term, "")
        if len(compact) >= 5 and re.search(r"[\u4e00-\u9fa5]", compact):
            candidates = [compact[:3], compact[3:]]
        elif len(compact) >= 4:
            candidates = [compact[:2], compact[2:]]
        else:
            candidates = [compact]
        for candidate in candidates:
            if len(candidate) >= 2 and candidate not in terms:
                terms.append(candidate)
    return terms[:8]


def _compact_name(value: str | None) -> str:
    text = re.sub(r"\s+", "", value or "")
    return text.replace("3", "三").replace("Ⅲ", "三").replace("III", "三").lower()


def _community_candidates(conn, city: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT name FROM communities WHERE city = ?
        UNION
        SELECT residential AS name FROM orders WHERE city = ? AND residential IS NOT NULL
        UNION
        SELECT community_name AS name FROM knowledge_documents
        WHERE city = ? AND status = 'active' AND community_name IS NOT NULL
        """,
        (city, city, city),
    ).fetchall()
    names: list[str] = []
    for row in rows:
        name = (row["name"] or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def normalize_community_name(conn, city: str, raw_name: str | None) -> dict[str, Any]:
    raw = (raw_name or "").strip()
    if not raw:
        return {"raw": None, "name": None, "matched": False, "score": 0.0, "ambiguous": False, "candidates": []}
    compact_raw = _compact_name(raw)
    scored: list[tuple[float, str]] = []
    for candidate in _community_candidates(conn, city):
        compact_candidate = _compact_name(candidate)
        if not compact_candidate:
            continue
        if compact_raw == compact_candidate:
            score = 1.0
        elif compact_raw in compact_candidate or compact_candidate in compact_raw:
            score = 0.86
        else:
            score = SequenceMatcher(None, compact_raw, compact_candidate).ratio()
        if score >= 0.58:
            scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return {"raw": raw, "name": raw, "matched": False, "score": 0.0, "ambiguous": False, "candidates": []}
    top_score, top_name = scored[0]
    alternatives = [{"name": name, "score": round(score, 3)} for score, name in scored[:5]]
    ambiguous = len(scored) > 1 and top_score < 0.88 and (top_score - scored[1][0]) < 0.08
    if top_score < 0.68:
        return {"raw": raw, "name": raw, "matched": False, "score": round(top_score, 3), "ambiguous": ambiguous, "candidates": alternatives}
    return {"raw": raw, "name": top_name, "matched": True, "score": round(top_score, 3), "ambiguous": ambiguous, "candidates": alternatives}


def extract_entities(conn, question: str, city: str, llm_entities: dict[str, Any] | None = None) -> dict[str, Any]:
    keywords = _keywords(question)
    category = None
    if any(word in question for word in KNOWLEDGE_KEYWORDS["policy"]):
        category = "policy"
    if any(word in question for word in KNOWLEDGE_KEYWORDS["community"]):
        category = "community" if category is None else category
    community_name = None
    raw_community = None
    if isinstance(llm_entities, dict):
        raw_community = llm_entities.get("community_name") or llm_entities.get("community_name_raw")
        if llm_entities.get("topic"):
            category = category or str(llm_entities.get("topic"))
    normalized = normalize_community_name(conn, city, raw_community)
    if normalized.get("name") and normalized.get("matched"):
        community_name = normalized["name"]
    for token in keywords:
        if community_name:
            break
        row = conn.execute(
            """
            SELECT community_name
            FROM knowledge_documents
            WHERE status = 'active'
              AND city = ?
              AND community_name IS NOT NULL
              AND (community_name LIKE ? OR tags LIKE ?)
            ORDER BY version DESC
            LIMIT 1
            """,
            (city, f"%{token}%", f"%{token}%"),
        ).fetchone()
        if row:
            community_name = row["community_name"]
            break
    return {
        "city": city,
        "keywords": keywords,
        "category": category,
        "community_name_raw": raw_community,
        "community_name": community_name,
        "community_normalization": normalized,
    }


def rewrite_query(question: str, entities: dict[str, Any]) -> str:
    parts = [question]
    if entities.get("community_name"):
        parts.append(str(entities["community_name"]))
    if entities.get("category") == "policy":
        parts.extend(["政策", "规则", "流程"])
    elif entities.get("category") == "community":
        parts.extend(["小区", "楼盘", "配套", "情况"])
    return " ".join(part for part in parts if part)


def _keyword_retrieve(conn, question: str, city: str, limit: int) -> list[dict]:
    keywords = _keywords(question)
    important_terms = _important_terms(question)
    if not keywords:
        return []
    clauses = ["kd.status = 'active'", "kc.status = 'active'", "kc.chunk_level = 'child'", "(kd.city IS NULL OR kd.city = ?)"]
    params: list[Any] = [city]
    like_clauses = []
    for keyword in keywords:
        like_clauses.append("(kd.title LIKE ? OR kc.content LIKE ? OR kd.tags LIKE ? OR kd.community_name LIKE ? OR kc.tags LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    clauses.append("(" + " OR ".join(like_clauses) + ")")
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT kc.id AS chunk_id, kd.id, kd.title, kc.content, kc.summary, kc.parent_chunk_id,
               kd.tags, kd.community_name, kd.knowledge_type, kd.source_type, kd.source_file,
               kd.source_url, kd.version, kd.create_time, 0.62 AS score
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        WHERE {' AND '.join(clauses)}
        ORDER BY kd.version DESC, kd.create_time DESC, kc.chunk_index ASC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    payload = rows_to_dicts(rows)
    compact_question = re.sub(r"\s+", "", question or "").lower()
    for item in payload:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ["title", "content", "summary", "tags", "community_name", "knowledge_type"]
        ).lower()
        compact_haystack = re.sub(r"\s+", "", haystack)
        hits = sum(1 for keyword in keywords if keyword.lower() in haystack)
        score = 0.4 + min(hits, 10) * 0.045
        important_hits = sum(1 for term in important_terms if term.lower() in compact_haystack)
        score += important_hits * 0.08
        if important_terms and important_hits == len(important_terms):
            score += 0.18
        for size in (6, 5, 4):
            phrases = [
                compact_question[index : index + size]
                for index in range(max(0, len(compact_question) - size + 1))
            ]
            phrase_hits = sum(1 for phrase in phrases if phrase and phrase in compact_haystack)
            score += min(phrase_hits, 4) * 0.04
        if str(item.get("title") or "").lower() in compact_question:
            score += 0.04
        item["score"] = round(min(score, 1.2), 4)
    return sorted(payload, key=lambda row: float(row.get("score") or 0), reverse=True)


def _chroma_retrieve(conn, question: str, city: str, entities: dict[str, Any], limit: int) -> list[dict]:
    where: dict[str, Any] = {"$and": [{"city": city}, {"chunk_level": "child"}]}
    rows = query_knowledge(question, where=where, limit=limit)
    if not rows:
        return []
    chroma_ids = [row["chroma_id"] for row in rows if row.get("chroma_id")]
    placeholders = ",".join("?" for _ in chroma_ids)
    if not placeholders:
        return []
    db_rows = conn.execute(
        f"""
        SELECT kc.id AS chunk_id, kd.id, kd.title, kc.content, kc.summary, kc.parent_chunk_id,
               kd.tags, kd.community_name, kd.knowledge_type, kd.source_type, kd.source_file, kd.source_url,
               kd.version, kd.create_time, kc.chroma_id
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        WHERE kc.chroma_id IN ({placeholders})
          AND kc.status = 'active'
          AND kd.status = 'active'
        """,
        tuple(chroma_ids),
    ).fetchall()
    score_map = {row["chroma_id"]: row["score"] for row in rows}
    payload = rows_to_dicts(db_rows)
    for item in payload:
        item["score"] = score_map.get(item.get("chroma_id"), 0)
    return payload


def _attach_parent_context(conn, items: list[dict]) -> list[dict]:
    parent_ids = sorted({item.get("parent_chunk_id") for item in items if item.get("parent_chunk_id")})
    parent_map: dict[int, str] = {}
    if parent_ids:
        placeholders = ",".join("?" for _ in parent_ids)
        rows = conn.execute(
            f"SELECT id, content FROM knowledge_chunks WHERE id IN ({placeholders}) AND status = 'active'",
            tuple(parent_ids),
        ).fetchall()
        parent_map = {row["id"]: row["content"] for row in rows}
    for item in items:
        parent_id = item.get("parent_chunk_id")
        if parent_id in parent_map:
            item["parent_content"] = parent_map[parent_id][:1800]
    return items


def retrieve_context(conn, question: str, city: str, limit: int = 5, entities: dict[str, Any] | None = None) -> list[dict]:
    entities = extract_entities(conn, question, city, entities)
    rewritten = rewrite_query(question, entities)
    candidates = _chroma_retrieve(conn, rewritten, city, entities, limit=12)
    candidates.extend(_keyword_retrieve(conn, rewritten, city, limit=12))

    deduped: dict[int, dict] = {}
    for item in candidates:
        chunk_id = int(item.get("chunk_id") or 0)
        if not chunk_id:
            continue
        existing = deduped.get(chunk_id)
        score = float(item.get("score") or 0)
        if entities.get("community_name") and item.get("community_name") == entities.get("community_name"):
            score += 0.15
        if entities.get("category") and str(item.get("knowledge_type") or "").lower().find(str(entities["category"])) >= 0:
            score += 0.1
        item["score"] = score
        item["retrieval_entities"] = entities
        if existing is None or score > float(existing.get("score") or 0):
            deduped[chunk_id] = item

    ranked = sorted(deduped.values(), key=lambda row: float(row.get("score") or 0), reverse=True)
    confident = [row for row in ranked if float(row.get("score") or 0) >= 0.2]
    return _attach_parent_context(conn, confident[:limit])
