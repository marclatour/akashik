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
        Return up to k fact_ids relevant to query_text.
        fact_ids must match those defined in the persona file.
        """

    def query_with_scores(self, query_text: str, k: int = 10) -> list[tuple[str, float]]:
        """
        Optional scored query interface. Falls back to uniform scores.
        """

        return [(fact_id, 1.0) for fact_id in self.query(query_text, k)]

    def reset(self) -> None:
        """
        Reset memory state between personas.
        Override if the system needs explicit cleanup.
        """

        return None
