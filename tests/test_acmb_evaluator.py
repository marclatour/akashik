from __future__ import annotations

import json

from benchmark.acmb.adapters.akashik_adapter import AkashikAdapter
from benchmark.acmb.adapters.base import ACMBAdapter
from benchmark.acmb.evaluate_acmb import evaluate_benchmark, evaluate_persona, evaluate_query
from benchmark.acmb.run_acmb import DEFAULT_PERSONAS_DIR, DEFAULT_QUERIES_DIR, load_personas, load_queries, main


def test_evaluate_query_fact_recall_all_hits() -> None:
    result = evaluate_query(["f1", "f2"], {"query_id": "q1", "query_type": "x", "must_include": ["f1", "f2"]})
    assert result["fact_recall"] == 1.0


def test_evaluate_query_fact_recall_no_hits() -> None:
    result = evaluate_query(["f3"], {"query_id": "q1", "query_type": "x", "must_include": ["f1"]})
    assert result["fact_recall"] == 0.0


def test_evaluate_query_fact_recall_half_hits() -> None:
    result = evaluate_query(["f1"], {"query_id": "q1", "query_type": "x", "must_include": ["f1", "f2"]})
    assert result["fact_recall"] == 0.5


def test_evaluate_query_belief_revision_fails_when_excluded_present() -> None:
    result = evaluate_query(["f1"], {"query_id": "q1", "query_type": "x", "must_exclude": ["f1"]})
    assert result["belief_revision_score"] == 0.0


def test_evaluate_query_belief_revision_passes_when_excluded_absent() -> None:
    result = evaluate_query(["f1"], {"query_id": "q1", "query_type": "x", "must_exclude": ["f2"]})
    assert result["belief_revision_score"] == 1.0


def test_evaluate_query_precision_perfect_when_all_returned_are_relevant() -> None:
    query = {"query_id": "q1", "query_type": "x", "must_include": ["f1"], "should_include": ["f2"]}
    result = evaluate_query(["f1", "f2"], query)
    assert result["fact_precision"] == 1.0


def test_evaluate_query_computes_distractor_penalty() -> None:
    query = {"query_id": "q1", "query_type": "x", "hard_distractors": ["f2", "f3"]}
    result = evaluate_query(["f1", "f2", "f3"], query)
    assert result["distractor_penalty"] == 2.0


def test_evaluate_query_computes_current_state_correct() -> None:
    query = {"query_id": "q1", "query_type": "x", "expected_current": ["f2"]}
    result = evaluate_query(["f1", "f2"], query)
    assert result["current_state_correct"] == 1.0


def test_evaluate_persona_aggregates_multiple_queries() -> None:
    queries = [
        {"query_id": "q1", "query_type": "x", "must_include": ["f1"], "expected_current": ["f1"]},
        {"query_id": "q2", "query_type": "x", "must_include": ["f2"], "must_exclude": ["f3"], "expected_current": ["f2"]},
    ]
    returned = {"q1": ["f1"], "q2": ["f2"]}
    result = evaluate_persona(returned, queries)
    assert result["fact_recall"] == 1.0
    assert result["belief_revision_score"] == 1.0
    assert result["temporal_correctness"] == 1.0


def test_evaluate_benchmark_aggregates_multiple_personas() -> None:
    summary = evaluate_benchmark(
        [
            {"fact_recall": 1.0, "belief_revision_score": 1.0, "fact_precision": 0.5, "temporal_correctness": 1.0, "distractor_penalty": 0.0},
            {"fact_recall": 0.0, "belief_revision_score": 0.0, "fact_precision": 0.5, "temporal_correctness": 0.0, "distractor_penalty": 2.0},
        ]
    )
    assert summary["fact_recall"] == 0.5
    assert summary["belief_revision_score"] == 0.5
    assert summary["fact_precision"] == 0.5
    assert summary["temporal_correctness"] == 0.5
    assert summary["distractor_penalty"] == 1.0


def test_runner_default_paths_point_to_akashik_home() -> None:
    assert DEFAULT_PERSONAS_DIR.endswith("/.akashik/data/benchmarks/acmb/personas")
    assert DEFAULT_QUERIES_DIR.endswith("/.akashik/data/benchmarks/acmb/queries")


def test_adapter_stub_query_returns_empty_list() -> None:
    adapter = AkashikAdapter()
    assert adapter.query("anything") == []


def test_adapter_stub_reset_does_not_raise() -> None:
    adapter = AkashikAdapter()
    adapter.reset()


def test_query_with_scores_default_returns_uniform_scores() -> None:
    class DummyAdapter(ACMBAdapter):
        def ingest_turn(self, turn: dict) -> None:
            return None

        def query(self, query_text: str, k: int = 10) -> list[str]:
            return ["f1", "f2"]

    adapter = DummyAdapter()
    assert adapter.query_with_scores("x") == [("f1", 1.0), ("f2", 1.0)]


def test_runner_queries_fire_at_turn_before(tmp_path, monkeypatch, capsys) -> None:
    personas_dir = tmp_path / "personas"
    queries_dir = tmp_path / "queries"
    stores_dir = tmp_path / "stores"
    personas_dir.mkdir()
    queries_dir.mkdir()
    stores_dir.mkdir()
    persona = {
        "persona_id": "persona_001",
        "sessions": [
            {
                "session_id": "s1",
                "session_number": 1,
                "session_type": "normal",
                "simulated_date": "2026-01-01",
                "turns": [
                    {"turn_id": "t001", "actor": "user", "content": "a", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t002", "actor": "assistant", "content": "b", "ground_truth_facts": [], "revises_facts": []},
                ],
            }
        ],
    }
    query_file = {
        "persona_id": "persona_001",
        "queries": [
            {
                "query_id": "q001",
                "query_type": "current_state",
                "turn_before": "t001",
                "query_text": "when",
                "must_include": [],
                "must_exclude": [],
                "hard_distractors": [],
                "expected_current": [],
            }
        ],
    }
    (personas_dir / "persona_001.json").write_text(json.dumps(persona), encoding="utf-8")
    (queries_dir / "queries_001.json").write_text(json.dumps(query_file), encoding="utf-8")

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
    monkeypatch.setattr("sys.argv", ["run_acmb.py", "--personas-dir", str(personas_dir), "--queries-dir", str(queries_dir), "--stores-dir", str(stores_dir)])

    assert main() == 0
    assert events == ["reset", "ingest:t001", "query", "ingest:t002"]
    assert "ACMB v0.3" in capsys.readouterr().out


def test_generated_personas_include_noise_session() -> None:
    from benchmark.acmb.generate_personas import build_personas

    personas = build_personas()
    assert any(any(session["session_type"] == "noise" for session in persona["sessions"]) for persona in personas)


def test_load_personas_and_queries_from_default_like_paths(tmp_path) -> None:
    personas_dir = tmp_path / "personas"
    queries_dir = tmp_path / "queries"
    personas_dir.mkdir()
    queries_dir.mkdir()
    (personas_dir / "persona_001.json").write_text(json.dumps({"persona_id": "persona_001"}), encoding="utf-8")
    (queries_dir / "queries_001.json").write_text(json.dumps({"persona_id": "persona_001", "queries": []}), encoding="utf-8")
    assert load_personas(str(personas_dir))[0]["persona_id"] == "persona_001"
    assert load_queries(str(queries_dir))["persona_001"] == []
