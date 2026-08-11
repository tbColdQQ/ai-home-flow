import re
from datetime import date
from typing import Any

from app.db.session import rows_to_dicts
from app.services.llm_service import (
    generate_sql_with_llm,
    llm_config_summary,
    llm_is_configured,
    summarize_answer_with_llm,
)
from app.services.rag_service import retrieve_context


FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|pragma|attach|detach|replace|truncate|vacuum|grant|revoke)\b",
    re.IGNORECASE,
)


def _month_bounds(question: str) -> tuple[str, str] | None:
    match = re.search(r"(\d{4})\s*\u5e74\s*(\d{1,2})\s*(?:\u6708|\u6708\u4efd)", question)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year + 1:04d}-01-01" if month == 12 else f"{year:04d}-{month + 1:02d}-01"
    return start, end


def _this_month_bounds() -> tuple[str, str]:
    today = date.today()
    start = today.replace(day=1)
    end = today.replace(year=today.year + 1, month=1, day=1) if today.month == 12 else today.replace(month=today.month + 1, day=1)
    return start.isoformat(), end.isoformat()


def _fallback_sql(question: str) -> dict[str, Any]:
    params: list[Any] = []
    where = []
    month_bounds = _month_bounds(question)
    if month_bounds:
        where.extend(["signing_date >= ?", "signing_date < ?"])
        params.extend(month_bounds)
    elif "\u672c\u6708" in question or "\u8fd9\u4e2a\u6708" in question:
        start, end = _this_month_bounds()
        where.extend(["signing_date >= ?", "signing_date < ?"])
        params.extend([start, end])
    elif "\u4eca\u5929" in question:
        today = date.today().isoformat()
        where.extend(["signing_date >= ?", "signing_date < ?"])
        params.extend([today, f"{today} 23:59:59"])

    residential_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]+)(?:\u5c0f\u533a|\u697c\u76d8)", question)
    if residential_match:
        residential = residential_match.group(1)
        skip_tokens = ["\u54ea\u4e2a", "\u54ea\u4e9b", "\u591a\u5c11", "\u5e74", "\u6708", "\u6708\u4efd"]
        if not any(token in residential for token in skip_tokens):
            where.append("residential LIKE ?")
            params.append(f"%{residential}%")

    where_sql = " WHERE " + " AND ".join(where) if where else ""
    if any(word in question for word in ["\u6700\u591a", "\u6392\u884c", "\u6392\u540d"]):
        return {
            "sql": f"""
                SELECT residential AS name, COUNT(*) AS count,
                       AVG(price / NULLIF(acreage, 0)) AS avg_unit_price
                FROM allowed_orders
                {where_sql}
                GROUP BY residential
                ORDER BY count DESC
                LIMIT 10
            """,
            "params": params,
            "chart": {"type": "bar", "x_field": "name", "y_field": "count"},
            "source": "fallback",
        }
    if any(word in question for word in ["\u5747\u4ef7", "\u5355\u4ef7"]):
        return {
            "sql": f"""
                SELECT COUNT(*) AS count,
                       AVG(price) AS avg_total_price,
                       AVG(price / NULLIF(acreage, 0)) AS avg_unit_price
                FROM allowed_orders
                {where_sql}
            """,
            "params": params,
            "chart": {"type": "none"},
            "source": "fallback",
        }
    return {
        "sql": f"""
            SELECT COUNT(*) AS count, SUM(price) AS total_price
            FROM allowed_orders
            {where_sql}
        """,
        "params": params,
        "chart": {"type": "none"},
        "source": "fallback",
    }


def _validate_sql_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if not payload:
        return None, "llm_returned_empty"
    sql = str(payload.get("sql") or "").strip()
    params = payload.get("params") or []
    if not sql or not sql.lower().startswith("select"):
        return None, "llm_sql_not_select"
    if ";" in sql or FORBIDDEN_SQL.search(sql):
        return None, "llm_sql_forbidden"
    lowered = sql.lower()
    if "allowed_orders" not in lowered:
        return None, "llm_sql_missing_allowed_orders"
    blocked_sources = [" orders", " users", " auth_sessions", " sqlite_master", " sqlite_schema"]
    if any(source in lowered for source in blocked_sources):
        return None, "llm_sql_blocked_source"
    if not isinstance(params, list):
        return None, "llm_params_not_list"
    return {
        "sql": sql,
        "params": params,
        "chart": payload.get("chart") or {"type": "none"},
        "source": "llm",
    }, None


