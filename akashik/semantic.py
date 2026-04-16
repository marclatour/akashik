"""Semantic fallback reranking for low-confidence fact candidates."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from typing import Any

from akashik.schema import MemoryUnit

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticConfig:
    model_name: str = "all-MiniLM-L6-v2"
    confidence_threshold: float = 0.72
    min_candidates: int = 2
    enabled: bool = True


class SemanticRanker:
    def __init__(self, config: SemanticConfig | None = None) -> None:
        self.config = config or SemanticConfig()
        self._model: Any | None = None
        self._load_failed = False

    def rerank(
        self,
        query: str,
        candidates: list[MemoryUnit],
        current_confidence: float,
    ) -> list[MemoryUnit]:
        if not self.config.enabled:
            return candidates
        if current_confidence >= self.config.confidence_threshold:
            return candidates
        if len(candidates) < self.config.min_candidates:
            return candidates

        model = self._load_model()
        if model is None:
            return candidates

        try:
            query_embedding = self._encode(model, query)
            ranked = sorted(
                (
                    (_cosine_similarity(query_embedding, self._encode(model, candidate.content)), index, candidate)
                    for index, candidate in enumerate(candidates)
                ),
                key=lambda item: (-item[0], item[1]),
            )
        except Exception as exc:
            LOGGER.warning("Semantic rerank failed; using existing order: %s", exc)
            return candidates

        return [candidate for _score, _index, candidate in ranked]

    def _load_model(self) -> Any | None:
        if self._load_failed:
            return None
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer

            self._model = _instantiate_model(SentenceTransformer, self.config.model_name)
        except Exception as exc:
            self._load_failed = True
            LOGGER.warning("Semantic model unavailable; using existing order: %s", exc)
            return None
        return self._model

    def _encode(self, model: Any, text: str) -> list[float]:
        embedding: Any = model.encode(
            text,
            batch_size=1,
            convert_to_numpy=False,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [float(value) for value in embedding]


def _instantiate_model(model_class: Any, model_name: str) -> Any:
    try:
        return model_class(model_name, device="cpu", local_files_only=True)
    except Exception:
        return model_class(model_name, device="cpu")


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
