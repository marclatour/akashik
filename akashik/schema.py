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
    lineage_parent_id: str | None = None
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: bytes | None = None
    section_heading: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    confirmation_count: int = 1
    last_confirmed_at: str | None = None
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
    temporal_answer: dict[str, Any] | None = None


@dataclass(slots=True)
class SourceCitation:
    fact_id: str
    content: str
    session_id: str | None
    session_date: str | None
    confidence: float
    confirmed_count: int


@dataclass(slots=True)
class ExecutorResult:
    answer: str | None
    answer_type: str
    answer_confidence: float
    coverage_confidence: float
    requires_reasoning: bool
    abstained: bool
    sources: list[SourceCitation]
    raw_facts: list[RetrievalResult]
    temporal_answer: dict[str, Any] | None = None


@dataclass(slots=True)
class StoreStats:
    total: int
    by_level: dict[str, int]
    db_path: str
