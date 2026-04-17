from __future__ import annotations

from akashik.ingest import ingest_text
from akashik.preference_extractor import extract_preferences
from akashik.store import Store


def test_strong_positive_love() -> None:
    extracted = extract_preferences("I love my Sony A7R IV camera")

    assert extracted == [
        {
            "entity": "user",
            "attribute": "preference",
            "value": "Sony A7R IV camera",
            "polarity": "like",
            "strength": "strong",
        }
    ]


def test_moderate_positive_prefer() -> None:
    extracted = extract_preferences("I prefer Adobe Premiere Pro for video editing")

    assert extracted[0]["polarity"] == "like"
    assert extracted[0]["strength"] == "moderate"
    assert extracted[0]["value"] == "Adobe Premiere Pro"


def test_weak_positive_thinking() -> None:
    extracted = extract_preferences("I'm thinking about trying DaVinci Resolve")

    assert extracted[0]["polarity"] == "like"
    assert extracted[0]["strength"] == "weak"


def test_strong_negative_hate() -> None:
    extracted = extract_preferences("I hate Windows")

    assert extracted[0]["polarity"] == "dislike"
    assert extracted[0]["strength"] == "strong"


def test_moderate_negative_dont_like() -> None:
    extracted = extract_preferences("I don't like general video editing resources")

    assert extracted[0]["polarity"] == "dislike"
    assert extracted[0]["strength"] == "moderate"


def test_multiple_preferences_in_one_turn() -> None:
    extracted = extract_preferences("I love Sony but I hate Canon")

    assert len(extracted) == 2
    assert ("Sony", "like", "strong") in {(item["value"], item["polarity"], item["strength"]) for item in extracted}
    assert ("Canon", "dislike", "strong") in {(item["value"], item["polarity"], item["strength"]) for item in extracted}


def test_pronoun_value_skipped() -> None:
    assert extract_preferences("I love it") == []


def test_generic_value_skipped() -> None:
    assert extract_preferences("I like everything") == []


def test_empty_value_skipped() -> None:
    assert extract_preferences("I prefer") == []


def test_stop_phrase_trimming() -> None:
    extracted = extract_preferences("I love Sony A7R IV for landscape photography")

    assert extracted[0]["value"] == "Sony A7R IV"


def test_assistant_turn_not_extracted(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I love Sony cameras.",
            metadata={"instance_id": "test", "session_date": "2024-01-01", "speaker": "assistant"},
        )

        derived = store.fetch_by_metadata_filters(level="fact", filters={"derived": "preference"})

        assert derived == []


def test_derived_fact_created_in_store(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I love my Sony A7R IV.",
            metadata={"instance_id": "test", "session_date": "2024-01-01", "speaker": "user"},
        )

        derived = store.fetch_by_metadata_filters(level="fact", filters={"derived": "preference"})

        assert len(derived) == 1
        assert derived[0].metadata["preference_strength"] == "strong"
        assert derived[0].metadata["derived"] == "preference"


def test_derived_fact_polarity_contradiction(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I love Canon.",
            metadata={"instance_id": "test", "session_date": "2024-01-01", "speaker": "user"},
        )
        ingest_text(
            store,
            "I hate Canon.",
            metadata={"instance_id": "test", "session_date": "2024-02-01", "speaker": "user"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"derived": "preference"})
        likes = [fact for fact in facts if fact.metadata["preference_polarity"] == "like"]
        dislikes = [fact for fact in facts if fact.metadata["preference_polarity"] == "dislike"]

        assert len(likes) == 1
        assert likes[0].metadata["preference_value"] == "Canon"
        assert likes[0].valid_until == "2024-02-01"
        assert len(dislikes) == 1
        assert dislikes[0].valid_until is None


def test_different_values_coexist(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I love Sony.",
            metadata={"instance_id": "test", "session_date": "2024-01-01", "speaker": "user"},
        )
        ingest_text(
            store,
            "I love Fuji.",
            metadata={"instance_id": "test", "session_date": "2024-02-01", "speaker": "user"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"derived": "preference"})

        assert len(facts) == 2
        assert all(fact.valid_until is None for fact in facts)


def test_derived_fact_reinforcement(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I prefer Sony.",
            metadata={"instance_id": "test", "session_date": "2024-01-01", "speaker": "user"},
        )
        ingest_text(
            store,
            "I prefer Sony.",
            metadata={"instance_id": "test", "session_date": "2024-02-01", "speaker": "user"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"derived": "preference"})

        assert len(facts) == 1
        assert facts[0].confirmation_count == 2


def test_raw_fact_preserved_alongside_derived(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I love Sony cameras.",
            metadata={"instance_id": "test", "session_date": "2024-01-01", "speaker": "user"},
        )

        facts = store.fetch_by_metadata_filters(level="fact", filters={"instance_id": "test"})
        raw = [fact for fact in facts if fact.metadata.get("derived") != "preference"]
        derived = [fact for fact in facts if fact.metadata.get("derived") == "preference"]

        assert raw
        assert derived


def test_strength_in_metadata(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I recommend Sony cameras.",
            metadata={"instance_id": "test", "session_date": "2024-01-01", "speaker": "user"},
        )

        derived = store.fetch_by_metadata_filters(level="fact", filters={"derived": "preference"})

        assert derived[0].metadata["preference_strength"] == "moderate"
