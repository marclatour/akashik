from __future__ import annotations

import json
from urllib import error

import akashik.ingest_pipeline as pipeline_module
from akashik.ingest_pipeline import ingest_turn
from akashik.store import Store


def _fact_count(store: Store) -> int:
    row = store.execute(
        "SELECT COUNT(*) FROM memory_units WHERE level = 'fact'"
    ).fetchone()
    return int(row[0])


def test_ollama_unavailable_skips_and_warns(tmp_path, monkeypatch, caplog) -> None:
    def _down(_text: str) -> str:
        raise error.URLError("connection refused")

    monkeypatch.setattr(pipeline_module, "_call_ollama", _down)

    with Store(tmp_path / "store.db") as store:
        with caplog.at_level("WARNING", logger="akashik.ingest_pipeline"):
            result = ingest_turn(store, "I live in Chicago.")

        assert result["written"] is False
        assert result["skipped_reason"] == "ollama_unavailable"
        assert _fact_count(store) == 0
    assert any("Ollama call failed" in record.message for record in caplog.records)


def test_unparseable_response_skips_and_warns(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(pipeline_module, "_call_ollama", lambda _text: "not json at all")

    with Store(tmp_path / "store.db") as store:
        with caplog.at_level("WARNING", logger="akashik.ingest_pipeline"):
            result = ingest_turn(store, "I live in Chicago.")

        assert result["written"] is False
        assert result["skipped_reason"] == "parse_error"
        assert result["raw_response"] == "not json at all"
        assert _fact_count(store) == 0
    assert any("Unparseable extraction response" in record.message for record in caplog.records)


def test_valid_extraction_writes_fact(tmp_path, monkeypatch) -> None:
    payload = json.dumps(
        {"fact": "User lives in Chicago", "topic": "location", "confidence": 0.95}
    )
    monkeypatch.setattr(pipeline_module, "_call_ollama", lambda _text: payload)

    with Store(tmp_path / "store.db") as store:
        result = ingest_turn(store, "I live in Chicago.", simulated_date="2026-06-10")

        assert result["written"] is True
        assert result["fact"] == "User lives in Chicago."
        assert result["skipped_reason"] is None
        assert _fact_count(store) == 1


def test_markdown_fenced_json_is_parsed(tmp_path, monkeypatch) -> None:
    payload = (
        "```json\n"
        + json.dumps({"fact": "User drives a Volvo", "topic": "vehicle", "confidence": 0.9})
        + "\n```"
    )
    monkeypatch.setattr(pipeline_module, "_call_ollama", lambda _text: payload)

    with Store(tmp_path / "store.db") as store:
        result = ingest_turn(store, "I drive a Volvo.")

        assert result["written"] is True
        assert result["fact"] == "User drives a Volvo."


def test_low_confidence_extraction_not_written(tmp_path, monkeypatch) -> None:
    payload = json.dumps(
        {"fact": "User might like jazz", "topic": "music", "confidence": 0.4}
    )
    monkeypatch.setattr(pipeline_module, "_call_ollama", lambda _text: payload)

    with Store(tmp_path / "store.db") as store:
        result = ingest_turn(store, "I guess jazz is fine sometimes.")

        assert result["written"] is False
        assert result["skipped_reason"] == "low_confidence"
        assert _fact_count(store) == 0


def test_third_party_fact_not_written(tmp_path, monkeypatch) -> None:
    payload = json.dumps(
        {"fact": "My wife works at Helio", "topic": "occupation", "confidence": 0.95}
    )
    monkeypatch.setattr(pipeline_module, "_call_ollama", lambda _text: payload)

    with Store(tmp_path / "store.db") as store:
        result = ingest_turn(store, "My wife works at Helio.")

        assert result["written"] is False
        assert result["skipped_reason"] == "third_party_fact"
        assert _fact_count(store) == 0


def test_null_fact_not_written(tmp_path, monkeypatch) -> None:
    payload = json.dumps({"fact": None, "topic": None, "confidence": 0.0})
    monkeypatch.setattr(pipeline_module, "_call_ollama", lambda _text: payload)

    with Store(tmp_path / "store.db") as store:
        result = ingest_turn(store, "I spent the weekend hiking.")

        assert result["written"] is False
        assert result["skipped_reason"] == "no_fact"
        assert _fact_count(store) == 0
