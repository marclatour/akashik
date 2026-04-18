"""
Naive RAG baseline for ACMB.
Chunks user turns by sentence, embeds with sentence-transformers,
retrieves by cosine similarity. No memory management, no belief
revision, no validity windows. Pure embedding retrieval baseline.
"""

from __future__ import annotations

import numpy as np

from benchmark.acmb.adapters.base import ACMBAdapter


class RagAdapter(ACMBAdapter):
    def __init__(self, model_name: str = "multi-qa-mpnet-base-dot-v1"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.chunks: list[str] = []
        self.embeddings: list[np.ndarray] = []

    def ingest_turn(self, turn: dict) -> None:
        if turn["actor"] != "user" or not turn.get("content"):
            return
        sentences = [part.strip() for part in turn["content"].split(".") if part.strip()]
        for sentence in sentences:
            embedding = self.model.encode(sentence, normalize_embeddings=True)
            self.chunks.append(sentence)
            self.embeddings.append(np.asarray(embedding, dtype=np.float32))

    def query(self, query_text: str, k: int = 10, **kwargs) -> list[str]:
        if not self.chunks:
            return []
        query_embedding = np.asarray(
            self.model.encode(query_text, normalize_embeddings=True),
            dtype=np.float32,
        )
        scores = [float(np.dot(query_embedding, embedding)) for embedding in self.embeddings]
        top_indices = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)[:k]
        return [self.chunks[idx] for idx in top_indices]

    def reset(self) -> None:
        self.chunks = []
        self.embeddings = []
