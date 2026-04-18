from __future__ import annotations

import inspect

from akashik.commitment_detector import detect_commitment, is_closure
from akashik.identity import content_hash, normalized_hash
from akashik.retrieve import MAX_COMMITMENTS, retrieve, retrieve_commitments
from akashik.schema import Commitment, MemoryUnit, RetrievalResponse
from akashik.store import Store
from benchmark.acmb.adapters.akashik_adapter import AkashikAdapter
from benchmark.longmemeval.run_longmemeval import _reset_store_contents


def _commitment(
    commitment_id: str,
    description: str,
    *,
    session_id: str | None = None,
    opened_at: str = "2026-01-01T00:00:00",
    status: str = "open",
    closed_at: str | None = None,
) -> Commitment:
    return Commitment(
        id=commitment_id,
        description=description,
        source_turn_id=None,
        session_id=session_id,
        opened_at=opened_at,
        closed_at=closed_at,
        status=status,
        related_facts=[],
        metadata={},
    )


def test_detect_commitment_returns_normalized_description() -> None:
    assert detect_commitment("I'll help find trail running gear if you want to build out a setup.") == "help find trail running gear"


def test_detect_commitment_returns_none_without_pattern() -> None:
    assert detect_commitment("Trail running gear seems expensive lately.") is None


def test_detect_commitment_strips_trigger_prefix() -> None:
    assert detect_commitment("I can draft the stakeholder update.") == "draft the stakeholder update"


def test_detect_commitment_trims_to_first_sentence() -> None:
    assert detect_commitment("I'll compare travel camera straps. We can do backpacks later.") == "compare travel camera straps"


def test_is_closure_true_for_closure_phrase_without_follow_up() -> None:
    assert is_closure("Thanks, that worked.") is True


def test_is_closure_false_when_text_contains_but() -> None:
    assert is_closure("Thanks, but I still need more help.") is False


def test_is_closure_false_for_neutral_text() -> None:
    assert is_closure("I went for a run this morning.") is False


def test_insert_commitment_stores_row_and_returns_id(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        commitment = _commitment("c1", "find trail running gear")
        assert store.insert_commitment(commitment) == "c1"
        rows = store._conn.execute("SELECT id FROM commitments").fetchall()
        assert [row[0] for row in rows] == ["c1"]


def test_get_open_commitments_returns_only_open(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "open commitment"))
        store.insert_commitment(_commitment("c2", "closed commitment", status="closed", closed_at="2026-01-02T00:00:00"))
        assert [commitment.id for commitment in store.get_open_commitments()] == ["c1"]


def test_get_open_commitments_returns_empty_when_all_closed(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "closed commitment", status="closed", closed_at="2026-01-02T00:00:00"))
        assert store.get_open_commitments() == []


def test_close_commitment_sets_closed_fields(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "find trail running gear"))
        store.close_commitment("c1", "2026-01-02T00:00:00")
        row = store._conn.execute(
            "SELECT status, closed_at FROM commitments WHERE id = ?",
            ("c1",),
        ).fetchone()
        assert tuple(row) == ("closed", "2026-01-02T00:00:00")


def test_get_commitments_by_session_filters_session(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "first", session_id="s1"))
        store.insert_commitment(_commitment("c2", "second", session_id="s2"))
        assert [commitment.id for commitment in store.get_commitments_by_session("s1")] == ["c1"]


def test_retrieve_commitments_returns_all_open_for_meta_language(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "find trail running gear", opened_at="2026-01-01T00:00:00"))
        store.insert_commitment(_commitment("c2", "draft stakeholder update", opened_at="2026-01-02T00:00:00"))
        results = retrieve_commitments(store, "what did you say you'd help me with?")
        assert [commitment.id for commitment in results] == ["c2", "c1"]


def test_retrieve_commitments_filters_by_overlap(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "find trail running gear"))
        store.insert_commitment(_commitment("c2", "draft stakeholder update"))
        results = retrieve_commitments(store, "trail gear")
        assert [commitment.id for commitment in results] == ["c1"]


def test_retrieve_commitments_returns_empty_when_no_open_commitments(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        assert retrieve_commitments(store, "what did you offer?") == []


def test_retrieve_commitments_returns_at_most_max_commitments(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        for index in range(MAX_COMMITMENTS + 2):
            store.insert_commitment(
                _commitment(
                    f"c{index}",
                    f"commitment {index}",
                    opened_at=f"2026-01-{index + 1:02d}T00:00:00",
                )
            )
        results = retrieve_commitments(store, "what did you offer?")
        assert len(results) == MAX_COMMITMENTS


def test_retrieve_commitments_returns_most_recent_first(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "older", opened_at="2026-01-01T00:00:00"))
        store.insert_commitment(_commitment("c2", "newer", opened_at="2026-01-03T00:00:00"))
        results = retrieve_commitments(store, "what did you offer?")
        assert [commitment.id for commitment in results] == ["c2", "c1"]


def test_commitments_cleared_in_reset_path_before_memory_units(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert_commitment(_commitment("c1", "find trail running gear"))
        store.insert(
            MemoryUnit(
                level="fact",
                content="I live in Denver.",
                content_hash=content_hash("I live in Denver."),
                normalized_hash=normalized_hash("I live in Denver."),
                metadata={"source": "tests"},
            )
        )
        _reset_store_contents(store)
        assert store._conn.execute("SELECT COUNT(*) FROM commitments").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM memory_units").fetchone()[0] == 0


def test_retrieve_signature_and_return_type_are_unchanged(tmp_path) -> None:
    with Store(tmp_path / "store.db") as store:
        store.insert(
            MemoryUnit(
                level="fact",
                content="I live in Denver.",
                content_hash=content_hash("I live in Denver."),
                normalized_hash=normalized_hash("I live in Denver."),
                metadata={"source": "tests"},
            )
        )
        assert "query" in inspect.signature(retrieve).parameters
        response = retrieve("I live in Denver.", store)
        assert isinstance(response, RetrievalResponse)


def test_end_to_end_commitment_query_returns_prefixed_description(tmp_path) -> None:
    adapter = AkashikAdapter(store_path=str(tmp_path / "acmb.db"))
    adapter.ingest_turn(
        {
            "turn_id": "t034",
            "actor": "assistant",
            "content": "I'll help find trail running gear if you want to build out a setup.",
            "ground_truth_facts": [],
            "simulated_date": "2026-03-25T00:00:00",
        },
        commitments=[
            {
                "commitment_id": "c001",
                "description": "help find trail running gear",
            }
        ],
    )
    results = adapter.query("what did you say you'd help me shop for?")
    assert "[COMMITMENT] help find trail running gear" in results
