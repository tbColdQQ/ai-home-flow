import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedOrder:
    data: dict
    confidence: dict[str, float]
    reasons: list[str]

    @property
    def needs_review(self) -> bool:
        return bool(self.reasons)


def _line_after_label(text: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}\s*[:：]\s*([^\n\r]+)", text)
    return match.group(1).strip() if match else None


def _number_after_label(text: str, label: str) -> float | None:
    value = _line_after_label(text, label)
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
    return float(match.group(0)) if match else None


def parse_order_text(text: str, city: str, business_date: str) -> ParsedOrder:
    clean_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    lines = clean_text.splitlines()
    residential = _line_after_label(clean_text, "维护楼盘")
    price = _number_after_label(clean_text, "成交价格")
    acreage = _number_after_label(clean_text, "房源面积")
    ca = _line_after_label(clean_text, "维护人CA")

    agent = None
    store = None
    for line in lines:
        if line in {"贝壳", "德佑", "房源售出", "贺报"}:
            continue
        if any(label in line for label in ["维护楼盘", "成交价格", "房源面积", "维护人CA", "今日房源"]):
            continue
        if agent is None and 2 <= len(line) <= 5 and not re.search(r"\d", line):
            agent = line
            continue
        if store is None and line.endswith("店"):
            store = line

    data = {
        "city": city,
        "residential": residential,
        "price": price,
        "acreage": acreage,
        "agent": agent,
        "store": store,
        "signing_date": business_date,
        "CA": ca,
        "status": "normal",
        "brand": "贝壳/德佑" if ("贝壳" in clean_text or "德佑" in clean_text) else None,
    }

    confidence = {
        "residential": 0.95 if residential else 0.0,
        "price": 0.98 if price else 0.0,
        "acreage": 0.98 if acreage else 0.0,
        "agent": 0.8 if agent else 0.0,
        "store": 0.85 if store else 0.0,
        "CA": 0.9 if ca else 0.0,
    }
    reasons = []
    required = {
        "residential": "楼盘缺失",
        "price": "成交价格缺失或格式异常",
        "acreage": "房源面积缺失或格式异常",
        "signing_date": "成交日期缺失",
    }
    for field, reason in required.items():
        if not data.get(field):
            reasons.append(reason)
    return ParsedOrder(data=data, confidence=confidence, reasons=reasons)

