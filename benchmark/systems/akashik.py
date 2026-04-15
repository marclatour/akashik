"""Akashik system wrapper for benchmark retrieval."""

from __future__ import annotations

from pathlib import Path

from akashik import Store, ingest_file, retrieve
from benchmark.corpus import CorpusDocument
from benchmark.systems import RetrievedItem


class AkashikSystem:
    display_name = "Akashik"

    def __init__(self, documents: list[CorpusDocument], *, db_path: str | Path | None = None) -> None:
        db_path = Path(db_path or "results/benchmark.db")
        db_path.parent.mkdir(exist_ok=True)
        self._store = Store(db_path)
        for document in documents:
            ingest_file(document.path, self._store)

    def search(self, query: str, *, limit: int = 5) -> list[RetrievedItem]:
        response = retrieve(query, self._store, level="fact", limit=limit)
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


def _normalize_source(source: str) -> str:
    return Path(source).name if source else ""
