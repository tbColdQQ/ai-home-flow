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


LABEL_ALIASES = {
    "residential": ["维护楼盘", "签约小区", "楼盘", "小区"],
    "price": ["成交价格", "签约金额", "成交价"],
    "acreage": ["房源面积", "签约面积", "面积"],
    "CA": ["维护人CA", "维护人 CA", "签约CA", "签约 CA", "CA"],
    "brand": ["签约品牌", "品牌"],
    "signing_date": ["签约时间", "成交时间", "成交日期", "签约日期"],
}

IGNORE_LINES = {
    "贝壳",
    "德佑",
    "房源售出",
    "房源售",
    "出",
    "贺报",
    "賀報",
    "報",
    "喜报",
    "让家更美好",
    "更美好",
    "二手成交速递",
    "nohep",
}

ORG_NAME_PATTERN = re.compile(
    r"(税务局|公安局|财政局|住建局|市场监管局|管理局|委员会|办事处|法院|检察院|医院|学校|银行|公司|集团)$"
)


def _normalize_label(line: str) -> str:
    return re.sub(r"[\s:：]+", "", line)


def _clean_value(value: str) -> str:
    return value.strip().strip(":：").strip()


def _line_after_labels(lines: list[str], labels: list[str]) -> str | None:
    normalized_labels = sorted({_normalize_label(label) for label in labels}, key=len, reverse=True)
    for index, line in enumerate(lines):
        normalized_line = _normalize_label(line)
        for label in normalized_labels:
            if normalized_line == label:
                for next_line in lines[index + 1 :]:
                    value = _clean_value(next_line)
                    if value:
                        return value
    for line in lines:
        normalized_line = _normalize_label(line)
        for label in normalized_labels:
            if normalized_line.startswith(label):
                value = _clean_value(line[len(label) :])
                if value:
                    return value
    return None


def _number_from_value(value: str | None, unit_multiplier: bool = False) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    number = float(match.group(0))
    if unit_multiplier and "万" in value:
        return number * 10000
    return number


def _number_after_labels(lines: list[str], labels: list[str], unit_multiplier: bool = False) -> float | None:
    return _number_from_value(_line_after_labels(lines, labels), unit_multiplier)


def _date_after_labels(lines: list[str], labels: list[str]) -> str | None:
    value = _line_after_labels(lines, labels)
    if not value:
        return None
    match = re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value)
    if not match:
        return None
    year, month, day = re.split(r"[-/]", match.group(0))
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _report_type(clean_text: str) -> str:
    if "贺报" in clean_text or "賀報" in clean_text or "房源售出" in clean_text:
        return "maintainor_report"
    if "喜报" in clean_text or "签约金额" in clean_text or "二手成交速递" in clean_text:
        return "agent_report"
    if "维护楼盘" in clean_text or "维护人CA" in clean_text:
        return "maintainor_report"
    return "unknown"


def _participant_and_store(lines: list[str], residential: str | None, ca: str | None, brand: str | None) -> tuple[str | None, str | None]:
    label_fragments = [label for aliases in LABEL_ALIASES.values() for label in aliases]
    participant = None
    store = None
    for line in lines:
        value = _clean_value(line)
        if not value or value in IGNORE_LINES:
            continue
        if any(fragment in value for fragment in label_fragments):
            continue
        if any(fragment in value for fragment in ["今日房源", "今日累计", "累计售出", "房源累计", "累计签单"]):
            continue
        if residential and value == residential:
            continue
        if ca and value == ca:
            continue
        if brand and value == brand:
            continue
        if store is None and value.endswith("店"):
            store = value
            continue
        if participant is None and 2 <= len(value) <= 5 and not re.search(r"\d", value) and not ORG_NAME_PATTERN.search(value):
            participant = value
    return participant, store


def parse_order_text(text: str, city: str, business_date: str) -> ParsedOrder:
    clean_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    lines = clean_text.splitlines()

    residential = _line_after_labels(lines, LABEL_ALIASES["residential"])
    price = _number_after_labels(lines, LABEL_ALIASES["price"], unit_multiplier=True)
    acreage = _number_after_labels(lines, LABEL_ALIASES["acreage"])
    ca = _line_after_labels(lines, LABEL_ALIASES["CA"])
    brand = _line_after_labels(lines, LABEL_ALIASES["brand"])
    parsed_signing_date = _date_after_labels(lines, LABEL_ALIASES["signing_date"])
    report_type = _report_type(clean_text)
    participant, participant_store = _participant_and_store(lines, residential, ca, brand)

    data = {
        "city": city,
        "residential": residential,
        "price": price,
        "acreage": acreage,
        "signing_date": parsed_signing_date or business_date,
        "CA": ca,
        "status": "normal",
        "brand": brand or ("贝壳/德佑" if ("贝壳" in clean_text or "德佑" in clean_text) else None),
        "report_type": report_type,
    }
    if report_type == "maintainor_report":
        data["maintainor"] = participant
        data["maintainor_store"] = participant_store
    else:
        data["agent"] = participant
        data["store"] = participant_store

    confidence = {
        "residential": 0.95 if residential else 0.0,
        "price": 0.98 if price else 0.0,
        "acreage": 0.98 if acreage else 0.0,
        "agent": 0.8 if data.get("agent") else 0.0,
        "store": 0.85 if data.get("store") else 0.0,
        "maintainor": 0.8 if data.get("maintainor") else 0.0,
        "maintainor_store": 0.85 if data.get("maintainor_store") else 0.0,
        "CA": 0.9 if ca else 0.0,
        "report_type": 0.9 if report_type != "unknown" else 0.0,
    }
    reasons = []
    required = {
        "residential": "楼盘缺失",
        "price": "成交价格缺失或格式异常",
        "acreage": "房源面积缺失或格式异常",
        "signing_date": "成交日期缺失",
    }
    if report_type == "agent_report":
        required["agent"] = "成交人缺失"
        required["store"] = "成交人门店缺失"
    if report_type == "maintainor_report":
        required["maintainor"] = "维护人缺失"
        required["maintainor_store"] = "维护人门店缺失"
    if report_type == "unknown":
        reasons.append("无法识别图片类型")

    for field, reason in required.items():
        if not data.get(field):
            reasons.append(reason)
    return ParsedOrder(data=data, confidence=confidence, reasons=reasons)
