import json
import urllib.error
import urllib.request
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
maintainor, parking, status, remark, location, brand.

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


ANSWER_PROMPT = """
You are home-flow's Chinese business analyst.
Answer the user's question in concise Chinese based only on the SQL result JSON.
If there is no data, say no matching transaction data was found and mention the likely filter period/condition.
For ranking results, name the top item and include its count. Add one short insight if useful.
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
    }


def call_llm(messages: list[dict[str, str]], json_mode: bool = True) -> str | None:
    if not llm_is_configured():
        return None

    url = settings.llm_base_url.rstrip("/") + "/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.1,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError):
        return None


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
