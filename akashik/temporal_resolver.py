"""Deterministic two-event temporal delta resolver.

Coverage is intentionally limited to explicit two-event delta questions.
Aggregation queries and broader temporal reasoning remain out of scope here.
"""

from __future__ import annotations

import logging
import re

from akashik.parse_temporal_scope import _parse_question_date
from akashik.query_normalize import normalize_event_description

LOGGER = logging.getLogger(__name__)

_AGGREGATION_PATTERNS = (
    re.compile(r"\bwhich\b.*\bmost\b", re.IGNORECASE),
    re.compile(r"\bwhat is the difference\b", re.IGNORECASE),
)
_FILLER_PREFIX_RE = re.compile(
    r"^(?:(?:the\s+day|the\s+time|the\s+moment)\s+)?i\s+|^(?:the\s+day|the\s+time|the\s+moment)\s+",
    re.IGNORECASE,
)
_CLASSIFIERS: list[re.Pattern[str]] = [
    re.compile(
        r"how many\s+(days|weeks|months)\s+(?:passed|had passed)\s+between\s+"
        r"(?:the day |the time |the moment )?(.*?)\s+and\s+"
        r"(?:the day |the time |the moment )?(.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"how long\s+(after|before|since)\s+(.*?)\s+(?:did|was|were)\s+(.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"how many\s+(days|weeks|months)\s+(?:was it|is it|did it take)\s+"
        r"(?:from|between)\s+(.*?)\s+(?:to|and)\s+(.*)",
        re.IGNORECASE,
    ),
]


def classify_temporal_query(question: str) -> dict | None:
    text = " ".join((question or "").split()).strip()
    if not text:
        return None
    if any(pattern.search(text) for pattern in _AGGREGATION_PATTERNS):
        return None

    for pattern in _CLASSIFIERS:
        match = pattern.search(text)
        if not match:
            continue
        if pattern is _CLASSIFIERS[1]:
            relation, event_a, event_b = match.groups()
            unit = "days"
            if relation.lower() == "before":
                event_a, event_b = event_b, event_a
        else:
            unit, event_a, event_b = match.groups()
        event_a = _clean_event_text(event_a)
        event_b = _clean_event_text(event_b)
        if not event_a or not event_b:
            return None
        return {
            "type": "delta",
            "unit": unit.lower() if unit else "days",
            "event_a": event_a,
            "event_b": event_b,
        }
    return None


def resolve_event_date(
    store,
    event_description: str,
    entity_filters: dict,
    confidence_threshold: float = 0.6,
) -> tuple[str, float] | None:
    try:
        from akashik.retrieve import retrieve
    except Exception:
        return None

    normalized_event = normalize_event_description(event_description)
    query_parts: list[str] = []
    for value in (event_description, normalized_event):
        cleaned = " ".join((value or "").split()).strip()
        if cleaned and cleaned not in query_parts:
            query_parts.append(cleaned)
    query = " ".join(query_parts)
    try:
        response = retrieve(
            query,
            store,
            level="fact",
            limit=1,
            entity_filters=entity_filters,
            _enable_temporal_resolver=False,
        )
    except Exception:
        return None
    if not response.results:
        return None
    result = response.results[0]
    overlap_confidence = _token_overlap(
        set(_event_tokens(event_description)),
        set(_event_tokens(result.unit.content)),
    )
    resolved_confidence = max(result.confidence, overlap_confidence)
    if resolved_confidence < confidence_threshold:
        return None
    session_date = str(result.unit.metadata.get("session_date", "")).strip()
    if not session_date:
        return None
    try:
        normalized_date = _parse_question_date(session_date).isoformat()
    except ValueError:
        return None
    return (normalized_date, resolved_confidence)


def compute_delta(
    date_a: str,
    date_b: str,
    unit: str,
) -> int | None:
    try:
        first = _parse_question_date(date_a)
        second = _parse_question_date(date_b)
    except ValueError:
        return None
    if unit == "days":
        return abs((second - first).days)
    if unit == "weeks":
        return abs((second - first).days) // 7
    if unit == "months":
        return abs((second.year - first.year) * 12 + (second.month - first.month))
    return None


def resolve_two_event_temporal(
    store,
    question: str,
    entity_filters: dict,
    question_date: str | None = None,
) -> dict | None:
    try:
        structured = classify_temporal_query(question)
        if structured is None:
            return None

        cached = _resolve_from_single_pass(
            store,
            question,
            structured,
            entity_filters,
            question_date=question_date,
        )
        if cached is None:
            event_a_result = resolve_event_date(store, structured["event_a"], entity_filters)
            if event_a_result is None:
                LOGGER.warning("Temporal delta resolution failed for event_a: %s", structured["event_a"])
                return None
            event_b_result = resolve_event_date(store, structured["event_b"], entity_filters)
            if event_b_result is None:
                LOGGER.warning("Temporal delta resolution failed for event_b: %s", structured["event_b"])
                return None
        else:
            event_a_result, event_b_result = cached

        delta = compute_delta(event_a_result[0], event_b_result[0], structured["unit"])
        if delta is None:
            return None
        return {
            "delta": delta,
            "unit": structured["unit"],
            "event_a": structured["event_a"],
            "event_a_date": event_a_result[0],
            "event_a_confidence": event_a_result[1],
            "event_b": structured["event_b"],
            "event_b_date": event_b_result[0],
            "event_b_confidence": event_b_result[1],
        }
    except Exception:
        return None


def _resolve_from_single_pass(
    store,
    question: str,
    structured: dict,
    entity_filters: dict,
    *,
    question_date: str | None,
) -> tuple[tuple[str, float], tuple[str, float]] | None:
    try:
        from akashik.retrieve import retrieve
    except Exception:
        return None
    try:
        response = retrieve(
            question,
            store,
            level="fact",
            limit=20,
            entity_filters=entity_filters,
            query_date=question_date,
            _enable_temporal_resolver=False,
        )
    except Exception:
        return None
    if not response.results:
        return None

    event_a = _match_event_in_results(structured["event_a"], response.results)
    event_b = _match_event_in_results(structured["event_b"], response.results)
    if event_a is None or event_b is None:
        return None
    if event_a[0] == event_b[0] and _clean_event_text(structured["event_a"]).casefold() != _clean_event_text(structured["event_b"]).casefold():
        return None
    return (event_a, event_b)


def _match_event_in_results(event_description: str, results) -> tuple[str, float] | None:
    target_tokens = set(_event_tokens(event_description))
    if not target_tokens:
        return None
    best: tuple[str, float] | None = None
    best_overlap = 0.0
    for result in results:
        session_date = str(result.unit.metadata.get("session_date", "")).strip()
        if not session_date:
            continue
        try:
            normalized_date = _parse_question_date(session_date).isoformat()
        except ValueError:
            continue
        content_tokens = set(_event_tokens(result.unit.content))
        overlap = _token_overlap(target_tokens, content_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best = (normalized_date, max(result.confidence, overlap))
    if best is None or best_overlap < 0.5:
        return None
    return best


def _event_tokens(text: str) -> list[str]:
    normalized = normalize_event_description(text)
    return re.findall(r"\w+", normalized.lower())


def _token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left)


def _clean_event_text(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip(" ?.,")
    cleaned = _FILLER_PREFIX_RE.sub("", cleaned).strip(" ?.,")
    return cleaned
