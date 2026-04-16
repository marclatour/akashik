"""Deterministic ingestion helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from akashik.identity import content_hash, normalized_hash
from akashik.schema import MemoryUnit

_SECTION_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])(?:["\')\]]+)?\s+')
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}\b")
_ANCHOR_TOKEN_RE = re.compile(r"\b[\w/-]+\b", re.UNICODE)
_ANCHOR_SKIP_TOKENS = {
    "agreement",
    "and",
    "co",
    "contract",
    "copy",
    "corp",
    "dated",
    "ex",
    "execution",
    "exhibit",
    "inc",
    "license",
    "llc",
    "ltd",
    "the",
    "this",
}


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
    base_metadata["entities"] = extract_entities(raw_text, filename=path.stem)

    with store.transaction():
        document = store.insert(_make_unit("document", raw_text, metadata=base_metadata))
        for section_text in split_sections(raw_text):
            section_heading = extract_section_heading(section_text)
            section_entities: dict = {}
            section = store.insert(
                _make_unit(
                    "section",
                    section_text,
                    parent_id=document.id,
                    metadata=base_metadata,
                    section_entities=section_entities,
                    section_heading=section_heading,
                )
            )
            for fact_text in split_facts(section_text):
                store.insert(
                    _make_unit(
                        "fact",
                        fact_text,
                        parent_id=section.id,
                        metadata=base_metadata,
                        section_entities=section_entities,
                        section_heading=section_heading,
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


def extract_section_heading(text: str) -> str | None:
    for line in text.splitlines():
        heading = line.strip()
        if not heading:
            continue
        if len(heading) <= 60 and not heading.endswith((".", "?", "!")):
            return heading
        return None
    return None


def extract_entities(text: str, *, filename: str | None = None) -> list[str]:
    seen: set[str] = set()
    entities: list[str] = []
    if filename:
        _append_entity_values(
            entities,
            seen,
            [
                _company_prefix_from_filename(filename),
                _year_from_filename(filename),
                _exhibit_number_from_filename(filename),
                _first_anchor_token(filename),
            ],
        )
    _append_entity_values(entities, seen, _anchor_tokens(text[:500]))
    for match in _ENTITY_RE.findall(text[:500]):
        entity = _clean_entity(match)
        if not entity:
            continue
        _append_entity_values(entities, seen, _entity_values(entity))
    return entities


def _append_entity_values(entities: list[str], seen: set[str], values: list[str | None]) -> None:
    for value in values:
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(value)


def _clean_entity(entity: str) -> str:
    return entity.strip(" ,.;:()[]{}\"'")


def _entity_values(entity: str) -> list[str]:
    values = [entity]
    values.extend(_anchor_tokens(entity))
    return values


def _anchor_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in _ANCHOR_TOKEN_RE.findall(text or ""):
        token = _clean_anchor_token(raw_token)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _first_anchor_token(text: str) -> str | None:
    tokens = _anchor_tokens(text)
    return tokens[0] if tokens else None


def _company_prefix_from_filename(filename: str) -> str | None:
    parts = re.split(r"[_\s.-]+", filename or "")
    prefix_parts: list[str] = []
    for part in parts:
        if not part:
            continue
        if re.search(r"\d", part):
            break
        cleaned = re.sub(r"[^a-z]", "", part.lower())
        if cleaned:
            prefix_parts.append(cleaned)
    prefix = "".join(prefix_parts)
    return prefix if len(prefix) >= 4 else None


def _year_from_filename(filename: str) -> str | None:
    match = re.search(r"(?:19|20)\d{2}", filename or "")
    return match.group(0) if match else None


def _exhibit_number_from_filename(filename: str) -> str | None:
    match = re.search(r"\bex[-_ .]*([0-9]+(?:\.[0-9]+)*)", filename or "", flags=re.IGNORECASE)
    if not match:
        return None
    return re.sub(r"[^a-z0-9]", "", f"ex{match.group(1)}".lower())


def _clean_anchor_token(token: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", token.lower())
    if len(cleaned) < 4:
        return ""
    if cleaned in _ANCHOR_SKIP_TOKENS:
        return ""
    if any(character.isdigit() for character in cleaned):
        return ""
    return cleaned


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


def _merge_child_metadata(
    metadata: dict | None,
    section_entities: dict | None = None,
) -> dict:
    merged = dict(metadata or {})
    section_entities = dict(section_entities or {})
    merged.update({key: value for key, value in section_entities.items() if key != "entities"})

    entities: list[str] = []
    seen: set[str] = set()
    for value in list((metadata or {}).get("entities", [])) + list(section_entities.get("entities", [])):
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        entities.append(normalized)
    if entities:
        merged["entities"] = entities
    return merged


def _make_unit(
    level: str,
    content: str,
    *,
    parent_id: str | None = None,
    metadata: dict | None = None,
    section_entities: dict | None = None,
    section_heading: str | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        metadata=_merge_child_metadata(metadata, section_entities),
        section_heading=section_heading,
    )
