"""
Akashik adapter for ACMB v0.1.
Wires real Akashik ingest and retrieval into the ACMB benchmark interface.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path

from akashik.identity import content_hash, normalized_hash
from akashik.schema import MemoryUnit
from akashik.store import Store
from benchmark.acmb.adapters.base import ACMBAdapter


class AkashikAdapter(ACMBAdapter):
    def __init__(self, store_path: str | None = None):
        self.store_path = store_path or os.path.expanduser(
            "~/.akashik/stores/benchmarks/acmb/akashik_acmb.db"
        )
        Path(self.store_path).parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.store_path)
        self._corpus_id: str | None = None
        self._document_id: str | None = None

    def reset(self) -> None:
        """
        Delete and recreate the store for a clean slate between personas.
        Per-persona stores are deleted entirely to avoid partial reset bugs.
        """

        try:
            self.store.close()
        except Exception:
            pass
        if os.path.exists(self.store_path):
            os.remove(self.store_path)
        Path(self.store_path).parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.store_path)
        self._corpus_id = None
        self._document_id = None

    def ingest_turn(self, turn: dict) -> None:
        """
        Ingest one conversation turn.
        User turns are stored as facts in memory_units.
        Assistant turns are logged to interaction_log only — never stored as facts.
        """

        self._ensure_roots()
        if turn["actor"] == "user":
            metadata = {
                "source": "acmb",
                "speaker": turn["actor"],
                "turn_id": turn["turn_id"],
                "ground_truth_facts": list(turn.get("ground_truth_facts", [])),
                "simulated_date": turn.get("simulated_date"),
                "tags": [],
            }
            self.store.insert(
                MemoryUnit(
                    level="fact",
                    content=turn["content"],
                    content_hash=content_hash(turn["content"]),
                    normalized_hash=normalized_hash(turn["content"]),
                    parent_id=self._document_id,
                    metadata=metadata,
                    valid_from=turn.get("simulated_date"),
                )
            )
        elif turn["actor"] == "assistant":
            self._log_interaction(turn)

    def _ensure_roots(self) -> None:
        if self._corpus_id is None:
            corpus = self.store.insert(
                MemoryUnit(
                    level="corpus",
                    content="ACMB persona corpus",
                    content_hash=content_hash("ACMB persona corpus"),
                    normalized_hash=normalized_hash("ACMB persona corpus"),
                    metadata={"source": "acmb", "tags": []},
                )
            )
            self._corpus_id = corpus.id
        if self._document_id is None:
            document = self.store.insert(
                MemoryUnit(
                    level="document",
                    content="ACMB persona document",
                    content_hash=content_hash("ACMB persona document"),
                    normalized_hash=normalized_hash("ACMB persona document"),
                    parent_id=self._corpus_id,
                    metadata={"source": "acmb", "tags": []},
                )
            )
            self._document_id = document.id

    def _log_interaction(self, turn: dict) -> None:
        """Write assistant turn to interaction_log. Never to memory_units."""
        try:
            self.store.log_interaction(
                {
                    "turn_id": turn["turn_id"],
                    "session_id": self._document_id or "unknown",
                    "timestamp": turn.get("simulated_date", datetime.now(UTC).isoformat()),
                    "actor": turn["actor"],
                    "raw_content": turn["content"],
                    "retrieved_fact_ids": None,
                    "context_packet_hash": None,
                    "user_correction": None,
                    "user_confirmed": None,
                }
            )
        except Exception:
            pass

    def query(self, query_text: str, k: int = 10) -> list[str]:
        """
        Retrieve top-k facts and return their ground_truth_fact_ids.
        Expression stays off for reproducibility in ACMB v0.1.
        """
        from akashik.retrieve import retrieve

        response = retrieve(query_text, self.store, level="fact", limit=k, use_expression=False)
        fact_ids: list[str] = []
        seen: set[str] = set()
        for result in response.results:
            for fact_id in (result.unit.metadata or {}).get("ground_truth_facts", []):
                if fact_id in seen:
                    continue
                seen.add(fact_id)
                fact_ids.append(fact_id)
        return fact_ids

    def query_with_scores(self, query_text: str, k: int = 10) -> list[tuple[str, float]]:
        """
        Retrieve top-k facts with scores.
        Score uses RetrievalResult confidence, otherwise rank proxy.
        """
        from akashik.retrieve import retrieve

        response = retrieve(query_text, self.store, level="fact", limit=k, use_expression=False)
        results: list[tuple[str, float]] = []
        seen: set[str] = set()
        for rank, retrieval_result in enumerate(response.results):
            score = retrieval_result.confidence if retrieval_result.confidence is not None else 1.0 / (rank + 1)
            for fact_id in (retrieval_result.unit.metadata or {}).get("ground_truth_facts", []):
                if fact_id in seen:
                    continue
                seen.add(fact_id)
                results.append((fact_id, float(score)))
        return results
