from __future__ import annotations

from akashik.ingest import ingest_text
from akashik.store import Store


def test_ingest_sets_valid_from(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2022-01-01"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})

        assert len(facts) == 1
        assert facts[0].valid_from == "2022-01-01"


def test_ingest_contradiction_closes_old_fact(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2022-01-01"},
        )
        ingest_text(
            store,
            "I live in New York.",
            metadata={"instance_id": "test", "session_date": "2024-06-01"},
        )

        facts = sorted(
            store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"}),
            key=lambda unit: unit.valid_from or "",
        )

        assert facts[0].content == "I live in Chicago."
        assert facts[0].valid_until == "2024-06-01"
        assert facts[1].content == "I live in New York."
        assert facts[1].valid_until is None


def test_ingest_no_contradiction_on_same_value(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2022-01-01"},
        )
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2024-06-01"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})

        assert len(facts) == 1
        assert facts[0].valid_until is None


def test_reinforcement_increments_count(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2023-01-01"},
        )
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2024-03-01"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})

        assert len(facts) == 1
        assert facts[0].confirmation_count == 2


def test_reinforcement_updates_last_confirmed(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2023-01-01"},
        )
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2024-03-01"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})

        assert facts[0].last_confirmed_at == "2024-03-01"


def test_reinforcement_does_not_modify_content(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2023-01-01"},
        )
        original = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})[0]

        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2024-03-01"},
        )
        updated = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})[0]

        assert updated.content == original.content
        assert updated.content_hash == original.content_hash
        assert updated.valid_from == original.valid_from


def test_new_fact_starts_at_count_1(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata={"instance_id": "test", "session_date": "2023-01-01"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})

        assert len(facts) == 1
        assert facts[0].confirmation_count == 1


def test_commit_fact_inserts_typed_fact(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        unit = commit_fact(
            store,
            "Episode 1 launches Friday",
            fact_type="decision",
            project="human_in_the_loop",
            session_date="2026-07-01",
        )

        stored = store.fetch_by_id(unit.id)
        assert stored is not None
        assert stored.level == "fact"
        assert stored.metadata["fact_type"] == "decision"
        assert stored.metadata["project"] == "human_in_the_loop"
        assert stored.valid_from == "2026-07-01"
        assert stored.valid_until is None

        chain = store.fetch_parent_chain(stored.id)
        assert [parent.level for parent in chain] == ["section", "document"]

        hits = store.search_fts("episode launches friday")
        assert any(hit.id == stored.id for hit in hits)


def test_commit_fact_rejects_invalid_input(tmp_path) -> None:
    import pytest

    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        with pytest.raises(ValueError, match="non-empty"):
            commit_fact(store, "   ")
        with pytest.raises(ValueError, match="fact_type"):
            commit_fact(store, "something", fact_type="musing")
        with pytest.raises(ValueError, match="unknown fact"):
            commit_fact(store, "something", supersedes="not-a-real-id")


def test_commit_fact_supersession_closes_and_links(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        first = commit_fact(
            store,
            "Ship episode one on Friday",
            fact_type="action_item",
            project="show",
            session_date="2026-07-01",
        )
        second = commit_fact(
            store,
            "Episode one shipped Saturday",
            fact_type="outcome",
            project="show",
            supersedes=first.id,
            session_date="2026-07-05",
        )

        old = store.fetch_by_id(first.id)
        new = store.fetch_by_id(second.id)
        assert old is not None and new is not None
        assert old.valid_until == "2026-07-05"
        assert new.lineage_parent_id == first.id
        assert new.valid_until is None


def test_commit_fact_restatement_reinforces(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        first = commit_fact(store, "The theme song is surf rock", session_date="2026-07-01")
        second = commit_fact(store, "The theme song is surf rock", session_date="2026-07-03")

        assert second.id == first.id
        stored = store.fetch_by_id(first.id)
        assert stored.confirmation_count == 2
        assert stored.last_confirmed_at == "2026-07-03"


def test_commit_fact_supersession_always_creates_lineage_node(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        first = commit_fact(store, "Use the red thumbnail", session_date="2026-07-01")
        second = commit_fact(
            store,
            "Use the red thumbnail",
            supersedes=first.id,
            session_date="2026-07-02",
        )

        assert second.id != first.id
        assert second.lineage_parent_id == first.id


def test_commit_fact_same_text_different_scope_stays_distinct(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        in_show = commit_fact(
            store, "Use the red thumbnail", project="show", session_date="2026-07-01"
        )
        in_blog = commit_fact(
            store, "Use the red thumbnail", project="blog", session_date="2026-07-02"
        )
        as_constraint = commit_fact(
            store,
            "Use the red thumbnail",
            fact_type="constraint",
            project="show",
            session_date="2026-07-03",
        )

        assert len({in_show.id, in_blog.id, as_constraint.id}) == 3
        assert store.fetch_by_id(in_show.id).confirmation_count == 1
        assert in_blog.metadata["project"] == "blog"
        assert as_constraint.metadata["fact_type"] == "constraint"

        restated = commit_fact(
            store, "Use the red thumbnail", project="show", session_date="2026-07-04"
        )
        assert restated.id == in_show.id
        assert store.fetch_by_id(in_show.id).confirmation_count == 2


def test_derived_preferences_stay_scoped_by_project(tmp_path) -> None:
    from akashik.ingest import commit_fact

    with Store(tmp_path / "store.db") as store:
        commit_fact(
            store,
            "I prefer TypeScript",
            fact_type="preference",
            project="show",
            session_date="2026-07-01",
            metadata={"speaker": "user"},
        )
        commit_fact(
            store,
            "I prefer TypeScript",
            fact_type="preference",
            project="blog",
            session_date="2026-07-02",
            metadata={"speaker": "user"},
        )

        derived = [
            unit
            for unit in store.fetch_by_metadata_filters(
                level="fact", filters={"derived": "preference"}
            )
            if unit.valid_until is None
        ]
        assert sorted(unit.metadata["project"] for unit in derived) == ["blog", "show"]

        commit_fact(
            store,
            "I prefer TypeScript",
            fact_type="preference",
            project="show",
            session_date="2026-07-03",
            metadata={"speaker": "user"},
        )
        by_project = {
            unit.metadata["project"]: unit
            for unit in store.fetch_by_metadata_filters(
                level="fact", filters={"derived": "preference"}
            )
            if unit.valid_until is None
        }
        assert by_project["show"].confirmation_count == 2
        assert by_project["blog"].confirmation_count == 1
