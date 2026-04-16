"""Shared system result models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RetrievedItem:
    content: str
    source: str | None
    rank: int
    metadata: dict[str, object] = field(default_factory=dict)
    confidence: float | None = None
    parent_chain: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "content": self.content,
            "source": self.source,
            "rank": self.rank,
            "metadata": self.metadata,
            "confidence": self.confidence,
            "parent_chain": self.parent_chain,
        }
