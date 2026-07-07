"""Minimal synchronous conversational ingest spike."""

from __future__ import annotations

from datetime import date
import json
import logging
from typing import Any
from urllib import error, request

from akashik.ingest import ingest_text

LOGGER = logging.getLogger(__name__)

_OLLAMA_URL = "http://localhost:11434/api/generate"
_MODEL = "qwen2.5:1.5b"
_MIN_CONFIDENCE = 0.85

_PROMPT_TEMPLATE = """You are extracting a persistent fact about a user from a conversational message.

A persistent fact is something stable and ongoing about the user: where they live, their job, their relationships, their regular habits, things they own.

Do not extract transient activities, one-time events, or facts about other people.
Do not copy words from these instructions into your output.
If the message contains negation or there is no persistent fact, return null for fact.
Return JSON only, no explanation.

Example:
Message: "I just moved to Denver from Chicago."
Output: {{"fact": "User lives in Denver", "topic": "location", "confidence": 0.95}}

Message: "I work as a data engineer at a startup called Helio."
Output: {{"fact": "User works as a data engineer at Helio", "topic": "occupation", "confidence": 0.95}}

Message: "I spent the weekend hiking."
Output: {{"fact": null, "topic": null, "confidence": 0.0}}

Format: {{"fact": "<specific fact about the user, or null>", "topic": "<broad topic or null>", "confidence": <0.0-1.0>}}

Message: "{text}"
"""


def _result(
    *,
    extracted: bool,
    fact: str | None,
    topic: str | None,
    raw_response: str | None,
    confidence: float,
    written: bool,
    skipped_reason: str | None,
) -> dict[str, Any]:
    return {
        "extracted": extracted,
        "fact": fact,
        "topic": topic,
        "raw_response": raw_response,
        "confidence": confidence,
        "written": written,
        "skipped_reason": skipped_reason,
    }


def _call_ollama(text: str) -> str | None:
    payload = json.dumps(
        {
            "model": _MODEL,
            "stream": False,
            "prompt": _PROMPT_TEMPLATE.format(text=text.replace('"', '\\"')),
            "options": {"temperature": 0, "seed": 0},
        }
    ).encode("utf-8")
    http_request = request.Request(
        _OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(http_request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    value = body.get("response")
    return str(value) if value is not None else None


def _canonical_fact(value: Any) -> str | None:
    if value is None:
        return None
    fact = str(value).strip()
    if not fact or fact.lower() == "null":
        return None
    if fact[-1] not in ".!?":
        fact = f"{fact}."
    return fact


_THIRD_PARTY_PREFIXES = (
    "my partner",
    "my spouse",
    "my wife",
    "my husband",
    "my friend",
    "my colleague",
    "my boss",
    "my manager",
    "my sister",
    "my brother",
    "my mother",
    "my father",
    "my mom",
    "my dad",
    "my son",
    "my daughter",
    "partner is",
    "partner works",
    "partner has",
)

_OWNS_A_PERSON_NOUNS = (
    "partner",
    "spouse",
    "wife",
    "husband",
    "friend",
    "colleague",
    "boss",
    "manager",
    "sister",
    "brother",
    "mother",
    "father",
    "mom",
    "dad",
    "son",
    "daughter",
)


def _is_third_party_fact(fact: str) -> bool:
    lowered = fact.strip().lower()
    for prefix in _THIRD_PARTY_PREFIXES:
        if lowered.startswith(prefix):
            return True
    for noun in _OWNS_A_PERSON_NOUNS:
        if f"owns a {noun}" in lowered:
            return True
    return False


def _topic_value(value: Any) -> str | None:
    if value is None:
        return None
    topic = str(value).strip()
    if not topic or topic.lower() == "null":
        return None
    return topic


def _strip_markdown_fences(raw_response: str | None) -> str:
    text = (raw_response or "").strip()
    if text.startswith("```json"):
        text = text[len("```json") :]
    elif text.startswith("```"):
        text = text[len("```") :]
    if text.endswith("```"):
        text = text[: -len("```")]
    return text.strip()


def ingest_turn(store, text: str, simulated_date: str | None = None) -> dict:
    """
    Extract at most one persistent fact from a user conversational turn and write
    it to the store.

    Returns a dict with:
    - extracted: bool
    - fact: str | None
    - topic: str | None
    - raw_response: str | None
    - confidence: float
    - written: bool
    - skipped_reason: str | None
    """

    try:
        raw_response = _call_ollama(text)
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        LOGGER.warning("Ollama call failed (%s); turn not ingested.", exc)
        return _result(
            extracted=False,
            fact=None,
            topic=None,
            raw_response=None,
            confidence=0.0,
            written=False,
            skipped_reason="ollama_unavailable",
        )

    try:
        parsed = json.loads(_strip_markdown_fences(raw_response))
    except (TypeError, json.JSONDecodeError):
        LOGGER.warning("Unparseable extraction response; turn not ingested: %r", raw_response)
        return _result(
            extracted=False,
            fact=None,
            topic=None,
            raw_response=raw_response,
            confidence=0.0,
            written=False,
            skipped_reason="parse_error",
        )

    fact = _canonical_fact(parsed.get("fact"))
    topic = _topic_value(parsed.get("topic"))
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    if fact is None:
        return _result(
            extracted=False,
            fact=None,
            topic=topic,
            raw_response=raw_response,
            confidence=confidence,
            written=False,
            skipped_reason="no_fact",
        )

    if _is_third_party_fact(fact):
        return _result(
            extracted=True,
            fact=fact,
            topic=topic,
            raw_response=raw_response,
            confidence=confidence,
            written=False,
            skipped_reason="third_party_fact",
        )

    if confidence < _MIN_CONFIDENCE:
        return _result(
            extracted=True,
            fact=fact,
            topic=topic,
            raw_response=raw_response,
            confidence=confidence,
            written=False,
            skipped_reason="low_confidence",
        )

    effective_date = simulated_date or date.today().isoformat()
    ingest_text(
        store,
        fact,
        metadata={
            "source": "ingest_pipeline",
            "simulated_date": effective_date,
            "topic": topic,
            "original_turn": text,
        },
    )
    return _result(
        extracted=True,
        fact=fact,
        topic=topic,
        raw_response=raw_response,
        confidence=confidence,
        written=True,
        skipped_reason=None,
    )
