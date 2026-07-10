"""Expression helpers — Addressed Cognition v0.20.x."""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC, datetime

from akashik.ingest import MIN_TOKEN_LENGTH
from akashik.query_normalize import normalize_query
from akashik.schema import MemoryUnit

TIER_DECAY_RATES = {
    "episodic": 0.01,
    "semantic": 0.005,
    "procedural": 0.001,
}
MAX_RAW_CANDIDATES = 1000
EXPRESSION_THRESHOLD = float(os.getenv("AKASHIK_EXPRESSION_THRESHOLD", "2.0"))
MAX_EXPRESSED_FACTS = int(os.getenv("AKASHIK_MAX_EXPRESSED_FACTS", "20"))
MAX_CANDIDATE_POOL = 150
MIN_CONTEXT_TERMS = 2

LOGGER = logging.getLogger(__name__)


def decay_rate_for_tier(tier: str) -> float:
    return TIER_DECAY_RATES.get(tier, 0.01)


def apply_decay(
    activation_weight: float,
    decay_rate: float,
    last_expressed_at: str | None,
) -> float:
    """
    Applies exponential decay to activation weight based on days
    elapsed since last expression. Returns decayed weight.
    Decay is lazy — applied on read, not on a timer.
    """
    if last_expressed_at is None:
        return activation_weight
    parsed = datetime.fromisoformat(last_expressed_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    elapsed_days = max((datetime.now(UTC) - parsed).total_seconds() / 86400, 0.0)
    decayed = activation_weight * math.exp(-decay_rate * elapsed_days)
    return max(decayed, 0.0)


def get_effective_activation(store, fact_id: str) -> float:
    """
    Returns the effective activation weight for a fact,
    with lazy decay applied. Does not write to the database.
    """
    rows = get_effective_activations(store, [fact_id])
    return rows.get(fact_id, 0.0)


def get_effective_activations(store, fact_ids: list[str]) -> dict[str, float]:
    """
    Returns effective activation weights for a list of facts.
    Applies lazy decay to each. Does not write to the database.
    """
    if not fact_ids:
        return {}
    placeholders = ", ".join("?" for _ in fact_ids)
    rows = store.execute(
        f"""
        SELECT fact_id, activation_weight, decay_rate, last_expressed_at
        FROM epigenetic_state
        WHERE fact_id IN ({placeholders})
        """,
        tuple(fact_ids),
    ).fetchall()
    return {
        str(row["fact_id"]): apply_decay(
            float(row["activation_weight"] or 0.0),
            float(row["decay_rate"] or 0.0),
            row["last_expressed_at"],
        )
        for row in rows
    }


def get_candidate_pool(store, context: dict, limit: int = 200) -> list[str]:
    """
    Returns a bounded list of fact_ids whose context index entries
    match the current context (entities, topics, domain, thread).
    Used by the expression engine to build the candidate set
    without a full corpus scan.

    Returns empty list when context is empty or no index matches found.
    Empty pool signals the expression engine to fall through to the
    existing retrieval stack. This is the expected behavior in v0.20.1
    since context extraction is naive — future versions will improve
    query-to-context mapping.
    TODO: context extraction from query text is not implemented in v0.20.1.
    Caller is responsible for providing context dict. Automatic extraction
    will be added in v0.20.2.
    """
    if not context:
        return []

    candidates: dict[str, tuple[float, str]] = {}
    for index_type, values in _context_filters(context).items():
        if not values:
            continue
        placeholders = ", ".join("?" for _ in values)
        rows = store.execute(
            f"""
            SELECT DISTINCT fci.fact_id, es.activation_weight, es.last_expressed_at
            FROM fact_context_index AS fci
            JOIN epigenetic_state AS es ON es.fact_id = fci.fact_id
            WHERE fci.index_type = ? AND fci.index_value IN ({placeholders})
            ORDER BY es.activation_weight DESC, es.last_expressed_at DESC
            LIMIT ?
            """,
            (index_type, *values, MAX_RAW_CANDIDATES),
        ).fetchall()
        for row in rows[:MAX_RAW_CANDIDATES]:
            fact_id = str(row["fact_id"])
            activation = float(row["activation_weight"] or 0.0)
            last_expressed = str(row["last_expressed_at"] or "")
            existing = candidates.get(fact_id)
            if existing is None or (activation, last_expressed) > existing:
                candidates[fact_id] = (activation, last_expressed)

    ranked = sorted(
        candidates.items(),
        key=lambda item: (item[1][0], item[1][1]),
        reverse=True,
    )
    return [fact_id for fact_id, _ in ranked[:limit]]


def _context_filters(context: dict) -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}
    plural_map = {"entities": "entity", "topics": "topic"}
    for key in ("entities", "topics"):
        value = context.get(key, [])
        if isinstance(value, list):
            filters[plural_map[key]] = [
                normalized
                for item in value
                for normalized in [_normalize_index_value(str(item))]
                if normalized
            ]
    for key in ("domain", "thread"):
        value = context.get(key)
        if value is None:
            continue
        normalized = _normalize_index_value(str(value))
        if normalized:
            filters[key] = [normalized]
    return filters


