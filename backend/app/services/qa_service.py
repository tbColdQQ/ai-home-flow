import json
import re
import time
from datetime import date, timedelta
from typing import Any

from app.db.session import rows_to_dicts
from app.services.llm_service import (
    extract_deal_query_with_llm,
    llm_config_summary,
    llm_is_configured,
    route_question_with_llm,
    summarize_answer_with_llm,
    summarize_answer_with_llm_stream,
)
from app.services.rag_service import normalize_community_name, retrieve_context


DEAL_WORDS = ["成交", "签约", "套数", "总额", "均价", "单价", "排名", "门店", "经纪人", "维护人", "价格"]
KNOWLEDGE_WORDS = ["政策", "规则", "流程", "制度", "小区", "楼盘", "学区", "配套", "交通", "物业", "资料", "情况", "怎么样"]
GROUP_BY_FIELDS = {"residential", "store", "agent", "maintainor", "area", "signing_month", "acreage_bucket"}
SORT_FIELDS = {"signing_date", "price", "acreage", "count", "total_price", "avg_price", "avg_unit_price", "bucket_order"}


def _month_range(year: int, month: int) -> dict[str, str]:
    start = date(year, month, 1)
    end = date(year + int(month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat()}


def _fallback_route(question: str, mode: str = "auto") -> dict[str, Any]:
    if mode == "deal":
        return {"intent": "deal_query", "confidence": 1, "reason": "用户手动选择成交数据", "entities": {}}
    if mode == "knowledge":
        return {"intent": "knowledge_query", "confidence": 1, "reason": "用户手动选择知识库", "entities": {}}
    has_deal = any(word in question for word in DEAL_WORDS)
    has_knowledge = any(word in question for word in KNOWLEDGE_WORDS)
    deal_action = any(word in question for word in ["成交", "签约", "套数", "总额", "均价", "单价", "排名", "排行", "最多", "多少套"])
    knowledge_action = any(word in question for word in ["政策", "规则", "流程", "制度", "情况", "怎么样", "配套", "学区", "物业", "资料"])
    if has_deal and deal_action and not knowledge_action:
        return {"intent": "deal_query", "confidence": 0.9, "reason": "明显的成交数据查询", "entities": {}}
    if has_deal and has_knowledge:
        return {"intent": "mixed_query", "confidence": 0.78, "reason": "同时包含成交和知识库关键词", "entities": {}}
    if has_deal:
        return {"intent": "deal_query", "confidence": 0.72, "reason": "包含成交数据查询关键词", "entities": {}}
    if has_knowledge:
        return {"intent": "knowledge_query", "confidence": 0.72, "reason": "包含知识库查询关键词", "entities": {}}
    return {"intent": "clarification", "confidence": 0.45, "reason": "问题范围不明确", "question": "你想查询成交数据，还是查询小区/政策资料？", "entities": {}}


def route_question(question: str, mode: str = "auto") -> dict[str, Any]:
    if mode in {"deal", "knowledge"}:
        return _fallback_route(question, mode)
    local = _fallback_route(question, mode)
    if float(local.get("confidence") or 0) >= 0.88:
        return local
    if llm_is_configured():
        payload = route_question_with_llm(question, mode)
        if payload and payload.get("intent"):
            return payload
    return local


def _fallback_deal_query(question: str, city: str) -> dict[str, Any]:
    today = date.today()
    query: dict[str, Any] = {
        "date_range": None,
        "city": city,
        "area": None,
        "street": None,
        "residential": None,
        "store": None,
        "agent": None,
        "maintainor": None,
        "price_range": None,
        "acreage_range": None,
        "metrics": ["count", "total_price"],
        "group_by": None,
        "sort": None,
        "limit": 50,
        "need_clarification": False,
        "missing_fields": [],
        "clarification_question": None,
        "source": "fallback",
    }
    match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", question)
    if match:
        query["date_range"] = _month_range(int(match.group(1)), int(match.group(2)))
    elif "本月" in question or "这个月" in question:
        query["date_range"] = _month_range(today.year, today.month)
    elif "上月" in question or "上个月" in question:
        prev = today.replace(day=1) - timedelta(days=1)
        query["date_range"] = _month_range(prev.year, prev.month)
    elif "今天" in question:
        query["date_range"] = {"start": today.isoformat(), "end": today.isoformat()}

    residential_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]{2,})(?:小区|楼盘)", question)
    if residential_match and not any(token in residential_match.group(1) for token in ["哪个", "哪些", "多少"]):
        query["residential"] = residential_match.group(1)
    elif "蔚蓝城市花园" in question:
        query["residential"] = "蔚蓝城市花园"

    area_range_match = re.search(r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*(?:平|平米|㎡|m2)", question, re.IGNORECASE)
    if area_range_match:
        query["acreage_range"] = {"min": float(area_range_match.group(1)), "max": float(area_range_match.group(2))}
        query["metrics"] = ["count", "avg_price", "avg_unit_price"]

    if any(word in question for word in ["最多", "排行", "排名"]):
        query["group_by"] = "residential" if "门店" not in question else "store"
        query["sort"] = {"field": "count", "direction": "desc"}
        query["metrics"] = ["count", "avg_unit_price"]
        query["limit"] = 10
    if "面积段" in question or "面积分布" in question or "各个面积" in question:
        query["group_by"] = "acreage_bucket"
        query["sort"] = {"field": "bucket_order", "direction": "asc"}
        query["metrics"] = ["count", "avg_price", "avg_unit_price"]
        query["limit"] = 20
    if any(word in question for word in ["明细", "列表", "记录", "哪些"]):
        query["metrics"] = ["deal_list"]
    if any(word in question for word in ["均价", "单价"]):
        query["metrics"] = list(dict.fromkeys(query["metrics"] + ["avg_unit_price"]))
    return query


def _normalize_deal_query(conn, payload: dict[str, Any] | None, question: str, city: str, router_entities: dict[str, Any] | None = None) -> dict[str, Any]:
    query = _fallback_deal_query(question, city)
    if payload:
        for key in ["date_range", "area", "street", "residential", "store", "agent", "maintainor", "price_range", "acreage_range"]:
            if key in payload:
                query[key] = payload.get(key)
        metrics = payload.get("metrics")
        if isinstance(metrics, list) and metrics:
            query["metrics"] = [str(metric) for metric in metrics[:6]]
        group_by = payload.get("group_by")
        query["group_by"] = group_by if group_by in GROUP_BY_FIELDS else None
        sort = payload.get("sort")
        if isinstance(sort, dict) and sort.get("field") in SORT_FIELDS and sort.get("direction") in {"asc", "desc"}:
            query["sort"] = {"field": sort["field"], "direction": sort["direction"]}
        limit = payload.get("limit")
        if isinstance(limit, int):
            query["limit"] = max(1, min(limit, 100))
        query["need_clarification"] = bool(payload.get("need_clarification", False))
        query["missing_fields"] = payload.get("missing_fields") if isinstance(payload.get("missing_fields"), list) else []
        query["clarification_question"] = payload.get("clarification_question")
        query["source"] = "llm"
    query["city"] = city
    if not query.get("residential") and isinstance(router_entities, dict):
        query["residential"] = router_entities.get("community_name") or router_entities.get("community_name_raw")
    normalized = normalize_community_name(conn, city, query.get("residential"))
    if normalized.get("name"):
        query["residential"] = normalized["name"]
        query["residential_normalization"] = normalized
    if not query.get("residential"):
        inferred = _infer_residential_from_question(conn, city, question)
        if inferred:
            query["residential"] = inferred
    return query


def extract_deal_query(conn, question: str, city: str, router_entities: dict[str, Any] | None = None) -> dict[str, Any]:
    if llm_is_configured():
        payload = extract_deal_query_with_llm(question, date.today().isoformat())
        return _normalize_deal_query(conn, payload, question, city, router_entities)
    query = _fallback_deal_query(question, city)
    if not query.get("residential") and isinstance(router_entities, dict):
        query["residential"] = router_entities.get("community_name") or router_entities.get("community_name_raw")
    normalized = normalize_community_name(conn, city, query.get("residential"))
    if normalized.get("name"):
        query["residential"] = normalized["name"]
        query["residential_normalization"] = normalized
    if not query.get("residential"):
        inferred = _infer_residential_from_question(conn, city, question)
        if inferred:
            query["residential"] = inferred
    return query


def _infer_residential_from_question(conn, city: str, question: str) -> str | None:
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
    matches = []
    for row in rows:
        name = (row["name"] or "").strip()
        if len(name) >= 2 and name in question:
            matches.append(name)
    if not matches:
        return None
    return sorted(matches, key=len, reverse=True)[0]


def _append_like(where: list[str], params: list[Any], field: str, value: str | None) -> None:
    if value:
        where.append(f"{field} LIKE ?")
        params.append(f"%{value}%")


def build_deal_sql(query: dict[str, Any]) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    date_range = query.get("date_range") if isinstance(query.get("date_range"), dict) else None
    if date_range and date_range.get("start"):
        where.append("signing_date >= ?")
        params.append(date_range["start"])
    if date_range and date_range.get("end"):
        where.append("signing_date < date(?, '+1 day')")
        params.append(date_range["end"])
    for field in ["area", "street", "residential", "store", "agent", "maintainor"]:
        _append_like(where, params, field, query.get(field))
    price_range = query.get("price_range") if isinstance(query.get("price_range"), dict) else None
    if price_range:
        if price_range.get("min") is not None:
            where.append("price >= ?")
            params.append(price_range["min"])
        if price_range.get("max") is not None:
            where.append("price <= ?")
            params.append(price_range["max"])
    acreage_range = query.get("acreage_range") if isinstance(query.get("acreage_range"), dict) else None
    if acreage_range:
        if acreage_range.get("min") is not None:
            where.append("acreage >= ?")
            params.append(acreage_range["min"])
        if acreage_range.get("max") is not None:
            where.append("acreage <= ?")
            params.append(acreage_range["max"])

    where_sql = " WHERE " + " AND ".join(where) if where else ""
    limit = int(query.get("limit") or 50)
    group_by = query.get("group_by")
    metrics = set(query.get("metrics") or ["count"])
    if group_by:
        if group_by == "signing_month":
            group_expr = "substr(signing_date, 1, 7)"
            order_expr = group_expr
            extra_select = ""
        elif group_by == "acreage_bucket":
            group_expr = """
                CASE
                    WHEN acreage < 60 THEN '60平以下'
                    WHEN acreage >= 60 AND acreage < 70 THEN '60-70平'
                    WHEN acreage >= 70 AND acreage < 80 THEN '70-80平'
                    WHEN acreage >= 80 AND acreage < 90 THEN '80-90平'
                    WHEN acreage >= 90 AND acreage < 100 THEN '90-100平'
                    WHEN acreage >= 100 AND acreage < 120 THEN '100-120平'
                    WHEN acreage >= 120 AND acreage < 140 THEN '120-140平'
                    ELSE '140平以上'
                END
            """
            order_expr = """
                CASE
                    WHEN acreage < 60 THEN 1
                    WHEN acreage >= 60 AND acreage < 70 THEN 2
                    WHEN acreage >= 70 AND acreage < 80 THEN 3
                    WHEN acreage >= 80 AND acreage < 90 THEN 4
                    WHEN acreage >= 90 AND acreage < 100 THEN 5
                    WHEN acreage >= 100 AND acreage < 120 THEN 6
                    WHEN acreage >= 120 AND acreage < 140 THEN 7
                    ELSE 8
                END
            """
            extra_select = f", MIN({order_expr}) AS bucket_order"
        else:
            group_expr = group_by
            order_expr = group_expr
            extra_select = ""
        order = query.get("sort") or {"field": "count", "direction": "desc"}
        order_field = order["field"] if order["field"] in SORT_FIELDS else "count"
        direction = order["direction"] if order["direction"] in {"asc", "desc"} else "desc"
        if group_by == "acreage_bucket" and order_field == "bucket_order":
            direction = "asc"
        chart_series = [{"field": "count", "label": "成交量", "type": "bar", "unit": "套"}]
        if "avg_price" in metrics:
            chart_series.append({"field": "avg_price", "label": "成交均价", "type": "line", "unit": "万元/套", "divisor": 10000})
        if "avg_unit_price" in metrics:
            chart_series.append({"field": "avg_unit_price", "label": "成交单价", "type": "line", "unit": "元/平"})
        return {
            "sql": f"""
                SELECT {group_expr} AS name, COUNT(*) AS count,
                       SUM(price) AS total_price,
                       AVG(price) AS avg_price,
                       AVG(price / NULLIF(acreage, 0)) AS avg_unit_price
                       {extra_select}
                FROM allowed_orders
                {where_sql}
                GROUP BY {group_expr}
                ORDER BY {order_field} {direction.upper()}
                LIMIT {limit}
            """,
            "params": params,
            "chart": {"type": "bar", "x_field": "name", "series": chart_series},
        }
    if "deal_list" in metrics:
        order = query.get("sort") or {"field": "signing_date", "direction": "desc"}
        order_field = order["field"] if order["field"] in {"signing_date", "price", "acreage"} else "signing_date"
        direction = order["direction"] if order["direction"] in {"asc", "desc"} else "desc"
        return {
            "sql": f"""
                SELECT ID, signing_date, residential, room_number, acreage, price,
                       ROUND(price / NULLIF(acreage, 0), 2) AS unit_price,
                       agent, store, maintainor, area, street
                FROM allowed_orders
                {where_sql}
                ORDER BY {order_field} {direction.upper()}
                LIMIT {limit}
            """,
            "params": params,
            "chart": {"type": "none"},
        }
    return {
        "sql": f"""
            SELECT COUNT(*) AS count,
                   SUM(price) AS total_price,
                   AVG(price) AS avg_price,
                   AVG(price / NULLIF(acreage, 0)) AS avg_unit_price
            FROM allowed_orders
            {where_sql}
        """,
        "params": params,
        "chart": {"type": "none"},
    }


def _execute_deal_query(conn, sql_payload: dict[str, Any], city: str) -> list[dict]:
    secured_sql = f"""
    WITH allowed_orders AS (
        SELECT *
        FROM orders
        WHERE city = ? AND COALESCE(status, 'normal') = 'normal'
    )
    {sql_payload["sql"]}
    """
    return rows_to_dicts(conn.execute(secured_sql, tuple([city] + sql_payload["params"])).fetchall())


def _chart_from_payload(payload: dict[str, Any], rows: list[dict]) -> dict | None:
    chart = payload.get("chart") or {}
    if chart.get("type") not in {"bar", "line"}:
        return None
    x_field = chart.get("x_field") or "name"
    if not rows or x_field not in rows[0]:
        return None
    x_values = [row.get(x_field) for row in rows]
    configured_series = chart.get("series")
    series = []
    if isinstance(configured_series, list) and configured_series:
        for item in configured_series:
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            if not field or field not in rows[0]:
                continue
            divisor = float(item.get("divisor") or 1)
            series.append(
                {
                    "name": item.get("label") or field,
                    "type": item.get("type") if item.get("type") in {"bar", "line"} else chart["type"],
                    "unit": item.get("unit") or "",
                    "data": [
                        round(float(row.get(field) or 0) / divisor, 2)
                        for row in rows
                    ],
                }
            )
    else:
        y_field = chart.get("y_field") or "count"
        if y_field in rows[0]:
            series.append({"name": y_field, "type": chart["type"], "unit": "", "data": [row.get(y_field) for row in rows]})
    if not series:
        return None
    return {"type": chart["type"], "x": x_values, "series": series, "y": series[0]["data"]}


def _fallback_answer(question: str, rows: list[dict], rag_context: list[dict], intent: str) -> str:
    if intent == "knowledge_query":
        if not rag_context:
            return "知识库中没有找到明确资料。"
        first = rag_context[0]
        title = first.get("title") or "知识库资料"
        return f"根据《{title}》：\n{str(first.get('content') or '')[:700]}"
    if rows:
        first = rows[0]
        if "name" in first and "count" in first:
            lines = ["查询结果如下："]
            for row in rows[:20]:
                parts = [f"{row.get('name') or '-'}：{row.get('count') or 0} 套"]
                if row.get("avg_price") is not None:
                    parts.append(f"成交均价约 {float(row.get('avg_price') or 0) / 10000:.2f} 万元/套")
                if row.get("avg_unit_price") is not None:
                    parts.append(f"平均单价约 {float(row.get('avg_unit_price') or 0):.0f} 元/平")
                if row.get("total_price") is not None:
                    parts.append(f"成交总额约 {float(row.get('total_price') or 0) / 10000:.2f} 万元")
                lines.append("，".join(parts) + "。")
            return "\n".join(lines)
        if "count" in first:
            total = first.get("total_price") or 0
            parts = [f"符合条件的成交共 {first.get('count') or 0} 套"]
            if first.get("avg_price") is not None:
                parts.append(f"成交均价约 {float(first.get('avg_price') or 0) / 10000:.2f} 万元/套")
            if first.get("avg_unit_price") is not None:
                parts.append(f"平均单价约 {float(first.get('avg_unit_price') or 0):.0f} 元/平")
            parts.append(f"成交总额约 {float(total) / 10000:.2f} 万元")
            return "，".join(parts) + "。"
        return f"查询到 {len(rows)} 条成交记录。"
    if rag_context:
        first = rag_context[0]
        return f"成交数据未查到匹配记录。知识库中相关资料来自《{first.get('title') or '知识库资料'}》。"
    return "没有查到符合条件的内部数据。"


def _stream_text(text: str, size: int = 18):
    buffer = ""
    for char in text:
        buffer += char
        if char in "。！？；\n" or len(buffer) >= size:
            yield buffer
            buffer = ""
            time.sleep(0.015)
    if buffer:
        yield buffer


def _answer(question: str, sql: str, rows: list[dict], rag_context: list[dict], intent: str) -> tuple[str, str]:
    if intent == "knowledge_query":
        sql = ""
        rows = []
    if intent in {"deal_query", "mixed_query"} and rows:
        return _fallback_answer(question, rows, rag_context, intent), "local_summary"
    llm_answer = summarize_answer_with_llm(question, sql, rows, rag_context)
    if llm_answer:
        return llm_answer, "llm"
    return _fallback_answer(question, rows, rag_context, intent), "fallback"


def answer_question(conn, question: str, city: str, mode: str = "auto", user_id: int | None = None, session_id: int | None = None) -> dict:
    started = time.perf_counter()
    clean_question = question.strip()
    router = route_question(clean_question, mode)
    intent = router.get("intent") or "clarification"
    deal_query: dict[str, Any] | None = None
    deal_rows: list[dict] = []
    sql_payload = {"sql": "", "params": [], "chart": {"type": "none"}}
    rag_context: list[dict] = []
    status = "completed"

    if intent == "clarification":
        answer = router.get("question") or "请补充你想查成交数据，还是查小区/政策资料。"
        answer_source = "router"
    elif intent == "unsupported":
        answer = "这个问题暂时不在系统可处理范围内。你可以查询成交数据、小区情况或政策资料。"
        answer_source = "router"
    else:
        if intent in {"knowledge_query", "mixed_query"}:
            rag_context = retrieve_context(conn, clean_question, city, entities=router.get("entities") if isinstance(router.get("entities"), dict) else None)
        if intent in {"deal_query", "mixed_query"}:
            deal_query = extract_deal_query(conn, clean_question, city, router.get("entities") if isinstance(router.get("entities"), dict) else None)
            if deal_query.get("need_clarification"):
                answer = deal_query.get("clarification_question") or "请补充查询条件。"
                answer_source = "deal_query_agent"
                status = "need_clarification"
            else:
                sql_payload = build_deal_sql(deal_query)
                deal_rows = _execute_deal_query(conn, sql_payload, city)
                answer, answer_source = _answer(clean_question, sql_payload["sql"], deal_rows, rag_context, intent)
        else:
            answer, answer_source = _answer(clean_question, "", [], rag_context, intent)

    result = {
        "answer": answer,
        "answer_source": answer_source,
        "intent": intent,
        "status": status,
        "router": router,
        "deal_query": deal_query,
        "deal_result": {"rows": deal_rows, "total": len(deal_rows)},
        "data": deal_rows,
        "sql": sql_payload["sql"],
        "sql_params": sql_payload["params"],
        "sql_source": "json_builder" if sql_payload["sql"] else None,
        "llm_config": llm_config_summary(),
        "chart": _chart_from_payload(sql_payload, deal_rows),
        "rag_context": rag_context,
        "sources": rag_context,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
    try:
        conn.execute(
            """
            INSERT INTO agent_runs(
                session_id, user_id, question, mode, intent, status, router_result_json,
                deal_query_json, deal_result_json, rag_sources_json, latency_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                clean_question,
                mode,
                intent,
                status,
                json.dumps(router, ensure_ascii=False),
                json.dumps(deal_query, ensure_ascii=False),
                json.dumps(result["deal_result"], ensure_ascii=False),
                json.dumps(rag_context, ensure_ascii=False),
                result["latency_ms"],
            ),
        )
    except Exception:
        pass
    return result


def answer_question_stream(conn, question: str, city: str, mode: str = "auto", user_id: int | None = None, session_id: int | None = None):
    started = time.perf_counter()
    step_started = started

    def timing(step: str) -> dict[str, Any]:
        nonlocal step_started
        now = time.perf_counter()
        payload = {
            "type": "timing",
            "step": step,
            "elapsed_ms": int((now - step_started) * 1000),
            "total_ms": int((now - started) * 1000),
        }
        step_started = now
        return payload

    clean_question = question.strip()
    yield {"type": "status", "content": "正在判断问题类型..."}
    router = route_question(clean_question, mode)
    intent = router.get("intent") or "clarification"
    yield {"type": "router", "content": router}
    yield timing("route")

    if intent in {"clarification", "unsupported"}:
        result = answer_question(conn, clean_question, city, mode, user_id, session_id)
        for chunk in _stream_text(result["answer"]):
            yield {"type": "delta", "content": chunk}
        yield timing("final")
        yield {"type": "final", "result": result}
        return

    rag_context: list[dict] = []
    if intent in {"knowledge_query", "mixed_query"}:
        yield {"type": "status", "content": "正在检索知识库..."}
        rag_context = retrieve_context(conn, clean_question, city, entities=router.get("entities") if isinstance(router.get("entities"), dict) else None)
        yield timing("rag_retrieve")
        if rag_context:
            yield {"type": "sources", "content": rag_context}

    deal_query = None
    deal_rows: list[dict] = []
    sql_payload = {"sql": "", "params": [], "chart": {"type": "none"}}
    if intent in {"deal_query", "mixed_query"}:
        yield {"type": "status", "content": "正在生成成交查询条件..."}
        deal_query = extract_deal_query(conn, clean_question, city, router.get("entities") if isinstance(router.get("entities"), dict) else None)
        yield timing("deal_query_extract")
        yield {"type": "deal_query", "content": deal_query}
        if deal_query.get("need_clarification"):
            result = answer_question(conn, clean_question, city, mode, user_id, session_id)
            for chunk in _stream_text(result["answer"]):
                yield {"type": "delta", "content": chunk}
            yield timing("final")
            yield {"type": "final", "result": result}
            return
        yield {"type": "status", "content": "正在查询成交数据库..."}
        sql_payload = build_deal_sql(deal_query)
        deal_rows = _execute_deal_query(conn, sql_payload, city)
        yield timing("sql_query")
        yield {"type": "deal_result", "content": {"rows": deal_rows, "total": len(deal_rows)}}

    yield {"type": "status", "content": "正在整理回答..."}
    answer = _fallback_answer(clean_question, deal_rows, rag_context, intent)
    answer_source = "local_stream"
    for chunk in _stream_text(answer):
        yield {"type": "delta", "content": chunk}
    yield timing("answer_local_stream")

    result = {
        "answer": answer,
        "answer_source": answer_source,
        "intent": intent,
        "status": "completed",
        "router": router,
        "deal_query": deal_query,
        "deal_result": {"rows": deal_rows, "total": len(deal_rows)},
        "data": deal_rows,
        "sql": sql_payload["sql"],
        "sql_params": sql_payload["params"],
        "sql_source": "json_builder" if sql_payload["sql"] else None,
        "llm_config": llm_config_summary(),
        "chart": _chart_from_payload(sql_payload, deal_rows),
        "rag_context": rag_context,
        "sources": rag_context,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
    yield timing("final")
    yield {"type": "final", "result": result}
