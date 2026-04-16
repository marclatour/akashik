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
