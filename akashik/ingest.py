"""Deterministic ingestion helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import uuid

from akashik.commitment_detector import detect_commitment, is_closure
from akashik.contradiction import close_fact, extract_triple, find_contradicting_fact
from akashik.identity import content_hash, normalized_hash
from akashik.preference_extractor import extract_preferences
from akashik.query_normalize import normalize_query
from akashik.schema import Commitment, MemoryUnit

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
_CONTEXT_INDEX_STOPWORDS = {
    "about",
    "after",
    "before",
    "being",
    "during",
    "first",
    "have",
    "into",
    "just",
    "last",
    "many",
    "most",
    "next",
    "over",
    "some",
    "than",
    "that",
    "them",
    "then",
    "there",
    "they",
    "very",
    "want",
    "week",
    "with",
    "would",
}
MIN_TOKEN_LENGTH = 4

FACT_TYPES = (
    "idea",
    "claim",
    "recommendation",
    "decision",
    "experiment",
    "action_item",
    "outcome",
    "preference",
    "constraint",
    "artifact",
)


def process_turn_commitments(store, turn: dict, *, session_id: str | None = None) -> None:
    """
    Apply commitment-layer side effects for conversational turns.
    Assistant turns may open commitments. User turns may close the most
    recent open commitment when the message clearly indicates completion.
    """

    actor = str(turn.get("actor", ""))
    content = str(turn.get("content", ""))
    timestamp = turn.get("timestamp") or turn.get("simulated_date") or datetime.utcnow().isoformat()
    if actor == "assistant":
        description = detect_commitment(content)
        if not description:
            return
        store.insert_commitment(
            Commitment(
                id=str(uuid.uuid4()),
                description=description,
                source_turn_id=turn.get("turn_id"),
                session_id=session_id,
                opened_at=timestamp,
                closed_at=None,
                status="open",
                related_facts=list(turn.get("ground_truth_facts", [])),
                metadata={},
            )
        )
        return
    if actor == "user" and is_closure(content):
        open_commitments = store.get_open_commitments()
        if not open_commitments:
            return
        most_recent = sorted(open_commitments, key=lambda commitment: commitment.opened_at, reverse=True)[0]
        store.close_commitment(most_recent.id, datetime.utcnow().isoformat())


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

    store.begin_bulk_ingest()
    try:
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
                    _insert_fact_unit(
                        store,
                        fact_text,
                        parent_id=section.id,
                        metadata=base_metadata,
                        section_entities=section_entities,
                        section_heading=section_heading,
                    )
        return document
    finally:
        store.end_bulk_ingest()


def ingest_text(
    store,
    text: str,
    *,
    level: str = "document",
    metadata: dict | None = None,
) -> MemoryUnit:
    if level != "document":
        raise ValueError("Akashik ingest only supports document-level text input.")

    raw_text = str(text)
    base_metadata = {
        "source": "inline",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [],
    }
    if metadata:
        base_metadata.update(metadata)
    base_metadata["source"] = str(base_metadata.get("source", "inline"))
    base_metadata["tags"] = list(base_metadata.get("tags", []))
    base_metadata["entities"] = _merge_entity_lists(
        list(base_metadata.get("entities", [])),
        extract_entities(raw_text),
    )

    sections = split_sections(raw_text)
    if not sections and raw_text.strip():
        sections = [raw_text.strip()]

    with store.transaction():
        document = store.insert(_make_unit("document", raw_text, metadata=base_metadata))
        for section_text in sections:
            section_heading = extract_section_heading(section_text)
            section = store.insert(
                _make_unit(
                    "section",
                    section_text,
                    parent_id=document.id,
                    metadata=base_metadata,
                    section_heading=section_heading,
                )
            )
            for fact_text in split_facts(section_text):
                _insert_fact_unit(
                    store,
                    fact_text,
                    parent_id=section.id,
                    metadata=base_metadata,
                    section_heading=section_heading,
                )
    return document


def ingest_turn_fact(
    store,
    content: str,
    *,
    parent_id: str,
    role: str,
    turn_id: str | None = None,
    session_date: str | None = None,
    metadata: dict | None = None,
    split: bool = True,
) -> list[MemoryUnit]:
    """Insert one conversation turn's content as fact unit(s) under a caller-owned section.

    Unlike ``ingest_text`` this does not create document/section scaffolding —
    the caller supplies ``parent_id`` (a section) and this function only emits
    facts. Contradiction detection, reinforcement, and preference-derived facts
    run through the shared ``_insert_fact_unit`` path.
    """
    raw = str(content or "")
    if not raw.strip():
        return []

    base_metadata: dict = {
        "source": "turn",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [],
        "speaker": role,
    }
    if turn_id is not None:
        base_metadata["turn_id"] = turn_id
    if session_date is not None:
        base_metadata["session_date"] = session_date
        base_metadata["simulated_date"] = session_date
    base_metadata["entities"] = _merge_entity_lists(extract_entities(raw))

    if metadata:
        caller = dict(metadata)
        caller_entities = caller.pop("entities", None)
        base_metadata.update(caller)
        if caller_entities is not None:
            base_metadata["entities"] = _merge_entity_lists(
                list(caller_entities) if isinstance(caller_entities, list) else [],
                base_metadata.get("entities", []),
            )
    base_metadata["speaker"] = role
    base_metadata["tags"] = list(base_metadata.get("tags", []))

    if split:
        fact_texts = split_facts(raw)
    else:
        stripped = raw.strip()
        fact_texts = [stripped] if stripped else []

    inserted: list[MemoryUnit] = []
    with store.transaction():
        for fact_text in fact_texts:
            unit = _insert_fact_unit(
                store,
                fact_text,
                parent_id=parent_id,
                metadata=base_metadata,
                section_heading=None,
            )
            inserted.append(unit)
    return inserted


def commit_fact(
    store,
    content: str,
    *,
    fact_type: str = "claim",
    project: str = "general",
    supersedes: str | None = None,
    source: str | None = None,
    session_id: str | None = None,
    session_date: str | None = None,
    metadata: dict | None = None,
) -> MemoryUnit:
    """Commit one fact deliberately — like a git commit, never ambient.

    The deliberate write path for agent/user memory: no sentence splitting,
    typed via ``fact_type``, scoped via ``project``. With ``supersedes`` the
    older fact's validity window is closed and the new unit records it as
    ``lineage_parent_id`` in the same transaction; the old fact is never
    deleted.
    """
    text = " ".join(str(content or "").split())
    if not text:
        raise ValueError("commit_fact requires non-empty content.")
    if fact_type not in FACT_TYPES:
        raise ValueError(f"fact_type must be one of {FACT_TYPES}, got {fact_type!r}")

    commit_date = str(session_date).strip() if session_date else datetime.now(timezone.utc).date().isoformat()

    superseded: MemoryUnit | None = None
    if supersedes is not None:
        superseded = store.fetch_by_id(supersedes)
        if superseded is None or superseded.level != "fact":
            raise ValueError(f"cannot supersede unknown fact {supersedes!r}")

    base_metadata: dict = {
        "source": source or "user",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [],
        "fact_type": fact_type,
        "project": project,
        "session_date": commit_date,
        "simulated_date": commit_date,
    }
    if session_id is not None:
        base_metadata["session_id"] = session_id
    base_metadata["entities"] = _merge_entity_lists(extract_entities(text))
    if metadata:
        caller = dict(metadata)
        caller_entities = caller.pop("entities", None)
        base_metadata.update(caller)
        if caller_entities is not None:
            base_metadata["entities"] = _merge_entity_lists(
                list(caller_entities) if isinstance(caller_entities, list) else [],
                base_metadata.get("entities", []),
            )

    with store.transaction():
        section = _ensure_commit_section(store, project)
        if superseded is not None:
            store.close_fact(superseded.id, commit_date)
        unit = _insert_fact_unit(
            store,
            text,
            parent_id=section.id,
            metadata=base_metadata,
            lineage_parent_id=superseded.id if superseded is not None else None,
            # Identical text committed under a different project or fact_type
            # is a distinct scoped fact, not a restatement of the old one.
            reinforce_scope_keys=("project", "fact_type"),
        )
    return unit


def _ensure_commit_section(store, project: str) -> MemoryUnit:
    """Find or create the document/section scaffolding for a project's commits."""
    scaffold_text = f"[akashik-commits] project={project}"
    existing_sections = [
        unit
        for unit in store.fetch_by_content_hash(content_hash(scaffold_text))
        if unit.level == "section"
    ]
    if existing_sections:
        return existing_sections[0]

    scaffold_metadata = {
        "source": "commit",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [],
        "project": project,
    }
    existing_documents = [
        unit
        for unit in store.fetch_by_content_hash(content_hash(scaffold_text))
        if unit.level == "document"
    ]
    if existing_documents:
        document = existing_documents[0]
    else:
        document = store.insert(
            _make_unit("document", scaffold_text, metadata=scaffold_metadata)
        )
    return store.insert(
        _make_unit(
            "section",
            scaffold_text,
            parent_id=document.id,
            metadata=scaffold_metadata,
        )
    )


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


