"""SQLite-backed memory storage."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Iterator
import uuid

from akashik.schema import Commitment, LEVELS, LEVEL_INDEX, MemoryUnit, StoreStats, validate_level

# FTS5 row addressing must stay integer-based. UUID ids remain the only public identifiers.
AKASHIK_SCHEMA_VERSION = 9
BACKFILL_BATCH_SIZE = 100

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_units (
    fts_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    level TEXT NOT NULL CHECK(level IN ('corpus', 'document', 'section', 'fact')),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    normalized_hash TEXT NOT NULL,
    lineage_parent_id TEXT REFERENCES memory_units(id),
    parent_id TEXT REFERENCES memory_units(id),
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding BLOB,
    section_heading TEXT,
    valid_from TEXT,
    valid_until TEXT,
    confirmation_count INTEGER DEFAULT 1,
    last_confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_units_level ON memory_units(level);
CREATE INDEX IF NOT EXISTS idx_memory_units_content_hash ON memory_units(content_hash);
CREATE INDEX IF NOT EXISTS idx_memory_units_normalized_hash ON memory_units(normalized_hash);
CREATE INDEX IF NOT EXISTS idx_memory_units_parent_id ON memory_units(parent_id);
CREATE INDEX IF NOT EXISTS idx_validity ON memory_units(valid_until);

CREATE TABLE IF NOT EXISTS epigenetic_state (
    fact_id TEXT PRIMARY KEY REFERENCES memory_units(id),
    activation_weight REAL DEFAULT 1.0,
    consolidation_tier TEXT NOT NULL DEFAULT 'episodic'
        CHECK(consolidation_tier IN ('episodic', 'semantic', 'procedural')),
    promoter_conditions TEXT DEFAULT NULL,
    repressor_conditions TEXT DEFAULT NULL,
    decay_rate REAL DEFAULT 0.01,
    reinforcement_count INTEGER DEFAULT 0,
    soft_reinforcement_count INTEGER DEFAULT 0,
    silenced INTEGER DEFAULT 0,
    silence_until TEXT DEFAULT NULL,
    last_expressed_at TEXT DEFAULT NULL,
    association_edges TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS interaction_log (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL CHECK(actor IN ('user', 'assistant', 'tool')),
    raw_content TEXT NOT NULL,
    retrieved_fact_ids TEXT DEFAULT NULL,
    context_packet_hash TEXT DEFAULT NULL,
    user_correction INTEGER DEFAULT NULL,
    user_confirmed INTEGER DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS fact_context_index (
    fact_id TEXT NOT NULL REFERENCES memory_units(id),
    index_type TEXT NOT NULL,
    index_value TEXT NOT NULL,
    PRIMARY KEY (fact_id, index_type, index_value)
);
CREATE INDEX IF NOT EXISTS idx_fact_context ON fact_context_index(index_type, index_value);

CREATE TABLE IF NOT EXISTS acmb_fact_id_index (
    ground_truth_fact_id TEXT NOT NULL,
    memory_unit_id TEXT NOT NULL,
    PRIMARY KEY (ground_truth_fact_id, memory_unit_id)
);
CREATE INDEX IF NOT EXISTS idx_acmb_fact_id ON acmb_fact_id_index(ground_truth_fact_id);

CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    source_turn_id TEXT,
    session_id TEXT,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
    related_facts TEXT,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status);
CREATE INDEX IF NOT EXISTS idx_commitments_session ON commitments(session_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_units_fts USING fts5(
    content,
    content='memory_units',
    content_rowid='fts_rowid',
    tokenize='unicode61 remove_diacritics 1'
);
"""

_SELECT_COLUMNS = """
SELECT id, level, content, content_hash, normalized_hash, lineage_parent_id, parent_id, metadata, embedding
       , section_heading
       , valid_from, valid_until
       , confirmation_count, last_confirmed_at
FROM memory_units
"""

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
LOGGER = logging.getLogger(__name__)


