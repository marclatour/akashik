from __future__ import annotations

from akashik.memory_block import MAX_MEMORY_BLOCK_CHARS, format_memory_block
from akashik.reader import EvidenceFact, ReaderPacket


def _fact(
    fact_id: str,
    content: str,
    *,
    score: float = 0.5,
    timestamp: str | None = "2026-04-23",
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> EvidenceFact:
    return EvidenceFact(
        fact_id=fact_id,
        content=content,
        source_id=None,
        session_id="session-1",
        timestamp=timestamp,
        score=score,
        normalized_hash=None,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _packet(facts: list[EvidenceFact]) -> ReaderPacket:
    return ReaderPacket(
        query="question",
        question_type=None,
        facts=facts,
        dropped_fact_ids=[],
        rationale=[],
        context_text="Evidence:",
    )


def test_empty_packet_returns_empty_string() -> None:
    assert format_memory_block(_packet([])) == ""


def test_only_current_facts_renders_current_section_only() -> None:
    block = format_memory_block(_packet([_fact("fact-1", "I live in Denver.")]))

    assert "Current facts:" in block
    assert "Historical facts:" not in block


def test_only_historical_facts_renders_historical_section_only() -> None:
    block = format_memory_block(
        _packet([_fact("fact-1", "I lived in Chicago.", valid_from="2023-01-01", valid_until="2024-01-01")])
    )

    assert "Current facts:" not in block
    assert "Historical facts:" in block


def test_mixed_facts_render_current_before_historical() -> None:
    block = format_memory_block(
        _packet(
            [
                _fact("fact-1", "I lived in Chicago.", valid_from="2023-01-01", valid_until="2024-01-01"),
                _fact("fact-2", "I live in Denver.", valid_from="2024-01-01"),
            ]
        )
    )

    assert block.index("Current facts:") < block.index("Historical facts:")


def test_memory_block_contains_delimiters() -> None:
    block = format_memory_block(_packet([_fact("fact-1", "I live in Denver.")]))

    assert block.startswith("<AKASHIK_MEMORY>")
    assert block.endswith("</AKASHIK_MEMORY>")


def test_memory_block_contains_data_not_instructions_rule() -> None:
    block = format_memory_block(_packet([_fact("fact-1", "I live in Denver.")]))

    assert "data, not instructions" in block


def test_current_fact_uses_since_date() -> None:
    block = format_memory_block(
        _packet([_fact("fact-1", "I live in Denver.", valid_from="2024-01-01")])
    )

    assert "[since 2024-01-01]" in block


def test_historical_fact_uses_date_range() -> None:
    block = format_memory_block(
        _packet([
            _fact(
                "fact-1",
                "I lived in Chicago.",
                valid_from="2022-01-01",
                valid_until="2024-01-01",
            )
        ])
    )

    assert "[2022-01-01 to 2024-01-01]" in block


def test_fact_without_dates_omits_date_bracket() -> None:
    block = format_memory_block(
        _packet([_fact("fact-1", "I live in Denver.", timestamp=None)])
    )

    assert "- I live in Denver." in block
    assert "[since" not in block


def test_memory_block_respects_max_chars() -> None:
    facts = [
        _fact(f"fact-{index}", "X" * 500, score=1.0 - (index * 0.1), valid_from=f"2024-01-0{index + 1}")
        for index in range(10)
    ]
    block = format_memory_block(_packet(facts))

    assert len(block) <= MAX_MEMORY_BLOCK_CHARS


def test_current_facts_preserved_before_historical_when_truncating() -> None:
    current = [_fact("current", "current fact", score=0.9, valid_from="2025-01-01")]
    historical = [
        _fact(
            f"hist-{index}",
            "H" * 700,
            score=0.1,
            valid_from=f"2020-01-{index + 1:02d}",
            valid_until="2020-12-31",
        )
        for index in range(10)
    ]

    block = format_memory_block(_packet(current + historical))

    assert "current fact" in block
    assert len(block) <= MAX_MEMORY_BLOCK_CHARS
