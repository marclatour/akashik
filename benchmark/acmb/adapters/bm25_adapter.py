"""
BM25 baseline adapter for ACMB.
Pure lexical retrieval using BM25Okapi (rank-bm25).
No embeddings, no LLM, no external dependencies beyond rank-bm25.

Purpose: establishes what pure keyword search achieves on ACMB.
Direct comparison to Akashik's FTS5 retrieval tier — both are
lexical, but Akashik adds validity filtering, structured memory,
and commitment tracking on top.

Fast, deterministic, fully local. No API key required.
"""

from benchmark.acmb.adapters.base import ACMBAdapter


class BM25Adapter(ACMBAdapter):
    def __init__(self):
        self.chunks: list[str] = []
        self._bm25 = None

    def _tokenize(self, text: str) -> list[str]:
        return text.lower().split()

    def _rebuild_index(self) -> None:
        if not self.chunks:
            self._bm25 = None
            return
        from rank_bm25 import BM25Okapi

        tokenized = [self._tokenize(chunk) for chunk in self.chunks]
        self._bm25 = BM25Okapi(tokenized)

    def ingest_turn(self, turn: dict, **kwargs) -> None:
        if turn["actor"] == "user" and turn.get("content"):
            sentences = [sentence.strip() for sentence in turn["content"].split(".") if sentence.strip()]
            for sentence in sentences:
                self.chunks.append(sentence)
            self._rebuild_index()

    def query(self, query_text: str, k: int = 10, **kwargs) -> list[str]:
        if self._bm25 is None or not self.chunks:
            return []
        query_tokens = self._tokenize(query_text)
        scores = self._bm25.get_scores(query_tokens)
        top_indices = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:k]
        return [self.chunks[index] for index in top_indices if scores[index] > 0]

    def reset(self) -> None:
        self.chunks = []
        self._bm25 = None
