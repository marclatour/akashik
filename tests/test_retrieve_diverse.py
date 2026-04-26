from __future__ import annotations

import inspect

from akashik import retrieve_diverse
from akashik.identity import content_hash, normalized_hash
from akashik.retrieve import retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store


def _metadata(source: str = "tests") -> dict:
    return {"source": source, "timestamp": "2026-04-14T00:00:00+00:00", "tags": []}


def _unit(
    level: str,
    content: str,
    parent_id: str | None = None,
    source: str = "tests",
    metadata: dict | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> MemoryUnit:
    unit_metadata = _metadata(source)
    if metadata:
        unit_metadata.update(metadata)
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata=unit_metadata,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _make_document_with_facts(
    store: Store,
    *,
    session_id: str,
    facts: list[str],
    source: str = "shared-source",
) -> None:
    document = store.insert(
        _unit(
            "document",
            f"Document {session_id}",
            source=source,
            metadata={"session_id": session_id, "instance_id": "instance"},
        )
    )
    section = store.insert(
        _unit(
            "section",
            f"Section {session_id}",
            parent_id=document.id,
            source=source,
            metadata={"session_id": session_id, "instance_id": "instance"},
        )
    )
    for fact in facts:
        store.insert(
            _unit(
                "fact",
                fact,
                parent_id=section.id,
                source=source,
                metadata={"session_id": session_id, "instance_id": "instance"},
            )
        )


def test_retrieve_diverse_returns_facts_from_multiple_sessions(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        _make_document_with_facts(
            store,
            session_id="s1",
            facts=[
                "shared anchor evidence about travel from session one",
                "shared anchor evidence about work from session one",
            ],
        )
        _make_document_with_facts(
            store,
            session_id="s2",
            facts=[
                "shared anchor evidence about travel from session two",
                "shared anchor evidence about work from session two",
            ],
        )
        _make_document_with_facts(
            store,
            session_id="s3",
            facts=[
                "shared anchor evidence about travel from session three",
                "shared anchor evidence about work from session three",
            ],
        )

        results = retrieve_diverse(
            store,
            "shared anchor evidence",
            limit=6,
            pool=20,
            top_sessions=3,
            facts_per_session=2,
        )

        session_ids = {result.metadata.get("session_id") for result in results}
        assert len(session_ids - {None}) >= 2


def test_retrieve_diverse_respects_limit(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        _make_document_with_facts(
            store,
            session_id="s1",
            facts=["anchor one", "anchor two", "anchor three"],
        )
        _make_document_with_facts(
            store,
            session_id="s2",
            facts=["anchor four", "anchor five", "anchor six"],
        )

        results = retrieve_diverse(
            store,
            "anchor",
            limit=2,
            pool=20,
            top_sessions=5,
            facts_per_session=3,
        )

        assert len(results) <= 2


def test_retrieve_diverse_falls_back_gracefully_on_single_session_store(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        _make_document_with_facts(
            store,
            session_id="solo",
            facts=[
                "single anchor evidence one",
                "single anchor evidence two",
                "single anchor evidence three",
            ],
        )

        results = retrieve_diverse(
            store,
            "single anchor evidence",
            limit=5,
            pool=20,
            top_sessions=5,
            facts_per_session=3,
        )

        assert results
        assert {result.metadata.get("session_id") for result in results} == {"solo"}


def test_retrieve_diverse_empty_store(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        assert retrieve_diverse(store, "nothing here") == []


def test_retrieve_diverse_signature_matches_retrieve() -> None:
    retrieve_signature = inspect.signature(retrieve)
    diverse_signature = inspect.signature(retrieve_diverse)

    assert "limit" in retrieve_signature.parameters
    assert diverse_signature.parameters["limit"].default == retrieve_signature.parameters["limit"].default
    assert "document_gate_n" in retrieve_signature.parameters
    assert "document_gate_n" in diverse_signature.parameters
    assert diverse_signature.parameters["query"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert diverse_signature.parameters["store"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
