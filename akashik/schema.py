"""Core schema models for Akashik."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

LEVELS = ("corpus", "document", "section", "fact")
LEVEL_INDEX = {level: index for index, level in enumerate(LEVELS)}


def validate_level(level: str) -> str:
    if level not in LEVELS:
        raise ValueError(f"Invalid level {level!r}; expected one of {LEVELS}.")
    return level


@dataclass(slots=True)
class MemoryUnit:
    level: str
    content: str
    content_hash: str
    normalized_hash: str
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: bytes | None = None
    section_heading: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        validate_level(self.level)
        self.metadata = dict(self.metadata or {})

    @property
    def source(self) -> str:
        source = self.metadata.get("source", "")
        return str(source) if source is not None else ""


@dataclass(slots=True)
class RetrievalResult:
    unit: MemoryUnit
    confidence: float
    parent_chain: list[MemoryUnit]

    @property
    def full_chain(self) -> list[MemoryUnit]:
        return [self.unit, *self.parent_chain]


@dataclass(slots=True)
class RetrievalResponse:
    results: list[RetrievalResult]
    confidence: float


@dataclass(slots=True)
class StoreStats:
    total: int
    by_level: dict[str, int]
    db_path: str
