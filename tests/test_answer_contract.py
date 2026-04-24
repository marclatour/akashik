from __future__ import annotations

from akashik.answer_contract import (
    AnswerContract,
    contract_to_answer_text,
    parse_answer_contract,
    validate_answer_contract,
)
from akashik.reader import EvidenceFact, ReaderPacket


def _packet() -> ReaderPacket:
    fact = EvidenceFact(
        fact_id="fact-1",
        content="I live in Denver.",
        source_id=None,
        session_id="session-1",
        timestamp="2026-04-23",
        score=0.9,
        normalized_hash="hash-1",
    )
    return ReaderPacket(
        query="Where do I live?",
        question_type="single-session-user",
        facts=[fact],
        dropped_fact_ids=[],
        rationale=[],
        context_text="Evidence:\n\n[1] fact_id=fact-1 score=0.9000 session=session-1 time=2026-04-23\nI live in Denver.",
    )


def test_valid_answer_contract_passes() -> None:
    packet = _packet()
    contract = AnswerContract(
        answer="You live in Denver.",
        confidence="high",
        fact_ids=["fact-1"],
        answer_type="direct",
        abstain_reason=None,
    )

    assert validate_answer_contract(contract, packet) == (True, None)


def test_parse_answer_contract_invalid_json_returns_none() -> None:
    assert parse_answer_contract("{not json}") is None


def test_parse_answer_contract_parses_markdown_fenced_json() -> None:
    contract = parse_answer_contract(
        """```json
{"answer":"Denver","confidence":"high","fact_ids":["fact-1"],"answer_type":"direct","abstain_reason":null}
```"""
    )

    assert contract is not None
    assert contract.answer == "Denver"


def test_validate_answer_contract_rejects_unknown_fact_id() -> None:
    packet = _packet()
    contract = AnswerContract(
        answer="You live in Denver.",
        confidence="high",
        fact_ids=["fact-2"],
        answer_type="direct",
        abstain_reason=None,
    )

    valid, error = validate_answer_contract(contract, packet)

    assert valid is False
    assert "unknown fact_ids" in str(error)


def test_validate_answer_contract_rejects_non_abstain_without_fact_ids() -> None:
    packet = _packet()
    contract = AnswerContract(
        answer="You live in Denver.",
        confidence="medium",
        fact_ids=[],
        answer_type="direct",
        abstain_reason=None,
    )

    assert validate_answer_contract(contract, packet) == (
        False,
        "fact_ids required when confidence is not abstain",
    )


def test_validate_answer_contract_rejects_abstain_without_reason() -> None:
    packet = _packet()
    contract = AnswerContract(
        answer="",
        confidence="abstain",
        fact_ids=[],
        answer_type="unknown",
        abstain_reason=None,
    )

    assert validate_answer_contract(contract, packet) == (
        False,
        "abstain_reason required when confidence=abstain",
    )


def test_abstain_contract_passes_and_converts_to_default_text() -> None:
    packet = _packet()
    contract = AnswerContract(
        answer="",
        confidence="abstain",
        fact_ids=[],
        answer_type="unknown",
        abstain_reason="Evidence is insufficient.",
    )

    assert validate_answer_contract(contract, packet) == (True, None)
    assert contract_to_answer_text(contract) == "I don't know."


def test_validate_answer_contract_rejects_overlong_answer() -> None:
    packet = _packet()
    contract = AnswerContract(
        answer="A" * 1001,
        confidence="high",
        fact_ids=["fact-1"],
        answer_type="direct",
        abstain_reason=None,
    )

    assert validate_answer_contract(contract, packet) == (False, "answer too long")
