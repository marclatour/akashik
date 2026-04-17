"""Akashik system wrapper for benchmark retrieval."""

from __future__ import annotations

from pathlib import Path

from akashik import Store, ingest_file, retrieve
from akashik.executor import execute as execute_query
from benchmark.corpus import CorpusDocument
from benchmark.systems import RetrievedItem


class AkashikSystem:
    display_name = "Akashik"

    def __init__(
        self,
        documents: list[CorpusDocument],
        *,
        db_path: str | Path | None = None,
        ingest_documents: bool = True,
    ) -> None:
        db_path = Path(db_path or "results/benchmark.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._store = Store(db_path)
        if ingest_documents:
            for document in documents:
                ingest_file(document.path, self._store)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        entity_filter: list[str] | None = None,
        clause_type: str | None = None,
        debug_label: str | None = None,
    ) -> list[RetrievedItem]:
        response = retrieve(
            query,
            self._store,
            level="fact",
            limit=limit,
            entity_filter=entity_filter,
            clause_type=clause_type,
            debug_label=debug_label,
        )
        results: list[RetrievedItem] = []
        for index, result in enumerate(response.results, start=1):
            results.append(
                RetrievedItem(
                    content=result.unit.content,
                    source=_normalize_source(result.unit.source),
                    rank=index,
                    confidence=result.confidence,
                    parent_chain=[
                        {
                            "level": parent.level,
                            "content": parent.content,
                            "source": _normalize_source(parent.source),
                        }
                        for parent in result.parent_chain
                    ],
                )
            )
        return results

    def close(self) -> None:
        self._store.close()

    def execute(
        self,
        query: str,
        *,
        limit: int = 5,
        entity_filter: list[str] | None = None,
        clause_type: str | None = None,
        abstention_threshold: float = 0.3,
    ):
        return execute_query(
            self._store,
            query,
            entity_filter=entity_filter,
            clause_type=clause_type,
            top_k=limit,
            abstention_threshold=abstention_threshold,
        )


def _normalize_source(source: str) -> str:
    return Path(source).name if source else ""
