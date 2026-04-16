"""Graph-enhanced retrieval stub."""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
import re
import sqlite3

from benchmark.corpus import CorpusDocument
from benchmark.systems import RetrievedItem

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


@dataclass(slots=True)
class SectionRecord:
    source: str
    content: str
    section_index: int
    entities: list[str]


class GraphRagSystem:
    display_name = "GraphRAG"

    def __init__(self, documents: list[CorpusDocument]) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE VIRTUAL TABLE graph_sections USING fts5(
                source UNINDEXED,
                content
            )
            """
        )
        self._sections: list[SectionRecord] = []
        self._entity_index: dict[str, set[str]] = defaultdict(set)
        self._index_documents(documents)

    def search(self, query: str, *, limit: int = 5) -> list[RetrievedItem]:
        fts_query = _build_fts_query(query)
        if not fts_query:
            return []

        matched_entities = [entity.lower() for entity in extract_entities(query)]
        candidate_sources: set[str] = set()
        for entity in matched_entities:
            candidate_sources.update(self._entity_index.get(entity, set()))

        rows = self._conn.execute(
            """
            SELECT rowid, source, content, bm25(graph_sections) AS score
            FROM graph_sections
            WHERE graph_sections MATCH ?
            ORDER BY score, rowid
            LIMIT 50
            """,
            (fts_query,),
        ).fetchall()

        ranked: list[tuple[tuple[int, int, float, int], RetrievedItem]] = []
        for row in rows:
            section = self._sections[row["rowid"] - 1]
            section_entity_matches = [
                entity for entity in matched_entities if entity in {value.lower() for value in section.entities}
            ]
            source_priority = 0 if not candidate_sources or section.source in candidate_sources else 1
            sort_key = (
                source_priority,
                -len(section_entity_matches),
                float(row["score"]),
                row["rowid"],
            )
            ranked.append(
                (
                    sort_key,
                    RetrievedItem(
                        content=row["content"],
                        source=row["source"],
                        rank=0,
                        metadata={
                            "matched_entities": section_entity_matches,
                            "section_index": section.section_index,
                        },
                    ),
                )
            )

        ranked.sort(key=lambda item: item[0])
        results: list[RetrievedItem] = []
        for index, (_, item) in enumerate(ranked[:limit], start=1):
            item.rank = index
            results.append(item)
        return results

    def close(self) -> None:
        self._conn.close()

    def _index_documents(self, documents: list[CorpusDocument]) -> None:
        for document in documents:
            for section_index, section in enumerate(document.sections):
                entities = extract_entities(section)
                for entity in entities:
                    self._entity_index[entity.lower()].add(document.filename)
                record = SectionRecord(
                    source=document.filename,
                    content=section,
                    section_index=section_index,
                    entities=entities,
                )
                self._sections.append(record)
                self._conn.execute(
                    "INSERT INTO graph_sections (source, content) VALUES (?, ?)",
                    (record.source, record.content),
                )


def extract_entities(text: str) -> list[str]:
    seen: set[str] = set()
    entities: list[str] = []
    for match in _ENTITY_RE.findall(text):
        if match in seen:
            continue
        seen.add(match)
        entities.append(match)
    return entities


def _build_fts_query(text: str) -> str:
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return ""
    return " AND ".join(f'"{token}"' for token in tokens)
