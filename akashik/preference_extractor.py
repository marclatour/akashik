"""Deterministic user preference extraction for conversational turns."""

from __future__ import annotations

import re

STOP_PHRASES = [" for ", " because ", " since ", " when ", " which "]
_PRONOUN_VALUES = {"it", "this", "that", "them"}
_GENERIC_VALUES = {"things", "stuff", "everything", "anything"}
_MAX_VALUE_LENGTH = 60

_PATTERN_SPECS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bi(?: absolutely)? love\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\bi always use\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\bi always\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\bi swear by\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\bnothing beats\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\b(.+?) is my favorite\b", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\bmy favorite .+? is\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\b(.+?) is the best\b", re.IGNORECASE), "like", "strong"),
    (re.compile(r"\bi(?: really)? like\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi(?:'d| would)? prefer\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi enjoy\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi(?:'ve| have)? been using\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi use\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi switched to\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi(?:'m| am)(?: really)? into\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi(?:'ve| have) been(?: really)? into\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi rely on\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi recommend\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\b(.+?) works (?:well|great) for me\b", re.IGNORECASE), "like", "moderate"),
    (re.compile(r"\bi(?:'ve| have) tried\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "weak"),
    (re.compile(r"\b(.+?) seems good\b", re.IGNORECASE), "like", "weak"),
    (re.compile(r"\b(.+?) looks good\b", re.IGNORECASE), "like", "weak"),
    (re.compile(r"\bi might try\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "weak"),
    (re.compile(r"\bi(?:'m| am) thinking about(?: trying)?\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "like", "weak"),
    (re.compile(r"\bi hate\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "dislike", "strong"),
    (re.compile(r"\bi can't stand\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "dislike", "strong"),
    (re.compile(r"\bi do(?: not|n't) like\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "dislike", "moderate"),
    (re.compile(r"\bi dislike\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "dislike", "moderate"),
    (re.compile(r"\b(.+?) doesn't work for me\b", re.IGNORECASE), "dislike", "moderate"),
    (re.compile(r"\b(.+?) isn't for me\b", re.IGNORECASE), "dislike", "moderate"),
    (re.compile(r"\bi avoid\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "dislike", "moderate"),
    (re.compile(r"\bi stopped using\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "dislike", "weak"),
    (re.compile(r"\bi gave up on\s+(.+?)(?=(?:\s+(?:but|and)\s+i\b)|$)", re.IGNORECASE), "dislike", "weak"),
]


def extract_preferences(content: str) -> list[dict]:
    text = " ".join((content or "").split()).strip()
    if not text:
        return []

    extracted: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for pattern, polarity, strength in _PATTERN_SPECS:
        for match in pattern.finditer(text):
            value = _clean_value(match.group(1))
            if not value:
                continue
            key = ("user", polarity, value.casefold())
            if key in seen:
                continue
            seen.add(key)
            extracted.append(
                {
                    "entity": "user",
                    "attribute": "preference",
                    "value": value,
                    "polarity": polarity,
                    "strength": strength,
                }
            )
    return extracted


def _clean_value(value: str) -> str:
    cleaned = " ".join((value or "").split()).strip()
    for stop in STOP_PHRASES:
        if stop in cleaned.lower():
            index = cleaned.lower().find(stop)
            cleaned = cleaned[:index]
            break
    cleaned = cleaned.strip().rstrip(".,!?")
    cleaned = re.sub(r"^(?:my|the|a|an)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned[:_MAX_VALUE_LENGTH].strip()
    lowered = cleaned.casefold()
    if len(cleaned) < 2:
        return ""
    if lowered in _PRONOUN_VALUES or lowered in _GENERIC_VALUES:
        return ""
    return cleaned
