from __future__ import annotations

import json

import pytest

import akashik.judge as judge


def test_normalize_basic() -> None:
    assert judge._normalize("7 days") == "7 day"


def test_normalize_numbers() -> None:
    assert judge._normalize("1,000") == "1000"


def test_deterministic_exact_match() -> None:
    assert judge._deterministic_match("Paris", "Paris") is True


def test_deterministic_substring() -> None:
    assert judge._deterministic_match("Paris", "The capital is Paris") is True


def test_deterministic_no_match() -> None:
    assert judge._deterministic_match("Paris", "London") is False


def test_deterministic_empty_answer() -> None:
    assert judge._deterministic_match("Paris", None) is None


def test_parse_yes() -> None:
    assert judge._parse_judgment("YES") is True


def test_parse_no() -> None:
    assert judge._parse_judgment("NO") is False


def test_parse_yes_with_explanation() -> None:
    assert judge._parse_judgment("yes, correct") is True


def test_parse_unparseable() -> None:
    assert judge._parse_judgment("maybe") is None


def test_judge_abstained(monkeypatch) -> None:
    called = {"count": 0}

    def fake_generate(**_kwargs):
        called["count"] += 1
        return "YES"

    monkeypatch.setattr(judge, "_ollama_generate", fake_generate)
    result = judge.judge_answer("q1", "Question?", "Paris", None)

    assert result.judgment is None
    assert result.abstained is True
    assert called["count"] == 0


def test_judge_deterministic_skips_ollama(monkeypatch) -> None:
    called = {"count": 0}

    def fake_generate(**_kwargs):
        called["count"] += 1
        return "YES"

    monkeypatch.setattr(judge, "_ollama_generate", fake_generate)
    result = judge.judge_answer("q1", "Question?", "Paris", "Paris")

    assert result.judgment is True
    assert result.confidence == judge.CONFIDENCE_DETERMINISTIC
    assert called["count"] == 0


def test_judge_model_yes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "cache.jsonl")
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: "YES")
    result = judge.judge_answer("q1", "Question?", "Paris", "London", use_cache=False)
    assert result.judgment is True


def test_judge_model_no(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "cache.jsonl")
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: "NO")
    result = judge.judge_answer("q1", "Question?", "Paris", "London", use_cache=False)
    assert result.judgment is False


def test_voting_3_0(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "cache.jsonl")
    responses = iter(["YES", "YES", "YES"])
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: next(responses))
    result = judge.judge_answer_with_voting("q1", "Question?", "Paris", "London", votes=3, use_cache=False)
    assert result.judgment is True
    assert result.confidence == judge.CONFIDENCE_HIGH


def test_voting_2_1(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "cache.jsonl")
    responses = iter(["YES", "YES", "NO"])
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: next(responses))
    result = judge.judge_answer_with_voting("q1", "Question?", "Paris", "London", votes=3, use_cache=False)
    assert result.judgment is True
    assert result.confidence == judge.CONFIDENCE_MEDIUM


def test_voting_1_2(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "cache.jsonl")
    responses = iter(["YES", "NO", "NO"])
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: next(responses))
    result = judge.judge_answer_with_voting("q1", "Question?", "Paris", "London", votes=3, use_cache=False)
    assert result.judgment is False
    assert result.confidence == judge.CONFIDENCE_MEDIUM


def test_voting_tie_conservative(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "cache.jsonl")
    responses = iter(["YES", "NO"])
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: next(responses))
    result = judge.judge_answer_with_voting("q1", "Question?", "Paris", "London", votes=2, use_cache=False)
    assert result.judgment is False


def test_unparseable_after_retries(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "cache.jsonl")
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: "maybe")
    result = judge.judge_answer_with_voting("q1", "Question?", "Paris", "London", votes=1, use_cache=False)
    assert result.judgment is None
    assert result.abstained is True


def test_ollama_unavailable_raises(monkeypatch) -> None:
    def fake_generate(**_kwargs):
        raise judge.OllamaUnavailableError("install ollama")

    monkeypatch.setattr(judge, "_ollama_generate", fake_generate)
    with pytest.raises(judge.OllamaUnavailableError, match="install ollama"):
        judge.judge_answer("q1", "Question?", "Paris", "London", use_cache=False)


def test_cache_hit_skips_ollama(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "cache.jsonl"
    cache_path.write_text(json.dumps({"key": judge._cache_key("Question?", "Paris", "London"), "judgment": True}) + "\n", encoding="utf-8")
    monkeypatch.setattr(judge, "CACHE_PATH", cache_path)
    called = {"count": 0}

    def fake_generate(**_kwargs):
        called["count"] += 1
        return "NO"

    monkeypatch.setattr(judge, "_ollama_generate", fake_generate)
    result = judge.judge_answer("q1", "Question?", "Paris", "London", use_cache=True)
    assert result.judgment is True
    assert result.from_cache is True
    assert called["count"] == 0


def test_cache_miss_saves_result(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "cache.jsonl"
    monkeypatch.setattr(judge, "CACHE_PATH", cache_path)
    monkeypatch.setattr(judge, "_ollama_generate", lambda **_kwargs: "NO")
    result = judge.judge_answer("q1", "Question?", "Paris", "London", use_cache=True)
    assert result.judgment is False
    saved = [json.loads(line) for line in cache_path.read_text(encoding="utf-8").splitlines()]
    assert saved
