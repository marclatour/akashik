from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from akashik.expression import (
    EXPRESSION_THRESHOLD,
    MAX_CANDIDATE_POOL,
    MAX_EXPRESSED_FACTS,
    MIN_CONTEXT_TERMS,
    express,
    extract_context,
)
from akashik.identity import content_hash, normalized_hash
from akashik.ingest import build_fact_context_entries
from akashik.retrieve import retrieve
from akashik.schema import MemoryUnit
from akashik.store import Store

expression_module = importlib.import_module("akashik.expression")
retrieve_module = importlib.import_module("akashik.retrieve")


def _unit(level: str, content: str, *, parent_id: str | None = None, metadata: dict | None = None) -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata=metadata or {"source": "tests"},
    )


def _doc_with_fact(store: Store, content: str, *, metadata: dict | None = None) -> MemoryUnit:
    document = store.insert(_unit("document", "doc", metadata=metadata))
    section = store.insert(_unit("section", "section", parent_id=document.id, metadata=metadata))
    fact = store.insert(_unit("fact", content, parent_id=section.id, metadata=metadata))
    store.insert_fact_context_entries(build_fact_context_entries(fact.content, fact.metadata), fact.id)
    return fact


def test_extract_context_returns_correct_topics() -> None:
    context = extract_context("What is my project roadmap?")

    assert "project" in context["topics"]
    assert "roadmap" in context["topics"]


def test_extract_context_filters_short_tokens() -> None:
    context = extract_context("new ai ux ml roadmap")

    assert "new" not in context["topics"]
    assert "roadmap" in context["topics"]


def test_extract_context_includes_entities_from_metadata() -> None:
    context = extract_context("vehicle maintenance", metadata={"entities": ["Subaru"]})

    assert context["entities"] == ["subaru"]


def test_extract_context_returns_empty_lists_when_no_long_tokens() -> None:
    context = extract_context("a an the in of")

    assert context == {"entities": [], "topics": [], "domain": [], "thread": []}


