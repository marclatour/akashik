"""
TF-IDF baseline adapter for ACMB.
Pure lexical retrieval using scikit-learn TF-IDF vectors and cosine similarity.
No embeddings, no LLM, no external services.

Purpose: establishes what a standard TF-IDF baseline achieves on ACMB.
Direct comparison to BM25 and Akashik's lexical retrieval path.
"""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from benchmark.acmb.adapters.base import ACMBAdapter


class TfidfAdapter(ACMBAdapter):
    def __init__(self):
        self.chunks: list[str] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None

    def _rebuild_index(self) -> None:
        if not self.chunks:
            self._vectorizer = None
            self._matrix = None
            return
        self._vectorizer = TfidfVectorizer(lowercase=True)
        self._matrix = self._vectorizer.fit_transform(self.chunks)

    def ingest_turn(self, turn: dict, **kwargs) -> None:
        if turn["actor"] == "user" and turn.get("content"):
            sentences = [sentence.strip() for sentence in turn["content"].split(".") if sentence.strip()]
            for sentence in sentences:
                self.chunks.append(sentence)
            self._rebuild_index()

    def query(self, query_text: str, k: int = 10, **kwargs) -> list[str]:
        if self._vectorizer is None or self._matrix is None or not self.chunks:
            return []
        query_vector = self._vectorizer.transform([query_text])
        scores = cosine_similarity(query_vector, self._matrix)[0]
        top_indices = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:k]
        return [self.chunks[index] for index in top_indices if float(scores[index]) > 0.0]

    def reset(self) -> None:
        self.chunks = []
        self._vectorizer = None
        self._matrix = None
