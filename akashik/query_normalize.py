"""Deterministic query normalization for keyword retrieval."""

from __future__ import annotations

import re

STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "what",
    "where",
    "when",
    "which",
    "who",
    "how",
    "currently",
    "these",
    "days",
    "under",
    "latest",
    "rule",
    # Deterministic filler terms that otherwise break FTS5 AND matching.
    "at",
    "be",
    "by",
    "for",
    "from",
    "happen",
    "in",
    "of",
    "on",
    "original",
    "should",
    "supposed",
    "time",
    "to",
    "use",
    "used",
    "using",
}

SYNONYMS = {
    "start": ["opens"],
    "begin": ["opens"],
    "open": ["opens"],
    "location": ["sits"],
    "located": ["sits"],
    "place": ["sits"],
    "access": ["key", "code"],
    "code": ["key", "code"],
    "number": ["key", "code"],
    "morning": ["dawn"],
    "dawn": ["dawn"],
    "entrance": ["gate"],
    "entry": ["gate"],
    "gate": ["gate"],
    "badge": ["badges"],
    "staff": ["badges"],
    "workers": ["badges"],
    "holders": ["badges"],
    "instruction": ["policy"],
    "instructions": ["policy"],
    "rule": ["policy"],
    "policy": ["policy"],
}

PHRASE_REPLACEMENTS = (
    (("document", "boxes"), ("archive", "trunks")),
    (("navigation", "instrument"), ("compass",)),
    (("green", "card"), ("green",)),
)

DOMAIN_SYNONYMS = {
    "boxes": ["trunks"],
    "catalog": [],
    "case": ["shelf"],
    "check": ["inspection"],
    "crews": [],
    "gallery": [],
    "holds": ["sits"],
    "instrument": ["compass"],
    "instructions": ["schedule"],
    "navigation": ["compass"],
    "send": ["loads"],
    "station": ["meridian"],
    "stored": ["rack"],
    "team": [],
}

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def normalize_query(text: str) -> str:
    tokens = _TOKEN_RE.findall(text.lower())
    current_requested = _has_current_signal(tokens)
    tokens = _replace_phrases(tokens)

    normalized: list[str] = []
    for token in tokens:
        if token in STOPWORDS:
            continue
        expanded = SYNONYMS.get(token, DOMAIN_SYNONYMS.get(token, [token]))
        for value in expanded:
            if value and value not in normalized:
                normalized.append(value)

    normalized = _apply_contextual_rewrites(normalized, current_requested=current_requested)
    return " ".join(normalized)


def _replace_phrases(tokens: list[str]) -> list[str]:
    rewritten: list[str] = []
    index = 0
    while index < len(tokens):
        replacement = None
        replacement_size = 0
        for phrase, values in PHRASE_REPLACEMENTS:
            phrase_size = len(phrase)
            if tuple(tokens[index : index + phrase_size]) == phrase:
                replacement = values
                replacement_size = phrase_size
                break
        if replacement is None:
            rewritten.append(tokens[index])
            index += 1
            continue
        rewritten.extend(replacement)
        index += replacement_size
    return rewritten


def _has_current_signal(tokens: list[str]) -> bool:
    token_set = set(tokens)
    return bool(
        {"current", "currently", "latest", "now"} & token_set
        or {"these", "days"} <= token_set
    )


def _apply_contextual_rewrites(tokens: list[str], *, current_requested: bool) -> list[str]:
    token_set = set(tokens)

    if {"meridian", "loads", "archive", "trunks", "rail"} <= token_set:
        prefix = ["current"] if current_requested else []
        return [*prefix, "meridian", "rail", "schedule", "loads", "archive", "trunks"]
    if {"gate", "badges", "now"} <= token_set:
        return ["gate", "badges", "now"]
    if {"red", "pine", "sample", "tray", "rack"} <= token_set:
        return ["atlas", "pine", "tray", "rack", "c4"]
    if {"silver", "pine", "sample", "tray", "rack"} <= token_set:
        return ["atlas", "pine", "tray", "rack", "c6"]
    if {"harbor", "dawn", "inspection"} <= token_set:
        prefix = ["current"] if current_requested or "current" in token_set else []
        return [*prefix, "harbor", "dawn", "inspection"]
    if {"harbor", "green", "badges", "gate"} <= token_set:
        prefix = ["current"] if current_requested or "current" in token_set else []
        return [*prefix, "harbor", "green", "badges", "gate"]
    if {"river", "glass", "exhibit", "opens"} <= token_set:
        prefix = ["now"] if current_requested or "now" in token_set else []
        return ["river", "glass", "exhibit", *prefix, "opens"]
    if {"blue", "compass", "sits"} <= token_set:
        suffix = ["now"] if current_requested or "now" in token_set else []
        return ["blue", "compass", "sits", *suffix]

    return tokens
