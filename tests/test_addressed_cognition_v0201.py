from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3

from akashik.expression import (
    apply_decay,
    decay_rate_for_tier,
    get_candidate_pool,
    get_effective_activation,
    get_effective_activations,
)
from akashik.identity import content_hash, normalized_hash
from akashik.ingest import MIN_TOKEN_LENGTH, ingest_text
from akashik.store import Store


def test_apply_decay_returns_original_when_last_expressed_is_none() -> None:
    assert apply_decay(1.5, 0.01, None) == 1.5


def test_apply_decay_returns_lower_weight_when_time_elapsed() -> None:
    past = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    assert apply_decay(1.0, 0.01, past) < 1.0


def test_apply_decay_never_returns_negative_value() -> None:
    past = (datetime.now(UTC) - timedelta(days=100000)).isoformat()
    assert apply_decay(1.0, 0.01, past) >= 0.0


def test_apply_decay_returns_approximately_original_weight_when_elapsed_zero() -> None:
    now = datetime.now(UTC).isoformat()
    assert abs(apply_decay(2.0, 0.01, now) - 2.0) < 1e-6


def test_apply_decay_guards_negative_elapsed_days() -> None:
    future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
    assert apply_decay(2.0, 0.01, future) == 2.0


def test_get_effective_activation_returns_decayed_weight(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "This fact should decay.", metadata={"instance_id": "decay-one"})
        fact_id = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "decay-one"})[0].id
        past = (datetime.now(UTC) - timedelta(days=20)).isoformat()
        store.execute(
            """
            UPDATE epigenetic_state
            SET activation_weight = 2.0,
                decay_rate = 0.01,
                last_expressed_at = ?
            WHERE fact_id = ?
            """,
            (past, fact_id),
        )

        effective = get_effective_activation(store, fact_id)

        assert 0.0 < effective < 2.0


def test_get_effective_activations_returns_multiple_weights(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "First activation fact.", metadata={"instance_id": "multi-one"})
        ingest_text(store, "Second activation fact.", metadata={"instance_id": "multi-two"})
        facts = store.fetch_by_metadata_filters(level="fact")
        first_id = next(f.id for f in facts if f.metadata.get("instance_id") == "multi-one")
        second_id = next(f.id for f in facts if f.metadata.get("instance_id") == "multi-two")
        past = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = 3.0, last_expressed_at = ? WHERE fact_id = ?",
            (past, first_id),
        )
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = 4.0, last_expressed_at = ? WHERE fact_id = ?",
            (past, second_id),
        )

        effective = get_effective_activations(store, [first_id, second_id])

        assert set(effective) == {first_id, second_id}
        assert effective[first_id] < 3.0
        assert effective[second_id] < 4.0


def test_fact_context_index_table_exists_with_columns_and_index(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        columns = {
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(fact_context_index)").fetchall()
        }
        indexes = {
            row["name"]
            for row in store._conn.execute("PRAGMA index_list(fact_context_index)").fetchall()
        }

        assert columns == {"fact_id", "index_type", "index_value"}
        assert "idx_fact_context" in indexes


def test_inserting_fact_populates_fact_context_index_with_topic_entries(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "Roadmap planning direction.",
            metadata={"instance_id": "topic-index"},
        )
        fact_id = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "topic-index"})[0].id

        rows = store._conn.execute(
            """
            SELECT index_type, index_value
            FROM fact_context_index
            WHERE fact_id = ?
            ORDER BY index_type, index_value
            """,
            (fact_id,),
        ).fetchall()

        entries = {(row["index_type"], row["index_value"]) for row in rows}
        assert ("topic", "roadmap") in entries
        assert ("topic", "planning") in entries
        assert ("topic", "direction") in entries


def test_short_tokens_are_not_written_to_fact_context_index(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "new roadmap plan", metadata={"instance_id": "short-token"})
        fact_id = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "short-token"})[0].id

        values = {
            row["index_value"]
            for row in store._conn.execute(
                "SELECT index_value FROM fact_context_index WHERE fact_id = ? AND index_type = 'topic'",
                (fact_id,),
            ).fetchall()
        }

        assert "new" not in values
        assert all(len(token) >= MIN_TOKEN_LENGTH for token in values)


def test_get_candidate_pool_returns_fact_ids_matching_context_entities_topics(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "Vehicle maintenance schedule.",
            metadata={"instance_id": "pool-hit", "entities": ["Subaru"], "thread": "personal"},
        )
        ingest_text(
            store,
            "Completely unrelated payment clause.",
            metadata={"instance_id": "pool-miss", "entities": ["Contract"]},
        )
        hit_id = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "pool-hit"})[0].id

        pool = get_candidate_pool(
            store,
            {"entities": ["Subaru"], "topics": ["maintenance"], "thread": "personal"},
        )

        assert hit_id in pool


