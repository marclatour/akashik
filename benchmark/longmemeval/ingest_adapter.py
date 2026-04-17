"""LongMemEval instance ingestion into the Akashik hierarchy."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re

from akashik.identity import content_hash, normalized_hash
from akashik.ingest import _insert_fact_unit, _merge_child_metadata
from akashik.schema import MemoryUnit

LOGGER = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")


def ingest_instance(store, instance: dict) -> int:
    """Ingest one LongMemEval instance. Returns fact count."""
    existing_corpus_id = _find_existing_corpus_id(store, instance["question_id"])
    if existing_corpus_id is not None:
        return _count_facts_for_corpus(store, existing_corpus_id)

    question_id = str(instance["question_id"])
    question_type = str(instance.get("question_type", ""))
    sessions = list(instance.get("haystack_sessions", []))
    session_ids = list(instance.get("haystack_session_ids", []))
    session_dates = list(instance.get("haystack_dates", []))
    skipped_turns = 0
    fact_count = 0

    corpus_metadata = _metadata(
        source=f"longmemeval:{question_id}",
        instance_id=question_id,
        question_type=question_type,
        entities=[question_id, question_type],
    )
    corpus = _make_unit("corpus", f"instance:{question_id}", metadata=corpus_metadata)

    with store.transaction():
        corpus = store.insert(corpus)
        for index, session in enumerate(sessions):
            session_id = str(session_ids[index])
            session_date = str(session_dates[index])
            document_metadata = _merge_child_metadata(
                corpus_metadata,
                {
                    "instance_id": question_id,
                    "session_id": session_id,
                    "session_date": session_date,
                    "question_type": question_type,
                    "entities": [session_id, session_date],
                },
            )
            document = store.insert(
                _make_unit(
                    "document",
                    _session_content(session),
                    parent_id=corpus.id,
                    metadata=document_metadata,
                )
            )
            for turn_index, turn in enumerate(session):
                content = str(turn.get("content", "")).strip()
                if not content:
                    skipped_turns += 1
                    continue
                role = str(turn.get("role", "")).strip().lower() or "unknown"
                section_entities = {"speaker": role, "entities": [role]}
                section_metadata = _merge_child_metadata(document_metadata, section_entities)
                has_answer = bool(turn.get("has_answer"))
                section = store.insert(
                    _make_unit(
                        "section",
                        content,
                        parent_id=document.id,
                        metadata=section_metadata,
                        section_heading=f"{role}_{turn_index}",
                    )
                )
                for sentence in _split_sentences(content):
                    fact_entities = {}
                    if has_answer:
                        fact_entities = {"has_answer": "true", "entities": ["true"]}
                    fact_metadata = _merge_child_metadata(section_metadata, fact_entities)
                    _insert_fact_unit(
                        store,
                        sentence,
                        parent_id=section.id,
                        metadata=fact_metadata,
                        section_heading=section.section_heading,
                    )
                    fact_count += 1

    if skipped_turns:
        LOGGER.info("Skipped %s empty LongMemEval turns for %s", skipped_turns, question_id)
    return fact_count


def _find_existing_corpus_id(store, question_id: str) -> str | None:
    rows = store._conn.execute(
        """
        SELECT id, metadata
        FROM memory_units
        WHERE level = 'corpus'
        ORDER BY fts_rowid
        """
    ).fetchall()
    for row in rows:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        if metadata.get("instance_id") == question_id:
            return str(row["id"])
    return None


def _count_facts_for_corpus(store, corpus_id: str) -> int:
    row = store._conn.execute(
        """
        SELECT COUNT(*)
        FROM memory_units AS fact
        JOIN memory_units AS section ON section.id = fact.parent_id
        JOIN memory_units AS document ON document.id = section.parent_id
        WHERE fact.level = 'fact'
          AND document.parent_id = ?
        """,
        (corpus_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def _split_sentences(content: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(content) if part.strip()]


def _session_content(session: list[dict]) -> str:
    return "\n".join(
        str(turn.get("content", "")).strip()
        for turn in session
        if str(turn.get("content", "")).strip()
    )


def _metadata(source: str, **values: object) -> dict:
    metadata = {
        "source": source,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [],
    }
    metadata.update(values)
    return metadata


def _make_unit(
    level: str,
    content: str,
    *,
    parent_id: str | None = None,
    metadata: dict | None = None,
    section_heading: str | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata=dict(metadata or {}),
        section_heading=section_heading,
    )
