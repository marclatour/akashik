"""Deterministic retrieval pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
import re

from akashik.expression import express, extract_context
from akashik.identity import content_hash, normalized_hash
from akashik.navigator import rank_facts
from akashik.parse_temporal_scope import _parse_question_date
from akashik.query_normalize import normalize_query
from akashik.semantic import SemanticRanker
from akashik.schema import LEVEL_INDEX, MemoryUnit, RetrievalResponse, RetrievalResult, validate_level
from akashik.temporal_resolver import resolve_two_event_temporal

LOGGER = logging.getLogger(__name__)
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
_SEMANTIC_RANKER = SemanticRanker()
_SEMANTIC_FALLBACK_THRESHOLD = _SEMANTIC_RANKER.config.confidence_threshold
_FACT_METADATA_ONLY_KEYS = {"speaker", "has_answer"}


def retrieve(
    query: str,
    store,
    *,
    level: str | None = None,
    limit: int = 10,
    entity_filter: list[str] | None = None,
    entity_filters: dict[str, str | list[str]] | None = None,
    clause_type: str | None = None,
    debug_label: str | None = None,
    metadata: dict | None = None,
    use_navigator: bool = True,
    use_semantic: bool = True,
    use_expression: bool = False,
    document_gate_n: int = 0,
    as_of: str | None = None,
    query_date: str | None = None,
    _enable_temporal_resolver: bool = True,
) -> RetrievalResponse:
    text = query.strip()
    if not text:
        return RetrievalResponse(results=[], confidence=0.0)

    if level is not None:
        validate_level(level)

    if use_expression:
        context = extract_context(text, metadata=metadata)
        expressed = express(store, text, context=context)
        if expressed:
            LOGGER.debug("Expression engine: returned %s facts, skipping retrieval stack", len(expressed))
            response = _build_response(
                expressed,
                store,
                level=level,
                limit=limit,
                base_confidence=1.0,
            )
            return _finalize_response(store, response)
        LOGGER.debug("Expression engine: fell through to retrieval stack")
    else:
        setattr(
            store,
            "_last_expression_stats",
            {
                "candidate_pool": 0,
                "above_threshold": 0,
                "expressed": 0,
                "bypassed_retrieval": False,
            },
        )

    valid_at = _normalize_as_of(as_of)
    parsed_query_date = _normalize_query_date(query_date)
    temporal_answer = None
    if (
        _enable_temporal_resolver
        and entity_filters
        and "instance_id" in entity_filters
    ):
        temporal_answer = resolve_two_event_temporal(
            store,
            text,
            entity_filters,
            question_date=query_date,
        )
    exact_matches = store.fetch_by_content_hash(
        content_hash(text),
        current_only=valid_at is None,
        as_of=valid_at,
    )
    response = _build_response(
        exact_matches,
        store,
        level=level,
        limit=limit,
        base_confidence=1.0,
        temporal_answer=temporal_answer,
    )
    if response.results:
        return _finalize_response(store, response)

    normalized_matches = store.fetch_by_normalized_hash(
        normalized_hash(text),
        current_only=valid_at is None,
        as_of=valid_at,
    )
    response = _build_response(
        normalized_matches,
        store,
        level=level,
        limit=limit,
        base_confidence=0.95,
        temporal_answer=temporal_answer,
    )
    if response.results:
        return _finalize_response(store, response)

    fts_query = normalize_query(text)
    fts_limit = max(limit * 5, 20)
    if entity_filter or entity_filters:
        fts_matches, scoped_confidence = _search_fts_with_entity_scope(
            store,
            fts_query,
            entity_filter=entity_filter,
            entity_filters=entity_filters,
            limit=fts_limit,
            clause_type=clause_type,
            debug_label=debug_label,
            use_navigator=use_navigator,
            use_semantic=use_semantic,
            document_gate_n=document_gate_n,
            as_of=valid_at,
            query_date=parsed_query_date,
        )
    else:
        fts_matches = _rerank_fts_matches(
            store.search_fts(
                fts_query,
                limit=fts_limit,
                current_only=valid_at is None,
                as_of=valid_at,
            )
        )
        scoped_confidence = 0.8
    response = _build_response(
        fts_matches,
        store,
        level=level,
        limit=limit,
        base_confidence=scoped_confidence,
        decay=0.05,
        temporal_answer=temporal_answer,
    )
    if response.results:
        return _finalize_response(store, response)

    return RetrievalResponse(results=[], confidence=0.0, temporal_answer=temporal_answer)


def _search_fts_with_entity_scope(
    store,
    query: str,
    *,
    entity_filter: list[str] | None,
    entity_filters: dict[str, str | list[str]] | None,
    limit: int,
    clause_type: str | None = None,
    debug_label: str | None = None,
    use_navigator: bool = True,
    use_semantic: bool = True,
    document_gate_n: int = 0,
    as_of: str | None = None,
    query_date=None,
) -> tuple[list[MemoryUnit], float]:
    document_scope_filters, fact_scope_filters = _split_entity_filters(entity_filters or {})
    document_ids = _document_ids_for_scope(
        store,
        entity_filter=entity_filter,
        entity_filters=document_scope_filters,
    )
    if not document_ids:
        return ([], 0.0)

    scoped_entity_filters = dict(document_scope_filters)
    if document_gate_n > 0:
        gated_document_ids = _score_documents_for_scope(
            store,
            query,
            document_ids=document_ids,
            top_n=document_gate_n,
            current_only=as_of is None,
            as_of=as_of,
        )
        LOGGER.debug(
            "document gate: %s docs passing gate (gate_n=%s)",
            len(gated_document_ids),
            document_gate_n,
        )
        if gated_document_ids:
            gated_session_ids = _document_ids_to_session_ids(store, gated_document_ids)
            if gated_session_ids:
                scoped_entity_filters["session_id"] = gated_session_ids
                LOGGER.debug(
                    "document gate: restricted to session_ids %s",
                    gated_session_ids,
                )
                document_ids = _document_ids_for_scope(
                    store,
                    entity_filter=entity_filter,
                    entity_filters=scoped_entity_filters,
                )
            else:
                LOGGER.debug("document gate: no session_ids resolved — fail-open")
        else:
            LOGGER.debug("document gate: empty result — fail-open, using full instance scope")

    tokens = _remove_entity_filter_tokens(_fts_tokens(query), entity_filter or [])
    fts_query = _build_fts_query(tokens)
    if not fts_query:
        return ([], 0.0)

    validity_sql, validity_params = _validity_sql(alias="fact", current_only=as_of is None, as_of=as_of)

    placeholders = ", ".join("?" for _ in document_ids)
    rows = store._conn.execute(
        f"""
        SELECT fact.id, fact.level, fact.content, fact.content_hash, fact.normalized_hash,
               fact.lineage_parent_id, fact.parent_id, fact.metadata, fact.embedding,
               fact.section_heading,
               fact.valid_from, fact.valid_until,
               fact.fts_rowid,
               section.id AS section_id,
               section.content AS section_content,
               section.section_heading AS section_heading,
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
          {validity_sql}
          {_fact_filter_sql(fact_scope_filters)}
        ORDER BY bm25(memory_units_fts), fact.fts_rowid
        LIMIT ?
        """,
        (
            fts_query,
            *document_ids,
            *validity_params,
            *_fact_filter_params(fact_scope_filters),
            max(limit * 50, 1000),
        ),
    ).fetchall()

    details = _scoped_candidate_details(store, rows, tokens, explicit_clause_type=clause_type)
    if not details:
        return ([], 0.0)

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
    ranked = _apply_navigator_tiebreak(
        ranked,
        query,
        use_navigator=use_navigator,
        query_date=query_date,
    )
    ranked = _apply_semantic_fallback(ranked, query, use_semantic=use_semantic)

    if debug_label:
        _print_scoped_debug(
            debug_label,
            query=query,
            entity_filter=entity_filter,
            winning_document=winning_document,
            candidates=ranked,
        )

    return ([detail["unit"] for detail in ranked[:limit]], _scoped_result_confidence(ranked))


def score_documents(
    store,
    query: str,
    entity_filters: dict[str, str | list[str]] | None,
    top_n: int = 5,
    *,
    current_only: bool = True,
    as_of: str | None = None,
) -> list[str]:
    document_scope_filters, _fact_scope_filters = _split_entity_filters(entity_filters or {})
    document_ids = _document_ids_for_scope(store, entity_filter=None, entity_filters=document_scope_filters)
    if not document_ids:
        LOGGER.debug("score_documents: 0 documents scored, top-%s: []", top_n)
        return []
    return _score_documents_for_scope(
        store,
        query,
        document_ids=document_ids,
        top_n=top_n,
        current_only=current_only,
        as_of=as_of,
    )


def _score_documents_for_scope(
    store,
    query: str,
    *,
    document_ids: list[str],
    top_n: int,
    current_only: bool = True,
    as_of: str | None = None,
) -> list[str]:
    tokens = _fts_tokens(query)
    fts_query = _build_fts_query(tokens)
    if not fts_query or not document_ids:
        LOGGER.debug("score_documents: 0 documents scored, top-%s: []", top_n)
        return []

    validity_sql, validity_params = _validity_sql(
        alias="fact",
        current_only=current_only,
        as_of=as_of,
    )

    placeholders = ", ".join("?" for _ in document_ids)
    rows = store._conn.execute(
        f"""
        SELECT document.id AS document_id,
               fact.content AS content,
               fact.fts_rowid AS fact_fts_rowid,
               bm25(memory_units_fts) AS rank
        FROM memory_units_fts
        JOIN memory_units AS fact ON fact.fts_rowid = memory_units_fts.rowid
        JOIN memory_units AS section ON section.id = fact.parent_id
        JOIN memory_units AS document ON document.id = section.parent_id
        WHERE memory_units_fts MATCH ?
          AND fact.level = 'fact'
          AND document.id IN ({placeholders})
          {validity_sql}
        ORDER BY bm25(memory_units_fts), fact.fts_rowid
        LIMIT ?
        """,
        (fts_query, *document_ids, *validity_params, max(top_n * 50, 1000)),
    ).fetchall()

    document_scores: dict[str, float] = {}
    document_order: dict[str, int] = {}
    for row in rows:
        rank = float(row["rank"])
        rank_score = -rank if rank < 0 else 1.0 / (1.0 + rank)
        coverage = _token_coverage(tokens, row["content"])
        score = rank_score * coverage
        document_id = str(row["document_id"])
        document_scores[document_id] = max(document_scores.get(document_id, 0.0), score)
        document_order.setdefault(document_id, int(row["fact_fts_rowid"]))

    ranked_document_ids = [
        document_id
        for document_id, _score in sorted(
            document_scores.items(),
            key=lambda item: (-item[1], document_order[item[0]]),
        )[:top_n]
    ]
    LOGGER.debug(
        "score_documents: %s documents scored, top-%s: %s",
        len(document_scores),
        top_n,
        ranked_document_ids[:top_n],
    )
    return ranked_document_ids


def _document_ids_for_scope(
    store,
    *,
    entity_filter: list[str] | None,
    entity_filters: dict[str, str | list[str]] | None,
) -> list[str]:
    list_ids = _document_ids_matching_entities(store, entity_filter or [])
    map_ids = _document_ids_matching_filter_map(store, entity_filters or {})
    if entity_filter and entity_filters:
        return [document_id for document_id in list_ids if document_id in set(map_ids)]
    if entity_filter:
        return list_ids
    if entity_filters:
        return map_ids
    rows = store._conn.execute(
        "SELECT id FROM memory_units WHERE level = 'document' ORDER BY fts_rowid"
    ).fetchall()
    return [str(row["id"]) for row in rows]


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
        if filters <= entity_values:
            document_ids.append(row["id"])
    return document_ids


def _document_ids_matching_filter_map(
    store,
    entity_filters: dict[str, str | list[str]],
) -> list[str]:
    if not entity_filters:
        return []
    documents = store.fetch_by_metadata_filters(level="document", filters=entity_filters)
    return [document.id for document in documents]


def _split_entity_filters(
    entity_filters: dict[str, str | list[str]],
) -> tuple[dict[str, str | list[str]], dict[str, str | list[str]]]:
    document_filters: dict[str, str | list[str]] = {}
    fact_filters: dict[str, str | list[str]] = {}
    for key, value in entity_filters.items():
        if key in _FACT_METADATA_ONLY_KEYS:
            fact_filters[key] = value
        else:
            document_filters[key] = value
    return document_filters, fact_filters


def _fact_filter_sql(filters: dict[str, str | list[str]]) -> str:
    clauses: list[str] = []
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, list):
            values = [item for item in value if item not in (None, "")]
            if not values:
                clauses.append("AND 1 = 0")
                continue
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"AND json_extract(fact.metadata, ?) IN ({placeholders})")
            continue
        clauses.append("AND json_extract(fact.metadata, ?) = ?")
    return "\n          ".join(clauses)


def _fact_filter_params(filters: dict[str, str | list[str]]) -> list[object]:
    params: list[object] = []
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, list):
            values = [item for item in value if item not in (None, "")]
            if not values:
                continue
            params.append(f"$.{key}")
            params.extend(values)
            continue
        params.append(f"$.{key}")
        params.append(value)
    return params


def _document_ids_to_session_ids(store, document_ids: list[str]) -> list[str]:
    session_ids: list[str] = []
    for document_id in document_ids:
        document = store.fetch_by_id(document_id)
        if document is None:
            LOGGER.debug("document gate: UUID %s not found in store, skipping", document_id)
            continue
        session_id = str(document.metadata.get("session_id", "")).strip()
        if not session_id:
            LOGGER.debug("document gate: UUID %s has no session_id, skipping", document_id)
            continue
        if session_id in session_ids:
            continue
        session_ids.append(session_id)
    return session_ids


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


def _normalize_as_of(as_of: str | None) -> str | None:
    if not as_of:
        return None
    return _parse_question_date(as_of).isoformat()


def _normalize_query_date(query_date: str | None):
    if not query_date:
        return None
    return _parse_question_date(query_date)


def _validity_sql(
    *,
    alias: str,
    current_only: bool,
    as_of: str | None,
) -> tuple[str, list[object]]:
    if as_of:
        return (
            f"AND (({alias}.valid_from IS NULL OR {alias}.valid_from <= ?) AND ({alias}.valid_until IS NULL OR {alias}.valid_until > ?))",
            [as_of, as_of],
        )
    if current_only:
        return (f"AND {alias}.valid_until IS NULL", [])
    return ("", [])


def _scoped_result_confidence(candidates: list[dict[str, object]]) -> float:
    if not candidates:
        return 0.0
    raw_score = float(candidates[0].get("raw_score", 0.0))
    return round(min(0.8, max(0.0, raw_score)), 3)


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
    title = str(row["section_heading"] or "").strip()
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
        SELECT content, section_heading
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
        section_heading = str(row["section_heading"] or "").strip()
        if section_heading:
            return section_heading
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
    temporal_answer: dict | None = None,
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
    return RetrievalResponse(results=results, confidence=top_confidence, temporal_answer=temporal_answer)


def _finalize_response(store, response: RetrievalResponse) -> RetrievalResponse:
    fact_ids = _returned_fact_ids(response)
    if not fact_ids:
        return response
    with store.transaction():
        update_activation_on_retrieval(store, fact_ids)
        if len(fact_ids) > 1:
            update_association_edges(store, fact_ids)
    return response


def _returned_fact_ids(response: RetrievalResponse) -> list[str]:
    seen: set[str] = set()
    fact_ids: list[str] = []
    for result in response.results:
        if result.unit.level != "fact":
            continue
        if result.unit.id in seen:
            continue
        seen.add(result.unit.id)
        fact_ids.append(result.unit.id)
    return fact_ids


def update_activation_on_retrieval(store, fact_ids: list[str]) -> None:
    now = datetime.now(UTC).isoformat()
    store.executemany(
        """
        UPDATE epigenetic_state
        SET activation_weight = MIN(
                activation_weight + (0.1 * (1.0 - activation_weight / 10.0)),
                10.0),
            soft_reinforcement_count = soft_reinforcement_count + 1,
            last_expressed_at = ?
        WHERE fact_id = ?
        """,
        [(now, fact_id) for fact_id in fact_ids],
    )
    # NOTE: decay_rate exists but decay is not applied in v0.20.0-alpha.
    # Decay will be applied lazily on read or via background worker later.


def update_association_edges(store, fact_ids: list[str], weight_increment: float = 0.1) -> None:
    fact_ids = fact_ids[:20]
    for index, fact_id_a in enumerate(fact_ids):
        for fact_id_b in fact_ids[index + 1 :]:
            _increment_edge(store, fact_id_a, fact_id_b, weight_increment)
            _increment_edge(store, fact_id_b, fact_id_a, weight_increment)
    # NOTE: JSON association_edges are a temporary storage format.
    # A dedicated edge table is the long-term design.


def _increment_edge(store, source_fact_id: str, target_fact_id: str, weight_increment: float) -> None:
    row = store.execute(
        "SELECT association_edges FROM epigenetic_state WHERE fact_id = ?",
        (source_fact_id,),
    ).fetchone()
    edges = _parse_association_edges(row["association_edges"] if row else None)
    for edge in edges:
        if edge["fact_id"] == target_fact_id:
            edge["weight"] = min(float(edge["weight"]) + weight_increment, 5.0)
            break
    else:
        edges.append({"fact_id": target_fact_id, "weight": min(weight_increment, 5.0)})
    trimmed_edges = sorted(
        edges,
        key=lambda edge: (-float(edge["weight"]), str(edge["fact_id"])),
    )[:50]
    store.execute(
        "UPDATE epigenetic_state SET association_edges = ? WHERE fact_id = ?",
        (json.dumps(trimmed_edges, sort_keys=True), source_fact_id),
    )


def _parse_association_edges(raw_edges: str | None) -> list[dict[str, object]]:
    if not raw_edges:
        return []
    try:
        parsed = json.loads(raw_edges)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    edges: list[dict[str, object]] = []
    for edge in parsed:
        if not isinstance(edge, dict):
            continue
        fact_id = edge.get("fact_id")
        weight = edge.get("weight")
        if not isinstance(fact_id, str):
            continue
        try:
            numeric_weight = float(weight)
        except (TypeError, ValueError):
            continue
        edges.append({"fact_id": fact_id, "weight": min(max(numeric_weight, 0.0), 5.0)})
    return edges


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


def _apply_navigator_tiebreak(
    candidates: list[dict[str, object]],
    query: str,
    *,
    use_navigator: bool,
    query_date=None,
) -> list[dict[str, object]]:
    if not use_navigator:
        return candidates
    if len(candidates) < 2:
        return candidates
    top_score = float(candidates[0]["final_score"])
    second_score = float(candidates[1]["final_score"])
    if top_score - second_score > 0.02:
        return candidates

    tied_candidates: list[dict[str, object]] = []
    remainder_start = 0
    for index, candidate in enumerate(candidates):
        if top_score - float(candidate["final_score"]) <= 0.02:
            tied_candidates.append(candidate)
            remainder_start = index + 1
            continue
        break
    if len(tied_candidates) < 2:
        return candidates

    facts = [candidate["unit"] for candidate in tied_candidates]
    try:
        ranked_pairs = rank_facts(facts, query, query_date=query_date)
    except TypeError:
        ranked_pairs = rank_facts(facts, query)
    ranked_facts = [fact for fact, _score in ranked_pairs]
    ranked_by_id = {fact.id: index for index, fact in enumerate(ranked_facts)}
    reranked_ties = sorted(
        tied_candidates,
        key=lambda candidate: ranked_by_id.get(candidate["unit"].id, len(ranked_by_id)),
    )
    return reranked_ties + candidates[remainder_start:]


def _apply_semantic_fallback(
    candidates: list[dict[str, object]],
    query: str,
    *,
    use_semantic: bool,
) -> list[dict[str, object]]:
    if not use_semantic:
        return candidates
    if not candidates:
        return candidates

    current_confidence = float(candidates[0].get("final_score", 0.0))
    facts = [candidate["unit"] for candidate in candidates]
    reranked = _SEMANTIC_RANKER.rerank(query, facts, current_confidence=current_confidence)
    if len(reranked) != len(candidates):
        return candidates

    candidate_by_id = {candidate["unit"].id: candidate for candidate in candidates}
    return [candidate_by_id[fact.id] for fact in reranked if fact.id in candidate_by_id]


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
