"""
BM25 + Akashik commitment detection adapter for ACMB.
Uses BM25 lexical retrieval plus Akashik's deterministic
commitment detector. Isolates whether commitment detection
helps lexical retrieval the same way it helped embedding retrieval.
"""

from benchmark.acmb.adapters.base import ACMBAdapter

MAX_COMMITMENTS = 5


class BM25AkashikAdapter(ACMBAdapter):
    def __init__(self):
        self.chunks: list[str] = []
        self._bm25 = None
        self.commitments: list[str] = []

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
        elif turn["actor"] == "assistant" and turn.get("content"):
            from akashik.commitment_detector import detect_commitment

            description = detect_commitment(turn["content"])
            if description:
                self.commitments.append(description)

    def query(self, query_text: str, k: int = 10, **kwargs) -> list[str]:
        from akashik.commitment_detector import COMMITMENT_META_QUERIES

        results: list[str] = []
        if self._bm25 is not None and self.chunks:
            query_tokens = self._tokenize(query_text)
            scores = self._bm25.get_scores(query_tokens)
            top_indices = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:k]
            results = [self.chunks[index] for index in top_indices if scores[index] > 0]
        query_lower = query_text.lower()
        if any(phrase in query_lower for phrase in COMMITMENT_META_QUERIES):
            for commitment in self.commitments[-MAX_COMMITMENTS:]:
                results.append(f"[COMMITMENT] {commitment}")
        return results

    def reset(self) -> None:
        self.chunks = []
        self._bm25 = None
        self.commitments = []