def _merge_entity_lists(*groups: object) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for value in group:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(normalized)
    return merged


def _insert_fact_unit(
    store,
    content: str,
    *,
    parent_id: str,
    metadata: dict | None = None,
    section_entities: dict | None = None,
    section_heading: str | None = None,
    lineage_parent_id: str | None = None,
    reinforce_scope_keys: tuple[str, ...] = (),
) -> MemoryUnit:
    unit = _make_unit(
        "fact",
        content,
        parent_id=parent_id,
        metadata=metadata,
        section_entities=section_entities,
        section_heading=section_heading,
        lineage_parent_id=lineage_parent_id,
    )
    triple = extract_triple(unit.content)
    valid_from = unit.valid_from
    instance_id = str(unit.metadata.get("instance_id", "")).strip() or None
    if triple and valid_from:
        contradiction = find_contradicting_fact(store, triple, instance_id)
        if contradiction is not None:
            close_fact(store, contradiction.id, valid_from)
    # An explicit lineage node must always be inserted so the supersession
    # chain stays reconstructible; reinforcement would drop the link.
    existing = (
        None
        if lineage_parent_id
        else _find_reinforceable_fact(store, unit, instance_id, scope_keys=reinforce_scope_keys)
    )
    if existing is not None:
        confirmed_at = valid_from or str(unit.metadata.get("session_date", "")).strip() or None
        if confirmed_at:
            store.increment_confirmation(existing.id, confirmed_at)
        stored = store.fetch_by_id(existing.id) or existing
    else:
        stored = store.insert(unit)
        store.insert_fact_context_entries(build_fact_context_entries(stored.content, stored.metadata), stored.id)

    _insert_preference_derived_facts(
        store,
        content=unit.content,
        parent_id=parent_id,
        metadata=metadata,
        section_entities=section_entities,
        section_heading=section_heading,
    )
    return stored


