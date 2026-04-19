from __future__ import annotations

import importlib
from pathlib import Path

from akashik.schema import MemoryUnit, RetrievalResponse, RetrievalResult
from benchmark.acmb.adapters.akashik_adapter import AkashikAdapter
from benchmark.acmb.run_acmb import main

retrieve_module = importlib.import_module("akashik.retrieve")


def test_adapter_initializes_without_error(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    assert adapter.store is not None


def test_ingest_user_turn_stores_fact_in_memory_units(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Denver.",
            "ground_truth_facts": ["f001"],
            "simulated_date": "2026-01-01",
        }
    )
    facts = adapter.store.fetch_by_metadata_filters(level="fact", filters={"turn_id": "t001"})
    assert len(facts) == 1
    assert "ground_truth_facts" not in facts[0].metadata


def test_ingest_assistant_turn_does_not_store_fact_in_memory_units(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t002",
            "actor": "assistant",
            "content": "I can help with that.",
            "ground_truth_facts": [],
            "simulated_date": "2026-01-01",
        }
    )
    facts = adapter.store.fetch_by_metadata_filters(level="fact")
    assert facts == []


def test_ingest_assistant_turn_writes_to_interaction_log(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t002",
            "actor": "assistant",
            "content": "I can help with that.",
            "ground_truth_facts": [],
            "simulated_date": "2026-01-01",
        }
    )
    count = adapter.store._conn.execute("SELECT COUNT(*) FROM interaction_log").fetchone()[0]
    assert count == 1


def test_query_returns_list_of_strings(tmp_path, monkeypatch) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    unit = MemoryUnit(
        level="fact",
        content="I live in Denver.",
        content_hash="a",
        normalized_hash="b",
        metadata={"ground_truth_facts": ["f001"]},
    )
    response = RetrievalResponse(results=[RetrievalResult(unit=unit, confidence=0.9, parent_chain=[])], confidence=0.9)
    monkeypatch.setattr(retrieve_module, "retrieve", lambda *args, **kwargs: response)
    result = adapter.query("x")
    assert result == ["I live in Denver."]
    assert all(isinstance(item, str) for item in result)


def test_query_returns_text_in_rank_order(tmp_path, monkeypatch) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    first = MemoryUnit(level="fact", content="I live in Denver.", content_hash="1", normalized_hash="1", metadata={"ground_truth_facts": ["f001"]})
    second = MemoryUnit(level="fact", content="I do trail running on weekends.", content_hash="2", normalized_hash="2", metadata={"ground_truth_facts": ["f002"]})
    response = RetrievalResponse(
        results=[
            RetrievalResult(unit=first, confidence=0.9, parent_chain=[]),
            RetrievalResult(unit=second, confidence=0.8, parent_chain=[]),
        ],
        confidence=0.9,
    )
    monkeypatch.setattr(retrieve_module, "retrieve", lambda *args, **kwargs: response)
    assert adapter.query("x") == ["I live in Denver.", "I do trail running on weekends."]


def test_query_with_scores_returns_ranked_tuples(tmp_path, monkeypatch) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    first = MemoryUnit(level="fact", content="I live in Denver.", content_hash="1", normalized_hash="1", metadata={"ground_truth_facts": ["f001"]})
    second = MemoryUnit(level="fact", content="I do trail running on weekends.", content_hash="2", normalized_hash="2", metadata={"ground_truth_facts": ["f002"]})
    response = RetrievalResponse(
        results=[
            RetrievalResult(unit=first, confidence=0.9, parent_chain=[]),
            RetrievalResult(unit=second, confidence=0.4, parent_chain=[]),
        ],
        confidence=0.9,
    )
    monkeypatch.setattr(retrieve_module, "retrieve", lambda *args, **kwargs: response)
    scored = adapter.query_with_scores("x")
    assert scored == [("I live in Denver.", 0.9), ("I do trail running on weekends.", 0.4)]
    assert scored[0][1] > scored[1][1]


def test_reset_recreates_store_cleanly(tmp_path) -> None:
    store_path = tmp_path / "acmb.db"
    adapter = AkashikAdapter(store_path=str(store_path))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Denver.",
            "ground_truth_facts": ["f001"],
            "simulated_date": "2026-01-01",
        }
    )
    assert store_path.exists()
    adapter.reset()
    assert store_path.exists()
    assert adapter.query("I live in Denver.") == []


def test_end_to_end_matching_query_returns_text(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Denver.",
            "ground_truth_facts": ["f001"],
            "simulated_date": "2026-01-01",
        }
    )
    assert "I live in Denver." in adapter.query("I live in Denver.")


def test_runner_queries_fire_at_turn_before_not_after_full_ingestion(tmp_path, monkeypatch, capsys) -> None:
    personas_dir = tmp_path / "personas"
    queries_dir = tmp_path / "queries"
    stores_dir = tmp_path / "stores"
    personas_dir.mkdir()
    queries_dir.mkdir()
    stores_dir.mkdir()
    (personas_dir / "persona_001.json").write_text(
        '{"persona_id":"persona_001","sessions":[{"session_id":"s1","session_number":1,"session_type":"normal","simulated_date":"2026-01-01","turns":[{"turn_id":"t001","actor":"user","content":"a","ground_truth_facts":[],"revises_facts":[]},{"turn_id":"t002","actor":"user","content":"b","ground_truth_facts":[],"revises_facts":[]}]}]}',
        encoding="utf-8",
    )
    (queries_dir / "queries_001.json").write_text(
        '{"persona_id":"persona_001","queries":[{"query_id":"q001","query_type":"current_state","turn_before":"t001","query_text":"when","must_include":[],"must_exclude":[],"hard_distractors":[],"expected_current":[]}]}',
        encoding="utf-8",
    )

    events: list[str] = []

    class RecordingAdapter:
        def reset(self) -> None:
            events.append("reset")

        def ingest_turn(self, turn: dict) -> None:
            events.append(f"ingest:{turn['turn_id']}")

        def query(self, query_text: str, k: int = 10) -> list[str]:
            events.append("query")
            return []

    monkeypatch.setattr("benchmark.acmb.run_acmb.get_adapter", lambda name, store_path: RecordingAdapter())
    monkeypatch.setattr(
        "sys.argv",
        ["run_acmb.py", "--personas-dir", str(personas_dir), "--queries-dir", str(queries_dir), "--stores-dir", str(stores_dir)],
    )
    assert main() == 0
    assert events == ["reset", "ingest:t001", "query", "ingest:t002"]
    assert "ACMB v0.3" in capsys.readouterr().out