def test_express_returns_empty_list_when_context_none(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        assert express(store, "query", context=None) == []


def test_express_returns_empty_list_when_context_too_sparse(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        context = {"entities": [], "topics": ["roadmap"], "domain": [], "thread": []}
        assert len(context["topics"]) + len(context["entities"]) < MIN_CONTEXT_TERMS
        assert express(store, "roadmap", context=context) == []


def test_express_returns_empty_list_when_candidate_pool_empty(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        context = {"entities": [], "topics": ["roadmap", "planning"], "domain": [], "thread": []}
        assert express(store, "roadmap planning", context=context) == []


def test_express_returns_empty_list_when_candidate_pool_too_large(tmp_path, monkeypatch) -> None:
    with Store(tmp_path / "store.db") as store:
        monkeypatch.setattr(
            expression_module,
            "get_candidate_pool",
            lambda *_args, **_kwargs: [f"fact-{index}" for index in range(MAX_CANDIDATE_POOL + 1)],
        )
        context = {"entities": [], "topics": ["roadmap", "planning"], "domain": [], "thread": []}
        assert express(store, "roadmap planning", context=context) == []


def test_express_returns_empty_list_when_no_candidates_clear_threshold(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = ? WHERE fact_id = ?",
            (EXPRESSION_THRESHOLD - 0.1, fact.id),
        )
        context = {"entities": ["subaru"], "topics": ["roadmap", "planning"], "domain": [], "thread": []}

        assert express(store, "roadmap planning", context=context) == []


def test_express_excludes_silenced_facts(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = ?, silenced = 1 WHERE fact_id = ?",
            (EXPRESSION_THRESHOLD + 1.0, fact.id),
        )
        context = {"entities": ["subaru"], "topics": ["roadmap", "planning"], "domain": [], "thread": []}

        assert express(store, "roadmap planning", context=context) == []


def test_express_excludes_future_silence_until(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = ?, silence_until = ? WHERE fact_id = ?",
            (EXPRESSION_THRESHOLD + 1.0, future, fact.id),
        )
        context = {"entities": ["subaru"], "topics": ["roadmap", "planning"], "domain": [], "thread": []}

        assert express(store, "roadmap planning", context=context) == []


def test_express_returns_facts_sorted_by_composite_score_desc(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        low = _doc_with_fact(store, "roadmap alpha detail", metadata={"entities": ["Subaru"]})
        high = _doc_with_fact(store, "roadmap beta detail", metadata={"entities": ["Subaru"]})
        now = datetime.now(UTC).isoformat()
        store.execute(
            """
            UPDATE epigenetic_state
            SET activation_weight = ?, reinforcement_count = ?, last_expressed_at = ?
            WHERE fact_id = ?
            """,
            (EXPRESSION_THRESHOLD + 0.1, 0, None, low.id),
        )
        store.execute(
            """
            UPDATE epigenetic_state
            SET activation_weight = ?, reinforcement_count = ?, last_expressed_at = ?
            WHERE fact_id = ?
            """,
            (EXPRESSION_THRESHOLD + 0.05, 3, now, high.id),
        )
        context = {"entities": ["subaru"], "topics": ["roadmap", "detail"], "domain": [], "thread": []}

        results = express(store, "roadmap detail", context=context)

        assert [fact.id for fact in results[:2]] == [high.id, low.id]


def test_express_returns_at_most_max_expressed_facts(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        for index in range(MAX_EXPRESSED_FACTS + 5):
            fact = _doc_with_fact(store, f"roadmap detail {index}", metadata={"entities": ["Subaru"]})
            store.execute(
                "UPDATE epigenetic_state SET activation_weight = ? WHERE fact_id = ?",
                (EXPRESSION_THRESHOLD + 1.0, fact.id),
            )
        context = {"entities": ["subaru"], "topics": ["roadmap", "detail"], "domain": [], "thread": []}

        results = express(store, "roadmap detail", context=context)

        assert len(results) == MAX_EXPRESSED_FACTS


def test_express_tags_returned_facts_with_expression_tier(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = ? WHERE fact_id = ?",
            (EXPRESSION_THRESHOLD + 1.0, fact.id),
        )
        context = {"entities": ["subaru"], "topics": ["roadmap", "planning"], "domain": [], "thread": []}

        results = express(store, "roadmap planning", context=context)

        assert results
        assert results[0].metadata["retrieval_tier"] == "expression"


def test_retrieve_use_expression_false_never_calls_express(tmp_path, monkeypatch) -> None:
    with Store(tmp_path / "store.db") as store:
        _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})
        called = {"value": False}

        def _boom(*_args, **_kwargs):
            called["value"] = True
            raise AssertionError("express should not be called")

        monkeypatch.setattr(retrieve_module, "express", _boom)

        retrieve("roadmap planning detail", store, level="fact", use_expression=False)

        assert called["value"] is False


def test_retrieve_with_expression_hit_returns_expression_results(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = ? WHERE fact_id = ?",
            (EXPRESSION_THRESHOLD + 1.0, fact.id),
        )

        response = retrieve("roadmap planning detail", store, level="fact", use_expression=True)

        assert response.results
        assert response.results[0].unit.id == fact.id
        assert response.results[0].unit.metadata["retrieval_tier"] == "expression"


def test_retrieve_with_expression_miss_falls_through_to_retrieval_stack(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})

        response = retrieve("roadmap planning detail", store, level="fact", use_expression=True)

        assert response.results
        assert response.results[0].unit.id == fact.id
        assert response.results[0].unit.metadata.get("retrieval_tier") != "expression"


def test_end_to_end_expression_tier_fires_with_activation_above_threshold(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        fact = _doc_with_fact(store, "roadmap planning detail", metadata={"entities": ["Subaru"]})
        store.execute(
            "UPDATE epigenetic_state SET activation_weight = ? WHERE fact_id = ?",
            (EXPRESSION_THRESHOLD + 0.5, fact.id),
        )

        response = retrieve("roadmap planning detail", store, level="fact", use_expression=True)

        assert response.results
        assert response.results[0].unit.id == fact.id
        assert response.results[0].unit.metadata["retrieval_tier"] == "expression"