def build_fact_context_entries(content: str, metadata: dict | None) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    normalized_content = normalize_query(content)
    for token in normalized_content.split():
        if token in _CONTEXT_INDEX_STOPWORDS or len(token) < MIN_TOKEN_LENGTH:
            continue
        entry = ("topic", token)
        if entry not in seen:
            seen.add(entry)
            entries.append(entry)

    metadata = dict(metadata or {})
    entities = metadata.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, str):
                continue
            normalized = _normalize_index_value(entity)
            if not normalized:
                continue
            entry = ("entity", normalized)
            if entry not in seen:
                seen.add(entry)
                entries.append(entry)

    for key in ("domain", "thread"):
        value = metadata.get(key)
        if not isinstance(value, str):
            continue
        normalized = _normalize_index_value(value)
        if not normalized:
            continue
        entry = (key, normalized)
        if entry not in seen:
            seen.add(entry)
            entries.append(entry)
    return entries


def _normalize_index_value(value: str) -> str:
    normalized = normalize_query(value)
    if normalized:
        return normalized
    return " ".join(value.lower().split())


def _make_unit(
    level: str,
    content: str,
    *,
    parent_id: str | None = None,
    metadata: dict | None = None,
    section_entities: dict | None = None,
    section_heading: str | None = None,
    lineage_parent_id: str | None = None,
) -> MemoryUnit:
    merged_metadata = _merge_child_metadata(metadata, section_entities)
    return MemoryUnit(
        level=level,
        content=content,
        content_hash=content_hash(content),
        normalized_hash=normalized_hash(content),
        parent_id=parent_id,
        lineage_parent_id=lineage_parent_id,
        metadata=merged_metadata,
        section_heading=section_heading,
        valid_from=(
            str(merged_metadata.get("session_date"))
            if level == "fact" and merged_metadata.get("session_date")
            else None
        ),
        confirmation_count=1,
        last_confirmed_at=(
            str(merged_metadata.get("session_date"))
            if level == "fact" and merged_metadata.get("session_date")
            else None
        ),
    )


