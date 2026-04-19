"""
RAG + Akashik commitment detection adapter for ACMB.
Uses embedding retrieval (same as rag adapter) plus
Akashik's deterministic commitment detector.

Purpose: isolate whether commitment detection alone explains
Akashik's gains, or whether structured memory adds independent
value. If rag_akashik matches Akashik on commitment queries but
loses on belief revision and distractors, structured memory is
doing real work beyond commitment detection.
"""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

from benchmark.acmb.adapters.base import ACMBAdapter

MAX_COMMITMENTS = 5
_MODEL = SentenceTransformer("multi-qa-mpnet-base-dot-v1")


class RagAkashikAdapter(ACMBAdapter):
    def __init__(self, model_name: str = "multi-qa-mpnet-base-dot-v1"):
        self.model = _MODEL
        self.chunks: list[str] = []
        self.embeddings: list[np.ndarray] = []
        self.commitments: list[str] = []

    def ingest_turn(self, turn: dict, **kwargs) -> None:
        if turn["actor"] == "user" and turn.get("content"):
            sentences = [sentence.strip() for sentence in turn["content"].split(".") if sentence.strip()]
            for sentence in sentences:
                embedding = self.model.encode(sentence, normalize_embeddings=True)
                self.chunks.append(sentence)
                self.embeddings.append(np.asarray(embedding, dtype=np.float32))
        elif turn["actor"] == "assistant" and turn.get("content"):
            from akashik.commitment_detector import detect_commitment

            description = detect_commitment(turn["content"])
            if description:
                self.commitments.append(description)

    def query(self, query_text: str, k: int = 10, **kwargs) -> list[str]:
        from akashik.commitment_detector import COMMITMENT_META_QUERIES

        results: list[str] = []
        if self.chunks:
            query_embedding = np.asarray(
                self.model.encode(query_text, normalize_embeddings=True),
                dtype=np.float32,
            )
            scores = [float(np.dot(query_embedding, embedding)) for embedding in self.embeddings]
            top_indices = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)[:k]
            results = [self.chunks[idx] for idx in top_indices]

        query_lower = query_text.lower()
        if any(phrase in query_lower for phrase in COMMITMENT_META_QUERIES):
            for commitment in self.commitments[-MAX_COMMITMENTS:]:
                results.append(f"[COMMITMENT] {commitment}")

        return results

    def reset(self) -> None:
        self.chunks = []
        self.embeddings = []
        self.commitments = []
