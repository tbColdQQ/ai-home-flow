import re
from datetime import date
from typing import Any

from app.db.session import rows_to_dicts
from app.services.llm_service import generate_sql_with_llm, summarize_answer_with_llm
from app.services.rag_service import retrieve_context


FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|pragma|attach|detach|replace|truncate|vacuum|grant|revoke)\b",
    re.IGNORECASE,
)


def _month_bounds(question: str) -> tuple[str, str] | None:
    match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*(?:月|月份)", question)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"
    return start, end


def _this_month_bounds() -> tuple[str, str]:
    today = date.today()
    start = today.replace(day=1)
    if today.month == 12:
        end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        end = today.replace(month=today.month + 1, day=1)
    return start.isoformat(), end.isoformat()


def _fallback_sql(question: str) -> dict[str, Any]:
    params: list[Any] = []
    where = []
    month_bounds = _month_bounds(question)
    if month_bounds:
        where.append("signing_date >= ?")
        where.append("signing_date < ?")
        params.extend(month_bounds)
    elif "本月" in question or "这个月" in question:
        start, end = _this_month_bounds()
        where.append("signing_date >= ?")
        where.append("signing_date < ?")
        params.extend([start, end])
    elif "今天" in question:
        where.append("signing_date >= ?")
        where.append("signing_date < ?")
        today = date.today().isoformat()
        params.extend([today, f"{today} 23:59:59"])

    residential_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]+)(?:小区|楼盘)", question)
    if residential_match:
        residential = residential_match.group(1)
        if not any(token in residential for token in ["哪个", "哪些", "多少", "年", "月", "月份"]):
            where.append("residential LIKE ?")
            params.append(f"%{residential}%")

    where_sql = " WHERE " + " AND ".join(where) if where else ""
    if any(word in question for word in ["最多", "排行", "排名"]):
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
    if any(word in question for word in ["均价", "单价"]):
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


def _validate_sql_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    sql = str(payload.get("sql") or "").strip()
    params = payload.get("params") or []
    if not sql or not sql.lower().startswith("select"):
        return None
    if ";" in sql or FORBIDDEN_SQL.search(sql):
        return None
    lowered = sql.lower()
    if "allowed_orders" not in lowered:
        return None
    blocked_sources = [" orders", " users", " auth_sessions", " sqlite_master", " sqlite_schema"]
    if any(source in lowered for source in blocked_sources):
        return None
    if not isinstance(params, list):
        return None
    return {
        "sql": sql,
        "params": params,
        "chart": payload.get("chart") or {"type": "none"},
        "source": "llm",
    }


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


def _fallback_answer(question: str, rows: list[dict]) -> str:
    if not rows:
        return "没有查询到符合条件的成交数据。"
    first = rows[0]
    if "name" in first and "count" in first:
        return f"{question} 查询结果：成交最多的是 {first['name']}，共 {first['count']} 套。"
    if "count" in first and "total_price" in first:
        total = first.get("total_price") or 0
        return f"符合条件的成交共 {first.get('count') or 0} 套，成交总额约 {total:.2f} 元。"
    if "avg_unit_price" in first:
        return f"符合条件的成交共 {first.get('count') or 0} 套，平均单价约 {(first.get('avg_unit_price') or 0):.2f} 元/平。"
    return f"查询到 {len(rows)} 条结果。"


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
    sql_payload = _validate_sql_payload(generate_sql_with_llm(clean_question, rag_context))
    if sql_payload is None:
        sql_payload = _fallback_sql(clean_question)

    try:
        rows = _execute_sql(conn, sql_payload, city)
    except Exception:
        sql_payload = _fallback_sql(clean_question)
        rows = _execute_sql(conn, sql_payload, city)

    answer = summarize_answer_with_llm(clean_question, sql_payload["sql"], rows, rag_context)
    if not answer:
        answer = _fallback_answer(clean_question, rows)

    return {
        "answer": answer,
        "data": rows,
        "sql": sql_payload["sql"],
        "sql_params": sql_payload["params"],
        "sql_source": sql_payload["source"],
        "chart": _chart_from_payload(sql_payload, rows),
        "rag_context": rag_context,
    }
