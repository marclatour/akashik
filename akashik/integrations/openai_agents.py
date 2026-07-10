"""OpenAI Agents SDK integration.

Division of labor:

- ``AkashikEvidenceSession`` stores RAW conversation items verbatim
  (short-term memory, the SDK ``Session`` protocol). Raw chat is evidence.
- Long-term memory enters the store only through deliberate ``commit_fact``
  calls — yours, or the agent's via the ``akashik_commit`` tool. Committed
  facts are memory.

Two read surfaces, use either or both:

1. ``make_memory_callback(store)`` -> ``RunConfig.session_input_callback``.
   Before every model call, facts relevant to the new turn are recalled and
   injected as a single ``<AKASHIK_MEMORY>`` block. Stale memory blocks from
   earlier turns are stripped from history first, so at most one fresh block
   reaches the model regardless of how the session persists callback output.
2. ``build_tools(store)`` -> ``[akashik_recall, akashik_commit,
   akashik_answer]`` so the agent can search, commit, and get deterministic
   typed answers on demand. Agent commits are tagged ``source='agent'``.

Do not combine SDK sessions with ``conversation_id`` /
``previous_response_id`` in the same run — pick one memory path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from akashik.executor import execute
from akashik.ingest import commit_fact
from akashik.memory_block import format_memory_block
from akashik.reader import read_context
from akashik.retrieve import retrieve, retrieve_diverse
from akashik.store import Store

try:  # pragma: no cover - exercised via fake modules in tests
    from agents import function_tool
    from agents.memory.session import SessionABC

    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    function_tool = None
    SessionABC = object
    _SDK_AVAILABLE = False

LOGGER = logging.getLogger(__name__)

MEMORY_BLOCK_PREFIX = "<AKASHIK_MEMORY>"
_SDK_INSTALL_HINT = "requires the OpenAI Agents SDK: pip install 'akashik[agents]'"

# Visibility policy lives here, not in the store: provenance tags (agent,
# project, ...) admit untagged "universal" facts, so a scoped agent still
# sees shared personal memory. instance_id is a strict profile dimension —
# it never matches by absence. The security boundary is the database file
# (one per local user), not any metadata tag.
_STRICT_FILTER_KEYS = ("instance_id",)


class AkashikEvidenceSession(SessionABC):
    """SDK Session backed by the store's append-only evidence log.

    Verbatim transcript only — facts never enter through this path.
    ``clear_session`` clears the transcript; committed facts survive.
    """

    def __init__(self, session_id: str, store: Store):
        if not _SDK_AVAILABLE:
            raise ImportError(f"AkashikEvidenceSession {_SDK_INSTALL_HINT}")
        self.session_id = session_id
        self.store = store

    async def get_items(self, limit: int | None = None) -> list[Any]:
        return self.store.get_session_items(self.session_id, limit=limit)

    async def add_items(self, items: list[Any]) -> None:
        if items:
            self.store.append_session_items(self.session_id, list(items))

    async def pop_item(self) -> Any | None:
        return self.store.pop_session_item(self.session_id)

    async def clear_session(self) -> None:
        self.store.clear_session_items(self.session_id)


def make_memory_callback(
    store: Store,
    *,
    project: str | None = None,
    entity_filters: dict | None = None,
    k: int = 8,
    max_facts: int = 8,
    query_date: str | None = None,
):
    """Build a ``RunConfig.session_input_callback`` that injects Akashik memory.

    With ``project`` / ``entity_filters`` set, recall follows the
    tagged-or-untagged policy: facts carrying the matching tags plus
    universal facts that carry none, with ``instance_id`` always strict.
    Unscoped recall uses ``retrieve_diverse`` for cross-session breadth.
    Recall failures never break the conversation: on error the items pass
    through unmodified.
    """
    filters = dict(entity_filters or {})
    if project is not None:
        filters["project"] = project

    def session_input_callback(history_items: list[Any], new_items: list[Any]) -> list[Any]:
        history = [item for item in history_items if not _is_memory_item(item)]
        passthrough = history + list(new_items)
        query = _extract_text(new_items).strip()
        if not query:
            return passthrough
        try:
            if filters:
                results: list[Any] = _retrieve_with_policy(
                    store, query, filters=filters, k=k, query_date=query_date
                )
            else:
                results = retrieve_diverse(store, query, limit=k)
            packet = read_context(query, results, max_facts=max_facts)
            block = format_memory_block(packet)
        except Exception:
            LOGGER.exception("Akashik memory recall failed; passing items through.")
            return passthrough
        if not block:
            return passthrough
        memory_item = {"role": "system", "content": block}
        return history + [memory_item] + list(new_items)

    return session_input_callback


def build_tools(
    store: Store,
    *,
    project: str | None = None,
    entity_filters: dict | None = None,
    k: int = 8,
) -> list[Any]:
    """Return ``[akashik_recall, akashik_commit, akashik_answer]`` FunctionTools."""
    if not _SDK_AVAILABLE:
        raise ImportError(f"build_tools {_SDK_INSTALL_HINT}")

    default_project = project or "general"
    base_filters = dict(entity_filters or {})
    if project is not None:
        base_filters["project"] = project

    @function_tool
    def akashik_recall(query: str, project: str | None = None) -> str:
        """Search long-term memory for committed facts, decisions, and outcomes.

        Args:
            query: Keywords describing what to recall.
            project: Optional project slug to scope the search.
        """
        filters = dict(base_filters)
        if project is not None:
            filters["project"] = project
        if filters:
            results = _retrieve_with_policy(store, query, filters=filters, k=k)
        else:
            results = retrieve(query, store, level="fact", limit=k).results
        if not results:
            return "No committed facts match that query."
        return "\n".join(_fact_line(result.unit) for result in results)

    @function_tool
    def akashik_commit(
        content: str,
        type: str,
        project: str | None = None,
        supersedes: str | None = None,
    ) -> str:
        """Commit a durable fact to long-term memory. Use deliberately, like a
        git commit — for decisions, outcomes, and action items, not chit-chat.

        Args:
            content: The fact, stated plainly and completely.
            type: One of: idea, claim, recommendation, decision, experiment,
                action_item, outcome, preference, constraint, artifact.
            project: Project slug this fact belongs to.
            supersedes: Optional fact id this commit replaces.
        """
        try:
            unit = commit_fact(
                store,
                content,
                fact_type=type,
                project=project or default_project,
                supersedes=supersedes,
                source="agent",
            )
        except ValueError as error:
            return f"Commit failed: {error}"
        return json.dumps(
            {
                "committed": unit.id,
                "type": unit.metadata.get("fact_type"),
                "project": unit.metadata.get("project"),
                "supersedes": supersedes,
            }
        )

    @function_tool
    def akashik_answer(question: str) -> str:
        """Answer a factual, temporal, or preference question directly from
        long-term memory with citations. Abstains rather than guessing.

        Args:
            question: The question to answer from committed facts.
        """
        # Execute unscoped so universal facts stay answerable, then enforce
        # the visibility policy on every cited source; mixed or out-of-scope
        # evidence abstains rather than leaking.
        result = execute(store, question)
        if result.abstained or not result.answer:
            return "No evidence found in memory; abstaining."
        if base_filters and not _sources_match_filters(store, result.sources, base_filters):
            return "No evidence found in memory; abstaining."
        lines = [f"Answer: {result.answer}"]
        for source in result.sources:
            lines.append(
                f"Source: [{source.fact_id}] ({source.session_date or 'undated'}) {source.content}"
            )
        return "\n".join(lines)

    return [akashik_recall, akashik_commit, akashik_answer]


def _fact_line(unit: Any) -> str:
    metadata = getattr(unit, "metadata", None) or {}
    fact_type = metadata.get("fact_type", "fact")
    fact_project = metadata.get("project", "general")
    date = (
        getattr(unit, "valid_from", None)
        or str(metadata.get("timestamp", ""))[:10]
        or "undated"
    )
    return f"[{unit.id}] ({fact_type}/{fact_project}, {date}) {unit.content}"


def _matches_filters(unit: Any, filters: dict, *, allow_untagged: bool = False) -> bool:
    """Apply the caller's visibility policy to one unit.

    Strict mode mirrors the store's metadata-equality semantics. With
    ``allow_untagged`` a unit whose metadata lacks a filter key still matches
    (a universal fact), except for keys in ``_STRICT_FILTER_KEYS``.
    """
    metadata = getattr(unit, "metadata", None) or {}
    for key, expected in filters.items():
        if expected is None:
            continue
        value = metadata.get(key)
        if value is None and allow_untagged and key not in _STRICT_FILTER_KEYS:
            continue
        if isinstance(expected, list):
            if value not in expected:
                return False
        elif value != expected:
            return False
    return True


def _retrieve_with_policy(
    store: Store,
    query: str,
    *,
    filters: dict,
    k: int,
    query_date: str | None = None,
) -> list[Any]:
    """Retrieve tagged facts plus universal (untagged) facts under one policy.

    Two passes: the tag-scoped retrieval stack (post-filtered, since its
    exact/normalized-hash stages run before entity scoping), then an unscoped
    pool filtered to tagged-or-untagged. Merged by descending confidence,
    deduplicated by fact id.
    """
    tagged = [
        result
        for result in retrieve(
            query,
            store,
            level="fact",
            limit=k,
            entity_filters=filters,
            query_date=query_date,
        ).results
        if _matches_filters(result.unit, filters)
    ]
    pool = retrieve(
        query,
        store,
        level="fact",
        limit=max(k * 3, 15),
        query_date=query_date,
    ).results
    universal = [
        result for result in pool if _matches_filters(result.unit, filters, allow_untagged=True)
    ]

    merged: list[Any] = []
    seen: set[str] = set()
    for result in [*tagged, *universal]:
        unit_id = str(result.unit.id)
        if unit_id in seen:
            continue
        seen.add(unit_id)
        merged.append(result)
    merged.sort(key=lambda result: -float(getattr(result, "confidence", 0.0)))
    return merged[:k]


def _sources_match_filters(store: Store, sources: list[Any], filters: dict) -> bool:
    if not sources:
        return False
    for source in sources:
        fact_id = getattr(source, "fact_id", None)
        if not fact_id:
            return False
        unit = store.fetch_by_id(str(fact_id))
        if unit is None or not _matches_filters(unit, filters, allow_untagged=True):
            return False
    return True


def _extract_text(items: list[Any]) -> str:
    """Pull plain text out of Responses-style input items, defensively."""
    parts: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for chunk in content:
                    if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                        parts.append(chunk["text"])
    return " ".join(parts)


def _is_memory_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return _extract_text([item]).lstrip().startswith(MEMORY_BLOCK_PREFIX)
