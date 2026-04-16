"""Deterministic temporal scope parsing for question text."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
import logging
import re

LOGGER = logging.getLogger(__name__)

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_MONTH_PATTERN = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
_DAY_PATTERN = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\byesterday\b", re.IGNORECASE), "yesterday"),
    (
        re.compile(r"\b(today|this morning|earlier today)\b", re.IGNORECASE),
        "today",
    ),
    (re.compile(r"\blast week\b", re.IGNORECASE), "last_week"),
    (re.compile(r"\bthis week\b", re.IGNORECASE), "this_week"),
    (re.compile(r"\blast month\b", re.IGNORECASE), "last_month"),
    (re.compile(r"\bthis month\b", re.IGNORECASE), "this_month"),
    (re.compile(r"\b(\d+)\s+days?\s+ago\b", re.IGNORECASE), "days_ago"),
    (re.compile(r"\b(\d+)\s+weeks?\s+ago\b", re.IGNORECASE), "weeks_ago"),
    (re.compile(r"\b(\d+)\s+months?\s+ago\b", re.IGNORECASE), "months_ago"),
    (re.compile(rf"\bin\s+{_MONTH_PATTERN}\b", re.IGNORECASE), "in_month"),
    (re.compile(rf"\blast\s+{_MONTH_PATTERN}\b", re.IGNORECASE), "last_named_month"),
    (re.compile(rf"\blast\s+{_DAY_PATTERN}\b", re.IGNORECASE), "last_day"),
    (re.compile(r"\b(recently|the other day)\b", re.IGNORECASE), "fuzzy_recent"),
]


def parse_temporal_scope(question: str, question_date: str) -> tuple[date, date] | None:
    normalized = (question or "").strip().lower()
    if not normalized:
        return None

    if _has_unsupported_multi_expression(normalized):
        LOGGER.warning("Unsupported multi-expression temporal query: %s", question)
        return None

    qd = _parse_question_date(question_date)

    for pattern, kind in _PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        if kind == "yesterday":
            day = qd - timedelta(days=1)
            return (day, day)
        if kind == "today":
            return (qd, qd)
        if kind == "last_week":
            return (qd - timedelta(days=7), qd - timedelta(days=1))
        if kind == "this_week":
            return (qd - timedelta(days=qd.weekday()), qd)
        if kind == "last_month":
            first_this_month = qd.replace(day=1)
            last_prev_month = first_this_month - timedelta(days=1)
            return _month_range(last_prev_month.year, last_prev_month.month)
        if kind == "this_month":
            return (qd.replace(day=1), qd)
        if kind == "days_ago":
            day = qd - timedelta(days=int(match.group(1)))
            return (day, day)
        if kind == "weeks_ago":
            start = qd - timedelta(days=7 * int(match.group(1)))
            return (start, start + timedelta(days=6))
        if kind == "months_ago":
            year, month = _shift_month(qd.year, qd.month, -int(match.group(1)))
            return _month_range(year, month)
        if kind == "in_month":
            month = _MONTH_NAMES[match.group(1).lower()]
            year = qd.year if month <= qd.month else qd.year - 1
            return _month_range(year, month)
        if kind == "last_named_month":
            month = _MONTH_NAMES[match.group(1).lower()]
            year = qd.year if month < qd.month else qd.year - 1
            return _month_range(year, month)
        if kind == "last_day":
            target = _DAY_NAMES[match.group(1).lower()]
            delta = (qd.weekday() - target) % 7
            delta = 7 if delta == 0 else delta
            day = qd - timedelta(days=delta)
            return (day, day)
        if kind == "fuzzy_recent":
            return (qd - timedelta(days=14), qd - timedelta(days=1))
    return None


def _has_unsupported_multi_expression(question: str) -> bool:
    if "between " in question:
        return True
    month_hits = re.findall(_MONTH_PATTERN, question, flags=re.IGNORECASE)
    return len(month_hits) > 1


def _month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    return (first, last)


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = (year * 12 + (month - 1)) + offset
    shifted_year, shifted_month = divmod(absolute, 12)
    return shifted_year, shifted_month + 1


def _parse_question_date(question_date: str) -> date:
    """Parse question_date from either ISO or LongMemEval format."""
    try:
        return date.fromisoformat(question_date[:10])
    except ValueError:
        pass
    try:
        return datetime.strptime(question_date[:10], "%Y/%m/%d").date()
    except ValueError:
        pass
    raise ValueError(f"Unrecognized question_date format: {question_date!r}")
