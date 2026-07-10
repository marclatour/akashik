from __future__ import annotations

from pathlib import Path

from akashik.identity import content_hash, normalized_hash
from akashik.ingest import build_fact_context_entries
from akashik.retrieve import _is_valid, retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store
from benchmark.longmemeval.run_longmemeval import _reset_store_contents


def _unit(
    content: str,
    *,
    metadata: dict | None = None,
    parent_id: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        level="fact",
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata={"source": "tests", "tags": [], **(metadata or {})},
        valid_from=valid_from,
        valid_until=valid_until,
    )


def test_is_valid_true_when_valid_until_none() -> None:
    unit = _unit("x", valid_until=None)
    assert _is_valid(unit) is True


def test_is_valid_true_when_valid_until_empty_string() -> None:
    unit = _unit("x", valid_until="")
    assert _is_valid(unit) is True


def test_is_valid_true_when_as_of_before_valid_until() -> None:
    unit = _unit("x", valid_until="2026-02-01T00:00:00")
    assert _is_valid(unit, "2026-01-31T00:00:00") is True


def test_is_valid_false_when_as_of_equals_valid_until() -> None:
    unit = _unit("x", valid_until="2026-02-01T00:00:00")
    assert _is_valid(unit, "2026-02-01T00:00:00") is False


def test_is_valid_false_when_as_of_after_valid_until() -> None:
    unit = _unit("x", valid_until="2026-02-01T00:00:00")
    assert _is_valid(unit, "2026-02-02T00:00:00") is False


def test_is_valid_fails_open_on_malformed_date() -> None:
    unit = _unit("x", valid_until="not-a-date")
    assert _is_valid(unit, "also-bad") is True


def test_retrieve_excludes_facts_with_expired_valid_until(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert(_unit("I live in Chicago.", valid_until="2026-01-01T00:00:00"))
        response = retrieve("I live in Chicago.", store, level="fact", as_of="2026-02-01T00:00:00")
        assert response.results == []


def test_retrieve_includes_facts_with_no_valid_until(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert(_unit("I live in Denver."))
        response = retrieve("I live in Denver.", store, level="fact", as_of="2026-02-01T00:00:00")
        assert [result.unit.content for result in response.results] == ["I live in Denver."]


def test_retrieve_includes_facts_with_future_valid_until(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert(_unit("I live in Denver.", valid_until="2026-03-01T00:00:00"))
        response = retrieve("I live in Denver.", store, level="fact", as_of="2026-02-01T00:00:00")
        assert [result.unit.content for result in response.results] == ["I live in Denver."]


def test_retrieve_as_of_filters_by_supplied_date_not_now(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert(_unit("I live in Denver.", valid_until="2026-03-01T00:00:00"))
        before = retrieve("I live in Denver.", store, level="fact", as_of="2026-02-01T00:00:00")
        after = retrieve("I live in Denver.", store, level="fact", as_of="2026-04-01T00:00:00")
        assert len(before.results) == 1
        assert after.results == []


def test_expired_high_activation_fact_is_not_returned(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        unit = store.insert(
            _unit(
                "I live in Chicago.",
                metadata={"ground_truth_facts": ["f001"], "entities": ["Chicago"]},
                valid_until="2026-01-01T00:00:00",
            )
        )
        store.insert_fact_context_entries(build_fact_context_entries(unit.content, unit.metadata), unit.id)
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = 9.0 WHERE fact_id = ?",
            (unit.id,),
        )
        response = retrieve(
            "live chicago",
            store,
            level="fact",
            use_expression=True,
            as_of="2026-02-01T00:00:00",
        )
        assert response.results == []


def test_reset_store_contents_clears_acmb_fact_id_index_before_memory_units(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        corpus = store.insert(
            MemoryUnit(
                level="corpus",
                content="c",
                content_hash=content_hash("c"),
                normalized_hash=normalized_hash("c"),
                metadata={"source": "tests", "tags": []},
            )
        )
        document = store.insert(
            MemoryUnit(
                level="document",
                content="d",
                content_hash=content_hash("d"),
                normalized_hash=normalized_hash("d"),
                parent_id=corpus.id,
                metadata={"source": "tests", "tags": []},
            )
        )
        fact = store.insert(
            _unit(
                "I live in Chicago.",
                parent_id=document.id,
                metadata={"ground_truth_facts": ["f001"]},
            )
        )
        store.execute(
            "INSERT OR IGNORE INTO acmb_fact_id_index (ground_truth_fact_id, memory_unit_id) VALUES (?, ?)",
            ("f001", fact.id),
        )
        _reset_store_contents(store)
        assert store._conn.execute("SELECT COUNT(*) FROM acmb_fact_id_index").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0] == 0


def test_validity_sql_never_filters_non_fact_levels(tmp_path: Path) -> None:
    with Store(tmp_path / "store.db") as store:
        closed_document = MemoryUnit(
            level="document",
            content="archived ledger of harbor closures",
            content_hash=content_hash("archived ledger of harbor closures"),
            normalized_hash=normalized_hash("archived ledger of harbor closures"),
            metadata={"source": "tests", "tags": []},
            valid_until="2020-01-01T00:00:00",
        )
        store.insert(closed_document)
        store.insert(
            _unit(
                "archived ledger entry about closures",
                valid_until="2020-01-01T00:00:00",
            )
        )

        results = store.search_fts("archived ledger", limit=10, current_only=True)

        levels = [unit.level for unit in results]
        assert "document" in levels
        assert "fact" not in levels


def test_is_valid_false_for_expired_tz_aware_valid_until() -> None:
    # A tz-aware valid_until used to raise TypeError against naive utcnow()
    # and fail open, keeping superseded facts alive forever.
    unit = _unit("x", valid_until="2020-01-01T00:00:00+00:00")
    assert _is_valid(unit) is False


def test_is_valid_mixed_naive_aware_as_of() -> None:
    unit = _unit("x", valid_until="2026-02-01T00:00:00+00:00")
    assert _is_valid(unit, "2026-01-31T00:00:00") is True
    assert _is_valid(unit, "2026-02-01T00:00:00") is False
