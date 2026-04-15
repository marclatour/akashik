"""Deterministic retrieval pipeline."""

from __future__ import annotations

import json
import re

from akashik.identity import content_hash, normalized_hash
from akashik.query_normalize import normalize_query
from akashik.schema import LEVEL_INDEX, MemoryUnit, RetrievalResponse, RetrievalResult, validate_level

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def retrieve(
    query: str,
    store,
    *,
    level: str | None = None,
    limit: int = 10,
    entity_filter: list[str] | None = None,
) -> RetrievalResponse:
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

    fts_query = normalize_query(text)
    fts_limit = max(limit * 5, 20)
    if entity_filter:
        fts_matches = _search_fts_with_entity_scope(
            store,
            fts_query,
            entity_filter=entity_filter,
            limit=fts_limit,
        )
    else:
        fts_matches = _rerank_fts_matches(store.search_fts(fts_query, limit=fts_limit))
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


def _search_fts_with_entity_scope(
    store,
    query: str,
    *,
    entity_filter: list[str],
    limit: int,
) -> list[MemoryUnit]:
    document_ids = _document_ids_matching_entities(store, entity_filter)
    if not document_ids:
        return []

    tokens = _remove_entity_filter_tokens(_fts_tokens(query), entity_filter)
    fts_query = _build_fts_query(tokens)
    if not fts_query:
        return []

    placeholders = ", ".join("?" for _ in document_ids)
    rows = store._conn.execute(
        f"""
        SELECT fact.id, fact.level, fact.content, fact.content_hash, fact.normalized_hash,
               fact.parent_id, fact.metadata, fact.embedding,
               fact.fts_rowid,
               bm25(memory_units_fts) AS rank
        FROM memory_units_fts
        JOIN memory_units AS fact ON fact.fts_rowid = memory_units_fts.rowid
        JOIN memory_units AS section ON section.id = fact.parent_id
        JOIN memory_units AS document ON document.id = section.parent_id
        WHERE memory_units_fts MATCH ?
          AND fact.level = 'fact'
          AND document.id IN ({placeholders})
        ORDER BY bm25(memory_units_fts), fact.fts_rowid
        LIMIT ?
        """,
        (fts_query, *document_ids, max(limit * 50, 1000)),
    ).fetchall()

    scored_rows = []
    for row in rows:
        coverage = _token_coverage(tokens, row["content"])
        rank = float(row["rank"])
        rank_score = -rank if rank < 0 else 1.0 / (1.0 + rank)
        score = rank_score * coverage
        scored_rows.append((score, coverage, rank, int(row["fts_rowid"]), row))

    scored_rows.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    return [store._row_to_unit(item[-1]) for item in scored_rows[:limit]]


def _document_ids_matching_entities(store, entity_filter: list[str]) -> list[str]:
    filters = {_normalize_entity_filter(value) for value in entity_filter if value.strip()}
    filters.discard("")
    if not filters:
        return []

    rows = store._conn.execute(
        """
        SELECT id, metadata
        FROM memory_units
        WHERE level = 'document'
        ORDER BY fts_rowid
        """
    ).fetchall()
    document_ids: list[str] = []
    for row in rows:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        entity_values = _metadata_entity_values(metadata.get("entities", []))
        if filters & entity_values:
            document_ids.append(row["id"])
    return document_ids


def _metadata_entity_values(entities: object) -> set[str]:
    values: set[str] = set()
    if not isinstance(entities, list):
        return values
    for entity in entities:
        if not isinstance(entity, str):
            continue
        normalized = _normalize_entity_filter(entity)
        if not normalized:
            continue
        values.add(normalized)
        first_token = normalized.split()[0]
        values.add(first_token)
    return values


def _normalize_entity_filter(value: str) -> str:
    return " ".join(_FTS_TOKEN_RE.findall(value.lower()))


def _fts_tokens(query: str) -> list[str]:
    deduped: list[str] = []
    for token in _FTS_TOKEN_RE.findall(query.lower()):
        if token not in deduped:
            deduped.append(token)
    return deduped


def _remove_entity_filter_tokens(tokens: list[str], entity_filter: list[str]) -> list[str]:
    entity_tokens: set[str] = set()
    for entity in entity_filter:
        entity_tokens.update(_fts_tokens(entity))
    scoped_tokens = [token for token in tokens if token not in entity_tokens]
    return scoped_tokens or tokens


def _build_fts_query(tokens: list[str]) -> str:
    return " OR ".join(f'"{token}"' for token in tokens)


def _token_coverage(query_tokens: list[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = set(_FTS_TOKEN_RE.findall(content.lower()))
    matching_tokens = sum(1 for token in query_tokens if token in content_tokens)
    return matching_tokens / len(query_tokens)


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
    by_source: dict[str, list[tuple[float, int, MemoryUnit]]] = {}
    document_scores: dict[str, float] = {}
    source_order: dict[str, int] = {}

    for index, candidate in enumerate(candidates):
        score = 1.0 / (1.0 + (index * 0.1))
        if candidate.level == "fact":
            score += _fact_brevity_bonus(candidate)

        source = candidate.source
        by_source.setdefault(source, []).append((score, index, candidate))
        document_scores[source] = document_scores.get(source, 0.0) + score
        source_order.setdefault(source, index)

    if not by_source:
        return []

    best_source = max(
        document_scores,
        key=lambda source: (document_scores[source], -source_order[source]),
    )
    best_candidates = sorted(by_source[best_source], key=lambda item: (-item[0], item[1]))
    return [candidate for _, _, candidate in best_candidates]


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
