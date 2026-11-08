"""Associative activation — compact-code expression stage (opt-in).

Experimental. Off by default; enabled with ``retrieve(..., use_association=True)``.

What it does, for fact-level queries that reach the FTS tier:

1. **Associate.** Each fact in a bounded pool (the most recent
   ``POOL_LIMIT`` current facts) gets a compact binary code: the sign bits of
   its sentence embedding (384 bits -> 48 bytes for all-MiniLM-L6-v2). Codes
   are cached in memory per store, so a fact is encoded once, not per query.
   The query is encoded once and matched by Hamming similarity (popcount).
   This is the "which memories match" operation in a form that maps directly
   onto in-memory / analog match hardware.
2. **Fuse.** Associative candidates are merged with the existing FTS ranking
   by reciprocal-rank fusion. Exact and normalized hash matches never reach
   this stage, so they still outrank everything (retrieval-order invariant).
3. **Arbitrate (current-state queries only).** When two returned facts are
   near-duplicates in code space and the newer one comes from a later session,
   the older one is withheld from this response. Nothing is written to the
   Sequence layer; the decision is per query, reversible and inspectable.
   Skipped entirely when ``as_of`` is set (historical queries want old facts).

Parameters below were fixed before benchmarking, not tuned on ACMB.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence

import numpy as np

from akashik.schema import MemoryUnit

LOGGER = logging.getLogger(__name__)

POOL_LIMIT = 1000           # bounded pool, independent of corpus size
ASSOC_K = 20                # associative candidates merged per query
RRF_K = 60                  # standard reciprocal-rank-fusion constant
# Sign-bit agreement 0.70 ~ cosine 0.59 (agreement = 1 - angle/pi).
SUPERSEDE_SIMILARITY = float(os.getenv("AKASHIK_ASSOC_SUPERSEDE", "0.70"))

Encoder = Callable[[Sequence[str]], np.ndarray]


def to_code(vectors: np.ndarray) -> np.ndarray:
    """Sign-bit binary codes, packed 8 bits per byte. Shape (n, dims/8)."""
    return np.packbits(np.asarray(vectors) > 0, axis=-1)


def code_similarity(query_code: np.ndarray, codes: np.ndarray) -> np.ndarray:
    """Fraction of agreeing bits between one code and many codes."""
    bits = codes.shape[-1] * 8
    differing = np.unpackbits(np.bitwise_xor(codes, query_code), axis=-1).sum(axis=-1)
    return 1.0 - differing / bits


class CodeCache:
    """In-memory fact_id -> code cache. Lives on the store object."""

    def __init__(self) -> None:
        self._codes: dict[str, np.ndarray] = {}
        self.encoded = 0  # facts encoded so far (cache misses)

    def codes_for(self, units: Sequence[MemoryUnit], encoder: Encoder) -> np.ndarray:
        missing = [unit for unit in units if unit.id not in self._codes]
        if missing:
            new_codes = to_code(encoder([unit.content for unit in missing]))
            for unit, code in zip(missing, new_codes, strict=True):
                self._codes[unit.id] = code
            self.encoded += len(missing)
        return np.stack([self._codes[unit.id] for unit in units])


def code_cache(store) -> CodeCache:
    cache = getattr(store, "_assoc_code_cache", None)
    if cache is None:
        cache = CodeCache()
        store._assoc_code_cache = cache
    return cache


def associate(
    store,
    query: str,
    encoder: Encoder,
    *,
    as_of: str | None,
    k: int = ASSOC_K,
    pool: Sequence[MemoryUnit] | None = None,
) -> list[tuple[MemoryUnit, float]]:
    if pool is None:
        pool = store.fetch_recent_facts(POOL_LIMIT, current_only=as_of is None, as_of=as_of)
    if not pool:
        return []
    codes = code_cache(store).codes_for(pool, encoder)
    query_code = to_code(encoder([query]))[0]
    sims = code_similarity(query_code, codes)
    # pool is newest-first; stable sort keeps newer facts first on ties
    order = np.argsort(-sims, kind="stable")[:k]
    return [(pool[i], float(sims[i])) for i in order]


def fuse(fts_ranked: Sequence[MemoryUnit], assoc_ranked: Sequence[MemoryUnit]) -> list[MemoryUnit]:
    """Reciprocal-rank fusion; deterministic tie-break by first appearance."""
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    units: dict[str, MemoryUnit] = {}
    for ranked in (fts_ranked, assoc_ranked):
        for rank, unit in enumerate(ranked):
            scores[unit.id] = scores.get(unit.id, 0.0) + 1.0 / (RRF_K + rank + 1)
            first_seen.setdefault(unit.id, len(first_seen))
            units[unit.id] = unit
    ordered = sorted(scores, key=lambda fid: (-scores[fid], first_seen[fid]))
    return [units[fid] for fid in ordered]


def _session_key(unit: MemoryUnit) -> str:
    metadata = unit.metadata or {}
    return str(unit.valid_from or metadata.get("session_date") or "")


def arbitrate(
    store,
    candidates: Sequence[MemoryUnit],
    encoder: Encoder,
    *,
    threshold: float = SUPERSEDE_SIMILARITY,
) -> tuple[list[MemoryUnit], list[tuple[str, str]]]:
    """Withhold older near-duplicates that a later-session fact supersedes.

    Returns (kept, withheld) where withheld lists (older_id, newer_id) pairs.
    """
    if len(candidates) < 2:
        return list(candidates), []
    codes = code_cache(store).codes_for(candidates, encoder)
    keys = [_session_key(unit) for unit in candidates]
    withheld: list[tuple[str, str]] = []
    dropped: set[int] = set()
    for i, older in enumerate(candidates):
        sims = code_similarity(codes[i], codes)
        for j, newer in enumerate(candidates):
            if i == j or j in dropped:
                continue
            if keys[j] and keys[i] and keys[j] > keys[i] and sims[j] >= threshold:
                dropped.add(i)
                withheld.append((older.id, newer.id))
                break
    kept = [unit for index, unit in enumerate(candidates) if index not in dropped]
    return kept, withheld


def associative_rerank(
    store,
    query: str,
    fts_ranked: Sequence[MemoryUnit],
    encoder: Encoder | None,
    *,
    as_of: str | None,
    expand: bool = True,
) -> list[MemoryUnit]:
    """Entry point used by retrieve(). Falls back to FTS order on any failure.

    ``expand=True`` (unscoped retrieval) associates over the bounded recent
    pool and may add facts FTS missed. ``expand=False`` (scoped retrieval)
    only re-ranks the candidates scoped search already returned, so entity
    filters, document gating and scope semantics are inherited unchanged and
    no out-of-scope fact can enter.
    """
    if encoder is None:
        return list(fts_ranked)
    try:
        pool = None if expand else list(fts_ranked)
        assoc = associate(store, query, encoder, as_of=as_of, pool=pool)
        merged = fuse(fts_ranked, [unit for unit, _sim in assoc])
        withheld: list[tuple[str, str]] = []
        if as_of is None:
            merged, withheld = arbitrate(store, merged, encoder)
        store._last_association_stats = {
            "associated": len(assoc),
            "withheld": withheld,
            "codes_encoded_total": code_cache(store).encoded,
        }
        return merged
    except Exception:
        LOGGER.exception("Associative stage failed; using FTS order.")
        return list(fts_ranked)


def default_encoder() -> Encoder | None:
    """Encoder backed by the semantic fallback's model, or None if unavailable."""
    from akashik.retrieve import _SEMANTIC_RANKER

    model = _SEMANTIC_RANKER._load_model()
    if model is None:
        return None

    def encode(texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            model.encode(
                list(texts),
                batch_size=min(32, max(1, len(texts))),
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        )

    return encode
