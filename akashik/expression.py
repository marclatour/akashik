"""Expression helpers — Addressed Cognition v0.20.x.

Currently a no-op: always returns empty, falling through to
the existing retrieval stack. Full implementation in v0.20.0.
"""

from __future__ import annotations

from datetime import UTC, datetime
import math
from typing import Optional

from akashik.query_normalize import normalize_query

TIER_DECAY_RATES = {
    "episodic": 0.01,
    "semantic": 0.005,
    "procedural": 0.001,
}
MAX_RAW_CANDIDATES = 1000


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
    for key in ("entities", "topics"):
        value = context.get(key, [])
        if isinstance(value, list):
            filters[key[:-1]] = [
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


def express(store, query: str, context: Optional[dict] = None) -> list:
    """
    Context-driven fact expression.
    v0.20.0-alpha: no-op stub, returns empty list.
    Retrieval falls through to existing stack.
    """
    del store, query, context
    return []
