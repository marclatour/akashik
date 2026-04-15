"""Deterministic retrieval pipeline."""

from __future__ import annotations

from akashik.identity import content_hash, normalized_hash
from akashik.schema import LEVEL_INDEX, MemoryUnit, RetrievalResponse, RetrievalResult, validate_level


def retrieve(query: str, store, *, level: str | None = None, limit: int = 10) -> RetrievalResponse:
    text = query.strip()
    if not text:
        return RetrievalResponse(results=[], confidence=0.0)

    if level is not None:
        validate_level(level)

    exact_matches = store.fetch_by_content_hash(content_hash(text))
    response = _build_response(exact_matches, store, level=level, limit=limit, base_confidence=1.0)
    if response.results:
        return response

    normalized_matches = store.fetch_by_normalized_hash(normalized_hash(text))
    response = _build_response(
        normalized_matches,
        store,
        level=level,
        limit=limit,
        base_confidence=0.95,
    )
    if response.results:
        return response

    fts_matches = _rerank_fts_matches(store.search_fts(text, limit=max(limit * 5, 20)))
    response = _build_response(
        fts_matches,
        store,
        level=level,
        limit=limit,
        base_confidence=0.8,
        decay=0.05,
    )
    if response.results:
        return response

    return RetrievalResponse(results=[], confidence=0.0)


def _build_response(
    candidates: list[MemoryUnit],
    store,
    *,
    level: str | None,
    limit: int,
    base_confidence: float,
    decay: float = 0.01,
) -> RetrievalResponse:
    resolved_units = _resolve_candidates(candidates, store, level=level)
    results: list[RetrievalResult] = []
    for index, unit in enumerate(resolved_units[:limit]):
        confidence = max(base_confidence - (index * decay), 0.0)
        results.append(
            RetrievalResult(
                unit=unit,
                confidence=round(confidence, 3),
                parent_chain=store.fetch_parent_chain(unit.id),
            )
        )
    top_confidence = results[0].confidence if results else 0.0
    return RetrievalResponse(results=results, confidence=top_confidence)


def _rerank_fts_matches(candidates: list[MemoryUnit]) -> list[MemoryUnit]:
    scored_candidates: list[tuple[float, int, MemoryUnit]] = []
    for index, candidate in enumerate(candidates):
        score = 1.0 - (index * 0.001)
        if candidate.level == "fact":
            score += _fact_brevity_bonus(candidate)
        scored_candidates.append((score, index, candidate))

    scored_candidates.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, _, candidate in scored_candidates]


def _fact_brevity_bonus(candidate: MemoryUnit) -> float:
    token_count = len(candidate.content.split())
    if token_count == 0:
        return 0.0
    return (1.0 / token_count) * 0.5


def _resolve_candidates(candidates: list[MemoryUnit], store, *, level: str | None) -> list[MemoryUnit]:
    if not candidates:
        return []
    if level is None:
        return _dedupe_units(candidates)

    direct = [candidate for candidate in candidates if candidate.level == level]
    to_resolve = direct or candidates

    resolved: list[MemoryUnit] = []
    for candidate in to_resolve:
        resolved.extend(_project_candidate(candidate, store, target_level=level))
    return _dedupe_units(resolved)


def _project_candidate(candidate: MemoryUnit, store, *, target_level: str) -> list[MemoryUnit]:
    if candidate.level == target_level:
        return [candidate]

    candidate_depth = LEVEL_INDEX[candidate.level]
    target_depth = LEVEL_INDEX[target_level]

    if candidate_depth > target_depth:
        for ancestor in store.fetch_parent_chain(candidate.id):
            if ancestor.level == target_level:
                return [ancestor]
        return []

    return store.fetch_descendants_at_level(candidate.id, target_level)


def _dedupe_units(units: list[MemoryUnit]) -> list[MemoryUnit]:
    seen: set[str] = set()
    deduped: list[MemoryUnit] = []
    for unit in units:
        if unit.id in seen:
            continue
        seen.add(unit.id)
        deduped.append(unit)
    return deduped
