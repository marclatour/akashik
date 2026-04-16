from __future__ import annotations

from akashik.ingest import ingest_text
from akashik.store import Store
from akashik.temporal_resolver import (
    classify_temporal_query,
    compute_delta,
    resolve_event_date,
    resolve_two_event_temporal,
)


def test_classify_days_between() -> None:
    result = classify_temporal_query(
        "How many days passed between the day I fixed my bike and the day I bought a new helmet?"
    )

    assert result == {
        "type": "delta",
        "unit": "days",
        "event_a": "fixed my bike",
        "event_b": "bought a new helmet",
    }


def test_classify_weeks_between() -> None:
    result = classify_temporal_query(
        "How many weeks passed between the time I sold baked goods and the Spring Fling Market?"
    )

    assert result is not None
    assert result["unit"] == "weeks"


def test_classify_months_between() -> None:
    result = classify_temporal_query(
        "How many months passed between the completion of my undergraduate degree and the submission of my masters thesis?"
    )

    assert result is not None
    assert result["unit"] == "months"


def test_classify_no_match() -> None:
    assert classify_temporal_query("What did I do last week?") is None


def test_classify_aggregation_returns_none() -> None:
    assert classify_temporal_query("Which airline did I fly most in March and April?") is None


def test_classify_strips_filler() -> None:
    result = classify_temporal_query(
        "How many days passed between the day I fixed my bike and the day I bought a new helmet?"
    )

    assert result is not None
    assert result["event_a"] == "fixed my bike"


def test_compute_delta_days() -> None:
    assert compute_delta("2024-01-01", "2024-01-15", "days") == 14


def test_compute_delta_weeks() -> None:
    assert compute_delta("2024-01-01", "2024-01-15", "weeks") == 2


def test_compute_delta_months() -> None:
    assert compute_delta("2024-01-15", "2024-03-15", "months") == 2


def test_compute_delta_absolute() -> None:
    assert compute_delta("2024-03-15", "2024-01-15", "months") == 2


def test_compute_delta_unparseable() -> None:
    assert compute_delta("bad-date", "2024-01-15", "days") is None


def test_resolve_event_date_found(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I fixed my mountain bike today.",
            metadata={"session_date": "2024-02-10", "instance_id": "test"},
        )

        resolved = resolve_event_date(
            store,
            "fixed mountain bike",
            {"instance_id": "test"},
        )

        assert resolved is not None
        assert resolved[0] == "2024-02-10"
        assert resolved[1] >= 0.6


def test_resolve_event_date_low_confidence(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I fixed my mountain bike today.",
            metadata={"session_date": "2024-02-10", "instance_id": "test"},
        )

        resolved = resolve_event_date(
            store,
            "completely unrelated event",
            {"instance_id": "test"},
        )

        assert resolved is None


def test_resolve_two_event_full_pipeline(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I fixed my mountain bike today.",
            metadata={"session_date": "2024-02-10", "instance_id": "test"},
        )
        ingest_text(
            store,
            "I decided to upgrade my road bike pedals.",
            metadata={"session_date": "2024-03-05", "instance_id": "test"},
        )

        result = resolve_two_event_temporal(
            store,
            "How many days passed between the day I fixed my mountain bike and the day I decided to upgrade my road bike pedals?",
            {"instance_id": "test"},
        )

        assert result is not None
        assert result["delta"] == 24
        assert result["unit"] == "days"
        assert result["event_a_date"] == "2024-02-10"
        assert result["event_b_date"] == "2024-03-05"


def test_resolve_two_event_fail_open(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        ingest_text(
            store,
            "I fixed my mountain bike today.",
            metadata={"session_date": "2024-02-10", "instance_id": "test"},
        )

        result = resolve_two_event_temporal(
            store,
            "How many days passed between the day I fixed my mountain bike and the day I bought a new helmet?",
            {"instance_id": "test"},
        )

        assert result is None
