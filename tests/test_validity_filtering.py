from __future__ import annotations

from pathlib import Path

from akashik.identity import content_hash, normalized_hash
from akashik.ingest import build_fact_context_entries
from akashik.retrieve import _is_valid, retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store
from benchmark.acmb.adapters.akashik_adapter import AkashikAdapter
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
        unit = store.insert(_unit("I live in Chicago.", valid_until="2026-01-01T00:00:00"))
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


def test_close_superseded_facts_sets_valid_until_via_index(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Chicago.",
            "ground_truth_facts": ["f001"],
            "revises_facts": [],
            "simulated_date": "2026-01-01T00:00:00",
        }
    )
    rows = adapter.store._conn.execute(
        "SELECT memory_unit_id FROM acmb_fact_id_index WHERE ground_truth_fact_id = ?",
        ("f001",),
    ).fetchall()
    assert rows
    unit_id = rows[0][0]
    adapter._close_superseded_facts(["f001"], "2026-02-01T00:00:00")
    fetched = adapter.store.fetch_by_id(unit_id)
    assert fetched is not None
    assert fetched.valid_until == "2026-02-01T00:00:00"


def test_close_superseded_facts_does_not_affect_other_facts(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Chicago.",
            "ground_truth_facts": ["f001"],
            "revises_facts": [],
            "simulated_date": "2026-01-01T00:00:00",
        }
    )
    adapter.ingest_turn(
        {
            "turn_id": "t002",
            "actor": "user",
            "content": "I like coffee.",
            "ground_truth_facts": ["f002"],
            "revises_facts": [],
            "simulated_date": "2026-01-02T00:00:00",
        }
    )
    adapter._close_superseded_facts(["f001"], "2026-02-01T00:00:00")
    rows = adapter.store._conn.execute(
        """
        SELECT m.id, m.valid_until
        FROM memory_units m
        JOIN acmb_fact_id_index i ON i.memory_unit_id = m.id
        WHERE i.ground_truth_fact_id = ?
        """,
        ("f002",),
    ).fetchall()
    assert rows[0][1] is None


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


def test_end_to_end_revision_excludes_old_fact_and_includes_new_fact(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Chicago.",
            "ground_truth_facts": ["f001"],
            "revises_facts": [],
            "simulated_date": "2026-01-01T00:00:00",
        }
    )
    adapter.ingest_turn(
        {
            "turn_id": "t002",
            "actor": "user",
            "content": "I moved to Denver.",
            "ground_truth_facts": ["f002"],
            "revises_facts": ["f001"],
            "simulated_date": "2026-02-01T00:00:00",
        }
    )
    assert "f001" not in adapter.query("I live in Chicago.", as_of="2026-02-01T00:00:00")
    assert "f002" in adapter.query("I moved to Denver.", as_of="2026-02-01T00:00:00")


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
