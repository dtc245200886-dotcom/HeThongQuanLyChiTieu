"""Validate Gemini output against database facts without hiding valid answers."""
import re
from typing import Any


SOFT_WARNING = (
    "\n\n⚠️ Lưu ý: Một số liệu trong câu trả lời chưa xác minh được "
    "từ dữ liệu hiện có."
)
MONEY_PATTERN = re.compile(
    r"(?<![\d\w])(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\s*"
    r"(?:đ|vnđ|vnd|đồng)?|\d+(?:[.,]\d+)?\s*(?:đ|vnđ|vnd|đồng))"
    r"(?![\d\w])",
    re.IGNORECASE,
)


def _parse_money(value: str) -> float | None:
    """Parse Vietnamese thousands formats such as 538.000 and 1.138.000."""
    value = value.lower().replace("đồng", "").replace("vnđ", "").replace("vnd", "").replace("đ", "")
    value = value.strip().replace(" ", "")
    if not value:
        return None

    separators = [index for index, char in enumerate(value) if char in ".,"]
    if not separators:
        return float(value)

    groups = re.split(r"[.,]", value)
    if len(groups) > 1 and all(len(group) == 3 for group in groups[1:]):
        return float("".join(groups))

    # Decimal notation is accepted for completeness, but is not treated as
    # a financial fact unless it matches a value supplied by the database.
    decimal_separator = "," if "," in value and "." not in value else "."
    return float(value.replace(decimal_separator, "."))


def _database_amounts(value: Any) -> list[float]:
    """Collect monetary fields recursively from the analyzer result."""
    if isinstance(value, dict):
        return [amount for item in value.values() for amount in _database_amounts(item)]
    if isinstance(value, list):
        return [amount for item in value for amount in _database_amounts(item)]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [float(value)]
    return []


def _matches_database(value: float, known: list[float]) -> bool:
    return any(abs(value - item) <= max(1.0, abs(item) * 0.01) for item in known)


def validate_response(response: str, facts: dict) -> str:
    """Keep Gemini's answer and append a warning for unverifiable money values."""
    text = (response or "").strip()
    if not text:
        raise ValueError("AI trả về nội dung rỗng")
    if len(text) > 8000:
        text = text[:7997].rstrip() + "..."

    known = _database_amounts(facts)
    maximum = max(known, default=0.0)
    has_unverified_amount = False
    has_abnormal_amount = False

    for token in MONEY_PATTERN.findall(text):
        numeric = _parse_money(token)
        if numeric is None:
            continue
        if known and numeric > maximum * 100 + 1:
            has_abnormal_amount = True
        elif not _matches_database(numeric, known):
            has_unverified_amount = True

    if (has_unverified_amount or has_abnormal_amount) and SOFT_WARNING not in text:
        return text + SOFT_WARNING
    return text
