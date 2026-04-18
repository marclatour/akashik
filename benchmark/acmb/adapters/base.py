from __future__ import annotations

from abc import ABC, abstractmethod


class ACMBAdapter(ABC):
    """
    System-agnostic adapter interface for ACMB.
    Any memory system implements these methods.
    """

    @abstractmethod
    def ingest_turn(self, turn: dict) -> None:
        """
        Ingest one conversation turn into the memory system.
        turn contains: turn_id, actor, content, ground_truth_facts,
        revises_facts, and simulated_date.
        """

    @abstractmethod
    def query(self, query_text: str, k: int = 10) -> list[str]:
        """
        Return up to k retrieved text snippets relevant to the query.
        Snippets are raw text — not fact_ids.
        The evaluator resolves fact_ids from text via natural_language matching.
        """

    def query_with_scores(self, query_text: str, k: int = 10) -> list[tuple[str, float]]:
        """
        Return up to k (text_snippet, score) pairs.
        Default implementation calls query() with score 1.0 for all results.
        """

        return [(text, 1.0) for text in self.query(query_text, k)]

    def reset(self) -> None:
        """
        Reset memory state between personas.
        Override if the system needs explicit cleanup.
        """

        return None
