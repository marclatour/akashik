from __future__ import annotations

from click.testing import CliRunner

from akashik.cli import cli
from akashik.executor import classify_query, execute
from akashik.identity import content_hash, normalized_hash
from akashik.ingest import ingest_text
from akashik.schema import MemoryUnit
from akashik.store import Store


def _metadata(**overrides) -> dict:
    metadata = {
        "source": "test",
        "timestamp": "2026-04-16T00:00:00+00:00",
        "tags": [],
        "instance_id": "test",
        "speaker": "user",
        "session_id": "session_1",
        "session_date": "2024-01-01",
    }
    metadata.update(overrides)
    return metadata


def _unit(
    content: str,
    *,
    metadata: dict | None = None,
    confirmation_count: int = 1,
    last_confirmed_at: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> MemoryUnit:
    unit_metadata = _metadata()
    if metadata:
        unit_metadata.update(metadata)
    return MemoryUnit(
        level="fact",
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        metadata=unit_metadata,
        confirmation_count=confirmation_count,
        last_confirmed_at=last_confirmed_at,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def test_classify_factual() -> None:
    assert classify_query("Where do I live?") == "factual"


def test_classify_temporal() -> None:
    assert classify_query("How many days passed between X and Y?") == "temporal"


def test_classify_preference() -> None:
    assert classify_query("What camera do I use?") == "preference"


def test_classify_preference_before_aggregation() -> None:
    assert classify_query("What tools do I use most?") == "preference"


def test_classify_aggregation() -> None:
    assert classify_query("How many times did I go to the gym?") == "aggregation"


def test_classify_unknown_fails_open() -> None:
    assert classify_query("Tell me something interesting") == "unknown"


def test_classify_when_did_i() -> None:
    assert classify_query("When did I start my new job?") == "temporal"


def test_classify_what_is_my() -> None:
    assert classify_query("What is my current address?") == "factual"


def test_classify_what_are_my() -> None:
    assert classify_query("What are my hobbies?") == "factual"


def test_classify_remind_me() -> None:
    assert classify_query("Can you remind me what I said about my diet?") == "factual"


def test_classify_across_conversations() -> None:
    assert classify_query("Across our conversations, how many books have I mentioned?") == "aggregation"


def test_classify_current_state() -> None:
    assert classify_query("What is my current job?") == "factual"


def test_classify_how_long_ago() -> None:
    assert classify_query("How long ago did I mention my trip to Paris?") == "temporal"


def test_classify_preference_still_before_aggregation() -> None:
    assert classify_query("What tools do I use most?") == "preference"


def test_factual_lookup_returns_answer(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "I live in Chicago.", metadata=_metadata())

        result = execute(store, "Where do I live?", entity_filters={"instance_id": "test"})

        assert "Chicago" in (result.answer or "")
        assert result.abstained is False
        assert result.sources
        assert result.raw_facts


def test_factual_value_extraction(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "I moved to New York.", metadata=_metadata())

        result = execute(store, "Where do I live?", entity_filters={"instance_id": "test"})

        assert result.answer == "New York"


def test_factual_lookup_abstains_on_low_confidence(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "I live in Chicago.", metadata=_metadata())

        result = execute(store, "phrase that matches nothing", entity_filters={"instance_id": "test"})

        assert result.abstained is True
        assert result.answer is None
        assert result.raw_facts == []


def test_factual_lookup_respects_validity(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I live in Chicago.",
            metadata=_metadata(session_date="2022-01-01"),
        )
        ingest_text(
            store,
            "I moved to New York last month.",
            metadata=_metadata(session_date="2024-06-01"),
        )

        result = execute(store, "Where do I live?", entity_filters={"instance_id": "test"})

        assert result.answer == "New York"


def test_temporal_delta_returns_answer(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I fixed my mountain bike today.",
            metadata=_metadata(session_date="2024-02-10"),
        )
        ingest_text(
            store,
            "I decided to upgrade my road bike pedals.",
            metadata=_metadata(session_date="2024-03-05"),
        )

        result = execute(
            store,
            "How many days passed between the day I fixed my mountain bike and the day I decided to upgrade my road bike pedals?",
            entity_filters={"instance_id": "test"},
        )

        assert result.answer == "24 days"
        assert len(result.sources) == 2


def test_temporal_falls_back_to_factual(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "I live in Chicago.", metadata=_metadata())

        result = execute(
            store,
            "How many days passed between the day I fixed my bike and the day I bought a helmet?",
            entity_filters={"instance_id": "test"},
        )

        assert result.answer_type == "temporal"
        assert result.requires_reasoning is True


def test_preference_returns_primary(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I love Sony.",
            metadata=_metadata(session_date="2024-01-01"),
        )
        ingest_text(
            store,
            "I prefer Sony.",
            metadata=_metadata(session_date="2024-02-01"),
        )
        ingest_text(
            store,
            "I like Fuji.",
            metadata=_metadata(session_date="2024-03-01"),
        )

        result = execute(store, "What camera do I use?", entity_filters={"instance_id": "test"})

        assert "Sony" in (result.answer or "")
        assert result.requires_reasoning is True


def test_preference_confidence_uses_reinforcement(tmp_path) -> None:
    with Store(tmp_path / "left.db") as left, Store(tmp_path / "right.db") as right:
        ingest_text(left, "I prefer Sony.", metadata=_metadata(session_date="2024-01-01"))
        ingest_text(left, "I prefer Sony.", metadata=_metadata(session_date="2024-02-01"))
        ingest_text(right, "I prefer Sony.", metadata=_metadata(session_date="2024-01-01"))

        reinforced = execute(left, "What camera do I use?", entity_filters={"instance_id": "test"})
        single = execute(right, "What camera do I use?", entity_filters={"instance_id": "test"})

        assert reinforced.answer_confidence > single.answer_confidence


def test_preference_falls_back_to_factual(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "I use a blue backpack.", metadata=_metadata())

        result = execute(store, "What do I use?", entity_filters={"instance_id": "test"})

        assert result.answer_type == "preference"
        assert result.raw_facts


def test_aggregation_count_uses_facts_not_sessions(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        texts = [
            "I went to the gym on Monday.",
            "I went to the gym on Tuesday.",
            "I went to the gym on Wednesday.",
            "I went to the gym on Thursday.",
            "I went to the gym on Friday.",
        ]
        for index, text in enumerate(texts, start=1):
            session_id = "session_a" if index <= 3 else "session_b"
            ingest_text(
                store,
                text,
                metadata=_metadata(session_id=session_id, session_date=f"2024-01-0{index}"),
            )

        result = execute(
            store,
            "How many times did I go to the gym?",
            entity_filters={"instance_id": "test"},
        )

        assert result.answer == "5"


def test_abstention_threshold(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "I live in Chicago.", metadata=_metadata())

        result = execute(
            store,
            "Where do I live?",
            entity_filters={"instance_id": "test"},
            abstention_threshold=0.99,
        )

        assert result.abstained is True


def test_raw_facts_always_returned(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        result = execute(store, "Where do I live?", entity_filters={"instance_id": "test"})

        assert result.raw_facts == []


def test_sources_have_provenance(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(store, "I live in Chicago.", metadata=_metadata())

        result = execute(store, "Where do I live?", entity_filters={"instance_id": "test"})

        assert result.sources
        source = result.sources[0]
        assert source.fact_id
        assert source.content
        assert source.session_id == "session_1"
        assert source.session_date == "2024-01-01"


def test_confidence_calculation_favors_reinforcement(tmp_path) -> None:
    with Store(tmp_path / "recent.db") as recent, Store(tmp_path / "old.db") as old:
        ingest_text(
            recent,
            "I live in Chicago.",
            metadata=_metadata(session_date="2024-12-01"),
        )
        ingest_text(
            recent,
            "I live in Chicago.",
            metadata=_metadata(session_date="2024-12-15"),
        )
        ingest_text(
            recent,
            "I live in Chicago.",
            metadata=_metadata(session_date="2024-12-20"),
        )
        ingest_text(
            old,
            "I live in Chicago.",
            metadata=_metadata(session_date="2022-01-01"),
        )

        recent_result = execute(
            recent,
            "Where do I live?",
            entity_filters={"instance_id": "test"},
            query_date="2024-12-01",
        )
        old_result = execute(
            old,
            "Where do I live?",
            entity_filters={"instance_id": "test"},
            query_date="2024-12-01",
        )

        assert recent_result.answer_confidence > old_result.answer_confidence


def test_coverage_confidence_smooth_formula(tmp_path) -> None:
    with Store(tmp_path / "one.db") as single, Store(tmp_path / "three.db") as triple:
        single.insert(
            _unit(
                "user preference: like Sony (strength: moderate)",
                metadata=_metadata(
                    derived="preference",
                    preference_value="Sony",
                    preference_strength="moderate",
                    preference_polarity="like",
                ),
            )
        )
        for index in range(3):
            triple.insert(
                _unit(
                    f"user preference: like Sony {index} (strength: moderate)",
                    metadata=_metadata(
                        session_id=f"session_{index}",
                        derived="preference",
                        preference_value="Sony",
                        preference_strength="moderate",
                        preference_polarity="like",
                    ),
                )
            )

        one_result = execute(single, "What camera do I use?", entity_filters={"instance_id": "test"})
        three_result = execute(triple, "What camera do I use?", entity_filters={"instance_id": "test"})

        assert 0.3 < one_result.coverage_confidence < 0.4
        assert three_result.coverage_confidence > one_result.coverage_confidence


def test_cli_execute_command(tmp_path) -> None:
    store_path = tmp_path / "store.db"
    with Store(store_path) as store:
        ingest_text(store, "I live in Chicago.", metadata=_metadata())

    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(store_path), "execute", "Where do I live?"])

    assert result.exit_code == 0
    assert "Answer:" in result.output


def test_execute_logs_and_abstains_on_internal_error(tmp_path, monkeypatch, caplog) -> None:
    import akashik.executor as executor_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(executor_module, "_execute_factual", _boom)

    with Store(tmp_path / "store.db") as store:
        with caplog.at_level("ERROR", logger="akashik.executor"):
            result = execute(store, "where do I live?")

    assert result.abstained is True
    assert any("execute() failed" in record.message for record in caplog.records)
    assert any(
        record.exc_text and "forced failure" in record.exc_text
        for record in caplog.records
    )
