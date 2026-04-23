from __future__ import annotations

import pytest

from akashik.identity import content_hash, normalized_hash
from akashik.ingest import extract_section_heading
from akashik.schema import MemoryUnit
from akashik.store import AKASHIK_SCHEMA_VERSION, Store


def _metadata(source: str = "tests") -> dict:
    return {"source": source, "timestamp": "2026-04-14T00:00:00+00:00", "tags": []}


def _unit(
    level: str,
    content: str,
    parent_id: str | None = None,
    section_heading: str | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata=_metadata(),
        section_heading=section_heading,
    )


def test_store_initializes_tables_and_indexes(tmp_path) -> None:
    db_path = tmp_path / "store.db"
    with Store(db_path) as store:
        tables = {
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        assert "memory_units" in tables
        assert "memory_units_fts" in tables


def test_insert_fetch_and_parent_chain(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Akashik stores local documents."))
        section = store.insert(_unit("section", "Storage rules live here.", parent_id=document.id))
        fact_one = store.insert(_unit("fact", "SQLite keeps data local.", parent_id=section.id))
        fact_two = store.insert(_unit("fact", "Hash lookups run first.", parent_id=section.id))

        assert store.fetch_by_id(document.id) == document
        assert [child.id for child in store.fetch_children(section.id)] == [fact_one.id, fact_two.id]
        chain = store.fetch_parent_chain(fact_one.id)
        assert [unit.level for unit in chain] == ["section", "document"]
        assert store.fetch_by_content_hash(content_hash(document.content))[0].id == document.id
        normalized = store.fetch_by_normalized_hash(normalized_hash("sqlite keeps data local."))
        assert normalized[0].id == fact_one.id


def test_search_fts_and_stats(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Akashik persists memory locally."))
        store.insert(_unit("section", "SQLite powers keyword search.", parent_id=document.id))
        stats = store.stats()

        matches = store.search_fts("keyword search")
        assert matches
        assert matches[0].level == "section"
        assert stats.total == 2
        assert stats.by_level["document"] == 1
        assert stats.by_level["section"] == 1
        assert stats.by_level["fact"] == 0


def test_bulk_ingest_rebuilds_fts_and_fact_context_index(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Bulk ingest document."))
        section = store.insert(_unit("section", "Bulk ingest section.", parent_id=document.id))

        store.begin_bulk_ingest()
        try:
            store.insert(
                _unit(
                    "fact",
                    "I prefer steel lunchboxes with matching thermoses.",
                    parent_id=section.id,
                )
            )
            assert store.search_fts("steel lunchboxes") == []
            assert (
                store._conn.execute("SELECT COUNT(*) FROM fact_context_index").fetchone()[0] == 0
            )
        finally:
            store.end_bulk_ingest()

        matches = store.search_fts("steel lunchboxes")
        assert matches
        assert matches[0].level == "fact"
        assert (
            store._conn.execute("SELECT COUNT(*) FROM fact_context_index").fetchone()[0] > 0
        )


def test_section_heading_round_trips(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        unit = store.insert(_unit("fact", "Heading is a first-class field.", section_heading="Renewal Term"))

        fetched = store.fetch_by_id(unit.id)

        assert fetched is not None
        assert fetched.section_heading == "Renewal Term"


def test_null_section_heading_round_trips_as_none(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        unit = store.insert(_unit("fact", "Missing heading stays null."))

        fetched = store.fetch_by_id(unit.id)

        assert fetched is not None
        assert fetched.section_heading is None


def test_section_heading_extraction_only_considers_first_non_empty_line() -> None:
    assert extract_section_heading("\nRenewal Term\nThis section continues.") == "Renewal Term"
    assert extract_section_heading("This first line is a complete sentence.\nRenewal Term") is None


def test_insert_rolls_back_when_fts_write_fails(tmp_path, monkeypatch) -> None:
    with Store(tmp_path / "store.db") as store:
        unit = _unit("document", "This insert must stay atomic.")

        def broken_insert_fts_row(*_args) -> None:
            raise RuntimeError("fts write failed")

        monkeypatch.setattr(store, "_insert_fts_row", broken_insert_fts_row)

        with pytest.raises(RuntimeError, match="fts write failed"):
            store.insert(unit)

        assert store.fetch_by_id(unit.id) is None
        assert store._conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM memory_units_fts").fetchone()[0] == 0


def test_transaction_rolls_back_multiple_inserts(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        with pytest.raises(RuntimeError, match="ingest failed"):
            with store.transaction():
                document = store.insert(_unit("document", "Document inserted before failure."))
                store.insert(_unit("section", "Section inserted before failure.", parent_id=document.id))
                raise RuntimeError("ingest failed")

        assert store._conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM memory_units_fts").fetchone()[0] == 0


def test_invalid_parent_is_rejected(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        with pytest.raises(ValueError, match="Parent"):
            store.insert(_unit("fact", "Orphan fact.", parent_id="missing-parent"))


def test_increment_confirmation_updates_fields(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = store.insert(_unit("fact", "Confirmed fact."))

        store.increment_confirmation(fact.id, "2024-03-01")
        updated = store.fetch_by_id(fact.id)

        assert updated is not None
        assert updated.confirmation_count == 2
        assert updated.last_confirmed_at == "2024-03-01"


def test_increment_confirmation_never_touches_content(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = store.insert(_unit("fact", "Content must remain stable."))
        original_content_hash = fact.content_hash
        original_normalized_hash = fact.normalized_hash

        store.increment_confirmation(fact.id, "2024-03-01")
        updated = store.fetch_by_id(fact.id)

        assert updated is not None
        assert updated.content == fact.content
        assert updated.content_hash == original_content_hash
        assert updated.normalized_hash == original_normalized_hash


def test_schema_version_written_on_open(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        stored = store._conn.execute("PRAGMA user_version").fetchone()[0]

        assert stored == AKASHIK_SCHEMA_VERSION


def test_schema_version_mismatch_detected(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store._conn.execute("PRAGMA user_version = 0")
        stored = store._conn.execute("PRAGMA user_version").fetchone()[0]

        assert stored == 0
        assert store.schema_version_mismatch() is True


def test_schema_version_match(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        assert store.schema_version_mismatch() is False
