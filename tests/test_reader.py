from __future__ import annotations

from dataclasses import dataclass, field

from akashik.reader import read_context


@dataclass
class _FakeUnit:
    id: str
    content: str
    normalized_hash: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class _FakeResult:
    unit: _FakeUnit
    confidence: float


def _result(
    fact_id: str,
    content: str,
    *,
    score: float,
    normalized_hash: str | None = None,
    session_id: str | None = "session-1",
    timestamp: str | None = "2026-04-23",
):
    metadata: dict[str, object] = {}
    if session_id is not None:
        metadata["session_id"] = session_id
    if timestamp is not None:
        metadata["simulated_date"] = timestamp
    return _FakeResult(
        unit=_FakeUnit(
            id=fact_id,
            content=content,
            normalized_hash=normalized_hash,
            metadata=metadata,
        ),
        confidence=score,
    )


def test_read_context_deduplicates_by_normalized_hash() -> None:
    packet = read_context(
        "where do i live?",
        [
            _result("fact-low", "I live in Denver.", score=0.40, normalized_hash="same"),
            _result("fact-high", "I live in Denver.", score=0.95, normalized_hash="same"),
        ],
    )

    assert [fact.fact_id for fact in packet.facts] == ["fact-high"]
    assert packet.dropped_fact_ids == ["fact-low"]
    assert any("normalized_hash" in message for message in packet.rationale)


def test_read_context_deduplicates_by_normalized_content_when_hash_missing() -> None:
    packet = read_context(
        "where do i live?",
        [
            _result("fact-a", "I live in Denver.", score=0.40, normalized_hash=None),
            _result("fact-b", " i LIVE in denver ", score=0.70, normalized_hash=None),
        ],
    )

    assert [fact.fact_id for fact in packet.facts] == ["fact-b"]
    assert packet.dropped_fact_ids == ["fact-a"]
    assert any("normalized content" in message for message in packet.rationale)


def test_read_context_enforces_max_facts() -> None:
    packet = read_context(
        "question",
        [
            _result(f"fact-{index}", f"fact {index}", score=float(10 - index))
            for index in range(5)
        ],
        max_facts=3,
    )

    assert [fact.fact_id for fact in packet.facts] == ["fact-0", "fact-1", "fact-2"]
    assert packet.dropped_fact_ids[-2:] == ["fact-3", "fact-4"]
    assert any("max_facts=3" in message for message in packet.rationale)


def test_read_context_enforces_max_chars() -> None:
    packet = read_context(
        "question",
        [
            _result("fact-1", "A" * 80, score=0.9),
            _result("fact-2", "B" * 80, score=0.8),
            _result("fact-3", "C" * 80, score=0.7),
        ],
        max_chars=180,
    )

    assert len(packet.context_text) <= 180
    assert packet.dropped_fact_ids
    assert any("max_chars=180" in message for message in packet.rationale)


def test_read_context_context_text_includes_fact_ids() -> None:
    packet = read_context(
        "question",
        [
            _result("fact-1", "First fact.", score=0.9),
            _result("fact-2", "Second fact.", score=0.8),
        ],
    )

    for fact in packet.facts:
        assert fact.fact_id in packet.context_text
