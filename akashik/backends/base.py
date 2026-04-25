"""Shared answer backend interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class BackendResponse:
    answer: str
    backend: str
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class AnswerBackend(ABC):
    """Common interface for answer generation backends."""

    @abstractmethod
    def generate(
        self,
        question: str,
        memory_block: str,
        *,
        max_tokens: int = 500,
    ) -> BackendResponse:
        """Generate an answer given a question and memory block."""
