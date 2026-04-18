"""
Full-context baseline for ACMB.
Stores all ingested turn content and returns the most recent content
up to a token budget. Simulates stuffing everything into a context
window with no retrieval or memory management.
"""

from __future__ import annotations

from akashik.query_normalize import normalize_query
from benchmark.acmb.adapters.base import ACMBAdapter

MAX_TOKENS = 4000


class FullContextAdapter(ACMBAdapter):
    def __init__(self):
        self.turns: list[str] = []

    def ingest_turn(self, turn: dict) -> None:
        if turn.get("content"):
            self.turns.append(turn["content"])

    def query(self, query_text: str, k: int = 10, **kwargs) -> list[str]:
        if not self.turns:
            return []
        result: list[str] = []
        token_count = 0
        for turn in reversed(self.turns):
            turn_tokens = len(normalize_query(turn).split())
            if token_count + turn_tokens > MAX_TOKENS:
                break
            result.insert(0, turn)
            token_count += turn_tokens
        return result[-k:]

    def reset(self) -> None:
        self.turns = []
