"""Deterministic retrieval pipeline."""

from __future__ import annotations

import json
import re

from akashik.identity import content_hash, normalized_hash
from akashik.query_normalize import normalize_query
from akashik.schema import LEVEL_INDEX, MemoryUnit, RetrievalResponse, RetrievalResult, validate_level

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_INLINE_HEADING_RE = re.compile(
    r"(?:^|\s)(?:\d+(?:\.\d+)*\.?\s*)?([A-Z][A-Z0-9 '&/,;-]{3,})\."
)
_CLAUSE_SIGNALS = {
    "renewal": {
        "automatic",
        "indefinite",
        "indefinitely",
        "perpetual",
        "renew",
        "renewal",
        "term",
    },
    "notice": {"days", "expiration", "notice", "terminate", "terminated", "written"},
    "governing_law": {
        "applicable",
        "govern",
        "governed",
        "governing",
        "jurisdiction",
        "law",
        "laws",
    },
}
_HEADING_SIGNALS = {
    "renewal": {"duration", "renewal", "term", "termination"},
    "notice": {"expiration", "notice", "notices"},
    "governing_law": {"applicable", "governing", "jurisdiction", "law"},
}
_STRONG_HEADING_FACT_SIGNALS = {
    "renewal": {"automatic", "continue", "continues", "indefinite", "indefinitely", "perpetual", "renew", "renewal"},
    "notice": {"days", "expiration", "notice", "terminate", "terminated", "written"},
    "governing_law": {"applicable", "govern", "governed", "governing", "jurisdiction", "law", "laws"},
}
_DEFINITION_PREFIXES = (
    "the period of",
    "means ",
    "shall mean",
    "defined as",
    "refers to",
    "is defined",
)
_MAX_SCORE_ADJUSTMENT = 0.3


