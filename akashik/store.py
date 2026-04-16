"""SQLite-backed memory storage."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterator

from akashik.schema import LEVELS, LEVEL_INDEX, MemoryUnit, StoreStats, validate_level

# FTS5 row addressing must stay integer-based. UUID ids remain the only public identifiers.

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_units (
    fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    level TEXT NOT NULL CHECK(level IN ('corpus', 'document', 'section', 'fact')),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    normalized_hash TEXT NOT NULL,
    parent_id TEXT REFERENCES memory_units(id),
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding BLOB,
    section_heading TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_units_level ON memory_units(level);
CREATE INDEX IF NOT EXISTS idx_memory_units_content_hash ON memory_units(content_hash);
CREATE INDEX IF NOT EXISTS idx_memory_units_normalized_hash ON memory_units(normalized_hash);
CREATE INDEX IF NOT EXISTS idx_memory_units_parent_id ON memory_units(parent_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_units_fts USING fts5(
    content,
    content='memory_units',
    content_rowid='fts_rowid',
    tokenize='unicode61 remove_diacritics 1'
);
"""

_SELECT_COLUMNS = """
SELECT id, level, content, content_hash, normalized_hash, parent_id, metadata, embedding
       , section_heading
FROM memory_units
"""

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class Store:
    def __init__(self, db_path: str | Path = "./akashik.db") -> None:
        self.db_path = str(Path(db_path))
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def initialize(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)
            self._migrate_schema()

    def _migrate_schema(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(memory_units)").fetchall()
        }
        if "section_heading" not in columns:
            self._conn.execute("ALTER TABLE memory_units ADD COLUMN section_heading TEXT")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._conn.in_transaction:
            yield
            return
        self._conn.execute("BEGIN")
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def insert(self, unit: MemoryUnit) -> MemoryUnit:
        validate_level(unit.level)
        if unit.parent_id is not None and self.fetch_by_id(unit.parent_id) is None:
            raise ValueError(f"Parent {unit.parent_id!r} does not exist.")

        if self._conn.in_transaction:
            self._insert_unit(unit)
            return unit

        with self._conn:
            self._insert_unit(unit)
        return unit

    def _insert_unit(self, unit: MemoryUnit) -> None:
        fts_rowid = self._insert_main_row(unit)
        self._insert_fts_row(fts_rowid, unit)

    def _insert_main_row(self, unit: MemoryUnit) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO memory_units (
                id, level, content, content_hash, normalized_hash, parent_id, metadata,
                embedding, section_heading
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unit.id,
                unit.level,
                unit.content,
                unit.content_hash,
                unit.normalized_hash,
                unit.parent_id,
                json.dumps(unit.metadata, sort_keys=True),
                unit.embedding,
                unit.section_heading,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_fts_row(self, fts_rowid: int, unit: MemoryUnit) -> None:
        self._conn.execute(
            """
            INSERT INTO memory_units_fts (rowid, content)
            VALUES (?, ?)
            """,
            (fts_rowid, unit.content),
        )

    def fetch_by_id(self, unit_id: str) -> MemoryUnit | None:
        row = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE id = ?",
            (unit_id,),
        ).fetchone()
        return self._row_to_unit(row) if row else None

    def fetch_by_content_hash(self, hash_value: str) -> list[MemoryUnit]:
        rows = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE content_hash = ? ORDER BY fts_rowid",
            (hash_value,),
        ).fetchall()
        return [self._row_to_unit(row) for row in rows]

    def fetch_by_normalized_hash(self, hash_value: str) -> list[MemoryUnit]:
        rows = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE normalized_hash = ? ORDER BY fts_rowid",
            (hash_value,),
        ).fetchall()
        return [self._row_to_unit(row) for row in rows]

    def fetch_children(self, parent_id: str) -> list[MemoryUnit]:
        rows = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE parent_id = ? ORDER BY fts_rowid",
            (parent_id,),
        ).fetchall()
        return [self._row_to_unit(row) for row in rows]

    def fetch_parent_chain(self, unit_id: str) -> list[MemoryUnit]:
        chain: list[MemoryUnit] = []
        current = self.fetch_by_id(unit_id)
        while current and current.parent_id:
            parent = self.fetch_by_id(current.parent_id)
            if parent is None:
                break
            chain.append(parent)
            current = parent
        return chain

    def fetch_descendants_at_level(self, unit_id: str, level: str) -> list[MemoryUnit]:
        validate_level(level)
        unit = self.fetch_by_id(unit_id)
        if unit is None:
            return []
        target_depth = LEVEL_INDEX[level]
        start_depth = LEVEL_INDEX[unit.level]
        if start_depth >= target_depth:
            return []

        descendants: list[MemoryUnit] = []
        for child in self.fetch_children(unit_id):
            child_depth = LEVEL_INDEX[child.level]
            if child.level == level:
                descendants.append(child)
                continue
            if child_depth < target_depth:
                descendants.extend(self.fetch_descendants_at_level(child.id, level))
        return descendants

    def search_fts(self, query: str, limit: int = 20) -> list[MemoryUnit]:
        query_tokens = self._fts_tokens(query)
        fts_query = self._build_fts_query(query_tokens)
        if not fts_query:
            return []
        fetch_limit = max(limit * 50, 1000)
        rows = self._conn.execute(
            """
            SELECT m.id, m.level, m.content, m.content_hash, m.normalized_hash,
                   m.parent_id, m.metadata, m.embedding,
                   m.section_heading,
                   m.fts_rowid,
                   bm25(memory_units_fts) AS rank
            FROM memory_units_fts AS f
            JOIN memory_units AS m ON m.fts_rowid = f.rowid
            WHERE memory_units_fts MATCH ?
            ORDER BY bm25(memory_units_fts),
                     CASE m.level
                         WHEN 'fact' THEN 0
                         WHEN 'section' THEN 1
                         WHEN 'document' THEN 2
                         WHEN 'corpus' THEN 3
                         ELSE 4
                     END,
                     m.fts_rowid
            LIMIT ?
            """,
            (fts_query, fetch_limit),
        ).fetchall()

        scored_rows = []
        for row in rows:
            coverage = _token_coverage(query_tokens, row["content"])
            rank = float(row["rank"])
            rank_score = -rank if rank < 0 else 1.0 / (1.0 + rank)
            score = rank_score * coverage * _level_weight(row["level"])
            scored_rows.append(
                (
                    score,
                    coverage,
                    rank,
                    _level_priority(row["level"]),
                    int(row["fts_rowid"]),
                    row,
                )
            )

        scored_rows.sort(key=lambda item: (-item[0], -item[1], item[2], item[3], item[4]))
        return [self._row_to_unit(item[-1]) for item in scored_rows[:limit]]

    def stats(self) -> StoreStats:
        total = int(self._conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0])
        counts = {level: 0 for level in LEVELS}
        for row in self._conn.execute(
            "SELECT level, COUNT(*) AS count FROM memory_units GROUP BY level ORDER BY level"
        ):
            counts[row["level"]] = int(row["count"])
        return StoreStats(total=total, by_level=counts, db_path=self.db_path)

    def _fts_tokens(self, query: str) -> list[str]:
        tokens = _FTS_TOKEN_RE.findall(query.lower())
        deduped: list[str] = []
        for token in tokens:
            if token not in deduped:
                deduped.append(token)
        return deduped

    def _build_fts_query(self, tokens: list[str]) -> str:
        if not tokens:
            return ""
        return " OR ".join(f'"{token}"' for token in tokens)

    def _row_to_unit(self, row: sqlite3.Row) -> MemoryUnit:
        return MemoryUnit(
            id=row["id"],
            level=row["level"],
            content=row["content"],
            content_hash=row["content_hash"],
            normalized_hash=row["normalized_hash"],
            parent_id=row["parent_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            embedding=row["embedding"],
            section_heading=row["section_heading"],
        )


def _token_coverage(query_tokens: list[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = set(_FTS_TOKEN_RE.findall(content.lower()))
    matching_tokens = sum(1 for token in query_tokens if token in content_tokens)
    return matching_tokens / len(query_tokens)


def _level_priority(level: str) -> int:
    if level == "fact":
        return 0
    if level == "section":
        return 1
    if level == "document":
        return 2
    if level == "corpus":
        return 3
    return 4


def _level_weight(level: str) -> float:
    if level == "fact":
        return 1.0
    if level == "section":
        return 0.8
    if level == "document":
        return 0.45
    if level == "corpus":
        return 0.25
    return 0.1
