"""Baseline chunked RAG using local sentence-transformer embeddings."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from benchmark.corpus import CorpusDocument
from benchmark.systems import RetrievedItem

MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"


@dataclass(slots=True)
class EmbeddedChunk:
    source: str
    content: str
    start_word: int
    end_word: int
    embedding: list[float]


class RagEmbeddingSystem:
    display_name = "RAG-Embedding"

    def __init__(
        self,
        documents: list[CorpusDocument],
        *,
        chunk_size: int = 200,
        overlap: int = 50,
        model_name: str = MODEL_NAME,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "RAG-Embedding requires sentence-transformers. Install it with "
                "`./.venv/bin/pip install sentence-transformers`."
            ) from exc

        self._model_name = model_name
        self._model = _load_model(SentenceTransformer, model_name)
        self._chunks: list[EmbeddedChunk] = []
        self._index_documents(documents, chunk_size=chunk_size, overlap=overlap)

    def search(self, query: str, *, limit: int = 5) -> list[RetrievedItem]:
        if not query.strip() or not self._chunks:
            return []

        query_embedding = self._encode(query)
        ranked = sorted(
            (
                (_cosine_similarity(query_embedding, chunk.embedding), chunk)
                for chunk in self._chunks
            ),
            key=lambda item: item[0],
            reverse=True,
        )

        results: list[RetrievedItem] = []
        for index, (score, chunk) in enumerate(ranked[:limit], start=1):
            results.append(
                RetrievedItem(
                    content=chunk.content,
                    source=chunk.source,
                    rank=index,
                    confidence=round(score, 6),
                    metadata={
                        "chunk_start_word": chunk.start_word,
                        "chunk_end_word": chunk.end_word,
                        "model": self._model_name,
                    },
                )
            )
        return results

    def close(self) -> None:
        return None

    def _index_documents(self, documents: list[CorpusDocument], *, chunk_size: int, overlap: int) -> None:
        stride = chunk_size - overlap
        for document in documents:
            words = document.text.split()
            for start in range(0, len(words), stride):
                window = words[start : start + chunk_size]
                if not window:
                    continue
                content = " ".join(window)
                self._chunks.append(
                    EmbeddedChunk(
                        source=document.filename,
                        content=content,
                        start_word=start,
                        end_word=start + len(window),
                        embedding=self._encode(content),
                    )
                )
                if start + chunk_size >= len(words):
                    break

    def _encode(self, text: str) -> list[float]:
        embedding: Any = self._model.encode(
            text,
            batch_size=1,
            convert_to_numpy=False,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [float(value) for value in embedding]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _load_model(model_class: Any, model_name: str) -> Any:
    try:
        return model_class(model_name, device="cpu", local_files_only=True)
    except Exception:
        return model_class(model_name, device="cpu")
