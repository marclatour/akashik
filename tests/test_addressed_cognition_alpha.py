from __future__ import annotations

import json
import sqlite3

from akashik.expression import express
from akashik.identity import content_hash, normalized_hash
from akashik.retrieve import _increment_edge, retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store


def _metadata() -> dict:
    return {"source": "tests", "session_id": "alpha-session"}


def _unit(
    level: str,
    content: str,
    *,
    parent_id: str | None = None,
    lineage_parent_id: str | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        lineage_parent_id=lineage_parent_id,
        parent_id=parent_id,
        metadata=_metadata(),
    )


def _doc_with_facts(store: Store, *contents: str) -> list[MemoryUnit]:
    document = store.insert(_unit("document", "Document"))
    section = store.insert(_unit("section", "Section", parent_id=document.id))
    return [store.insert(_unit("fact", content, parent_id=section.id)) for content in contents]


def test_lineage_parent_id_column_exists_and_defaults_null(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        columns = {
            row["name"]: row
            for row in store._conn.execute("PRAGMA table_info(memory_units)").fetchall()
        }
        assert "lineage_parent_id" in columns

        fact = _doc_with_facts(store, "alpha fact")[0]
        row = store._conn.execute(
            "SELECT lineage_parent_id FROM memory_units WHERE id = ?",
            (fact.id,),
        ).fetchone()
        assert row["lineage_parent_id"] is None


def test_inserting_fact_also_inserts_epigenetic_row_same_transaction(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_facts(store, "epigenetic fact")[0]

        row = store._conn.execute(
            "SELECT * FROM epigenetic_state WHERE fact_id = ?",
            (fact.id,),
        ).fetchone()

        assert row is not None
        assert row["fact_id"] == fact.id


def test_epigenetic_row_defaults(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_facts(store, "default fact")[0]

        row = store._conn.execute(
            """
            SELECT activation_weight, consolidation_tier, silenced
            FROM epigenetic_state
            WHERE fact_id = ?
            """,
            (fact.id,),
        ).fetchone()

        assert row["activation_weight"] == 1.0
        assert row["consolidation_tier"] == "episodic"
        assert row["silenced"] == 0


def test_interaction_log_table_exists_with_expected_columns(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        columns = {
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(interaction_log)").fetchall()
        }

        assert columns == {
            "id",
            "turn_id",
            "session_id",
            "timestamp",
            "actor",
            "raw_content",
            "retrieved_fact_ids",
            "context_packet_hash",
            "user_correction",
            "user_confirmed",
        }


def test_retrieval_updates_activation_weight_and_soft_reinforcement_count(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_facts(store, "The lantern code appears once.")[0]

        retrieve("The lantern code appears once.", store, level="fact")

        row = store._conn.execute(
            """
            SELECT activation_weight, soft_reinforcement_count, last_expressed_at
            FROM epigenetic_state
            WHERE fact_id = ?
            """,
            (fact.id,),
        ).fetchone()

        assert row["activation_weight"] > 1.0
        assert row["soft_reinforcement_count"] == 1
        assert row["last_expressed_at"] is not None


def test_retrieval_does_not_update_epigenetic_state_for_facts_not_returned(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        matched, unmatched = _doc_with_facts(
            store,
            "Matched content for retrieval.",
            "Completely unrelated fact.",
        )

        retrieve("Matched content for retrieval.", store, level="fact")

        matched_row = store._conn.execute(
            "SELECT soft_reinforcement_count FROM epigenetic_state WHERE fact_id = ?",
            (matched.id,),
        ).fetchone()
        unmatched_row = store._conn.execute(
            "SELECT soft_reinforcement_count FROM epigenetic_state WHERE fact_id = ?",
            (unmatched.id,),
        ).fetchone()

        assert matched_row["soft_reinforcement_count"] == 1
        assert unmatched_row["soft_reinforcement_count"] == 0


def test_activation_weight_is_capped_at_ten(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_facts(store, "Capped activation fact.")[0]
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = 9.95 WHERE fact_id = ?",
            (fact.id,),
        )

        retrieve("Capped activation fact.", store, level="fact")

        row = store._conn.execute(
            "SELECT activation_weight FROM epigenetic_state WHERE fact_id = ?",
            (fact.id,),
        ).fetchone()
        assert row["activation_weight"] <= 10.0


def test_coretrieved_facts_gain_association_edges(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        first, second = _doc_with_facts(
            store,
            "alpha keyword first fact",
            "alpha keyword second fact",
        )

        retrieve("alpha keyword", store, level="fact", limit=2)

        first_edges = json.loads(
            store._conn.execute(
                "SELECT association_edges FROM epigenetic_state WHERE fact_id = ?",
                (first.id,),
            ).fetchone()["association_edges"]
        )
        second_edges = json.loads(
            store._conn.execute(
                "SELECT association_edges FROM epigenetic_state WHERE fact_id = ?",
                (second.id,),
            ).fetchone()["association_edges"]
        )

        assert any(edge["fact_id"] == second.id for edge in first_edges)
        assert any(edge["fact_id"] == first.id for edge in second_edges)


def test_association_edges_are_capped_at_fifty_per_fact(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        source = _doc_with_facts(store, "source fact")[0]
        targets = _doc_with_facts(store, *[f"target fact {index}" for index in range(55)])

        for target in targets:
            _increment_edge(store, source.id, target.id, 0.1)

        row = store._conn.execute(
            "SELECT association_edges FROM epigenetic_state WHERE fact_id = ?",
            (source.id,),
        ).fetchone()
        edges = json.loads(row["association_edges"])

        assert len(edges) == 50


def test_expression_stub_returns_empty_list(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        assert express(store, "query", context={"thread": "personal"}) == []


def test_lineage_parent_id_round_trips_through_insert_and_retrieval(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        parent = _doc_with_facts(store, "Original fact.")[0]
        document = store.fetch_parent_chain(parent.id)[-1]
        section = store.fetch_parent_chain(parent.id)[0]
        successor = store.insert(
            _unit(
                "fact",
                "Superseding fact.",
                parent_id=section.id,
                lineage_parent_id=parent.id,
            )
        )

        fetched = store.fetch_by_id(successor.id)
        response = retrieve("Superseding fact.", store, level="fact")

        assert fetched is not None
        assert fetched.lineage_parent_id == parent.id
        assert response.results[0].unit.lineage_parent_id == parent.id
        assert document.level == "document"


def test_schema_migration_runs_cleanly_on_legacy_store(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
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
        CREATE VIRTUAL TABLE memory_units_fts USING fts5(
            content,
            content='memory_units',
            content_rowid='fts_rowid',
            tokenize='unicode61 remove_diacritics 1'
        )
        """
    )
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        """
        INSERT INTO memory_units (
            id, level, content, content_hash, normalized_hash, parent_id, metadata,
            embedding, section_heading, valid_from, valid_until,
            confirmation_count, last_confirmed_at
        ) VALUES (?, 'fact', ?, ?, ?, NULL, '{}', NULL, NULL, NULL, NULL, 1, NULL)
        """,
        (
            "legacy-fact",
            "Legacy fact",
            content_hash("Legacy fact"),
            normalized_hash("Legacy fact"),
        ),
    )
    rowid = conn.execute(
        "SELECT fts_rowid FROM memory_units WHERE id = 'legacy-fact'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO memory_units_fts (rowid, content) VALUES (?, ?)",
        (rowid, "Legacy fact"),
    )
    conn.commit()
    conn.close()

    with Store(db_path) as store:
        migrated_columns = {
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(memory_units)").fetchall()
        }
        epigenetic_row = store._conn.execute(
            "SELECT * FROM epigenetic_state WHERE fact_id = 'legacy-fact'"
        ).fetchone()

        assert "lineage_parent_id" in migrated_columns
        assert epigenetic_row is not None