def _normalize_index_value(value: str) -> str:
    normalized = normalize_query(value)
    if normalized:
        return normalized
    return " ".join(value.lower().split())


def extract_context(query: str, metadata: dict | None = None) -> dict:
    """
    Extracts a context dict from a query string.
    Deterministic, no LLM, no embeddings.
    Symmetric with ingest-time fact_context_index population.
    """
    normalized = normalize_query(query)
    tokens = [token for token in normalized.split() if len(token) >= MIN_TOKEN_LENGTH]
    metadata = dict(metadata or {})
    entities = [_normalize_index_value(str(item)) for item in metadata.get("entities", []) if str(item).strip()]
    domain_value = metadata.get("domain", [])
    thread_value = metadata.get("thread", [])
    domain = domain_value if isinstance(domain_value, list) else [domain_value] if domain_value else []
    thread = thread_value if isinstance(thread_value, list) else [thread_value] if thread_value else []
    return {
        "entities": [value for value in entities if value],
        "topics": tokens,
        "domain": [_normalize_index_value(str(item)) for item in domain if str(item).strip()],
        "thread": [_normalize_index_value(str(item)) for item in thread if str(item).strip()],
    }


def express(store, query: str, context: dict | None = None) -> list[MemoryUnit]:
    """
    Context-driven fact expression — Addressed Cognition v0.20.2.
    """
    _set_expression_stats(store, candidate_pool=0, above_threshold=0, expressed=0, bypassed=False)
    if not context:
        LOGGER.debug("Expression engine: no context, falling through")
        return []

    total_terms = len(context.get("topics", [])) + len(context.get("entities", []))
    if total_terms < MIN_CONTEXT_TERMS:
        LOGGER.debug("Expression engine: context too sparse (%s terms), falling through", total_terms)
        return []

    candidate_ids = get_candidate_pool(store, context, limit=MAX_CANDIDATE_POOL + 1)
    if not candidate_ids:
        LOGGER.debug("Expression engine: empty candidate pool, falling through")
        return []
    if len(candidate_ids) > MAX_CANDIDATE_POOL:
        LOGGER.debug(
            "Expression engine: candidate pool too large (>%s), falling through",
            MAX_CANDIDATE_POOL,
        )
        _set_expression_stats(store, candidate_pool=len(candidate_ids), above_threshold=0, expressed=0, bypassed=False)
        return []

    effective_weights = get_effective_activations(store, candidate_ids)
    scored: list[tuple[str, float]] = []
    utc_now = datetime.now(UTC)
    for fact_id, weight in effective_weights.items():
        if weight < EXPRESSION_THRESHOLD:
            continue
        epig = store.get_epigenetic(fact_id)
        if epig is None:
            continue
        if epig.get("silenced"):
            continue
        silence_until = epig.get("silence_until")
        if silence_until:
            parsed_silence_until = datetime.fromisoformat(str(silence_until))
            if parsed_silence_until.tzinfo is None:
                parsed_silence_until = parsed_silence_until.replace(tzinfo=UTC)
            if parsed_silence_until > utc_now:
                continue
        recency_bonus = 0.2 if epig.get("last_expressed_at") else 0.0
        reinforcement_bonus = min(int(epig.get("reinforcement_count", 0)) * 0.1, 0.5)
        composite = weight + recency_bonus + reinforcement_bonus
        scored.append((fact_id, composite))

    if not scored:
        LOGGER.debug("Expression engine: no candidates above threshold, falling through")
        _set_expression_stats(
            store,
            candidate_pool=len(candidate_ids),
            above_threshold=0,
            expressed=0,
            bypassed=False,
        )
        return []

    scored.sort(key=lambda item: item[1], reverse=True)
    top_ids = [fact_id for fact_id, _score in scored[:MAX_EXPRESSED_FACTS]]
    facts = store.get_facts_by_ids(top_ids)
    for fact in facts:
        fact.metadata["retrieval_tier"] = "expression"

    LOGGER.info(
        "Expression engine: pool=%s, above_threshold=%s, expressed=%s",
        len(candidate_ids),
        len(scored),
        len(facts),
    )
    _set_expression_stats(
        store,
        candidate_pool=len(candidate_ids),
        above_threshold=len(scored),
        expressed=len(facts),
        bypassed=bool(facts),
    )
    return facts


def _set_expression_stats(
    store,
    *,
    candidate_pool: int,
    above_threshold: int,
    expressed: int,
    bypassed: bool,
) -> None:
    store._last_expression_stats = {"candidate_pool": candidate_pool, "above_threshold": above_threshold, "expressed": expressed, "bypassed_retrieval": bypassed}
