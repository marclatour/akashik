"""Expression engine stub — Addressed Cognition v0.20.0-alpha.

Currently a no-op: always returns empty, falling through to
the existing retrieval stack. Full implementation in v0.20.0.
"""

from __future__ import annotations

from typing import Optional


def express(store, query: str, context: Optional[dict] = None) -> list:
    """
    Context-driven fact expression.
    v0.20.0-alpha: no-op stub, returns empty list.
    Retrieval falls through to existing stack.
    """
    del store, query, context
    return []
