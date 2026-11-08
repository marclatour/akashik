"""
Akashik adapter for ACMB v0.1.
Wires real Akashik ingest and retrieval into the ACMB benchmark interface.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from akashik.commitment_detector import detect_commitment, is_closure
from akashik.identity import content_hash, normalized_hash
from akashik.ingest import ingest_turn_fact
from akashik.schema import Commitment, MemoryUnit
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
        self._section_id: str | None = None

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
        self._section_id = None

    def ingest_turn(self, turn: dict, commitments: list[dict] | None = None) -> None:
        """
        Ingest one conversation turn.
        User turns are stored as facts in memory_units.
        Assistant turns are logged to interaction_log only — never stored as facts.

        Fairness note: this adapter does not read oracle fields
        (ground_truth_facts, revises_facts) or the caller-supplied
        commitments list. It sees only what a real runtime would see —
        raw turn content and actor/turn identifiers.
        """

        self._ensure_roots()
        simulated_date = turn.get("simulated_date")
        if turn["actor"] == "user":
            content = turn["content"]
            ingest_turn_fact(
                self.store,
                content,
                parent_id=self._section_id,
                role=turn["actor"],
                turn_id=turn["turn_id"],
                session_date=simulated_date,
                metadata={"source": "acmb"},
            )
            if is_closure(turn["content"]):
                open_commitments = self.store.get_open_commitments()
                if open_commitments:
                    most_recent = sorted(
                        open_commitments,
                        key=lambda commitment: commitment.opened_at,
                        reverse=True,
                    )[0]
                    self.store.close_commitment(most_recent.id, datetime.utcnow().isoformat())
        elif turn["actor"] == "assistant":
            description = detect_commitment(turn["content"])
            if description:
                self.store.insert_commitment(
                    Commitment(
                        id=str(uuid.uuid4()),
                        description=description,
                        source_turn_id=turn["turn_id"],
                        session_id=self._document_id,
                        opened_at=turn.get("simulated_date", datetime.now(UTC).isoformat()),
                        closed_at=None,
                        status="open",
                        related_facts=[],
                        metadata={},
                    )
                )
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
        if self._section_id is None:
            section = self.store.insert(
                MemoryUnit(
                    level="section",
                    content="ACMB persona session",
                    content_hash=content_hash("ACMB persona session"),
                    normalized_hash=normalized_hash("ACMB persona session"),
                    parent_id=self._document_id,
                    metadata={"source": "acmb", "tags": []},
                )
            )
            self._section_id = section.id

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

    def query(self, query_text: str, k: int = 10, as_of: str | None = None) -> list[str]:
        """
        Retrieve top-k facts and return their raw fact content.
        Expression stays off for reproducibility in ACMB v0.1.
        """
        from akashik.retrieve import retrieve, retrieve_commitments

        response = retrieve(
            query_text,
            self.store,
            level="fact",
            limit=k,
            use_expression=False,
            use_association=os.getenv("AKASHIK_ACMB_ASSOCIATION") == "1",
            as_of=as_of,
        )
        texts = [result.unit.content for result in response.results if result.unit.content]
        commitments = retrieve_commitments(self.store, query_text)
        for commitment in commitments:
            texts.append(f"[COMMITMENT] {commitment.description}")
        return texts

    def query_with_scores(
        self,
        query_text: str,
        k: int = 10,
        as_of: str | None = None,
    ) -> list[tuple[str, float]]:
        """
        Retrieve top-k facts with scores.
        Score uses RetrievalResult confidence, otherwise rank proxy.
        """
        from akashik.retrieve import retrieve

        response = retrieve(
            query_text,
            self.store,
            level="fact",
            limit=k,
            use_expression=False,
            use_association=os.getenv("AKASHIK_ACMB_ASSOCIATION") == "1",
            as_of=as_of,
        )
        results: list[tuple[str, float]] = []
        for rank, retrieval_result in enumerate(response.results):
            score = retrieval_result.confidence if retrieval_result.confidence is not None else 1.0 / (rank + 1)
            if retrieval_result.unit.content:
                results.append((retrieval_result.unit.content, float(score)))
        return results
