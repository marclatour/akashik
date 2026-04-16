from __future__ import annotations

from datetime import date

from akashik.identity import content_hash, normalized_hash
from akashik.navigator import (
    _decay_score,
    is_label_like,
    rank_facts,
    score_heading_match,
    score_recency,
    score_specificity,
)
from akashik.schema import MemoryUnit


def _fact(
    content: str,
    *,
    section_heading: str | None = None,
    metadata: dict | None = None,
    confirmation_count: int = 1,
    last_confirmed_at: str | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        level="fact",
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        metadata=dict(metadata or {"source": "test.txt"}),
        section_heading=section_heading,
        confirmation_count=confirmation_count,
        last_confirmed_at=last_confirmed_at,
    )


def test_specificity_scores_higher_for_qualified_facts() -> None:
    qualified = score_specificity(
        'For purposes of Section 12, "Buyer" means Atlas Corp with respect to Ontario operations.'
    )
    general = score_specificity("This Agreement is governed by Ontario law.")

    assert qualified > general


def test_is_label_like_true_for_short_headings() -> None:
    assert is_label_like("TERM AND RENEWAL") is True
    assert is_label_like("Termination for Cause") is True
    assert is_label_like("Governing Law") is True


def test_is_label_like_false_for_substantive_facts() -> None:
    assert is_label_like("This Agreement shall be governed by the laws of the State of California.") is False
    assert is_label_like("Either party may terminate this Agreement upon thirty days written notice.") is False


def test_recency_penalizes_superseded_facts() -> None:
    assert score_recency({"superseded_by": "new-fact-id"}) == 0.0
    assert score_recency({}) == 1.0


def test_heading_match_exact_returns_1() -> None:
    assert score_heading_match("Governing Law Jurisdiction", "governed laws jurisdiction") == 1.0


def test_heading_match_partial_returns_0_5() -> None:
    assert score_heading_match("Governing Law", "governed laws jurisdiction") == 0.5


def test_heading_match_none_returns_0() -> None:
    assert score_heading_match("Definitions", "governed laws jurisdiction") == 0.0
    assert score_heading_match(None, "governed laws jurisdiction") == 0.0


def test_label_like_fact_capped_at_0_1() -> None:
    label = _fact("Governing Law", section_heading="Governing Law")

    ranked = rank_facts([label], "governed laws jurisdiction")

    assert ranked[0][1] <= 0.1


def test_specificity_requires_minimum_tokens() -> None:
    assert score_specificity("Ontario law governs.") == 0.0


def test_specificity_scores_positive_signals() -> None:
    assert score_specificity(
        "Compliance shall follow the laws of California under this agreement."
    ) == 0.5
    assert score_specificity(
        "For purposes of this Agreement, the Company shall comply with the laws of California."
    ) == 1.0


def test_heading_match_not_applied_to_label_like_facts() -> None:
    label = _fact("Governing Law", section_heading="Governing Law")
    substantive = _fact(
        "This Agreement shall be governed by the laws of the State of California.",
        section_heading="Governing Law",
    )

    ranked = rank_facts([label, substantive], "governed laws jurisdiction")

    assert [fact for fact, _score in ranked] == [substantive, label]
    assert ranked[1][1] <= 0.1


def test_rank_facts_returns_descending_order() -> None:
    definitions = _fact(
        "This Agreement is governed by Ontario law.",
        section_heading="Definitions",
    )
    governing = _fact(
        'For purposes of Section 12, "Buyer" is governed by Ontario law with respect to Atlas Corp.',
        section_heading="Governing Law Jurisdiction",
    )

    ranked = rank_facts([definitions, governing], "governed laws jurisdiction")

    assert [fact for fact, _score in ranked] == [governing, definitions]
    assert ranked[0][1] > ranked[1][1]


def test_rank_facts_stable_on_ties() -> None:
    first = _fact("Plain operational fact.", section_heading="Definitions")
    second = _fact("Plain operational fact.", section_heading="Definitions")

    ranked = rank_facts([first, second], "unmatched query")

    assert [fact for fact, _score in ranked] == [first, second]


def test_decay_score_unreinforced() -> None:
    fact = _fact("Test fact.", confirmation_count=1, last_confirmed_at="2024-11-30")

    assert _decay_score(fact, query_date=date(2024, 12, 1)) == 0.03


def test_decay_score_reinforced() -> None:
    fact = _fact("Test fact.", confirmation_count=3, last_confirmed_at="2024-11-30")

    assert _decay_score(fact, query_date=date(2024, 12, 1)) == 0.05


def test_decay_score_recent() -> None:
    fact = _fact("Test fact.", confirmation_count=1, last_confirmed_at="2024-11-30")

    assert _decay_score(fact, query_date=date(2024, 12, 1)) == 0.03


def test_decay_score_stale() -> None:
    fact = _fact("Test fact.", confirmation_count=1, last_confirmed_at="2022-01-01")

    assert _decay_score(fact, query_date=date(2024, 12, 1)) == 0.0


def test_decay_score_no_query_date() -> None:
    fact = _fact("Test fact.", confirmation_count=4, last_confirmed_at="2024-11-01")

    assert _decay_score(fact, query_date=None) == 0.0


def test_decay_score_max() -> None:
    fact = _fact("Test fact.", confirmation_count=4, last_confirmed_at="2024-12-01")

    assert _decay_score(fact, query_date=date(2024, 12, 1)) == 0.06
