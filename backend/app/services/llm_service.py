import json
from collections.abc import Iterator
from typing import Any

from app.core.config import settings


SQL_PROMPT = """
You are the SQL generator for home-flow.
Return JSON only. Do not add explanations.

The backend already applies RBAC and city filtering through a read-only CTE named allowed_orders.
You must query ONLY from allowed_orders.

Available columns:
ID, city, area, street, residential, room_number, acreage, list_price, price,
agent, store, signing_date, CA, creator, create_time, modifier, modify_time,
maintainor, maintainor_store, parking, status, remark, location, brand.

Important data rules:
- signing_date is stored as text in yyyy-mm-dd or yyyy-mm-dd HH:MM:SS style.
- price is stored in yuan.
- acreage is square meters.
- For a Chinese month like "2026年6月" or "2026年6月份", use signing_date >= "2026-06-01" AND signing_date < "2026-07-01".
- For rankings like "哪个小区成交最多", group by residential and order by COUNT(*) DESC.

Output JSON format:
{
  "sql": "SELECT residential AS name, COUNT(*) AS count FROM allowed_orders WHERE signing_date >= ? AND signing_date < ? GROUP BY residential ORDER BY count DESC LIMIT 10",
  "params": ["2026-06-01", "2026-07-01"],
  "chart": {"type": "bar|line|none", "x_field": "name", "y_field": "count"}
}

Rules:
- SQL must be a single SELECT statement.
- Use ? placeholders for all dynamic values.
- Do not include city/status filters; backend has already applied them.
- Do not use INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, ATTACH, DETACH.
- Do not query orders, users, auth_sessions, sqlite_master, or any table except allowed_orders.
- Keep result rows at or below 50 unless the user explicitly asks for more.
""".strip()

ROUTER_PROMPT = """
You are the router agent for a Chinese real-estate internal system.
Return JSON only.

Classify the user's question:
- deal_query: query transaction/deal/order data, statistics, rankings, prices, areas, stores, agents.
- knowledge_query: ask about communities, policies, rules, processes, documents, school district, facilities.
- mixed_query: requires both transaction data and knowledge documents.
- clarification: missing enough information and cannot infer a useful route.
- unsupported: not related to this system.

Output:
{
  "intent": "deal_query|knowledge_query|mixed_query|clarification|unsupported",
  "confidence": 0.0,
  "entities": {
    "city": null,
    "community_name_raw": null,
    "community_name": null,
    "topic": null,
    "date_range": null
  },
  "reason": "short Chinese reason",
  "question": "optional clarification question"
}

If the user mentions a community with a typo or short name, infer a likely corrected community
name from the user's wording only. If uncertain, keep community_name null and put the original
text in community_name_raw.
""".strip()

DEAL_QUERY_PROMPT = """
You extract structured filters for querying transaction data.
Return JSON only. Do not return SQL.

Available fields:
- date_range: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} where end is inclusive.
- city, area, street, residential, store, agent, maintainor.
- price_range: {"min": number|null, "max": number|null}; price is yuan.
- acreage_range: {"min": number|null, "max": number|null}; acreage is sqm.
- metrics: one or more of count,total_price,avg_price,avg_unit_price,deal_list.
- group_by: null or one of residential,store,agent,maintainor,area,signing_month,acreage_bucket.
- sort: {"field": "signing_date|price|acreage|count|total_price|avg_price|avg_unit_price|bucket_order", "direction": "asc|desc"}.
- limit: integer, default 50, max 100.

For Chinese relative dates, use current_date from input.
If the user asks for rankings, include group_by and sort by count desc unless another metric is requested.
If the user asks for details/list, include deal_list.
If the user asks for "各个面积段", "面积段", or area distribution, set group_by to acreage_bucket and include metrics count,avg_price,avg_unit_price.
If the user asks for a concrete area range like "90-100平米", set acreage_range to {"min": 90, "max": 100} and include metrics count,avg_price,avg_unit_price.
Output:
{
  "date_range": null,
  "city": null,
  "area": null,
  "street": null,
  "residential": null,
  "store": null,
  "agent": null,
  "maintainor": null,
  "price_range": null,
  "acreage_range": null,
  "metrics": ["count"],
  "group_by": null,
  "sort": null,
  "limit": 50,
  "need_clarification": false,
  "missing_fields": [],
  "clarification_question": null
}
""".strip()