def test_get_candidate_pool_returns_at_most_limit_results(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        for index in range(5):
            ingest_text(store, f"roadmap planning item {index}", metadata={"instance_id": f"limit-{index}"})

        pool = get_candidate_pool(store, {"topics": ["roadmap"]}, limit=3)

        assert len(pool) == 3


def test_get_candidate_pool_returns_at_most_max_raw_candidates_before_limit(tmp_path, monkeypatch) -> None:
    with Store(tmp_path / "store.db") as store:
        for index in range(5):
            ingest_text(store, f"roadmap planning item {index}", metadata={"instance_id": f"raw-{index}"})

        monkeypatch.setattr("akashik.expression.MAX_RAW_CANDIDATES", 2)
        pool = get_candidate_pool(store, {"topics": ["roadmap"]}, limit=10)

        assert len(pool) == 2


def test_get_candidate_pool_returns_results_ordered_by_activation_weight_desc(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "roadmap alpha item", metadata={"instance_id": "order-low"})
        ingest_text(store, "roadmap beta item", metadata={"instance_id": "order-high"})
        facts = {
            fact.metadata["instance_id"]: fact.id
            for fact in store.fetch_by_metadata_filters(level="fact")
            if fact.metadata.get("instance_id") in {"order-low", "order-high"}
        }
        old = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        new = datetime.now(UTC).isoformat()
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = 2.0, last_expressed_at = ? WHERE fact_id = ?",
            (old, facts["order-low"]),
        )
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = 5.0, last_expressed_at = ? WHERE fact_id = ?",
            (new, facts["order-high"]),
        )

        pool = get_candidate_pool(store, {"topics": ["roadmap"]}, limit=2)

        assert pool == [facts["order-high"], facts["order-low"]]


def test_get_candidate_pool_returns_empty_list_when_context_empty(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        assert get_candidate_pool(store, {}) == []


def test_decay_rate_for_tier_returns_expected_values() -> None:
    assert decay_rate_for_tier("episodic") == 0.01
    assert decay_rate_for_tier("semantic") == 0.005
    assert decay_rate_for_tier("procedural") == 0.001


def test_schema_migration_creates_fact_context_index_and_backfills_existing_facts(tmp_path) -> None:
    db_path = tmp_path / "legacy_v6.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memory_units (
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
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE epigenetic_state (
            fact_id TEXT PRIMARY KEY REFERENCES memory_units(id),
            activation_weight REAL DEFAULT 1.0,
            consolidation_tier TEXT NOT NULL DEFAULT 'episodic',
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
    conn.execute(
        """
        CREATE TABLE interaction_log (
            id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            raw_content TEXT NOT NULL,
            retrieved_fact_ids TEXT DEFAULT NULL,
            context_packet_hash TEXT DEFAULT NULL,
            user_correction INTEGER DEFAULT NULL,
            user_confirmed INTEGER DEFAULT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE memory_units_fts USING fts5(
            content,
            content='memory_units',
            content_rowid='fts_rowid',
            tokenize='unicode61 remove_diacritics 1'
        )
        """
    )
    conn.execute("PRAGMA user_version = 6")
    conn.execute(
        """
        INSERT INTO memory_units (
            id, level, content, content_hash, normalized_hash, lineage_parent_id, parent_id,
            metadata, embedding, section_heading, valid_from, valid_until,
            confirmation_count, last_confirmed_at
        ) VALUES (?, 'fact', ?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, NULL, 1, NULL)
        """,
        (
            "legacy-v6-fact",
            "Legacy roadmap planning fact",
            content_hash("Legacy roadmap planning fact"),
            normalized_hash("Legacy roadmap planning fact"),
            '{"entities": ["Subaru"], "thread": "personal"}',
        ),
    )
    conn.execute(
        "INSERT INTO epigenetic_state (fact_id) VALUES ('legacy-v6-fact')"
    )
    rowid = conn.execute(
        "SELECT fts_rowid FROM memory_units WHERE id = 'legacy-v6-fact'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO memory_units_fts (rowid, content) VALUES (?, ?)",
        (rowid, "Legacy roadmap planning fact"),
    )
    conn.commit()
    conn.close()

    with Store(db_path) as store:
        columns = {
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(fact_context_index)").fetchall()
        }
        rows = store._conn.execute(
            """
            SELECT index_type, index_value
            FROM fact_context_index
            WHERE fact_id = 'legacy-v6-fact'
            """
        ).fetchall()

        assert columns == {"fact_id", "index_type", "index_value"}
        assert ("topic", "roadmap") in {(row["index_type"], row["index_value"]) for row in rows}

