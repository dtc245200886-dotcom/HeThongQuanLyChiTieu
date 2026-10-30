"""Parse financial intent and Vietnamese time phrases without calling an LLM."""
from dataclasses import dataclass
from datetime import date, timedelta
import re


@dataclass(frozen=True)
class ParsedQuestion:
    intent: str
    period: str
    start_date: date
    end_date: date


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def parse_question(question: str, today: date | None = None) -> ParsedQuestion:
    today = today or date.today()
    normalized = " ".join(question.lower().split())
    if any(word in normalized for word in ("ngân sách", "budget", "vượt")):
        intent = "budget"
    elif any(word in normalized for word in ("tiết kiệm", "gợi ý", "nên chi")):
        intent = "recommendation"
    elif any(word in normalized for word in ("xu hướng", "tăng", "giảm", "so sánh")):
        intent = "trend"
    elif any(word in normalized for word in ("top", "nhiều nhất", "danh mục")):
        intent = "category"
    elif any(word in normalized for word in ("thu nhập", "tổng thu")):
        intent = "income"
    elif any(word in normalized for word in ("số dư", "còn lại")):
        intent = "balance"
    else:
        intent = "summary"

    if "hôm nay" in normalized:
        period = "today"
        start_date = end_date = today
    elif "tuần này" in normalized:
        period = "week"
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif "năm nay" in normalized:
        period = "year"
        start_date = date(today.year, 1, 1)
        end_date = date(today.year, 12, 31)
    else:
        period = "month"
        start_date = date(today.year, today.month, 1)
        end_date = _month_end(today.year, today.month)
    return ParsedQuestion(intent, period, start_date, end_date)
