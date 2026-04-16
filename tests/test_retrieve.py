from __future__ import annotations

import importlib

from akashik.identity import content_hash, normalized_hash
from akashik.ingest import ingest_file
from akashik.retrieve import _apply_navigator_tiebreak, retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store

retrieve_module = importlib.import_module("akashik.retrieve")


def _metadata(source: str = "tests") -> dict:
    return {"source": source, "timestamp": "2026-04-14T00:00:00+00:00", "tags": []}


def _unit(level: str, content: str, parent_id: str | None = None, source: str = "tests") -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata=_metadata(source),
    )


def test_exact_match_wins(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Project notes."))
        section = store.insert(_unit("section", "Implementation section.", parent_id=document.id))
        fact = store.insert(_unit("fact", "The lantern code appears once.", parent_id=section.id))

        response = retrieve("The lantern code appears once.", store, level="fact")

        assert response.confidence == 1.0
        assert response.results[0].unit.id == fact.id
        assert [unit.level for unit in response.results[0].parent_chain] == ["section", "document"]


def test_normalized_match_wins_when_raw_text_differs(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Project notes."))
        section = store.insert(_unit("section", "Normalization section.", parent_id=document.id))
        fact = store.insert(_unit("fact", "Local Memory Library", parent_id=section.id))

        response = retrieve("  local   memory library  ", store, level="fact")

        assert response.confidence == 0.95
        assert response.results[0].unit.id == fact.id


def test_fts_match_returns_requested_fact_at_rank_one(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Storage notes for local memory.", source="doc.txt"))
        section = store.insert(_unit("section", "SQLite decisions and retrieval rules.", parent_id=document.id, source="doc.txt"))
        fact = store.insert(
            _unit(
                "fact",
                "SQLite keeps the library local and deterministic for retrieval.",
                parent_id=section.id,
                source="doc.txt",
            )
        )
        store.insert(
            _unit(
                "fact",
                "Vectors are out of scope for version zero point one.",
                parent_id=section.id,
                source="doc.txt",
            )
        )

        response = retrieve("local deterministic retrieval", store, level="fact")

        assert response.results
        assert response.results[0].unit.id == fact.id
        assert response.results[0].confidence < 0.95
        assert response.results[0].unit.source == "doc.txt"


def test_fts_rerank_prefers_shorter_fact_with_same_terms(tmp_path, monkeypatch) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Project notes.", source="doc.txt"))
        section = store.insert(_unit("section", "Brevity section.", parent_id=document.id, source="doc.txt"))
        long_fact = store.insert(
            _unit(
                "fact",
                "needle appears in this long preamble sentence that keeps adding operational context "
                "about routing, provenance, archival notes, and repeated explanatory detail.",
                parent_id=section.id,
                source="doc.txt",
            )
        )
        short_fact = store.insert(_unit("fact", "needle answer.", parent_id=section.id, source="doc.txt"))

        monkeypatch.setattr(store, "search_fts", lambda *_args, **_kwargs: [long_fact, short_fact])

        response = retrieve("needle", store, level="fact")

        assert response.results[0].unit.id == short_fact.id


def test_traversal_resolves_to_requested_level(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        document = store.insert(_unit("document", "Root document"))
        section = store.insert(
            _unit(
                "section",
                "Section about local indexing and storage guarantees.",
                parent_id=document.id,
            )
        )
        fact = store.insert(
            _unit("fact", "Local indexing stays inside SQLite.", parent_id=section.id)
        )

        upward = retrieve("inside SQLite", store, level="section")
        downward = retrieve("Section about local indexing and storage guarantees.", store, level="fact")

        assert upward.results[0].unit.id == section.id
        assert downward.results[0].unit.id == fact.id


def test_empty_result_returns_zero_confidence(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        blank = retrieve("   ", store, level="fact")
        missing = retrieve("phrase that does not exist anywhere", store, level="fact")

        assert blank.results == []
        assert blank.confidence == 0.0
        assert missing.results == []
        assert missing.confidence == 0.0


def test_navigator_tiebreak_does_not_override_clear_winner(monkeypatch) -> None:
    first = _unit("fact", "First fact.", source="doc.txt")
    second = _unit("fact", "Second fact.", source="doc.txt")
    candidates = [
        {"unit": first, "final_score": 1.0},
        {"unit": second, "final_score": 0.9},
    ]

    monkeypatch.setattr(
        retrieve_module,
        "rank_facts",
        lambda facts, query: [(facts[1], 0.9), (facts[0], 0.1)],
    )

    ranked = _apply_navigator_tiebreak(candidates, "test query", use_navigator=True)

    assert [detail["unit"].id for detail in ranked] == [first.id, second.id]


def test_navigator_tiebreak_only_reorders_near_tie(monkeypatch) -> None:
    first = _unit("fact", "First fact.", source="doc.txt")
    second = _unit("fact", "Second fact.", source="doc.txt")
    third = _unit("fact", "Third fact.", source="doc.txt")
    candidates = [
        {"unit": first, "final_score": 1.0},
        {"unit": second, "final_score": 0.99},
        {"unit": third, "final_score": 0.8},
    ]

    monkeypatch.setattr(
        retrieve_module,
        "rank_facts",
        lambda facts, query: [(facts[1], 0.9), (facts[0], 0.8)],
    )

    ranked = _apply_navigator_tiebreak(candidates, "test query", use_navigator=True)

    assert [detail["unit"].id for detail in ranked] == [second.id, first.id, third.id]


def test_acceptance_case_ingest_and_retrieve_unique_fact(tmp_path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text(_sample_document(), encoding="utf-8")

    with Store(tmp_path / "store.db") as store:
        document = ingest_file(file_path, store)
        response = retrieve("blue glass shelf twenty two", store, level="fact")

        assert response.results
        top = response.results[0]
        assert top.unit.level == "fact"
        assert "blue glass" in top.unit.content.lower()
        assert top.parent_chain[0].level == "section"
        assert top.parent_chain[1].id == document.id


def _sample_document() -> str:
    paragraph_one = " ".join(
        [
            "Akashik is a local first memory library designed for deterministic storage and retrieval."
            " The project favors stable hashes over probabilistic ranking."
            " Developers can read every record because the database remains in SQLite."
            " Each paragraph becomes a section and each sentence becomes a fact."
        ]
        * 9
    )
    paragraph_two = " ".join(
        [
            "The archive room keeps routine notes about indexes, hierarchy, and transaction safety."
            " Every insert writes to the primary table and the keyword index together."
        ]
        * 9
    )
    paragraph_two = " ".join(
        [
            paragraph_two,
            "A blue glass bottle sits on shelf twenty two beside the field notebook.",
            "That line exists once so retrieval can prove the correct fact returns first.",
        ]
    )
    paragraph_three = " ".join(
        [
            "Query routing starts with exact hashes, then normalized hashes, then keyword search."
            " Parent and child traversal only happens after the earlier checks fail to return a direct hit."
            " The system stays small on purpose because version zero point one is a library, not a service."
            " Simple tools are easier to verify, test, and run entirely on a laptop."
        ]
        * 9
    )
    return "\n\n".join([paragraph_one, paragraph_two, paragraph_three])