def _execute_sql(conn, sql_payload: dict[str, Any], city: str) -> list[dict]:
    secured_sql = f"""
    WITH allowed_orders AS (
        SELECT *
        FROM orders
        WHERE city = ? AND COALESCE(status, 'normal') = 'normal'
    )
    {sql_payload["sql"]}
    """
    rows = conn.execute(secured_sql, tuple([city] + sql_payload["params"])).fetchall()
    return rows_to_dicts(rows)


def _choose_sql_payload(question: str, rag_context: list[dict]) -> tuple[dict[str, Any], str | None]:
    if not llm_is_configured():
        return _fallback_sql(question), "llm_not_configured"

    llm_payload = generate_sql_with_llm(question, rag_context)
    sql_payload, validation_error = _validate_sql_payload(llm_payload)
    if sql_payload:
        return sql_payload, None
    return _fallback_sql(question), validation_error or "llm_sql_invalid"


def _fallback_answer(question: str, rows: list[dict]) -> str:
    if not rows:
        return "\u6ca1\u6709\u67e5\u8be2\u5230\u7b26\u5408\u6761\u4ef6\u7684\u6210\u4ea4\u6570\u636e\u3002"
    first = rows[0]
    if "name" in first and "count" in first:
        return f"{question} \u67e5\u8be2\u7ed3\u679c\uff1a\u6210\u4ea4\u6700\u591a\u7684\u662f {first['name']}\uff0c\u5171 {first['count']} \u5957\u3002"
    if "count" in first and "total_price" in first:
        total = first.get("total_price") or 0
        return f"\u7b26\u5408\u6761\u4ef6\u7684\u6210\u4ea4\u5171 {first.get('count') or 0} \u5957\uff0c\u6210\u4ea4\u603b\u989d\u7ea6 {total:.2f} \u5143\u3002"
    if "avg_unit_price" in first:
        return f"\u7b26\u5408\u6761\u4ef6\u7684\u6210\u4ea4\u5171 {first.get('count') or 0} \u5957\uff0c\u5e73\u5747\u5355\u4ef7\u7ea6 {(first.get('avg_unit_price') or 0):.2f} \u5143/\u5e73\u3002"
    return f"\u67e5\u8be2\u5230 {len(rows)} \u6761\u7ed3\u679c\u3002"


def _chart_from_payload(payload: dict[str, Any], rows: list[dict]) -> dict | None:
    chart = payload.get("chart") or {}
    if chart.get("type") not in {"bar", "line"}:
        return None
    x_field = chart.get("x_field") or "name"
    y_field = chart.get("y_field") or "count"
    if not rows or x_field not in rows[0] or y_field not in rows[0]:
        return None
    return {
        "type": chart["type"],
        "x": [row.get(x_field) for row in rows],
        "y": [row.get(y_field) for row in rows],
    }


def answer_question(conn, question: str, city: str) -> dict:
    clean_question = question.strip()
    rag_context = retrieve_context(conn, clean_question, city)

    sql_payload, fallback_reason = _choose_sql_payload(clean_question, rag_context)
    try:
        rows = _execute_sql(conn, sql_payload, city)
    except Exception:
        fallback_reason = "llm_sql_execution_failed" if sql_payload["source"] == "llm" else "fallback_sql_execution_failed"
        sql_payload = _fallback_sql(clean_question)
        rows = _execute_sql(conn, sql_payload, city)

    answer = summarize_answer_with_llm(clean_question, sql_payload["sql"], rows, rag_context)
    answer_source = "llm" if answer else "fallback"
    if not answer:
        answer = _fallback_answer(clean_question, rows)

    return {
        "answer": answer,
        "answer_source": answer_source,
        "data": rows,
        "sql": sql_payload["sql"],
        "sql_params": sql_payload["params"],
        "sql_source": sql_payload["source"],
        "llm_fallback_reason": fallback_reason,
        "llm_config": llm_config_summary(),
        "chart": _chart_from_payload(sql_payload, rows),
        "rag_context": rag_context,
    }