ANSWER_PROMPT = """
You are home-flow's Chinese business analyst.
Answer the user's question in concise Chinese based only on the SQL result JSON and rag_context.
SQL rows are transaction data. rag_context is uploaded knowledge such as community basics, school district information, and text extracted from PDFs or images.
If SQL rows are empty but rag_context is relevant, answer from rag_context and mention the knowledge title/source.
If both SQL rows and rag_context are empty, say no matching internal data was found.
For ranking results, name the top item and include its count. Add one short insight if useful.
When uploaded knowledge conflicts, the context has already been filtered to active latest documents, so treat later active knowledge as authoritative.
Do not invent data.
""".strip()


def llm_is_configured() -> bool:
    return bool(settings.llm_enabled and settings.llm_api_key)


def llm_config_summary() -> dict[str, Any]:
    return {
        "enabled": settings.llm_enabled,
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "has_api_key": bool(settings.llm_api_key),
        "framework": "langchain",
        "cost_controls_reserved": {
            "daily_user_limit": settings.llm_daily_user_limit,
            "daily_token_limit": settings.llm_daily_token_limit,
            "max_input_chars": settings.llm_max_input_chars,
            "max_output_tokens": settings.llm_max_output_tokens,
            "enforced": False,
        },
    }


def _normalize_openai_base_url(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/compatible-mode"):
        return f"{cleaned}/v1"
    return cleaned


def _build_chat_model():
    provider = settings.llm_provider.lower()
    if provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=_normalize_openai_base_url(settings.llm_base_url),
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )


def _message_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def call_llm(messages: list[dict[str, str]], json_mode: bool = True) -> str | None:
    if not llm_is_configured():
        return None

    try:
        model = _build_chat_model()
        if json_mode and hasattr(model, "bind"):
            model = model.bind(response_format={"type": "json_object"})
        response = model.invoke([(message["role"], message["content"]) for message in messages])
        return _message_content(response).strip()
    except Exception:
        return None


def call_llm_stream(messages: list[dict[str, str]], json_mode: bool = False) -> Iterator[str]:
    if not llm_is_configured():
        return

    try:
        model = _build_chat_model()
        if json_mode and hasattr(model, "bind"):
            model = model.bind(response_format={"type": "json_object"})
        for chunk in model.stream([(message["role"], message["content"]) for message in messages]):
            content = _message_content(chunk)
            if content:
                yield content
    except Exception:
        return


def generate_sql_with_llm(question: str, rag_context: list[dict] | None = None) -> dict[str, Any] | None:
    content = call_llm(
        [
            {"role": "system", "content": SQL_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "rag_context": rag_context or []},
                    ensure_ascii=False,
                ),
            },
        ],
        json_mode=True,
    )
    if not content:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def route_question_with_llm(question: str, mode: str = "auto") -> dict[str, Any] | None:
    content = call_llm(
        [
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": json.dumps({"question": question, "mode": mode}, ensure_ascii=False)},
        ],
        json_mode=True,
    )
    if not content:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def extract_deal_query_with_llm(question: str, current_date: str) -> dict[str, Any] | None:
    content = call_llm(
        [
            {"role": "system", "content": DEAL_QUERY_PROMPT},
            {"role": "user", "content": json.dumps({"question": question, "current_date": current_date}, ensure_ascii=False)},
        ],
        json_mode=True,
    )
    if not content:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def summarize_answer_with_llm(question: str, sql: str, rows: list[dict], rag_context: list[dict] | None = None) -> str | None:
    content = call_llm(
        [
            {"role": "system", "content": ANSWER_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "sql": sql,
                        "rows": rows[:50],
                        "rag_context": rag_context or [],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        json_mode=False,
    )
    return content.strip() if content else None


def summarize_answer_with_llm_stream(
    question: str,
    sql: str,
    rows: list[dict],
    rag_context: list[dict] | None = None,
) -> Iterator[str]:
    yield from call_llm_stream(
        [
            {"role": "system", "content": ANSWER_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "sql": sql,
                        "rows": rows[:50],
                        "rag_context": rag_context or [],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        json_mode=False,
    )