def retrieve(
    query: str,
    store,
    *,
    level: str | None = None,
    limit: int = 10,
    entity_filter: list[str] | None = None,
    clause_type: str | None = None,
    debug_label: str | None = None,
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
            clause_type=clause_type,
            debug_label=debug_label,
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
    clause_type: str | None = None,
    debug_label: str | None = None,
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
               section.id AS section_id,
               section.content AS section_content,
               section.metadata AS section_metadata,
               section.fts_rowid AS section_fts_rowid,
               document.id AS document_id,
               document.metadata AS document_metadata,
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

    details = _scoped_candidate_details(store, rows, tokens, explicit_clause_type=clause_type)
    if not details:
        return []

    by_document: dict[str, list[dict[str, object]]] = {}
    document_scores: dict[str, float] = {}
    document_best_scores: dict[str, float] = {}
    document_best_coverages: dict[str, float] = {}
    document_order: dict[str, int] = {}
    for detail in details:
        document_id = str(detail["document_id"])
        by_document.setdefault(document_id, []).append(detail)
        document_scores[document_id] = document_scores.get(document_id, 0.0) + float(detail["raw_score"])
        document_best_scores[document_id] = max(
            document_best_scores.get(document_id, 0.0),
            float(detail["raw_score"]),
        )
        document_best_coverages[document_id] = max(
            document_best_coverages.get(document_id, 0.0),
            float(detail["coverage"]),
        )
        document_order.setdefault(document_id, int(detail["order"]))

    winning_document = max(
        document_scores,
        key=lambda document_id: (
            document_best_coverages[document_id],
            document_best_scores[document_id],
            document_scores[document_id],
            -document_order[document_id],
        ),
    )
    ranked = _rerank_scoped_fact_candidates(by_document[winning_document])

    if debug_label:
        _print_scoped_debug(
            debug_label,
            query=query,
            entity_filter=entity_filter,
            winning_document=winning_document,
            candidates=ranked,
        )

    return [detail["unit"] for detail in ranked[:limit]]


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


def _scoped_candidate_details(
    store,
    rows,
    query_tokens: list[str],
    *,
    explicit_clause_type: str | None,
) -> list[dict[str, object]]:
    clause_type = _resolve_clause_type(query_tokens, explicit_clause_type)
    details: list[dict[str, object]] = []
    for order, row in enumerate(rows):
        coverage = _token_coverage(query_tokens, row["content"])
        rank = float(row["rank"])
        rank_score = -rank if rank < 0 else 1.0 / (1.0 + rank)
        raw_score = rank_score * coverage
        unit = store._row_to_unit(row)
        section_title = _section_title_for_row(store, row)
        document_metadata = json.loads(row["document_metadata"]) if row["document_metadata"] else {}
        details.append(
            {
                "unit": unit,
                "order": order,
                "raw_score": raw_score,
                "coverage": coverage,
                "rank": rank,
                "fts_rowid": int(row["fts_rowid"]),
                "document_id": row["document_id"],
                "document_source": str(document_metadata.get("source", "")),
                "clause_type": clause_type,
                "section_title": section_title,
            }
        )
    return details


def _rerank_scoped_fact_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered = sorted(
        candidates,
        key=lambda detail: (
            -float(detail["raw_score"]),
            -float(detail["coverage"]),
            float(detail["rank"]),
            int(detail["fts_rowid"]),
        ),
    )
    for index, detail in enumerate(ordered):
        unit = detail["unit"]
        clause_type = detail["clause_type"]
        base_score = max(1.0 - (index * 0.04), 0.0)
        clause_boost = _clause_type_boost(unit.content, clause_type)
        definition_penalty = _definition_penalty(unit.content)
        heading_boost = _section_heading_boost(
            str(detail.get("section_title") or ""),
            clause_type,
            unit.content,
        )
        adjustment = _clamp(clause_boost + definition_penalty + heading_boost)
        detail["base_score"] = base_score
        detail["clause_boost"] = clause_boost
        detail["definition_penalty"] = definition_penalty
        detail["heading_boost"] = heading_boost
        detail["final_score"] = base_score + adjustment

    return sorted(
        ordered,
        key=lambda detail: (
            -float(detail["final_score"]),
            -float(detail["base_score"]),
            -float(detail["clause_boost"]),
            -float(detail["heading_boost"]),
            int(detail["fts_rowid"]),
        ),
    )


def _resolve_clause_type(query_tokens: list[str], explicit_clause_type: str | None) -> str | None:
    if explicit_clause_type in _CLAUSE_SIGNALS:
        return explicit_clause_type

    token_set = set(query_tokens)
    scores = {
        clause_type: len(token_set & signals)
        for clause_type, signals in _CLAUSE_SIGNALS.items()
    }
    best_clause_type = max(scores, key=scores.get)
    return best_clause_type if scores[best_clause_type] > 0 else None


def _clause_type_boost(content: str, clause_type: str | None) -> float:
    if not clause_type:
        return 0.0
    if _is_standalone_heading_fact(content):
        return 0.0
    signals = _CLAUSE_SIGNALS.get(clause_type, set())
    content_tokens = set(_FTS_TOKEN_RE.findall(content.lower()))
    hits = len(content_tokens & signals)
    return min(hits * 0.15, 0.2)


def _definition_penalty(content: str) -> float:
    normalized = " ".join(content.lower().split())
    stripped = _strip_leading_numbering(normalized)
    if _starts_with_definition_prefix(stripped):
        return -0.2

    label_match = re.match(r"^[a-z][a-z\s-]{0,40}:\s+(.*)$", stripped)
    if label_match and _starts_with_definition_prefix(label_match.group(1)):
        return -0.2

    words = stripped.split()
    if not words:
        return 0.0
    for prefix in _DEFINITION_PREFIXES:
        prefix_words = prefix.strip().split()
        if prefix.strip() in stripped and len(prefix_words) / len(words) > 0.4:
            return -0.2
    return 0.0


def _is_standalone_heading_fact(content: str) -> bool:
    text = " ".join(content.split()).strip()
    if len(text) > 80 or len(text.split()) > 8:
        return False
    if not text.endswith("."):
        return False
    return bool(re.match(r"^(?:\d+(?:\.\d+)*\.?\s+)?[A-Za-z][A-Za-z\s&,'/-]+\.$", text))


def _starts_with_definition_prefix(content: str) -> bool:
    return any(content.startswith(prefix) for prefix in _DEFINITION_PREFIXES)


def _strip_leading_numbering(content: str) -> str:
    return re.sub(r"^(?:\(?[a-z]\)|\d+(?:\.\d+)*\.?)\s+", "", content).strip()


def _section_heading_boost(section_title: str, clause_type: str | None, content: str) -> float:
    if not section_title or not clause_type:
        return 0.0
    heading_tokens = set(_FTS_TOKEN_RE.findall(section_title.lower()))
    signals = _HEADING_SIGNALS.get(clause_type, set())
    content_tokens = set(_FTS_TOKEN_RE.findall(content.lower()))
    strong_fact_signals = _STRONG_HEADING_FACT_SIGNALS.get(clause_type, set())
    return 0.15 if heading_tokens & signals and content_tokens & strong_fact_signals else 0.0


def _section_title_for_row(store, row) -> str:
    section_metadata = json.loads(row["section_metadata"]) if row["section_metadata"] else {}
    title = str(section_metadata.get("title", "") or "").strip()
    if title:
        return title

    title = _nearest_inline_heading(row["section_content"], row["content"])
    if title:
        return title

    previous_title = _previous_section_title(
        store,
        document_id=row["document_id"],
        section_fts_rowid=int(row["section_fts_rowid"]),
    )
    return previous_title or ""


def _nearest_inline_heading(section_content: str, fact_content: str) -> str:
    anchor = fact_content[:80]
    position = section_content.find(anchor)
    if position < 0:
        position = section_content.find(fact_content[:40])
    if position < 0:
        return ""

    prefix = section_content[:position]
    matches = list(_INLINE_HEADING_RE.finditer(prefix))
    if not matches:
        return ""
    return _clean_heading(matches[-1].group(1))


def _previous_section_title(store, *, document_id: str, section_fts_rowid: int) -> str:
    rows = store._conn.execute(
        """
        SELECT content, metadata
        FROM memory_units
        WHERE parent_id = ?
          AND level = 'section'
          AND fts_rowid < ?
        ORDER BY fts_rowid DESC
        LIMIT 6
        """,
        (document_id, section_fts_rowid),
    ).fetchall()
    for row in rows:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        metadata_title = str(metadata.get("title", "") or "").strip()
        if metadata_title:
            return metadata_title
        title = _standalone_section_title(row["content"])
        if title:
            return title
    return ""


def _standalone_section_title(content: str) -> str:
    text = " ".join(content.split())
    if len(text) > 90 or len(text.split()) > 9:
        return ""
    if not re.search(r"[A-Za-z]", text):
        return ""
    return _clean_heading(text)


def _clean_heading(text: str) -> str:
    cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", text.strip())
    return cleaned.strip(" .;:-")


def _clamp(value: float) -> float:
    return max(min(value, _MAX_SCORE_ADJUSTMENT), -_MAX_SCORE_ADJUSTMENT)


def _print_scoped_debug(
    label: str,
    *,
    query: str,
    entity_filter: list[str],
    winning_document: str,
    candidates: list[dict[str, object]],
) -> None:
    source = ""
    if candidates:
        source = str(candidates[0].get("document_source") or candidates[0]["unit"].source)
    print(f"\n[Akashik scoped debug] {label}")
    print(f"normalized query used: {query}")
    print(f"entity_filter applied: {entity_filter}")
    print(f"winning document selected: {source or winning_document}")
    print("top 5 fact candidates:")
    for index, detail in enumerate(candidates[:5], start=1):
        unit = detail["unit"]
        print(
            "  {index}. content={content!r} base={base:.4f} clause_boost={clause:.4f} "
            "definition_penalty={definition:.4f} heading_boost={heading:.4f} "
            "final={final:.4f} section_title={title!r}".format(
                index=index,
                content=_compact_for_debug(unit.content, limit=80),
                base=float(detail["base_score"]),
                clause=float(detail["clause_boost"]),
                definition=float(detail["definition_penalty"]),
                heading=float(detail["heading_boost"]),
                final=float(detail["final_score"]),
                title=detail.get("section_title") or "",
            )
        )
    if candidates:
        selected = candidates[0]
        print(
            "selected fact: {content!r} because it has the highest final score "
            "after bounded in-document reranking.".format(
                content=_compact_for_debug(selected["unit"].content, limit=120)
            )
        )


def _compact_for_debug(text: str, *, limit: int) -> str:
    compacted = re.sub(r"\s+", " ", text).strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3] + "..."


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
