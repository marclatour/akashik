"""OpenAI Agents SDK + Akashik long-term memory demo.

Part 1 runs with NO API key: commits facts, supersedes one, shows project
state, the supersession log, and exactly what the memory callback would
inject before a model call.

Part 2 runs when OPENAI_API_KEY is set: a live two-session agent. Session 1
commits a decision through the akashik_commit tool; session 2 (a fresh
session id, same store) answers from the injected memory block.

Run:

    ./.venv/bin/python examples/openai_agents_memory.py

Requires the agents extra for Part 2:

    ./.venv/bin/python -m pip install -e ".[agents]"
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from akashik.env import load_env
from akashik.ingest import commit_fact
from akashik.integrations.openai_agents import (
    AkashikEvidenceSession,
    build_tools,
    make_memory_callback,
)
from akashik.store import Store

DB_PATH = Path("./akashik_agents_demo.db")
PROJECT = "human_in_the_loop"


def part_one(store: Store) -> None:
    print("=== Part 1: deterministic memory, no API key needed ===\n")

    commit_fact(
        store,
        "Episode 1 of Human in the Loop is the Akashik memory demo video",
        fact_type="decision",
        project=PROJECT,
        session_date="2026-07-01",
    )
    action = commit_fact(
        store,
        "Record the Akashik demo screencast",
        fact_type="action_item",
        project=PROJECT,
        session_date="2026-07-02",
    )
    outcome = commit_fact(
        store,
        "Demo screencast recorded and edited",
        fact_type="outcome",
        project=PROJECT,
        supersedes=action.id,
        session_date="2026-07-05",
    )

    print("Project state (current facts only):")
    units = store.fetch_by_metadata_filters(level="fact", filters={"project": PROJECT})
    for unit in units:
        if unit.valid_until is None:
            print(f"  [{unit.metadata.get('fact_type')}] {unit.content}")

    print("\nSupersession log for the action item:")
    for unit in store.fetch_lineage_chain(outcome.id):
        status = "current" if unit.valid_until is None else f"superseded until {unit.valid_until}"
        print(f"  [{unit.id[:8]}] ({status}) {unit.content}")

    print("\nWhat the model would be shown for 'what is the state of episode one?':")
    callback = make_memory_callback(store, project=PROJECT)
    combined = callback(
        [], [{"role": "user", "content": "what is the state of episode one?"}]
    )
    for item in combined:
        if isinstance(item, dict) and str(item.get("content", "")).startswith("<AKASHIK_MEMORY>"):
            print(item["content"])


async def part_two(store: Store) -> None:
    from agents import Agent, Runner
    from agents.run import RunConfig

    print("\n=== Part 2: live agent with memory injection and commit tool ===\n")

    agent = Agent(
        name="assistant",
        instructions=(
            "You are a production assistant with long-term memory. "
            "Commit important decisions and outcomes with akashik_commit. "
            "Trust the <AKASHIK_MEMORY> block as verified fact evidence."
        ),
        tools=build_tools(store, project=PROJECT),
    )
    run_config = RunConfig(session_input_callback=make_memory_callback(store, project=PROJECT))

    result = await Runner.run(
        agent,
        "We just decided the episode title is 'Memory Is a Deliberate Act'. "
        "Commit that decision to memory.",
        session=AkashikEvidenceSession("demo_session_1", store),
        run_config=run_config,
    )
    print(f"Session 1: {result.final_output}\n")

    result = await Runner.run(
        agent,
        "What did we decide the episode title is?",
        session=AkashikEvidenceSession("demo_session_2", store),
        run_config=run_config,
    )
    print(f"Session 2 (fresh session, same store): {result.final_output}")


def main() -> None:
    load_env()  # picks up OPENAI_API_KEY from ./.env or ~/.akashik/.env
    if DB_PATH.exists():
        DB_PATH.unlink()
    with Store(DB_PATH) as store:
        part_one(store)
        if os.environ.get("OPENAI_API_KEY"):
            asyncio.run(part_two(store))
        else:
            print("\nSet OPENAI_API_KEY to run Part 2 (live agent).")


if __name__ == "__main__":
    main()
