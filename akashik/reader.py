"""Deterministic Reader layer for bounded evidence packets."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class EvidenceFact:
    fact_id: str
    content: str
    source_id: str | None
    session_id: str | None
    timestamp: str | None
    score: float
    normalized_hash: str | None


@dataclass(frozen=True)
class ReaderPacket:
    query: str
    question_type: str | None
    facts: list[EvidenceFact]
    dropped_fact_ids: list[str]
    rationale: list[str]
    context_text: str


@dataclass(frozen=True)
class _PreparedFact:
    evidence: EvidenceFact
    original_index: int
    dedupe_key: tuple[str, str]


def read_context(
    query: str,
    retrieval_results: list,
    *,
    question_type: str | None = None,
    max_facts: int = 12,
    max_chars: int = 6000,
    as_of: str | None = None,
) -> ReaderPacket:
    del as_of  # reserved for future deterministic shaping

    prepared = [
        _prepare_fact(result, index)
        for index, result in enumerate(retrieval_results)
    ]
    deduped, dedupe_dropped, dedupe_rationale = _dedupe_facts(prepared)

    limited = deduped[:max_facts]
    limit_dropped = [item.evidence.fact_id for item in deduped[max_facts:]]
    rationale = list(dedupe_rationale)
    if limit_dropped:
        rationale.append(
            f"Dropped {len(limit_dropped)} facts to enforce max_facts={max_facts}."
        )

    kept: list[EvidenceFact] = []
    char_dropped: list[str] = []
    for item in limited:
        candidate = kept + [item.evidence]
        rendered = _render_context(candidate, max_chars=max_chars)
        if len(rendered) <= max_chars:
            kept.append(item.evidence)
            continue
        char_dropped.append(item.evidence.fact_id)

    if char_dropped:
        rationale.append(
            f"Dropped {len(char_dropped)} facts to enforce max_chars={max_chars}."
        )

    dropped_fact_ids = dedupe_dropped + limit_dropped + char_dropped
    context_text = _render_context(kept, max_chars=max_chars)
    return ReaderPacket(
        query=str(query),
        question_type=question_type,
        facts=kept,
        dropped_fact_ids=dropped_fact_ids,
        rationale=rationale,
        context_text=context_text,
    )


def _prepare_fact(result: Any, index: int) -> _PreparedFact:
    fact_id = _string_or_none(
        _extract_value(result, ("unit", "id"), ("memory_unit", "id"), ("id",), ("fact_id",))
    ) or f"missing-fact-{index + 1}"
    content = _string_or_none(
        _extract_value(
            result,
            ("unit", "content"),
            ("memory_unit", "content"),
            ("content",),
        )
    ) or ""
    metadata = _extract_value(
        result,
        ("unit", "metadata"),
        ("memory_unit", "metadata"),
        ("metadata",),
    )
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    normalized = _string_or_none(
        _extract_value(
            result,
            ("unit", "normalized_hash"),
            ("memory_unit", "normalized_hash"),
            ("normalized_hash",),
        )
    )
    score_value = _extract_value(result, ("score",), ("confidence",))
    try:
        score = float(score_value)
    except (TypeError, ValueError):
        score = 0.0

    evidence = EvidenceFact(
        fact_id=fact_id,
        content=content,
        source_id=_metadata_value(metadata_dict, "source_id", "source"),
        session_id=_metadata_value(metadata_dict, "session_id"),
        timestamp=_metadata_value(
            metadata_dict,
            "timestamp",
            "created_at",
            "simulated_date",
            "session_date",
        ),
        score=score,
        normalized_hash=normalized,
    )
    if normalized:
        dedupe_key = ("hash", normalized)
    else:
        dedupe_key = ("content", _normalize_content(content))
    return _PreparedFact(evidence=evidence, original_index=index, dedupe_key=dedupe_key)


def _dedupe_facts(
    prepared: list[_PreparedFact],
) -> tuple[list[_PreparedFact], list[str], list[str]]:
    kept_by_key: dict[tuple[str, str], _PreparedFact] = {}
    dropped_fact_ids: list[str] = []
    dropped_by_mode: dict[str, int] = {"hash": 0, "content": 0}

    for item in prepared:
        existing = kept_by_key.get(item.dedupe_key)
        if existing is None:
            kept_by_key[item.dedupe_key] = item
            continue
        if _is_better_candidate(item, existing):
            dropped_fact_ids.append(existing.evidence.fact_id)
            dropped_by_mode[item.dedupe_key[0]] += 1
            kept_by_key[item.dedupe_key] = item
        else:
            dropped_fact_ids.append(item.evidence.fact_id)
            dropped_by_mode[item.dedupe_key[0]] += 1

    deduped = sorted(
        kept_by_key.values(),
        key=lambda item: (-item.evidence.score, item.original_index),
    )
    rationale: list[str] = []
    if dropped_by_mode["hash"]:
        rationale.append(
            f"Deduplicated {dropped_by_mode['hash']} facts by normalized_hash."
        )
    if dropped_by_mode["content"]:
        rationale.append(
            f"Deduplicated {dropped_by_mode['content']} facts by normalized content."
        )
    return deduped, dropped_fact_ids, rationale


def _is_better_candidate(candidate: _PreparedFact, existing: _PreparedFact) -> bool:
    if candidate.evidence.score != existing.evidence.score:
        return candidate.evidence.score > existing.evidence.score
    return candidate.original_index < existing.original_index


def _render_context(facts: list[EvidenceFact], *, max_chars: int) -> str:
    text = "Evidence:"
    if not facts:
        return text[:max_chars]
    blocks = [text]
    for index, fact in enumerate(facts, start=1):
        session = fact.session_id or "-"
        timestamp = fact.timestamp or "-"
        blocks.append(
            (
                f"[{index}] fact_id={fact.fact_id} score={fact.score:.4f} "
                f"session={session} time={timestamp}\n"
                f"{fact.content}"
            )
        )
    return "\n\n".join(blocks)


def _extract_value(item: Any, *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current = item
        found = True
        for part in path:
            if isinstance(current, dict):
                if part not in current:
                    found = False
                    break
                current = current[part]
                continue
            if not hasattr(current, part):
                found = False
                break
            current = getattr(current, part)
        if found:
            return current
    return None


def _metadata_value(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        return str(value)
    return None


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _normalize_content(content: str) -> str:
    return " ".join(re.findall(r"\w+", (content or "").lower(), flags=re.UNICODE))
