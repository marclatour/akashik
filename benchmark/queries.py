"""Benchmark query loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from benchmark import DEFAULT_QUERIES_PATH

DIFFICULTIES = ("easy", "medium", "hard")
EXPECTED_LEVELS = ("fact", "section", "document")


@dataclass(slots=True)
class BenchmarkQuery:
    query_id: str
    query_text: str
    expected_fact: str
    expected_source: str
    expected_level: str
    difficulty: str


def load_queries(
    queries_path: str | Path | None = None,
    *,
    corpus_filenames: set[str] | None = None,
) -> list[BenchmarkQuery]:
    path = Path(queries_path or DEFAULT_QUERIES_PATH).resolve()
    raw_queries = json.loads(path.read_text(encoding="utf-8"))
    queries = [BenchmarkQuery(**item) for item in raw_queries]
    validate_queries(queries, corpus_filenames=corpus_filenames)
    return queries


def validate_queries(
    queries: list[BenchmarkQuery],
    *,
    corpus_filenames: set[str] | None = None,
) -> None:
    if len(queries) < 20:
        raise ValueError(f"Benchmark query set must contain at least 20 queries; found {len(queries)}.")

    seen_ids: set[str] = set()
    for query in queries:
        if query.query_id in seen_ids:
            raise ValueError(f"Duplicate query id {query.query_id!r}.")
        seen_ids.add(query.query_id)

        if query.difficulty not in DIFFICULTIES:
            raise ValueError(f"Invalid difficulty {query.difficulty!r} for query {query.query_id!r}.")
        if query.expected_level not in EXPECTED_LEVELS:
            raise ValueError(
                f"Invalid expected level {query.expected_level!r} for query {query.query_id!r}."
            )
        if not query.query_text.strip():
            raise ValueError(f"Query {query.query_id!r} must not be empty.")
        if not query.expected_fact.strip():
            raise ValueError(f"Query {query.query_id!r} must define an expected fact.")
        if corpus_filenames is not None and query.expected_source not in corpus_filenames:
            raise ValueError(
                f"Query {query.query_id!r} references unknown source {query.expected_source!r}."
            )