class Store:
    def __init__(self, db_path: str | Path = "./akashik.db") -> None:
        self.db_path = str(Path(db_path))
        db_file = Path(self.db_path)
        self._db_preexisting = db_file.exists() and db_file.stat().st_size > 0
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._bulk_ingest_mode = False
        self._bulk_ingest_batch_open = False
        self._bulk_ingest_fact_count = 0
        self._opened_user_version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        self.initialize()

    def initialize(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA_SQL)
            self._migrate_schema()
            self._conn.execute(f"PRAGMA user_version = {AKASHIK_SCHEMA_VERSION}")
        if self._db_preexisting and self._opened_user_version != AKASHIK_SCHEMA_VERSION:
            self._warn_schema_mismatch(self._opened_user_version)

    def _migrate_schema(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(memory_units)").fetchall()
        }
        if "lineage_parent_id" not in columns:
            self._conn.execute("ALTER TABLE memory_units ADD COLUMN lineage_parent_id TEXT REFERENCES memory_units(id)")
        if "section_heading" not in columns:
            self._conn.execute("ALTER TABLE memory_units ADD COLUMN section_heading TEXT")
        if "valid_from" not in columns:
            self._conn.execute("ALTER TABLE memory_units ADD COLUMN valid_from TEXT")
        if "valid_until" not in columns:
            self._conn.execute("ALTER TABLE memory_units ADD COLUMN valid_until TEXT")
        if "confirmation_count" not in columns:
            self._conn.execute(
                "ALTER TABLE memory_units ADD COLUMN confirmation_count INTEGER DEFAULT 1"
            )
        if "last_confirmed_at" not in columns:
            self._conn.execute("ALTER TABLE memory_units ADD COLUMN last_confirmed_at TEXT")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS epigenetic_state (
                fact_id TEXT PRIMARY KEY REFERENCES memory_units(id),
                activation_weight REAL DEFAULT 1.0,
                consolidation_tier TEXT NOT NULL DEFAULT 'episodic'
                    CHECK(consolidation_tier IN ('episodic', 'semantic', 'procedural')),
                promoter_conditions TEXT DEFAULT NULL,
                repressor_conditions TEXT DEFAULT NULL,
                decay_rate REAL DEFAULT 0.01,
                reinforcement_count INTEGER DEFAULT 0,
                soft_reinforcement_count INTEGER DEFAULT 0,
                silenced INTEGER DEFAULT 0,
                silence_until TEXT DEFAULT NULL,
                last_expressed_at TEXT DEFAULT NULL,
                association_edges TEXT DEFAULT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interaction_log (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                actor TEXT NOT NULL CHECK(actor IN ('user', 'assistant', 'tool')),
                raw_content TEXT NOT NULL,
                retrieved_fact_ids TEXT DEFAULT NULL,
                context_packet_hash TEXT DEFAULT NULL,
                user_correction INTEGER DEFAULT NULL,
                user_confirmed INTEGER DEFAULT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fact_context_index (
                fact_id TEXT NOT NULL REFERENCES memory_units(id),
                index_type TEXT NOT NULL,
                index_value TEXT NOT NULL,
                PRIMARY KEY (fact_id, index_type, index_value)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS acmb_fact_id_index (
                ground_truth_fact_id TEXT NOT NULL,
                memory_unit_id TEXT NOT NULL,
                PRIMARY KEY (ground_truth_fact_id, memory_unit_id)
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_validity ON memory_units(valid_until)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_units_lineage_parent_id ON memory_units(lineage_parent_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fact_context ON fact_context_index(index_type, index_value)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_acmb_fact_id ON acmb_fact_id_index(ground_truth_fact_id)"
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commitments (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                source_turn_id TEXT,
                session_id TEXT,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
                related_facts TEXT,
                metadata TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_commitments_session ON commitments(session_id)"
        )
        self._conn.execute(
            """
            INSERT INTO epigenetic_state (fact_id)
            SELECT memory_units.id
            FROM memory_units
            LEFT JOIN epigenetic_state ON epigenetic_state.fact_id = memory_units.id
            WHERE memory_units.level = 'fact'
              AND epigenetic_state.fact_id IS NULL
            """
        )
        self._backfill_fact_context_index()

    def close(self) -> None:
        self._conn.close()

    def begin_bulk_ingest(self) -> None:
        """Switch the store into a faster ingest mode for corpus loading."""
        if self._bulk_ingest_mode:
            return
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA cache_size = -65536")
        self._bulk_ingest_mode = True
        self._bulk_ingest_batch_open = False
        self._bulk_ingest_fact_count = 0

    def end_bulk_ingest(self) -> None:
        """Finalize deferred secondary indexes after bulk ingest completes."""
        if not self._bulk_ingest_mode:
            return
        try:
            if self._bulk_ingest_batch_open and self._conn.in_transaction:
                self._conn.commit()
            self._bulk_ingest_batch_open = False
            self._bulk_ingest_fact_count = 0
            self._bulk_ingest_mode = False
            with self.transaction():
                self._conn.execute(
                    "INSERT INTO memory_units_fts(memory_units_fts) VALUES('rebuild')"
                )
                self._backfill_fact_context_index()
            self._conn.execute("PRAGMA synchronous = FULL")
            self._conn.execute("PRAGMA cache_size = -2000")
        finally:
            self._bulk_ingest_batch_open = False
            self._bulk_ingest_fact_count = 0
            self._bulk_ingest_mode = False

    def schema_version_mismatch(self) -> bool:
        stored = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        mismatch = stored != AKASHIK_SCHEMA_VERSION or (
            self._db_preexisting and self._opened_user_version != AKASHIK_SCHEMA_VERSION
        )
        if mismatch:
            self._warn_schema_mismatch(stored)
        return mismatch

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

        if self._conn.in_transaction and not self._bulk_ingest_batch_open:
            self._insert_unit(unit)
            return unit

        if self._bulk_ingest_mode:
            if not self._bulk_ingest_batch_open:
                self._conn.execute("BEGIN")
                self._bulk_ingest_batch_open = True
            try:
                self._insert_unit(unit)
                if unit.level == "fact":
                    self._bulk_ingest_fact_count += 1
            except Exception:
                if self._bulk_ingest_batch_open and self._conn.in_transaction:
                    self._conn.rollback()
                self._bulk_ingest_batch_open = False
                self._bulk_ingest_fact_count = 0
                raise
            if self._bulk_ingest_fact_count >= BACKFILL_BATCH_SIZE:
                self._conn.commit()
                self._bulk_ingest_batch_open = False
                self._bulk_ingest_fact_count = 0
            return unit

        with self._conn:
            self._insert_unit(unit)
        return unit

    def _insert_unit(self, unit: MemoryUnit) -> None:
        fts_rowid = self._insert_main_row(unit)
        if not self._bulk_ingest_mode:
            self._insert_fts_row(fts_rowid, unit)
        self._insert_epigenetic_row(unit)

    def _insert_main_row(self, unit: MemoryUnit) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO memory_units (
                id, level, content, content_hash, normalized_hash, lineage_parent_id, parent_id, metadata,
                embedding, section_heading, valid_from, valid_until,
                confirmation_count, last_confirmed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unit.id,
                unit.level,
                unit.content,
                unit.content_hash,
                unit.normalized_hash,
                unit.lineage_parent_id,
                unit.parent_id,
                json.dumps(unit.metadata, sort_keys=True),
                unit.embedding,
                unit.section_heading,
                unit.valid_from,
                unit.valid_until,
                unit.confirmation_count,
                unit.last_confirmed_at,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_epigenetic_row(self, unit: MemoryUnit) -> None:
        if unit.level != "fact":
            return
        from akashik.expression import decay_rate_for_tier

        self._conn.execute(
            """
            INSERT INTO epigenetic_state (fact_id, decay_rate)
            VALUES (?, ?)
            """,
            (unit.id, decay_rate_for_tier("episodic")),
        )

    def insert_fact_context_entries(
        self,
        entries: list[tuple[str, str]],
        fact_id: str,
    ) -> None:
        if not entries or self._bulk_ingest_mode:
            return
        self.executemany(
            """
            INSERT OR IGNORE INTO fact_context_index (fact_id, index_type, index_value)
            VALUES (?, ?, ?)
            """,
            [(fact_id, index_type, index_value) for index_type, index_value in entries],
        )

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

    def get_facts_by_ids(self, fact_ids: list[str]) -> list[MemoryUnit]:
        if not fact_ids:
            return []
        placeholders = ", ".join("?" for _ in fact_ids)
        rows = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE id IN ({placeholders}) ORDER BY fts_rowid",
            tuple(fact_ids),
        ).fetchall()
        by_id = {str(row["id"]): self._row_to_unit(row) for row in rows}
        return [by_id[fact_id] for fact_id in fact_ids if fact_id in by_id]

    def get_epigenetic(self, fact_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT fact_id, activation_weight, consolidation_tier, promoter_conditions,
                   repressor_conditions, decay_rate, reinforcement_count,
                   soft_reinforcement_count, silenced, silence_until,
                   last_expressed_at, association_edges
            FROM epigenetic_state
            WHERE fact_id = ?
            """,
            (fact_id,),
        ).fetchone()
        return dict(row) if row else None

    def insert_commitment(self, commitment: Commitment) -> str:
        self.execute(
            """
            INSERT INTO commitments (
                id, description, source_turn_id, session_id, opened_at,
                closed_at, status, related_facts, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                commitment.id,
                commitment.description,
                commitment.source_turn_id,
                commitment.session_id,
                commitment.opened_at,
                commitment.closed_at,
                commitment.status,
                json.dumps(commitment.related_facts),
                json.dumps(commitment.metadata, sort_keys=True),
            ),
        )
        return commitment.id

    def get_open_commitments(self) -> list[Commitment]:
        rows = self._conn.execute(
            """
            SELECT id, description, source_turn_id, session_id, opened_at,
                   closed_at, status, related_facts, metadata
            FROM commitments
            WHERE status = 'open'
            ORDER BY opened_at DESC, id DESC
            """
        ).fetchall()
        return [self._row_to_commitment(row) for row in rows]

    def close_commitment(self, commitment_id: str, closed_at: str) -> None:
        self.execute(
            """
            UPDATE commitments
            SET status = 'closed',
                closed_at = ?
            WHERE id = ?
            """,
            (closed_at, commitment_id),
        )

    def get_commitments_by_session(self, session_id: str) -> list[Commitment]:
        rows = self._conn.execute(
            """
            SELECT id, description, source_turn_id, session_id, opened_at,
                   closed_at, status, related_facts, metadata
            FROM commitments
            WHERE session_id = ?
            ORDER BY opened_at DESC, id DESC
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_commitment(row) for row in rows]

    def fetch_by_content_hash(
        self,
        hash_value: str,
        *,
        current_only: bool = False,
        as_of: str | None = None,
    ) -> list[MemoryUnit]:
        validity_sql, params = self._validity_sql(
            alias="memory_units",
            current_only=current_only,
            as_of=as_of,
        )
        rows = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE content_hash = ?{validity_sql} ORDER BY fts_rowid",
            (hash_value, *params),
        ).fetchall()
        return [self._row_to_unit(row) for row in rows]

    def fetch_by_normalized_hash(
        self,
        hash_value: str,
        *,
        current_only: bool = False,
        as_of: str | None = None,
    ) -> list[MemoryUnit]:
        validity_sql, params = self._validity_sql(
            alias="memory_units",
            current_only=current_only,
            as_of=as_of,
        )
        rows = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE normalized_hash = ?{validity_sql} ORDER BY fts_rowid",
            (hash_value, *params),
        ).fetchall()
        return [self._row_to_unit(row) for row in rows]

    def fetch_children(self, parent_id: str) -> list[MemoryUnit]:
        rows = self._conn.execute(
            f"{_SELECT_COLUMNS} WHERE parent_id = ? ORDER BY fts_rowid",
            (parent_id,),
        ).fetchall()
        return [self._row_to_unit(row) for row in rows]

    def fetch_by_metadata_filters(
        self,
        *,
        level: str | None = None,
        filters: dict[str, str | list[str]] | None = None,
    ) -> list[MemoryUnit]:
        if level is not None:
            validate_level(level)
        filters = filters or {}
        sql = [_SELECT_COLUMNS.strip(), "WHERE 1 = 1"]
        params: list[object] = []
        if level is not None:
            sql.append("AND level = ?")
            params.append(level)
        where_sql, where_params = self._metadata_filter_sql(filters)
        if where_sql:
            sql.append(where_sql)
            params.extend(where_params)
        sql.append("ORDER BY fts_rowid")
        rows = self._conn.execute("\n".join(sql), tuple(params)).fetchall()
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

    def search_fts(
        self,
        query: str,
        limit: int = 20,
        *,
        current_only: bool = False,
        as_of: str | None = None,
    ) -> list[MemoryUnit]:
        query_tokens = self._fts_tokens(query)
        fts_query = self._build_fts_query(query_tokens)
        if not fts_query:
            return []
        fetch_limit = max(limit * 50, 1000)
        validity_sql, validity_params = self._validity_sql(
            alias="m",
            current_only=current_only,
            as_of=as_of,
        )
        rows = self._conn.execute(
            """
            SELECT m.id, m.level, m.content, m.content_hash, m.normalized_hash,
                   m.lineage_parent_id, m.parent_id, m.metadata, m.embedding,
                   m.section_heading,
                   m.valid_from, m.valid_until,
                   m.confirmation_count, m.last_confirmed_at,
                   m.fts_rowid,
                   bm25(memory_units_fts) AS rank
            FROM memory_units_fts AS f
            JOIN memory_units AS m ON m.fts_rowid = f.rowid
            WHERE memory_units_fts MATCH ?
            """
            + validity_sql
            + """
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
            (fts_query, *validity_params, fetch_limit),
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

    def _metadata_filter_sql(
        self,
        filters: dict[str, str | list[str]],
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, list):
                values = [item for item in value if item not in (None, "")]
                if not values:
                    return "AND 1 = 0", []
                placeholders = ", ".join("?" for _ in values)
                if key == "document_id":
                    clauses.append(f"AND id IN ({placeholders})")
                    params.extend(values)
                    continue
                clauses.append(f"AND json_extract(metadata, ?) IN ({placeholders})")
                params.append(f"$.{key}")
                params.extend(values)
                continue
            if key == "document_id":
                clauses.append("AND id = ?")
                params.append(value)
                continue
            clauses.append("AND json_extract(metadata, ?) = ?")
            params.append(f"$.{key}")
            params.append(value)
        return "\n".join(clauses), params

    def close_fact(self, fact_id: str, valid_until: str) -> None:
        self._conn.execute(
            """
            UPDATE memory_units
            SET valid_until = ?
            WHERE id = ?
              AND level = 'fact'
            """,
            (valid_until, fact_id),
        )

    def increment_confirmation(self, fact_id: str, confirmed_at: str) -> None:
        self._conn.execute(
            """
            UPDATE memory_units
            SET confirmation_count = COALESCE(confirmation_count, 1) + 1,
                last_confirmed_at = ?
            WHERE id = ?
              AND level = 'fact'
            """,
            (confirmed_at, fact_id),
        )

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        if self._conn.in_transaction:
            return self._conn.execute(sql, params)
        with self._conn:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq_of_params) -> sqlite3.Cursor:
        params = list(seq_of_params)
        if not params:
            return self._conn.executemany(sql, [])
        if self._conn.in_transaction:
            return self._conn.executemany(sql, params)
        with self._conn:
            return self._conn.executemany(sql, params)

    def log_interaction(self, record: dict) -> None:
        """Write one record to interaction_log. Best-effort."""
        self.execute(
            """
            INSERT OR IGNORE INTO interaction_log
            (id, turn_id, session_id, timestamp, actor, raw_content,
             retrieved_fact_ids, context_packet_hash, user_correction, user_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                record.get("turn_id"),
                record.get("session_id"),
                record.get("timestamp"),
                record.get("actor"),
                record.get("raw_content"),
                record.get("retrieved_fact_ids"),
                record.get("context_packet_hash"),
                record.get("user_correction"),
                record.get("user_confirmed"),
            ),
        )

    def _validity_sql(
        self,
        *,
        alias: str,
        current_only: bool,
        as_of: str | None,
    ) -> tuple[str, list[object]]:
        if as_of:
            return (
                f"\n              AND ({alias}.level != 'fact' OR ({alias}.valid_from IS NULL OR {alias}.valid_from <= ?) AND ({alias}.valid_until IS NULL OR {alias}.valid_until > ?))",
                [as_of, as_of],
            )
        if current_only:
            return (
                f"\n              AND ({alias}.level != 'fact' OR {alias}.valid_until IS NULL)",
                [],
            )
        return ("", [])

    def _row_to_unit(self, row: sqlite3.Row) -> MemoryUnit:
        keys = set(row.keys())
        return MemoryUnit(
            id=row["id"],
            level=row["level"],
            content=row["content"],
            content_hash=row["content_hash"],
            normalized_hash=row["normalized_hash"],
            lineage_parent_id=row["lineage_parent_id"] if "lineage_parent_id" in keys else None,
            parent_id=row["parent_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            embedding=row["embedding"],
            section_heading=row["section_heading"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            confirmation_count=int(row["confirmation_count"] or 1) if "confirmation_count" in keys else 1,
            last_confirmed_at=row["last_confirmed_at"] if "last_confirmed_at" in keys else None,
        )

    def _row_to_commitment(self, row: sqlite3.Row) -> Commitment:
        return Commitment(
            id=str(row["id"]),
            description=str(row["description"]),
            source_turn_id=row["source_turn_id"],
            session_id=row["session_id"],
            opened_at=str(row["opened_at"]),
            closed_at=row["closed_at"],
            status=str(row["status"]),
            related_facts=json.loads(row["related_facts"]) if row["related_facts"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def _warn_schema_mismatch(self, stored: int) -> None:
        if stored == AKASHIK_SCHEMA_VERSION:
            return
        LOGGER.warning(
            "store %s has schema version %s, current is %s — will reingest",
            self.db_path,
            stored,
            AKASHIK_SCHEMA_VERSION,
        )

    def _backfill_fact_context_index(self) -> None:
        missing = self._conn.execute(
            """
            SELECT 1
            FROM memory_units m
            WHERE m.level = 'fact'
              AND NOT EXISTS (
                SELECT 1
                FROM fact_context_index fci
                WHERE fci.fact_id = m.id
              )
            LIMIT 1
            """
        ).fetchone()
        if missing is None:
            return
        rows = self._conn.execute(
            """
            SELECT id, content, metadata
            FROM memory_units
            WHERE level = 'fact'
            ORDER BY fts_rowid
            """
        ).fetchall()
        total = len(rows)
        if total == 0:
            return
        from akashik.ingest import build_fact_context_entries

        for offset in range(0, total, BACKFILL_BATCH_SIZE):
            batch = rows[offset : offset + BACKFILL_BATCH_SIZE]
            insert_rows: list[tuple[str, str, str]] = []
            for row in batch:
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                entries = build_fact_context_entries(row["content"], metadata)
                insert_rows.extend(
                    (str(row["id"]), index_type, index_value)
                    for index_type, index_value in entries
                )
            if insert_rows:
                self._conn.executemany(
                    """
                    INSERT OR IGNORE INTO fact_context_index (fact_id, index_type, index_value)
                    VALUES (?, ?, ?)
                    """,
                    insert_rows,
                )
            LOGGER.info(
                "Backfilling fact_context_index: %s / %s",
                min(offset + BACKFILL_BATCH_SIZE, total),
                total,
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
