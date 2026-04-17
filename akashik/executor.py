"""Deterministic executor for cited answers over retrieved Akashik facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
import re

from akashik.parse_temporal_scope import _parse_question_date
from akashik.query_normalize import normalize_query
from akashik.retrieve import retrieve
from akashik.schema import ExecutorResult, RetrievalResult, SourceCitation
from akashik.temporal_resolver import classify_temporal_query, resolve_two_event_temporal

COMMON_PREFIXES = [
    "I live in ",
    "I moved to ",
    "I am in ",
    "I work at ",
    "I work as ",
    "My name is ",
    "I use ",
    "I drive ",
    "I study at ",
]

_TRAILING_TEMPORAL_RE = re.compile(
    r"\s+(?:today|yesterday|recently|last\s+\w+|this\s+\w+|next\s+\w+)\b.*$",
    re.IGNORECASE,
)
_TEMPORAL_SINGLE_PATTERNS = [
    re.compile(r"\bwhen did i\b|\bwhen was\b", re.IGNORECASE),
    re.compile(r"\bwhat date\b|\bwhat day\b", re.IGNORECASE),
    re.compile(r"\bhow long ago\b|\bhow long have i\b", re.IGNORECASE),
    re.compile(r"\bhow long did\b|\bhow long has\b", re.IGNORECASE),
    re.compile(r"\bwhat year\b|\bwhat month\b", re.IGNORECASE),
    re.compile(r"\bhow recent\b|\bmost recently\b", re.IGNORECASE),
    re.compile(r"\bwhich .* first\b|\bwhat .* first\b", re.IGNORECASE),
    re.compile(r"\bhow many (?:days|weeks|months) before\b|\bhow many (?:days|weeks|months) after\b", re.IGNORECASE),
]
_PREFERENCE_PATTERNS = [
    re.compile(r"\bwhat do i (?:like|prefer|use)\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s| is) my favorite\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+\w[\w\s-]*\s+do i (?:use|prefer)\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+\w[\w\s-]*\s+do i (?:use|prefer|like|rely on)\b", re.IGNORECASE),
    re.compile(r"\bcan you (?:recommend|suggest)\b", re.IGNORECASE),
    re.compile(r"\bwhat kind of\b|\bwhat type of\b", re.IGNORECASE),
]
_AGGREGATION_PATTERNS = [
    re.compile(r"\bhow many times\b", re.IGNORECASE),
    re.compile(r"\bhow often\b", re.IGNORECASE),
    re.compile(r"\bhow frequently\b", re.IGNORECASE),
    re.compile(r"\bhow many\s+\w+\s+did i\b", re.IGNORECASE),
    re.compile(r"\bhow many\b", re.IGNORECASE),
    re.compile(r"\bhow much total\b|\bhow much have i\b|\bhow much did i\b", re.IGNORECASE),
    re.compile(r"\bwhich\s+\w[\w\s-]*\s+did i do most\b", re.IGNORECASE),
    re.compile(r"\bmost frequent\b", re.IGNORECASE),
    re.compile(r"\blist all\b", re.IGNORECASE),
    re.compile(r"\bwhat are all\b", re.IGNORECASE),
    re.compile(r"\bacross our conversations\b|\boverall\b|\bcombining\b", re.IGNORECASE),
]
_FACTUAL_PATTERNS = [
    re.compile(r"\bwhere do i\b|\bwhere did i\b", re.IGNORECASE),
    re.compile(r"\bwhat did i\b|\bwhat did i say\b|\bwhat did i tell\b", re.IGNORECASE),
    re.compile(r"\bwho is my\b|\bwho was my\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s| is) my\b|\bwhat are my\b|\bwhat was my\b", re.IGNORECASE),
    re.compile(r"\btell me about my\b|\bremind me\b|\bcan you remind me\b", re.IGNORECASE),
    re.compile(r"\bdo i have\b|\bdid i have\b", re.IGNORECASE),
    re.compile(r"\bam i\b|\bwas i\b", re.IGNORECASE),
    re.compile(r"\bwhat size\b|\bwhat color\b", re.IGNORECASE),
    re.compile(r"\bhow much do i\b|\bhow much did i\b", re.IGNORECASE),
    re.compile(r"\bwhat is the latest\b|\bmost recent\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s| is) my current\b|\bwhat do i do now\b|\bwhere do i work now\b", re.IGNORECASE),
    re.compile(r"\bhave i changed\b|\bdid i switch\b", re.IGNORECASE),
    re.compile(r"\bbased on what i've told you\b|\bbased on our conversations\b", re.IGNORECASE),
]
_AGGREGATION_MULTI_HINTS = [
    re.compile(r"\btimes\b|\bitems\b|\bprojects\b|\bbooks\b|\bmovies\b|\bexpenses\b|\brestaurants\b|\bweeks\b|\bdays\b|\bmonths\b", re.IGNORECASE),
    re.compile(r"\bacross our conversations\b|\boverall\b|\btotal\b|\ball\b|\bmost\b", re.IGNORECASE),
]
_PREFERENCE_STRENGTH_ORDER = {"strong": 3, "moderate": 2, "weak": 1}


def extract_value(content: str) -> str:
    text = " ".join((content or "").split()).strip()
    for prefix in COMMON_PREFIXES:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :]
            break
    text = _TRAILING_TEMPORAL_RE.sub("", text).rstrip(".,!?").strip()
    return text


def classify_query(question: str) -> str:
    text = " ".join((question or "").split()).strip()
    if not text:
        return "unknown"
    if classify_temporal_query(text) is not None:
        return "temporal"
    if any(pattern.search(text) for pattern in _TEMPORAL_SINGLE_PATTERNS):
        return "temporal"
    if any(pattern.search(text) for pattern in _PREFERENCE_PATTERNS):
        return "preference"
    if any(pattern.search(text) for pattern in _AGGREGATION_PATTERNS) and _has_aggregation_plural_intent(text):
        return "aggregation"
    if any(pattern.search(text) for pattern in _FACTUAL_PATTERNS):
        return "factual"
    return "unknown"


def execute(
    store,
    query: str,
    entity_filters: dict | None = None,
    query_date: str | None = None,
    top_k: int = 10,
    abstention_threshold: float = 0.3,
) -> ExecutorResult:
    answer_type = classify_query(query)
    try:
        if answer_type == "temporal":
            return _execute_temporal(
                store,
                query,
                entity_filters=entity_filters,
                query_date=query_date,
                top_k=top_k,
                abstention_threshold=abstention_threshold,
                answer_type=answer_type,
            )
        if answer_type == "preference":
            return _execute_preference(
                store,
                query,
                entity_filters=entity_filters,
                query_date=query_date,
                top_k=top_k,
                abstention_threshold=abstention_threshold,
                answer_type=answer_type,
            )
        if answer_type == "aggregation":
            return _execute_aggregation(
                store,
                query,
                entity_filters=entity_filters,
                query_date=query_date,
                top_k=max(top_k, 50),
                abstention_threshold=abstention_threshold,
                answer_type=answer_type,
            )
        return _execute_factual(
            store,
            query,
            entity_filters=entity_filters,
            query_date=query_date,
            top_k=top_k,
            abstention_threshold=abstention_threshold,
            answer_type=answer_type,
        )
    except Exception:
        return _abstained_result(
            answer_type=answer_type,
            raw_facts=[],
            requires_reasoning=True,
        )


def _execute_factual(
    store,
    query: str,
    *,
    entity_filters: dict | None,
    query_date: str | None,
    top_k: int,
    abstention_threshold: float,
    answer_type: str,
    requires_reasoning: bool = False,
) -> ExecutorResult:
    response = retrieve(
        query,
        store,
        level="fact",
        limit=top_k,
        entity_filters=entity_filters,
        query_date=query_date,
    )
    results = response.results
    if not results or results[0].confidence < abstention_threshold:
        effective_confidence = _effective_retrieval_confidence(results[0]) if results else 0.0
    else:
        effective_confidence = _effective_retrieval_confidence(results[0])
    if not results or effective_confidence < abstention_threshold:
        return _abstained_result(
            answer_type=answer_type,
            raw_facts=results,
            temporal_answer=response.temporal_answer,
            requires_reasoning=True if answer_type != "factual" else requires_reasoning,
        )

    top_fact = results[0]
    answer = extract_value(top_fact.unit.content)
    if not answer:
        return _abstained_result(
            answer_type=answer_type,
            raw_facts=results,
            temporal_answer=response.temporal_answer,
            requires_reasoning=True if answer_type != "factual" else requires_reasoning,
        )
    confidence = min(
        1.0,
        _effective_retrieval_confidence(top_fact)
        * _recency_weight(top_fact, query_date)
        * math.log1p(max(top_fact.unit.confirmation_count, 1)),
    )
    return ExecutorResult(
        answer=answer,
        answer_type=answer_type,
        answer_confidence=confidence,
        coverage_confidence=confidence,
        requires_reasoning=requires_reasoning,
        abstained=False,
        sources=[_citation_from_result(top_fact)],
        raw_facts=results,
        temporal_answer=response.temporal_answer,
    )


def _execute_temporal(
    store,
    query: str,
    *,
    entity_filters: dict | None,
    query_date: str | None,
    top_k: int,
    abstention_threshold: float,
    answer_type: str,
) -> ExecutorResult:
    response = retrieve(
        query,
        store,
        level="fact",
        limit=top_k,
        entity_filters=entity_filters,
        query_date=query_date,
    )
    results = response.results
    temporal_answer = resolve_two_event_temporal(
        store,
        query,
        entity_filters or {},
        question_date=query_date,
    ) if entity_filters else None
    if temporal_answer is not None:
        sources = _temporal_sources(store, temporal_answer, entity_filters, query_date)
        confidence = min(
            float(temporal_answer["event_a_confidence"]),
            float(temporal_answer["event_b_confidence"]),
        )
        if confidence < abstention_threshold:
            return _abstained_result(
                answer_type=answer_type,
                raw_facts=results,
                temporal_answer=temporal_answer,
                requires_reasoning=False,
            )
        return ExecutorResult(
            answer=f"{temporal_answer['delta']} {temporal_answer['unit']}",
            answer_type=answer_type,
            answer_confidence=confidence,
            coverage_confidence=confidence,
            requires_reasoning=False,
            abstained=False,
            sources=sources,
            raw_facts=results,
            temporal_answer=temporal_answer,
        )
    factual = _execute_factual(
        store,
        query,
        entity_filters=entity_filters,
        query_date=query_date,
        top_k=top_k,
        abstention_threshold=abstention_threshold,
        answer_type=answer_type,
        requires_reasoning=True,
    )
    return factual


def _execute_preference(
    store,
    query: str,
    *,
    entity_filters: dict | None,
    query_date: str | None,
    top_k: int,
    abstention_threshold: float,
    answer_type: str,
) -> ExecutorResult:
    response = retrieve(
        query,
        store,
        level="fact",
        limit=top_k,
        entity_filters=entity_filters,
        query_date=query_date,
    )
    results = response.results
    candidates = _scoped_preference_candidates(store, entity_filters)
    if not candidates:
        return _execute_factual(
            store,
            query,
            entity_filters=entity_filters,
            query_date=query_date,
            top_k=top_k,
            abstention_threshold=abstention_threshold,
            answer_type=answer_type,
            requires_reasoning=True,
        )

    grouped: dict[str, list[RetrievalResult]] = defaultdict(list)
    for result in candidates:
        value = str(result.unit.metadata.get("preference_value", "")).strip()
        if not value:
            continue
        grouped[value].append(result)
    if not grouped:
        return _execute_factual(
            store,
            query,
            entity_filters=entity_filters,
            query_date=query_date,
            top_k=top_k,
            abstention_threshold=abstention_threshold,
            answer_type=answer_type,
            requires_reasoning=True,
        )

    ranked_groups = sorted(
        grouped.items(),
        key=lambda item: (
            -sum(result.unit.confirmation_count for result in item[1]),
            -_date_key(max((result.unit.last_confirmed_at or result.unit.valid_from or "") for result in item[1])),
            -max(_PREFERENCE_STRENGTH_ORDER.get(str(result.unit.metadata.get("preference_strength", "")), 0) for result in item[1]),
            -max(result.confidence for result in item[1]),
            item[0].casefold(),
        ),
    )
    primary_value, primary_group = ranked_groups[0]
    top_fact = max(primary_group, key=lambda result: result.confidence)
    total_confirmations = sum(result.unit.confirmation_count for result in primary_group)
    answer_confidence = min(1.0, _effective_retrieval_confidence(top_fact) * math.log1p(total_confirmations))
    coverage_confidence = min(1.0, math.log1p(len(primary_group)) / 2)
    if answer_confidence < abstention_threshold:
        return _abstained_result(
            answer_type=answer_type,
            raw_facts=results,
            temporal_answer=response.temporal_answer,
            requires_reasoning=True,
        )

    source_results: list[RetrievalResult] = []
    for _value, group in ranked_groups[:3]:
        source_results.append(max(group, key=lambda result: result.confidence))
    return ExecutorResult(
        answer=f"prefers {primary_value}",
        answer_type=answer_type,
        answer_confidence=answer_confidence,
        coverage_confidence=coverage_confidence,
        requires_reasoning=True,
        abstained=False,
        sources=[_citation_from_result(result) for result in source_results],
        raw_facts=results,
        temporal_answer=response.temporal_answer,
    )


def _execute_aggregation(
    store,
    query: str,
    *,
    entity_filters: dict | None,
    query_date: str | None,
    top_k: int,
    abstention_threshold: float,
    answer_type: str,
) -> ExecutorResult:
    response = retrieve(
        query,
        store,
        level="fact",
        limit=top_k,
        entity_filters=entity_filters,
        query_date=query_date,
    )
    results = response.results
    candidates = _scoped_fact_candidates(store, entity_filters)
    matched_candidates = _filter_candidates_for_query(candidates, query)
    lowered = " ".join((query or "").split()).lower()
    answer: str | None = None
    source_results: list[RetrievalResult] = []
    if "how many times" in lowered or re.search(r"\bhow many\s+\w+\s+did i\b", lowered):
        answer = str(len(matched_candidates)) if matched_candidates else None
        source_results = matched_candidates[: min(5, len(matched_candidates))]
    elif "list all" in lowered or "what are all" in lowered:
        values = []
        for result in matched_candidates:
            content = result.unit.content
            if content not in values:
                values.append(content)
        answer = ", ".join(values) if values else None
        source_results = matched_candidates[: min(5, len(matched_candidates))]
    elif re.search(r"\bwhich\b.*\bmost\b", lowered) or "most frequent" in lowered:
        grouped: dict[str, list[RetrievalResult]] = defaultdict(list)
        for result in matched_candidates:
            grouped[result.unit.content].append(result)
        if grouped:
            top_content, top_group = max(
                grouped.items(),
                key=lambda item: (len(item[1]), max(result.confidence for result in item[1])),
            )
            answer = extract_value(top_content)
            source_results = top_group[: min(5, len(top_group))]
    if answer is None:
        return _abstained_result(
            answer_type=answer_type,
            raw_facts=results,
            temporal_answer=response.temporal_answer,
            requires_reasoning=True,
        )

    answer_confidence = 0.6
    coverage_confidence = min(1.0, math.log1p(len(matched_candidates)) / 2) if matched_candidates else 0.0
    if answer_confidence < abstention_threshold:
        return _abstained_result(
            answer_type=answer_type,
            raw_facts=results,
            temporal_answer=response.temporal_answer,
            requires_reasoning=True,
        )
    return ExecutorResult(
        answer=answer,
        answer_type=answer_type,
        answer_confidence=answer_confidence,
        coverage_confidence=coverage_confidence,
        requires_reasoning=True,
        abstained=False,
        sources=[_citation_from_result(result) for result in source_results],
        raw_facts=results,
        temporal_answer=response.temporal_answer,
    )


def _citation_from_result(result: RetrievalResult) -> SourceCitation:
    metadata = result.unit.metadata
    session_id = str(metadata.get("session_id", "")).strip() or None
    session_date = str(metadata.get("session_date", "")).strip() or None
    return SourceCitation(
        fact_id=result.unit.id,
        content=result.unit.content,
        session_id=session_id,
        session_date=session_date,
        confidence=_effective_retrieval_confidence(result),
        confirmed_count=result.unit.confirmation_count,
    )


def _temporal_sources(store, temporal_answer: dict, entity_filters: dict | None, query_date: str | None) -> list[SourceCitation]:
    sources: list[SourceCitation] = []
    for event_key in ("event_a", "event_b"):
        event_query = str(temporal_answer.get(event_key, ""))
        if not event_query:
            continue
        response = retrieve(
            event_query,
            store,
            level="fact",
            limit=1,
            entity_filters=entity_filters,
            query_date=query_date,
            _enable_temporal_resolver=False,
        )
        if response.results:
            sources.append(_citation_from_result(response.results[0]))
    deduped: list[SourceCitation] = []
    seen: set[str] = set()
    for source in sources:
        if source.fact_id in seen:
            continue
        seen.add(source.fact_id)
        deduped.append(source)
    return deduped


def _recency_weight(result: RetrievalResult, query_date: str | None) -> float:
    if not query_date:
        return 1.0
    try:
        query_day = _parse_question_date(query_date)
    except ValueError:
        return 1.0
    candidate_date = result.unit.last_confirmed_at or result.unit.valid_from
    if not candidate_date:
        return 1.0
    try:
        confirmed_day = _parse_question_date(candidate_date)
    except ValueError:
        return 1.0
    days = max((query_day - confirmed_day).days, 0)
    return 1.0 - (0.5 * min(days, 365) / 365.0)


def _abstained_result(
    *,
    answer_type: str,
    raw_facts: list[RetrievalResult],
    temporal_answer: dict | None = None,
    requires_reasoning: bool,
) -> ExecutorResult:
    return ExecutorResult(
        answer=None,
        answer_type=answer_type,
        answer_confidence=0.0,
        coverage_confidence=0.0,
        requires_reasoning=requires_reasoning,
        abstained=True,
        sources=[],
        raw_facts=raw_facts,
        temporal_answer=temporal_answer,
    )


def _date_key(value: str) -> int:
    if not value:
        return 0
    try:
        parsed = _parse_question_date(value)
    except ValueError:
        return 0
    return int(parsed.toordinal())


def _has_aggregation_plural_intent(text: str) -> bool:
    return any(pattern.search(text) for pattern in _AGGREGATION_MULTI_HINTS)


def _effective_retrieval_confidence(result: RetrievalResult) -> float:
    return result.confidence if result.confidence > 0 else 0.8


def _scoped_preference_candidates(store, entity_filters: dict | None) -> list[RetrievalResult]:
    filters = dict(entity_filters or {})
    filters["derived"] = "preference"
    units = [
        unit
        for unit in store.fetch_by_metadata_filters(level="fact", filters=filters)
        if unit.valid_until is None
    ]
    units.sort(
        key=lambda unit: (
            -(unit.confirmation_count),
            -( _date_key(unit.last_confirmed_at or unit.valid_from or "")),
            unit.id,
        )
    )
    return [
        RetrievalResult(unit=unit, confidence=0.8, parent_chain=store.fetch_parent_chain(unit.id))
        for unit in units
    ]


def _scoped_fact_candidates(store, entity_filters: dict | None) -> list[RetrievalResult]:
    filters = dict(entity_filters or {})
    units = [
        unit
        for unit in store.fetch_by_metadata_filters(level="fact", filters=filters or None)
        if unit.valid_until is None
    ]
    return [
        RetrievalResult(unit=unit, confidence=0.8, parent_chain=store.fetch_parent_chain(unit.id))
        for unit in units
    ]


def _filter_candidates_for_query(candidates: list[RetrievalResult], query: str) -> list[RetrievalResult]:
    tokens = {token for token in normalize_query(query).split() if token}
    if not tokens:
        return candidates
    matched: list[RetrievalResult] = []
    for result in candidates:
        content_tokens = set(normalize_query(result.unit.content).split())
        if tokens & content_tokens:
            matched.append(result)
    return matched
