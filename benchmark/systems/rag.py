"""Baseline chunked RAG using SQLite FTS5."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from benchmark.corpus import CorpusDocument
from benchmark.systems import RetrievedItem

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(slots=True)
class Chunk:
    source: str
    content: str
    start_word: int
    end_word: int


class RagSystem:
    display_name = "RAG"

    def __init__(self, documents: list[CorpusDocument], *, chunk_size: int = 200, overlap: int = 50) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE VIRTUAL TABLE rag_chunks USING fts5(
                source UNINDEXED,
                content
            )
            """
        )
        self._chunks: list[Chunk] = []
        self._index_documents(documents, chunk_size=chunk_size, overlap=overlap)

    def search(self, query: str, *, limit: int = 5) -> list[RetrievedItem]:
        query_tokens = _tokenize(query)
        fts_query = _build_fts_query(query_tokens, operator="OR")
        if not fts_query:
            return []

        rows = self._conn.execute(
            """
            SELECT rowid, source, content, bm25(rag_chunks) AS score
            FROM rag_chunks
            WHERE rag_chunks MATCH ?
            ORDER BY rowid
            LIMIT 100
            """,
            (fts_query,),
        ).fetchall()

        ranked_rows = sorted(
            rows,
            key=lambda row: (
                -_overlap_count(query_tokens, row["content"]),
                row["rowid"],
            ),
        )

        results: list[RetrievedItem] = []
        for index, row in enumerate(ranked_rows[:limit], start=1):
            chunk = self._chunks[row["rowid"] - 1]
            results.append(
                RetrievedItem(
                    content=row["content"],
                    source=row["source"],
                    rank=index,
                    metadata={
                        "chunk_start_word": chunk.start_word,
                        "chunk_end_word": chunk.end_word,
                    },
                )
            )
        return results

    def close(self) -> None:
        self._conn.close()

    def _index_documents(self, documents: list[CorpusDocument], *, chunk_size: int, overlap: int) -> None:
        stride = chunk_size - overlap
        for document in documents:
            words = document.text.split()
            for start in range(0, len(words), stride):
                window = words[start : start + chunk_size]
                if not window:
                    continue
                chunk = Chunk(
                    source=document.filename,
                    content=" ".join(window),
                    start_word=start,
                    end_word=start + len(window),
                )
                self._chunks.append(chunk)
                self._conn.execute(
                    "INSERT INTO rag_chunks (source, content) VALUES (?, ?)",
                    (chunk.source, chunk.content),
                )
                if start + chunk_size >= len(words):
                    break


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _build_fts_query(tokens: list[str], *, operator: str) -> str:
    if not tokens:
        return ""
    return f" {operator} ".join(f'"{token}"' for token in tokens)


def _overlap_count(query_tokens: list[str], content: str) -> int:
    content_tokens = set(_tokenize(content))
    return len(set(query_tokens) & content_tokens)
