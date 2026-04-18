from __future__ import annotations

import os

from benchmark.acmb.adapters.base import ACMBAdapter


class AkashikAdapter(ACMBAdapter):
    """
    Akashik implementation of the ACMB adapter.
    Stub in v0.1 — full wiring in next slice.
    """

    def __init__(self, store_path: str | None = None):
        self.store_path = store_path or os.path.expanduser(
            "~/.akashik/stores/benchmarks/acmb/akashik_acmb.db"
        )
        self.store = None

    def ingest_turn(self, turn: dict) -> None:
        return None

    def query(self, query_text: str, k: int = 10) -> list[str]:
        return []

    def reset(self) -> None:
        return None
