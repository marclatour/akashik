from __future__ import annotations

from akashik.identity import content_hash, normalized_hash
from akashik.schema import MemoryUnit
from akashik.semantic import SemanticConfig, SemanticRanker


def _unit(content: str) -> MemoryUnit:
    return MemoryUnit(
        level="fact",
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        metadata={"source": "tests"},
    )


def test_rerank_returns_original_order_above_threshold(monkeypatch) -> None:
    ranker = SemanticRanker()
    calls: list[str] = []

    monkeypatch.setattr(ranker, "_load_model", lambda: calls.append("load"))

    candidates = [_unit("alpha"), _unit("beta")]
    ranked = ranker.rerank("query", candidates, current_confidence=0.9)

    assert ranked == candidates
    assert calls == []


def test_rerank_returns_original_order_below_min_candidates(monkeypatch) -> None:
    ranker = SemanticRanker()
    calls: list[str] = []

    monkeypatch.setattr(ranker, "_load_model", lambda: calls.append("load"))

    candidates = [_unit("alpha")]
    ranked = ranker.rerank("query", candidates, current_confidence=0.5)

    assert ranked == candidates
    assert calls == []


def test_rerank_fires_below_threshold(monkeypatch) -> None:
    ranker = SemanticRanker()

    class FakeModel:
        def encode(self, text: str, **_kwargs):
            mapping = {
                "semantic query": [1.0, 0.0],
                "alpha candidate": [0.0, 1.0],
                "beta candidate": [1.0, 0.0],
                "gamma candidate": [0.5, 0.5],
            }
            return mapping[text]

    monkeypatch.setattr(ranker, "_load_model", lambda: FakeModel())

    candidates = [_unit("alpha candidate"), _unit("beta candidate"), _unit("gamma candidate")]
    ranked = ranker.rerank("semantic query", candidates, current_confidence=0.5)

    assert len(ranked) == len(candidates)
    assert ranked[0].content == "beta candidate"


def test_rerank_fail_open_on_bad_model() -> None:
    ranker = SemanticRanker(SemanticConfig(model_name="nonexistent-model"))
    candidates = [_unit("alpha"), _unit("beta")]

    ranked = ranker.rerank("query", candidates, current_confidence=0.5)

    assert ranked == candidates


def test_semantic_ranker_is_lazy(monkeypatch) -> None:
    ranker = SemanticRanker()
    assert ranker._model is None

    load_calls: list[str] = []

    class FakeModel:
        def encode(self, text: str, **_kwargs):
            return [1.0, 0.0] if text == "query" else [0.0, 1.0]

    def fake_load():
        load_calls.append("load")
        return FakeModel()

    monkeypatch.setattr(ranker, "_load_model", fake_load)

    ranker.rerank("query", [_unit("alpha"), _unit("beta")], current_confidence=0.5)

    assert load_calls == ["load"]
