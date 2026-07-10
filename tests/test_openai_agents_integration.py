from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types

import pytest

from akashik.ingest import commit_fact
from akashik.store import Store


@pytest.fixture
def integration(monkeypatch):
    """Load akashik.integrations.openai_agents against a fake agents SDK."""
    agents_module = types.ModuleType("agents")
    agents_module.function_tool = lambda func: func
    memory_module = types.ModuleType("agents.memory")
    session_module = types.ModuleType("agents.memory.session")

    class SessionABC:
        pass

    session_module.SessionABC = SessionABC
    agents_module.memory = memory_module
    memory_module.session = session_module

    monkeypatch.setitem(sys.modules, "agents", agents_module)
    monkeypatch.setitem(sys.modules, "agents.memory", memory_module)
    monkeypatch.setitem(sys.modules, "agents.memory.session", session_module)

    import akashik.integrations.openai_agents as module

    module = importlib.reload(module)
    yield module
    monkeypatch.undo()
    importlib.reload(module)


def _store(tmp_path) -> Store:
    return Store(tmp_path / "store.db")


def test_evidence_session_roundtrip(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        session = integration.AkashikEvidenceSession("s1", store)
        items = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        asyncio.run(session.add_items(items))

        assert asyncio.run(session.get_items()) == items
        assert asyncio.run(session.pop_item()) == items[1]
        assert asyncio.run(session.get_items()) == items[:1]


def test_clear_session_preserves_committed_facts(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        session = integration.AkashikEvidenceSession("s1", store)
        asyncio.run(session.add_items([{"role": "user", "content": "hello"}]))
        fact = commit_fact(store, "Launch decided for Friday", fact_type="decision")

        asyncio.run(session.clear_session())

        assert asyncio.run(session.get_items()) == []
        stored = store.fetch_by_id(fact.id)
        assert stored is not None
        assert stored.valid_until is None


def test_memory_callback_injects_single_block(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        commit_fact(store, "The launch is scheduled for Friday", fact_type="decision")
        callback = integration.make_memory_callback(store)

        new_items = [{"role": "user", "content": "when is the launch scheduled?"}]
        combined = callback([], new_items)

        blocks = [
            item
            for item in combined
            if isinstance(item, dict)
            and str(item.get("content", "")).startswith(integration.MEMORY_BLOCK_PREFIX)
        ]
        assert len(blocks) == 1
        assert "scheduled for Friday" in blocks[0]["content"]
        assert combined[-1] == new_items[0]


def test_memory_callback_strips_stale_blocks(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        commit_fact(store, "The launch is scheduled for Friday", fact_type="decision")
        callback = integration.make_memory_callback(store)

        history = [
            {"role": "system", "content": "<AKASHIK_MEMORY>\nstale block\n</AKASHIK_MEMORY>"},
            {"role": "user", "content": "earlier turn"},
        ]
        combined = callback(history, [{"role": "user", "content": "when is the launch scheduled?"}])

        blocks = [
            item
            for item in combined
            if isinstance(item, dict)
            and str(item.get("content", "")).startswith(integration.MEMORY_BLOCK_PREFIX)
        ]
        assert len(blocks) == 1
        assert "stale block" not in blocks[0]["content"]
        assert {"role": "user", "content": "earlier turn"} in combined


def test_memory_callback_passthrough_without_matches(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        callback = integration.make_memory_callback(store)
        history = [{"role": "user", "content": "earlier turn"}]
        new_items = [{"role": "user", "content": "zxq unmatched"}]

        assert callback(history, new_items) == history + new_items
        assert callback(history, [{"role": "user", "content": ""}]) == history + [
            {"role": "user", "content": ""}
        ]


def test_memory_callback_project_scoping(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        commit_fact(store, "Thumbnail uses the red variant", project="show")
        commit_fact(store, "Thumbnail uses the blue variant", project="other")
        callback = integration.make_memory_callback(store, project="show")

        combined = callback([], [{"role": "user", "content": "which thumbnail variant?"}])

        block = next(
            item["content"]
            for item in combined
            if isinstance(item, dict)
            and str(item.get("content", "")).startswith(integration.MEMORY_BLOCK_PREFIX)
        )
        assert "red variant" in block
        assert "blue variant" not in block


def test_recall_tool_formats_citations(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        unit = commit_fact(
            store,
            "Episode one script is locked",
            fact_type="decision",
            project="show",
        )
        recall, _commit, _answer = integration.build_tools(store)

        output = recall("episode script locked")
        assert f"[{unit.id}]" in output
        assert "decision/show" in output

        # Unscoped recall is best-effort (core retrieval fails open to semantic
        # candidates); the deterministic no-match guarantee is scoped recall.
        assert recall("zxq unmatched", project="empty") == "No committed facts match that query."


def test_commit_tool_writes_agent_fact(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        _recall, commit_tool, _answer = integration.build_tools(store, project="show")

        payload = json.loads(commit_tool("Shot list finalized", "outcome"))
        stored = store.fetch_by_id(payload["committed"])
        assert stored is not None
        assert stored.metadata["source"] == "agent"
        assert stored.metadata["fact_type"] == "outcome"
        assert stored.metadata["project"] == "show"

        assert commit_tool("something", "musing").startswith("Commit failed:")


def test_answer_tool_abstains_without_evidence(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        _recall, _commit, answer = integration.build_tools(store)

        assert "abstaining" in answer("Where do I live?")


def test_build_tools_requires_sdk(tmp_path) -> None:
    import akashik.integrations.openai_agents as module

    module = importlib.reload(module)
    if module._SDK_AVAILABLE:
        pytest.skip("real openai-agents SDK installed")
    with _store(tmp_path) as store:
        with pytest.raises(ImportError):
            module.build_tools(store)
        # The session implements the structural Session protocol and needs
        # no SDK at all.
        session = module.AkashikEvidenceSession("s1", store)
        asyncio.run(session.add_items([{"role": "user", "content": "hi"}]))
        assert asyncio.run(session.get_items()) == [{"role": "user", "content": "hi"}]


def test_memory_callback_exact_match_does_not_leak_across_scope(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        commit_fact(store, "The launch is Friday", project="other")
        callback = integration.make_memory_callback(store, project="show")

        history = [{"role": "user", "content": "earlier turn"}]
        new_items = [{"role": "user", "content": "The launch is Friday"}]
        combined = callback(history, new_items)

        assert combined == history + new_items


def test_recall_tool_exact_match_does_not_leak_across_scope(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        commit_fact(store, "The launch is Friday", project="other")
        recall, _commit, _answer = integration.build_tools(store, project="show")

        assert recall("The launch is Friday") == "No committed facts match that query."


def test_answer_tool_exact_match_does_not_leak_across_scope(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        commit_fact(store, "I live in Denver", project="other")
        _recall, _commit, answer = integration.build_tools(store, project="show")

        output = answer("Where do I live?")

        assert "abstaining" in output
        assert "Denver" not in output


def test_memory_callback_includes_universal_facts_in_scoped_recall(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        commit_fact(store, "Thumbnail uses the red variant", project="show")
        # universal personal fact: no project tag
        from akashik.ingest import ingest_text

        ingest_text(store, "I moved to Denver", metadata={"session_date": "2026-07-01"})
        callback = integration.make_memory_callback(store, project="show")

        combined = callback([], [{"role": "user", "content": "where did I move? which thumbnail variant?"}])

        block = next(
            item["content"]
            for item in combined
            if isinstance(item, dict)
            and str(item.get("content", "")).startswith(integration.MEMORY_BLOCK_PREFIX)
        )
        assert "red variant" in block
        assert "Denver" in block


def test_recall_tool_includes_universal_facts(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        from akashik.ingest import ingest_text

        ingest_text(store, "I moved to Denver", metadata={"session_date": "2026-07-01"})
        commit_fact(store, "Blue variant chosen", project="other")
        recall, _commit, _answer = integration.build_tools(store, project="show")

        output = recall("moved Denver variant")
        assert "Denver" in output
        assert "Blue variant" not in output


def test_instance_id_stays_strict_under_policy(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        from akashik.ingest import ingest_text

        ingest_text(store, "I moved to Denver", metadata={"session_date": "2026-07-01"})
        callback = integration.make_memory_callback(
            store, entity_filters={"instance_id": "user_a"}
        )

        combined = callback([], [{"role": "user", "content": "where did I move?"}])

        blocks = [
            item
            for item in combined
            if isinstance(item, dict)
            and str(item.get("content", "")).startswith(integration.MEMORY_BLOCK_PREFIX)
        ]
        assert blocks == []


def test_answer_tool_answers_from_universal_facts(tmp_path, integration) -> None:
    with _store(tmp_path) as store:
        from akashik.ingest import ingest_text

        ingest_text(store, "I live in Denver", metadata={"session_date": "2026-07-01"})
        _recall, _commit, answer = integration.build_tools(store, project="show")

        output = answer("Where do I live?")
        assert "Denver" in output
