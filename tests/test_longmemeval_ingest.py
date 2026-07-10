from __future__ import annotations

import copy
import json

from akashik.store import Store
from benchmark.longmemeval.ingest_adapter import ingest_instance

SYNTHETIC_INSTANCE = {
    "question_id": "test_q_001",
    "question_type": "single-session-user",
    "question": "What book did the user mention?",
    "answer": "Dune",
    "question_date": "2024-03-15",
    "haystack_session_ids": ["sess_a", "sess_b"],
    "haystack_dates": ["2024-03-10", "2024-03-12"],
    "answer_session_ids": ["sess_b"],
    "haystack_sessions": [
        [
            {"role": "user", "content": "I've been reading a lot lately."},
            {"role": "assistant", "content": "That's great. What kind of books?"},
        ],
        [
            {"role": "user", "content": "I just finished Dune. It was incredible."},
            {"role": "assistant", "content": "A classic. Did you enjoy the world-building?"},
        ],
    ],
}


def test_fact_count() -> None:
    with Store(":memory:") as store:
        count = ingest_instance(store, SYNTHETIC_INSTANCE)

        assert count == 7


def test_instance_id_scoping() -> None:
    with Store(":memory:") as store:
        ingest_instance(store, SYNTHETIC_INSTANCE)

        facts = _fact_rows(store)

        assert facts
        assert all(row["metadata"]["instance_id"] == "test_q_001" for row in facts)
        assert all("test_q_001" in row["metadata"]["entities"] for row in facts)


def test_session_date_propagation() -> None:
    with Store(":memory:") as store:
        ingest_instance(store, SYNTHETIC_INSTANCE)

        facts = _fact_rows(store)
        dates_by_session = {row["metadata"]["session_id"]: row["metadata"]["session_date"] for row in facts}

        assert dates_by_session["sess_a"] == "2024-03-10"
        assert dates_by_session["sess_b"] == "2024-03-12"


def test_speaker_entity() -> None:
    with Store(":memory:") as store:
        ingest_instance(store, SYNTHETIC_INSTANCE)

        facts = _fact_rows(store)
        dune_fact = next(row for row in facts if "Dune" in row["content"])
        reading_fact = next(row for row in facts if "reading" in row["content"])
        assistant_fact = next(row for row in facts if "world-building" in row["content"])

        assert dune_fact["metadata"]["speaker"] == "user"
        assert reading_fact["metadata"]["speaker"] == "user"
        assert assistant_fact["metadata"]["speaker"] == "assistant"


def test_empty_turn_skipped() -> None:
    instance = copy.deepcopy(SYNTHETIC_INSTANCE)
    instance["haystack_sessions"][0].append({"role": "assistant", "content": "   "})

    with Store(":memory:") as store:
        count = ingest_instance(store, instance)

        assert count == 7
        assert len(_fact_rows(store)) == 7


def test_idempotent_ingest() -> None:
    with Store(":memory:") as store:
        first = ingest_instance(store, SYNTHETIC_INSTANCE)
        second = ingest_instance(store, SYNTHETIC_INSTANCE)

        assert first == 7
        assert second == 7
        assert len(_fact_rows(store)) == 7


def _fact_rows(store) -> list[dict]:
    rows = store._conn.execute(
        """
        SELECT fact.content, fact.metadata
        FROM memory_units AS fact
        WHERE fact.level = 'fact'
        ORDER BY fact.fts_rowid
        """
    ).fetchall()
    return [{"content": row["content"], "metadata": json.loads(row["metadata"])} for row in rows]
