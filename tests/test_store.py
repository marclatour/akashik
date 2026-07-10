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


def test_fts_repaired_after_interrupted_bulk_ingest(tmp_path) -> None:
    db_path = tmp_path / "store.db"
    store = Store(db_path)
    store.begin_bulk_ingest()
    store.insert(_unit("fact", "The beacon fires at dawn."))
    store.insert(_unit("fact", "The harbor closes at dusk."))
    # Simulate a crash after a batch commit but before end_bulk_ingest():
    # the rows are durable, the FTS index never saw them.
    store._conn.commit()
    store._conn.close()

    with Store(db_path) as reopened:
        results = reopened.search_fts("beacon", limit=10)
        assert [unit.content for unit in results] == ["The beacon fires at dawn."]


def test_fetch_recent_facts_bounded_and_newest_first(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        for index in range(5):
            store.insert(_unit("fact", f"Fact number {index}."))
        store.insert(_unit("document", "Documents are excluded."))

        recent = store.fetch_recent_facts(3)

        assert [unit.content for unit in recent] == [
            "Fact number 4.",
            "Fact number 3.",
            "Fact number 2.",
        ]


def test_fetch_lineage_chain_linear(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        first = commit_fact(store, "Living in Chicago right now", session_date="2021-01-01")
        second = commit_fact(
            store, "Moved to New York City", supersedes=first.id, session_date="2023-01-01"
        )
        third = commit_fact(
            store, "Moved again to Boston", supersedes=second.id, session_date="2025-01-01"
        )

        for member in (first.id, second.id, third.id):
            chain = store.fetch_lineage_chain(member)
            assert [unit.id for unit in chain] == [first.id, second.id, third.id]


def test_fetch_lineage_chain_branching(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        root = commit_fact(store, "Original plan is option A", session_date="2026-01-01")
        branch_one = commit_fact(
            store, "Revised plan is option B", supersedes=root.id, session_date="2026-02-01"
        )
        branch_two = commit_fact(
            store, "Competing revision is option C", supersedes=root.id, session_date="2026-02-02"
        )

        chain_ids = {unit.id for unit in store.fetch_lineage_chain(branch_one.id)}
        assert chain_ids == {root.id, branch_one.id, branch_two.id}


def test_fetch_lineage_chain_unknown_id(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        assert store.fetch_lineage_chain("missing") == []


def test_session_items_roundtrip(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        items = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
        ]
        store.append_session_items("s1", items)
        store.append_session_items("s2", [{"role": "user", "content": "other session"}])

        assert store.get_session_items("s1") == items
        assert store.get_session_items("s1", limit=2) == items[1:]

        popped = store.pop_session_item("s1")
        assert popped == items[2]
        assert store.get_session_items("s1") == items[:2]

        store.clear_session_items("s1")
        assert store.get_session_items("s1") == []
        assert store.pop_session_item("s1") is None
        assert store.get_session_items("s2") == [{"role": "user", "content": "other session"}]


def test_default_db_path_env_override(tmp_path, monkeypatch) -> None:
    from akashik.store import default_db_path

    target = tmp_path / "custom" / "mem.db"
    monkeypatch.setenv("AKASHIK_DB", str(target))

    resolved = default_db_path()
    assert resolved == target
    assert resolved.parent.is_dir()


def test_default_db_path_falls_back_to_home(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from akashik.store import default_db_path

    monkeypatch.delenv("AKASHIK_DB", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    resolved = default_db_path()
    assert resolved == tmp_path / ".akashik" / "memory.db"
    assert resolved.parent.is_dir()


def test_store_uses_default_db_path(tmp_path, monkeypatch) -> None:
    target = tmp_path / "default.db"
    monkeypatch.setenv("AKASHIK_DB", str(target))

    with Store() as store:
        assert store.db_path == str(target)
    assert target.exists()


def test_concurrent_process_open_and_write(tmp_path) -> None:
    """Multiple agent processes share one store on a device; simultaneous
    first-opens must not crash on the WAL/schema-creation race."""
    import subprocess
    import sys

    db_path = tmp_path / "shared.db"
    script = (
        "import sys\n"
        "from akashik.ingest import commit_fact\n"
        "from akashik.store import Store\n"
        "with Store(sys.argv[1]) as store:\n"
        "    commit_fact(store, f'fact from agent {sys.argv[2]}', project=sys.argv[2])\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(db_path), f"agent{i}"],
            stderr=subprocess.PIPE,
        )
        for i in range(4)
    ]
    failures = []
    for proc in procs:
        _out, err = proc.communicate(timeout=60)
        if proc.returncode != 0:
            failures.append(err.decode())
    assert not failures, failures

    with Store(db_path) as store:
        facts = store.execute(
            "SELECT COUNT(*) FROM memory_units WHERE level='fact'"
        ).fetchone()[0]
        total = store.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0]
        fts = store.execute("SELECT COUNT(*) FROM memory_units_fts_docsize").fetchone()[0]
        assert facts == 4
        assert total == fts


def _barrier_commit_worker(db_path: str, barrier, agent: str, status) -> None:
    from akashik.ingest import commit_fact
    from akashik.store import Store

    try:
        with Store(db_path) as store:
            barrier.wait(timeout=30)
            for index in range(10):
                commit_fact(store, f"{agent} distinct fact {index}", project=agent)
    except Exception as exc:
        status.put(f"{agent}: {exc!r}")
        raise
    status.put(f"{agent}: ok")


def _barrier_retrieval_worker(db_path: str, barrier, status) -> None:
    # Not a pure reader: retrieve() commits activation bookkeeping, so this
    # exercises retrieval availability under write contention — not
    # concurrent WAL readership (raw SELECTs are the concurrent-read path).
    from akashik.retrieve import retrieve
    from akashik.store import Store

    try:
        with Store(db_path) as store:
            barrier.wait(timeout=30)
            for _ in range(30):
                retrieve("distinct fact", store, level="fact", limit=5)
    except Exception as exc:
        status.put(f"retrieval: {exc!r}")
        raise
    status.put("retrieval: ok")


def _barrier_reinforce_worker(db_path: str, barrier, status) -> None:
    from akashik.ingest import commit_fact
    from akashik.store import Store

    try:
        with Store(db_path) as store:
            barrier.wait(timeout=30)
            commit_fact(store, "the same shared fact", project="shared")
    except Exception as exc:
        status.put(f"reinforce: {exc!r}")
        raise
    status.put("reinforce: ok")


def _collect_statuses(queue, count: int) -> list[str]:
    # Queue.empty() is unreliable across processes; every worker reports
    # exactly one status, so consume that many with blocking gets.
    return [queue.get(timeout=60) for _ in range(count)]


def test_barrier_synchronized_concurrent_writers(tmp_path) -> None:
    """Writers must queue, not fail, when their transactions overlap.

    All processes open the store first, then release together on a barrier so
    the write transactions genuinely contend (a deferred BEGIN fails the
    second writer instantly on snapshot upgrade; BEGIN IMMEDIATE queues it)."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    db_path = str(tmp_path / "shared.db")
    status = ctx.Queue()
    barrier = ctx.Barrier(4)
    workers = [
        ctx.Process(target=_barrier_commit_worker, args=(db_path, barrier, f"agent{i}", status))
        for i in range(3)
    ]
    workers.append(ctx.Process(target=_barrier_retrieval_worker, args=(db_path, barrier, status)))
    for proc in workers:
        proc.start()
    statuses = _collect_statuses(status, len(workers))
    for proc in workers:
        proc.join(timeout=60)
        assert proc.exitcode == 0
    assert all(entry.endswith("ok") for entry in statuses), statuses
    with Store(db_path) as store:
        facts = store.execute(
            "SELECT COUNT(*) FROM memory_units WHERE level='fact'"
        ).fetchone()[0]
        total = store.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0]
        fts = store.execute("SELECT COUNT(*) FROM memory_units_fts_docsize").fetchone()[0]
        assert facts == 30
        assert total == fts


def test_concurrent_identical_commits_reinforce_once(tmp_path) -> None:
    """Reinforcement decisions serialize: N processes committing the same
    fact converge to one unit with N confirmations, never duplicates."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    db_path = str(tmp_path / "shared.db")
    status = ctx.Queue()
    barrier = ctx.Barrier(4)
    workers = [
        ctx.Process(target=_barrier_reinforce_worker, args=(db_path, barrier, status))
        for _ in range(4)
    ]
    for proc in workers:
        proc.start()
    statuses = _collect_statuses(status, len(workers))
    for proc in workers:
        proc.join(timeout=60)
        assert proc.exitcode == 0
    assert all(entry.endswith("ok") for entry in statuses), statuses
    with Store(db_path) as store:
        rows = store.execute(
            "SELECT confirmation_count FROM memory_units"
            " WHERE level='fact' AND content = 'the same shared fact'"
        ).fetchall()
        assert len(rows) == 1
        assert int(rows[0][0]) == 4
