"""Limited rule-based contradiction detection for high-frequency personal facts."""

from __future__ import annotations

import re

from akashik.schema import MemoryUnit

_MAX_VALUE_LENGTH = 50
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^(?:i live in|i(?: am|'m) living in|i moved to)\s+(.+)$", re.IGNORECASE),
        "location",
    ),
    (
        re.compile(r"^(?:i work at|i work for|i(?: am|'m) working at)\s+(.+)$", re.IGNORECASE),
        "employer",
    ),
    (
        re.compile(r"^(?:i work as|i(?: am|'m) a|my job is)\s+(.+)$", re.IGNORECASE),
        "role",
    ),
    (
        re.compile(r"^(?:i study at|i go to|i attend)\s+(.+)$", re.IGNORECASE),
        "school",
    ),
    (
        re.compile(r"^(?:i(?: am|'m)\s+(.+?)\s+years old|i turned\s+(.+)$|my age is\s+(.+)$)", re.IGNORECASE),
        "age",
    ),
    (
        re.compile(r"^(?:i drive a|i own a|i bought a)\s+(.+)$", re.IGNORECASE),
        "vehicle",
    ),
    (
        re.compile(r"^(?:i use|i switched to|i prefer)\s+(.+)$", re.IGNORECASE),
        "preference",
    ),
    (
        re.compile(r"^(?:my name is|i go by|call me)\s+(.+)$", re.IGNORECASE),
        "name",
    ),
]


def extract_triple(content: str) -> tuple[str, str, str] | None:
    text = " ".join((content or "").split()).strip()
    if not text:
        return None
    for pattern, attribute in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        value = next((group for group in match.groups() if group), "")
        value = value.strip(" ,.;:!?\"'()[]{}")[:_MAX_VALUE_LENGTH].strip()
        if not value:
            return None
        return ("user", attribute, value)
    return None


def find_contradicting_fact(
    store,
    triple: tuple[str, str, str],
    instance_id: str | None = None,
) -> MemoryUnit | None:
    entity, attribute, value = triple
    filters: dict[str, str] = {}
    if instance_id:
        filters["instance_id"] = instance_id
    candidates = store.fetch_by_metadata_filters(level="fact", filters=filters or None)
    matching: list[MemoryUnit] = []
    for candidate in candidates:
        if candidate.valid_until is not None:
            continue
        candidate_triple = extract_triple(candidate.content)
        if candidate_triple is None:
            continue
        cand_entity, cand_attribute, cand_value = candidate_triple
        if (cand_entity, cand_attribute) != (entity, attribute):
            continue
        if cand_value.casefold() == value.casefold():
            continue
        matching.append(candidate)
    if not matching:
        return None
    matching.sort(
        key=lambda unit: (
            unit.valid_from or "",
            unit.metadata.get("session_date", "") or "",
        )
    )
    return matching[-1]


def close_fact(store, fact_id: str, valid_until: str) -> None:
    store.close_fact(fact_id, valid_until)
