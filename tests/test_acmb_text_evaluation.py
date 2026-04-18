from __future__ import annotations

import numpy as np

from benchmark.acmb.adapters.akashik_adapter import AkashikAdapter
from benchmark.acmb.adapters.full_context_adapter import FullContextAdapter
from benchmark.acmb.adapters.rag_adapter import RagAdapter
from benchmark.acmb.evaluate_acmb import resolve_fact_ids, tokenize


def _persona_facts() -> list[dict]:
    return [
        {"fact_id": "f001", "natural_language": "I live in Denver."},
        {"fact_id": "f002", "natural_language": "I do trail running on weekends."},
        {"fact_id": "f003", "natural_language": "I used to ski most weekends."},
    ]


def test_tokenize_strips_stopwords_and_normalizes_text() -> None:
    assert tokenize("I live in Denver, and I run on weekends.") == {"live", "denver", "run", "weekends"}


def test_resolve_fact_ids_returns_correct_match() -> None:
    assert resolve_fact_ids(["I live in Denver now."], _persona_facts()) == ["f001"]


def test_resolve_fact_ids_returns_empty_when_below_threshold() -> None:
    assert resolve_fact_ids(["I bought a new frying pan."], _persona_facts()) == []


def test_resolve_fact_ids_deduplicates() -> None:
    matched = resolve_fact_ids(["I live in Denver.", "Denver is where I live."], _persona_facts())
    assert matched == ["f001"]


def test_resolve_fact_ids_preserves_retrieval_order() -> None:
    matched = resolve_fact_ids(
        ["I do trail running on weekends.", "I live in Denver."],
        _persona_facts(),
    )
    assert matched == ["f002", "f001"]


def test_resolve_fact_ids_threshold_controls_match_strictness() -> None:
    texts = ["Denver area."]
    assert resolve_fact_ids(texts, _persona_facts(), threshold=0.5) == []
    assert resolve_fact_ids(texts, _persona_facts(), threshold=0.3) == ["f001"]


def test_resolve_fact_ids_returns_best_match_per_snippet() -> None:
    facts = [
        {"fact_id": "f001", "natural_language": "I live in Denver."},
        {"fact_id": "f002", "natural_language": "I live in Colorado."},
    ]
    assert resolve_fact_ids(["I live in Denver."], facts) == ["f001"]


def test_resolve_fact_ids_prefers_higher_scoring_similar_fact() -> None:
    facts = [
        {"fact_id": "f001", "natural_language": "I trail run in the foothills every weekend."},
        {"fact_id": "f002", "natural_language": "I run sometimes on weekends."},
    ]
    assert resolve_fact_ids(["I trail run every weekend in the foothills."], facts) == ["f001"]


def test_akashik_adapter_query_returns_text_not_fact_ids(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Denver.",
            "ground_truth_facts": ["f001"],
            "revises_facts": [],
            "simulated_date": "2026-01-01",
        }
    )
    results = adapter.query("I live in Denver.")
    assert results == ["I live in Denver."]
    assert "f001" not in results


class _FakeSentenceTransformer:
    def encode(self, text: str, normalize_embeddings: bool = True):
        lowered = text.lower()
        values = np.array(
            [
                float("denver" in lowered or "live" in lowered or "where" in lowered),
                float("trail" in lowered or "running" in lowered or "weekends" in lowered),
                float(len(lowered.split())),
            ],
            dtype=np.float32,
        )
        norm = np.linalg.norm(values)
        return values if norm == 0 else values / norm


def test_rag_adapter_ingests_sentence_chunks_and_returns_text(monkeypatch) -> None:
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", lambda model_name: _FakeSentenceTransformer())
    adapter = RagAdapter()
    adapter.ingest_turn({"actor": "user", "content": "I live in Denver. I do trail running on weekends."})
    result = adapter.query("Where do I live?", k=1)
    assert result == ["I live in Denver"]


def test_rag_adapter_reset_clears_chunks_and_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", lambda model_name: _FakeSentenceTransformer())
    adapter = RagAdapter()
    adapter.ingest_turn({"actor": "user", "content": "I live in Denver. I do trail running on weekends."})
    adapter.reset()
    assert adapter.chunks == []
    assert adapter.embeddings == []


def test_full_context_adapter_returns_most_recent_turns_within_budget() -> None:
    adapter = FullContextAdapter()
    adapter.ingest_turn({"content": "First turn."})
    adapter.ingest_turn({"content": "Second turn."})
    adapter.ingest_turn({"content": "Third turn."})
    assert adapter.query("anything", k=2) == ["Second turn.", "Third turn."]


def test_full_context_adapter_reset_clears_turns() -> None:
    adapter = FullContextAdapter()
    adapter.ingest_turn({"content": "First turn."})
    adapter.reset()
    assert adapter.turns == []


def test_end_to_end_text_resolution_with_akashik_adapter(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t001",
            "actor": "user",
            "content": "I live in Denver.",
            "ground_truth_facts": ["f001"],
            "revises_facts": [],
            "simulated_date": "2026-01-01",
        }
    )
    texts = adapter.query("Where do I live?")
    matched = resolve_fact_ids(texts, _persona_facts())
    assert matched == ["f001"]