def _find_reinforceable_fact(
    store,
    unit: MemoryUnit,
    instance_id: str | None,
    *,
    scope_keys: tuple[str, ...] = (),
) -> MemoryUnit | None:
    candidates = store.fetch_by_normalized_hash(unit.normalized_hash)
    for candidate in candidates:
        if candidate.level != "fact":
            continue
        if candidate.valid_until is not None:
            continue
        if instance_id and candidate.metadata.get("instance_id") != instance_id:
            continue
        if any(candidate.metadata.get(key) != unit.metadata.get(key) for key in scope_keys):
            continue
        return candidate
    return None


def _insert_preference_derived_facts(
    store,
    *,
    content: str,
    parent_id: str,
    metadata: dict | None,
    section_entities: dict | None,
    section_heading: str | None,
) -> None:
    merged_metadata = _merge_child_metadata(metadata, section_entities)
    if str(merged_metadata.get("speaker", "")).strip().lower() != "user":
        return

    valid_from = str(merged_metadata.get("session_date", "")).strip() or None
    instance_id = str(merged_metadata.get("instance_id", "")).strip() or None
    # Derived facts inherit commit scope: a preference stated in one project
    # must not reinforce or close a derived fact in another.
    project = str(merged_metadata.get("project", "")).strip() or None
    for preference in extract_preferences(content):
        value = str(preference["value"])
        polarity = str(preference["polarity"])
        strength = str(preference["strength"])
        contradiction = _find_preference_fact(
            store,
            instance_id=instance_id,
            value=value,
            polarity="like" if polarity == "dislike" else "dislike",
            project=project,
        )
        if contradiction is not None and valid_from:
            close_fact(store, contradiction.id, valid_from)

        reinforcement = _find_preference_fact(
            store,
            instance_id=instance_id,
            value=value,
            polarity=polarity,
            project=project,
        )
        if reinforcement is not None:
            if valid_from:
                store.increment_confirmation(reinforcement.id, valid_from)
            continue

        derived_metadata = dict(merged_metadata)
        derived_metadata.update(
            {
                "derived": "preference",
                "preference_polarity": polarity,
                "preference_strength": strength,
                "preference_value": value,
            }
        )
        derived_unit = MemoryUnit(
            level="fact",
            content=f"user preference: {polarity} {value} (strength: {strength})",
            content_hash=content_hash(f"user preference: {polarity} {value} (strength: {strength})"),
            normalized_hash=normalized_hash(f"user preference: {polarity} {value} (strength: {strength})"),
            parent_id=parent_id,
            metadata=derived_metadata,
            section_heading=section_heading,
            valid_from=valid_from,
            confirmation_count=1,
            last_confirmed_at=valid_from,
        )
        store.insert(derived_unit)


def _find_preference_fact(
    store,
    *,
    instance_id: str | None,
    value: str,
    polarity: str,
    project: str | None = None,
) -> MemoryUnit | None:
    filters: dict[str, str] = {
        "derived": "preference",
        "preference_value": value,
        "preference_polarity": polarity,
    }
    if instance_id:
        filters["instance_id"] = instance_id
    if project:
        filters["project"] = project
    candidates = store.fetch_by_metadata_filters(level="fact", filters=filters)
    current = [candidate for candidate in candidates if candidate.valid_until is None]
    if not current:
        return None
    current.sort(key=lambda unit: (unit.last_confirmed_at or unit.valid_from or "", unit.id))
    return current[-1]
