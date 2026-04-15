"""Deterministic ingestion helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from akashik.identity import content_hash, normalized_hash
from akashik.schema import MemoryUnit

_SECTION_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])(?:["\')\]]+)?\s+')


def ingest_file(
    file_path: str | Path,
    store,
    *,
    level: str = "document",
    metadata: dict | None = None,
) -> MemoryUnit:
    if level != "document":
        raise ValueError("Akashik 0.1.0 ingest only supports --level document.")

    path = Path(file_path).expanduser().resolve()
    raw_text = path.read_text(encoding="utf-8")
    existing = [
        unit
        for unit in store.fetch_by_content_hash(content_hash(raw_text))
        if unit.level == "document"
    ]
    if existing:
        return existing[0]

    base_metadata = _base_metadata(path, metadata)

    with store.transaction():
        document = store.insert(_make_unit("document", raw_text, metadata=base_metadata))
        for section_text in split_sections(raw_text):
            section = store.insert(
                _make_unit(
                    "section",
                    section_text,
                    parent_id=document.id,
                    metadata=base_metadata,
                )
            )
            for fact_text in split_facts(section_text):
                store.insert(
                    _make_unit(
                        "fact",
                        fact_text,
                        parent_id=section.id,
                        metadata=base_metadata,
                    )
                )
    return document


def split_sections(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    return [part.strip() for part in _SECTION_SPLIT_RE.split(stripped) if part.strip()]


def split_facts(text: str) -> list[str]:
    collapsed = " ".join(text.split())
    if not collapsed:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(collapsed) if part.strip()]
    return parts or [collapsed]


def _base_metadata(path: Path, metadata: dict | None) -> dict:
    merged = {
        "source": str(path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [],
    }
    if metadata:
        merged.update(metadata)
    merged["source"] = str(merged.get("source", path))
    merged["tags"] = list(merged.get("tags", []))
    if "timestamp" not in merged or not merged["timestamp"]:
        merged["timestamp"] = datetime.now(timezone.utc).isoformat()
    return merged


def _make_unit(
    level: str,
    content: str,
    *,
    parent_id: str | None = None,
    metadata: dict | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata=dict(metadata or {}),
    )
