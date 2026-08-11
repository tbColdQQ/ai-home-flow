import re
from datetime import date
from typing import Any

from app.db.session import rows_to_dicts
from app.services.llm_service import parse_intent_with_llm
from app.services.rag_service import retrieve_context


def _month_range() -> tuple[str, str]:
    today = date.today()
    return today.replace(day=1).isoformat(), today.isoformat()


def _year_range() -> tuple[str, str]:
    today = date.today()
    return today.replace(month=1, day=1).isoformat(), today.isoformat()


def _fallback_intent(question: str) -> dict[str, Any]:
    intent: dict[str, Any] = {
        "metric": "count",
        "date_range": "none",
        "residential": None,
        "store": None,
        "agent": None,
        "area": None,
        "group_by": None,
        "chart": any(word in question for word in ["\u753b\u56fe", "\u56fe\u8868", "\u8d8b\u52bf"]),
    }
    if "\u4eca\u5929" in question:
        intent["date_range"] = "today"
    elif "\u672c\u6708" in question or "\u8fd9\u4e2a\u6708" in question:
        intent["date_range"] = "this_month"
    elif "\u4eca\u5e74" in question or "\u672c\u5e74" in question:
        intent["date_range"] = "this_year"

    if any(word in question for word in ["\u5747\u4ef7", "\u5355\u4ef7"]):
        intent["metric"] = "avg_unit_price"
    elif any(word in question for word in ["\u6700\u591a", "\u6392\u884c", "\u6392\u540d"]):
        intent["metric"] = "ranking"
        intent["group_by"] = "residential"
        intent["chart"] = True
    elif "\u660e\u7ec6" in question or "\u54ea\u4e9b" in question:
        intent["metric"] = "detail"

    residential_match = re.search(
        r"([\u4e00-\u9fa5A-Za-z0-9\u4e00\u671f\u4e8c\u671f\u4e09\u671f\u56db\u671f\u4e94\u671f\u516d\u671f\u4e03\u671f\u516b\u671f\u4e5d\u671f\u5341\u671f]+)(?:\u5c0f\u533a|\u697c\u76d8)",
        question,
    )
    if residential_match:
        intent["residential"] = residential_match.group(1)
    return intent


def _normalize_intent(question: str) -> dict[str, Any]:
    fallback = _fallback_intent(question)
    llm_intent = parse_intent_with_llm(question)
    if not llm_intent:
        return fallback
    fallback.update({key: value for key, value in llm_intent.items() if key in fallback})
    return fallback


def _build_filters(intent: dict[str, Any], city: str) -> tuple[str, list[Any]]:
    clauses = ["city = ?", "COALESCE(status, 'normal') = 'normal'"]
    params: list[Any] = [city]

    if intent["date_range"] == "today":
        clauses.append("signing_date = ?")
        params.append(date.today().isoformat())
    elif intent["date_range"] == "this_month":
        start_date, end_date = _month_range()
        clauses.extend(["signing_date >= ?", "signing_date <= ?"])
        params.extend([start_date, end_date])
    elif intent["date_range"] == "this_year":
        start_date, end_date = _year_range()
        clauses.extend(["signing_date >= ?", "signing_date <= ?"])
        params.extend([start_date, end_date])

    for field in ["residential", "store", "agent", "area"]:
        value = intent.get(field)
        if value:
            clauses.append(f"{field} LIKE ?")
            params.append(f"%{value}%")
    return " AND ".join(clauses), params


def _empty_answer(intent: dict[str, Any]) -> dict:
    return {
        "answer": "\u6ca1\u6709\u67e5\u8be2\u5230\u7b26\u5408\u6761\u4ef6\u7684\u6210\u4ea4\u6570\u636e\u3002",
        "data": {"count": 0},
        "intent": intent,
    }


def answer_question(conn, question: str, city: str) -> dict:
    intent = _normalize_intent(question.strip())
    rag_context = retrieve_context(conn, question, city)
    where_sql, params = _build_filters(intent, city)
    metric = intent["metric"]

    if metric in {"avg_total_price", "avg_unit_price"}:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS count,
                   AVG(price) AS avg_total_price,
                   AVG(price / NULLIF(acreage, 0)) AS avg_unit_price
            FROM orders
            WHERE {where_sql}
            """,
            tuple(params),
        ).fetchone()
        if not row["count"]:
            return _empty_answer(intent)
        return {
            "answer": f"{city}\u7b26\u5408\u6761\u4ef6\u7684\u6210\u4ea4\u5171 {row['count']} \u5957\uff0c\u5e73\u5747\u603b\u4ef7\u7ea6 {row['avg_total_price']:.2f} \u5143\uff0c\u5e73\u5747\u5355\u4ef7\u7ea6 {row['avg_unit_price']:.2f} \u5143/\u5e73\u3002",
            "data": dict(row),
            "intent": intent,
            "rag_context": rag_context,
        }

    if metric == "ranking":
        group_by = intent.get("group_by") or "residential"
        if group_by not in {"residential", "store", "agent", "area"}:
            group_by = "residential"
        rows = conn.execute(
            f"""
            SELECT {group_by} AS name, COUNT(*) AS count,
                   AVG(price / NULLIF(acreage, 0)) AS avg_unit_price
            FROM orders
            WHERE {where_sql}
            GROUP BY {group_by}
            ORDER BY count DESC
            LIMIT 10
            """,
            tuple(params),
        ).fetchall()
        items = rows_to_dicts(rows)
        if not items:
            return _empty_answer(intent)
        top = items[0]
        return {
            "answer": f"\u6210\u4ea4\u6700\u591a\u7684\u662f {top['name']}\uff0c\u5171 {top['count']} \u5957\u3002",
            "data": items,
            "chart": {"type": "bar", "x": [i["name"] for i in items], "y": [i["count"] for i in items]},
            "intent": intent,
            "rag_context": rag_context,
        }

    if metric == "detail":
        rows = conn.execute(
            f"""
            SELECT signing_date, residential, acreage, price, agent, store
            FROM orders
            WHERE {where_sql}
            ORDER BY signing_date DESC, ID DESC
            LIMIT 20
            """,
            tuple(params),
        ).fetchall()
        items = rows_to_dicts(rows)
        return {
            "answer": f"\u67e5\u5230 {len(items)} \u6761\u6210\u4ea4\u660e\u7ec6\uff0c\u5df2\u8fd4\u56de\u6700\u65b0 20 \u6761\u3002",
            "data": items,
            "intent": intent,
            "rag_context": rag_context,
        }

    row = conn.execute(
        f"SELECT COUNT(*) AS count, SUM(price) AS total_price FROM orders WHERE {where_sql}",
        tuple(params),
    ).fetchone()
    return {
        "answer": f"{city}\u7b26\u5408\u6761\u4ef6\u7684\u6210\u4ea4\u5171 {row['count'] or 0} \u5957\uff0c\u6210\u4ea4\u603b\u989d\u7ea6 {(row['total_price'] or 0):.2f} \u5143\u3002",
        "data": dict(row),
        "intent": intent,
        "rag_context": rag_context,
    }
