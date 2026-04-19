from __future__ import annotations

from akashik import ingest_turn_fact
from akashik.identity import content_hash, normalized_hash
from akashik.schema import MemoryUnit
from akashik.store import Store


def _roots(store: Store) -> str:
    corpus = store.insert(
        MemoryUnit(
            level="corpus",
            content="c",
            content_hash=content_hash("c"),
            normalized_hash=normalized_hash("c"),
            metadata={"tags": []},
        )
    )
    document = store.insert(
        MemoryUnit(
            level="document",
            content="d",
            content_hash=content_hash("d"),
            normalized_hash=normalized_hash("d"),
            parent_id=corpus.id,
            metadata={"tags": []},
        )
    )
    section = store.insert(
        MemoryUnit(
            level="section",
            content="s",
            content_hash=content_hash("s"),
            normalized_hash=normalized_hash("s"),
            parent_id=document.id,
            metadata={"tags": []},
        )
    )
    return section.id


def test_happy_path_single_fact() -> None:
    with Store(":memory:") as store:
        section_id = _roots(store)
        result = ingest_turn_fact(
            store,
            "I live in Denver.",
            parent_id=section_id,
            role="user",
            turn_id="t1",
            session_date="2026-01-01",
        )
        assert len(result) == 1
        fact = result[0]
        assert fact.level == "fact"
        assert fact.valid_from == "2026-01-01"
        assert fact.metadata["speaker"] == "user"
        assert fact.metadata["turn_id"] == "t1"


def test_sentence_split_creates_multiple_facts() -> None:
    with Store(":memory:") as store:
        section_id = _roots(store)
        result = ingest_turn_fact(
            store,
            "I live in Denver. I work at Acme. I drive a Tesla.",
            parent_id=section_id,
            role="user",
            turn_id="t2",
            session_date="2026-01-02",
        )
        assert len(result) == 3
        for fact in result:
            assert fact.metadata["speaker"] == "user"
            assert fact.metadata["turn_id"] == "t2"
            assert fact.valid_from == "2026-01-02"


def test_split_false_creates_single_fact() -> None:
    with Store(":memory:") as store:
        section_id = _roots(store)
        result = ingest_turn_fact(
            store,
            "I live in Denver. I work at Acme.",
            parent_id=section_id,
            role="user",
            session_date="2026-01-03",
            split=False,
        )
        assert len(result) == 1
        assert "Denver" in result[0].content
        assert "Acme" in result[0].content


def test_contradiction_closes_old_fact() -> None:
    with Store(":memory:") as store:
        section_id = _roots(store)
        first = ingest_turn_fact(
            store,
            "I live in Boston.",
            parent_id=section_id,
            role="user",
            turn_id="t1",
            session_date="2026-01-01",
        )
        assert len(first) == 1
        old_id = first[0].id

        ingest_turn_fact(
            store,
            "I live in Seattle.",
            parent_id=section_id,
            role="user",
            turn_id="t2",
            session_date="2026-02-01",
        )

        refreshed = store.fetch_by_id(old_id)
        assert refreshed is not None
        assert refreshed.valid_until == "2026-02-01"


def test_reinforcement_increments_confirmation() -> None:
    with Store(":memory:") as store:
        section_id = _roots(store)
        first = ingest_turn_fact(
            store,
            "The sky is blue today.",
            parent_id=section_id,
            role="user",
            session_date="2026-01-01",
        )
        second = ingest_turn_fact(
            store,
            "The sky is blue today.",
            parent_id=section_id,
            role="user",
            session_date="2026-01-02",
        )
        assert len(first) == 1
        assert len(second) == 1
        assert first[0].id == second[0].id

        facts = store.fetch_by_metadata_filters(level="fact", filters=None)
        matching = [f for f in facts if f.content.strip() == "The sky is blue today."]
        assert len(matching) == 1
        assert matching[0].confirmation_count >= 2


def test_blank_content_returns_empty_list() -> None:
    with Store(":memory:") as store:
        section_id = _roots(store)
        assert ingest_turn_fact(store, "", parent_id=section_id, role="user") == []
        assert ingest_turn_fact(store, "   \n  ", parent_id=section_id, role="user") == []
        facts = store.fetch_by_metadata_filters(level="fact", filters=None)
        assert facts == []


def test_metadata_passthrough() -> None:
    with Store(":memory:") as store:
        section_id = _roots(store)
        result = ingest_turn_fact(
            store,
            "I love Rust programming.",
            parent_id=section_id,
            role="user",
            session_date="2026-01-01",
            metadata={
                "domain": "hobbies",
                "thread": "coding",
                "entities": ["RustLang"],
            },
        )
        assert len(result) == 1
        meta = result[0].metadata
        assert meta["domain"] == "hobbies"
        assert meta["thread"] == "coding"
        assert "RustLang" in meta["entities"]
        assert meta["speaker"] == "user"

        rows = store._conn.execute(
            "SELECT index_type, index_value FROM fact_context_index WHERE fact_id = ?",
            (result[0].id,),
        ).fetchall()
        entries = {(row["index_type"], row["index_value"]) for row in rows}
        assert ("domain", "hobbies") in entries
        assert ("thread", "coding") in entries
