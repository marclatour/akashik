from __future__ import annotations

from datetime import date
import logging

from akashik.parse_temporal_scope import parse_temporal_scope


QUESTION_DATE = "2024-03-15"


def test_yesterday() -> None:
    assert parse_temporal_scope("What changed yesterday?", QUESTION_DATE) == (
        date(2024, 3, 14),
        date(2024, 3, 14),
    )


def test_today_variants() -> None:
    assert parse_temporal_scope("What happened this morning?", QUESTION_DATE) == (
        date(2024, 3, 15),
        date(2024, 3, 15),
    )
    assert parse_temporal_scope("What changed earlier today?", QUESTION_DATE) == (
        date(2024, 3, 15),
        date(2024, 3, 15),
    )


def test_last_week() -> None:
    assert parse_temporal_scope("Show me last week", QUESTION_DATE) == (
        date(2024, 3, 8),
        date(2024, 3, 14),
    )


def test_this_week() -> None:
    assert parse_temporal_scope("What happened this week?", QUESTION_DATE) == (
        date(2024, 3, 11),
        date(2024, 3, 15),
    )


def test_last_month() -> None:
    assert parse_temporal_scope("What changed last month?", QUESTION_DATE) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
    )


def test_this_month() -> None:
    assert parse_temporal_scope("What changed this month?", QUESTION_DATE) == (
        date(2024, 3, 1),
        date(2024, 3, 15),
    )


def test_days_ago() -> None:
    assert parse_temporal_scope("What happened 5 days ago?", QUESTION_DATE) == (
        date(2024, 3, 10),
        date(2024, 3, 10),
    )


def test_weeks_ago() -> None:
    assert parse_temporal_scope("What happened 2 weeks ago?", QUESTION_DATE) == (
        date(2024, 3, 1),
        date(2024, 3, 7),
    )


def test_months_ago() -> None:
    assert parse_temporal_scope("What changed 2 months ago?", QUESTION_DATE) == (
        date(2024, 1, 1),
        date(2024, 1, 31),
    )


def test_in_month_uses_most_recent_past_year() -> None:
    assert parse_temporal_scope("What happened in March?", QUESTION_DATE) == (
        date(2024, 3, 1),
        date(2024, 3, 31),
    )
    assert parse_temporal_scope("What happened in December?", QUESTION_DATE) == (
        date(2023, 12, 1),
        date(2023, 12, 31),
    )


def test_last_named_month() -> None:
    assert parse_temporal_scope("What happened last February?", QUESTION_DATE) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
    )
    assert parse_temporal_scope("What happened last March?", QUESTION_DATE) == (
        date(2023, 3, 1),
        date(2023, 3, 31),
    )


def test_last_day_name() -> None:
    assert parse_temporal_scope("What happened last Monday?", QUESTION_DATE) == (
        date(2024, 3, 11),
        date(2024, 3, 11),
    )


def test_fuzzy_recent_window() -> None:
    assert parse_temporal_scope("What changed recently?", QUESTION_DATE) == (
        date(2024, 3, 1),
        date(2024, 3, 14),
    )
    assert parse_temporal_scope("What happened the other day?", QUESTION_DATE) == (
        date(2024, 3, 1),
        date(2024, 3, 14),
    )


def test_returns_none_when_no_temporal_expression_found() -> None:
    assert parse_temporal_scope("What does the agreement say?", QUESTION_DATE) is None


def test_returns_none_for_unsupported_multi_expression(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        result = parse_temporal_scope("What happened between January and March?", QUESTION_DATE)

    assert result is None
    assert "Unsupported multi-expression temporal query" in caplog.text


def test_longmemeval_question_date_format_is_supported() -> None:
    assert parse_temporal_scope("What happened yesterday?", "2023/04/10 (Mon) 23:07") == (
        date(2023, 4, 9),
        date(2023, 4, 9),
    )
