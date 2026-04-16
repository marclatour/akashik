from __future__ import annotations

from akashik.contradiction import close_fact, extract_triple, find_contradicting_fact
from akashik.identity import content_hash, normalized_hash
from akashik.schema import MemoryUnit
from akashik.store import Store


def _unit(level: str, content: str, *, parent_id: str | None = None, metadata: dict | None = None, valid_from: str | None = None, valid_until: str | None = None) -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata={"source": "tests", "timestamp": "2026-04-16T00:00:00+00:00", "tags": [], **(metadata or {})},
        valid_from=valid_from,
        valid_until=valid_until,
    )


def test_extract_triple_location() -> None:
    assert extract_triple("I live in Chicago") == ("user", "location", "Chicago")


def test_extract_triple_employer() -> None:
    assert extract_triple("I work at Google") == ("user", "employer", "Google")


def test_extract_triple_no_match() -> None:
    assert extract_triple("The weather is nice today") is None


def test_extract_triple_empty_value() -> None:
    assert extract_triple("I live in") is None


def test_find_contradicting_fact_found(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "doc", metadata={"instance_id": "test"}))
        section = store.insert(_unit("section", "section", parent_id=document.id, metadata={"instance_id": "test"}))
        old = store.insert(
            _unit(
                "fact",
                "I live in Chicago",
                parent_id=section.id,
                metadata={"instance_id": "test"},
                valid_from="2022-01-01",
            )
        )

        found = find_contradicting_fact(store, ("user", "location", "New York"), "test")

        assert found is not None
        assert found.id == old.id


def test_find_contradicting_fact_same_value(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "doc", metadata={"instance_id": "test"}))
        section = store.insert(_unit("section", "section", parent_id=document.id, metadata={"instance_id": "test"}))
        store.insert(
            _unit(
                "fact",
                "I live in Chicago",
                parent_id=section.id,
                metadata={"instance_id": "test"},
                valid_from="2022-01-01",
            )
        )

        found = find_contradicting_fact(store, ("user", "location", "Chicago"), "test")

        assert found is None


def test_close_fact_sets_valid_until(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "doc"))
        section = store.insert(_unit("section", "section", parent_id=document.id))
        fact = store.insert(_unit("fact", "I work at Google", parent_id=section.id, valid_from="2022-01-01"))

        close_fact(store, fact.id, "2024-01-01")

        fetched = store.fetch_by_id(fact.id)
        assert fetched is not None
        assert fetched.valid_until == "2024-01-01"
        assert fetched.content == "I work at Google"


def test_close_fact_never_deletes(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "doc"))
        section = store.insert(_unit("section", "section", parent_id=document.id))
        fact = store.insert(_unit("fact", "I work at Google", parent_id=section.id, valid_from="2022-01-01"))

        close_fact(store, fact.id, "2024-01-01")

        assert store.fetch_by_id(fact.id) is not None
