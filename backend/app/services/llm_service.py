import json
import urllib.error
import urllib.request
from typing import Any

from app.core.config import settings


SYSTEM_PROMPT = """
You are the intent parser for home-flow, a Chinese second-hand housing transaction QA system.
Return JSON only. Do not generate SQL.

Database fields:
city, area, street, residential, acreage, list_price, price, agent, store,
signing_date, CA, maintainor, parking, status, location, brand.

Output JSON:
{
  "metric": "count|total_price|avg_total_price|avg_unit_price|ranking|detail",
  "date_range": "today|this_month|this_year|none",
  "residential": null,
  "store": null,
  "agent": null,
  "area": null,
  "group_by": null,
  "chart": false
}

Rules:
- The backend will enforce city-level data permissions.
- If the user asks for ranking, most, top, or leaderboard, use metric=ranking and group_by=residential unless another grouping is explicit.
- If the user asks for unit price or average price in Chinese, use metric=avg_unit_price.
- If the user asks for details, records, or list, use metric=detail.
- If the user asks for a chart, trend, or visualization, set chart=true.
""".strip()


def call_llm(messages: list[dict[str, str]]) -> str | None:
    if not settings.llm_enabled or not settings.llm_api_key:
        return None

    url = settings.llm_base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
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


def parse_intent_with_llm(question: str) -> dict[str, Any] | None:
    content = call_llm(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
    )
    if not content:
        return None
    try:
        intent = json.loads(content)
    except json.JSONDecodeError:
        return None
    return intent if isinstance(intent, dict) else None
