"""
Akashik + Ollama flagship demo.

A minimal chat loop that shows Akashik memory persisting across sessions.
Facts accumulate in a local store; the LLM gets them injected as context,
not as chat history.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib import error, request

from akashik.ingest_pipeline import ingest_turn
from akashik.retrieve import retrieve
from akashik.store import Store

_STORE_PATH = Path.home() / ".akashik" / "stores" / "demo" / "chat.db"
_OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
_CHAT_MODEL = "qwen2.5:1.5b"
_RETRIEVAL_LIMIT = 5

_SYSTEM_WITH_FACTS = """You are a helpful personal assistant with memory.

What you remember about this person:
{facts}

Use this context naturally in your responses. If you don't have relevant memory, just respond normally."""

_SYSTEM_NO_FACTS = (
    "You are a helpful personal assistant. You don't know much about this person yet."
)


def _retrieve_facts(store, query: str) -> list[str]:
    response = retrieve(query, store, level="fact", limit=_RETRIEVAL_LIMIT)
    return [r.unit.content for r in response.results if r.unit.content]


def _build_system_prompt(facts: list[str]) -> str:
    if not facts:
        return _SYSTEM_NO_FACTS
    bulleted = "\n".join(f"- {fact}" for fact in facts)
    return _SYSTEM_WITH_FACTS.format(facts=bulleted)


def _stream_ollama(system_prompt: str, user_message: str) -> str:
    payload = json.dumps(
        {
            "model": _CHAT_MODEL,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    http_request = request.Request(
        _OLLAMA_CHAT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    collected: list[str] = []
    with request.urlopen(http_request, timeout=120) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            token = chunk.get("message", {}).get("content", "")
            if token:
                collected.append(token)
                sys.stdout.write(token)
                sys.stdout.flush()
            if chunk.get("done"):
                break
    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(collected)


def _count_facts(store) -> int:
    row = store._conn.execute(
        "SELECT COUNT(*) FROM memory_units WHERE level = 'fact'"
    ).fetchone()
    return int(row[0]) if row else 0


def _reset_store() -> None:
    if _STORE_PATH.exists():
        _STORE_PATH.unlink()


def _run(reset: bool) -> int:
    if reset:
        _reset_store()
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with Store(_STORE_PATH) as store:
        initial_count = _count_facts(store)
        print(f"Akashik chat demo — store at {_STORE_PATH}")
        print(f"Facts in memory: {initial_count}")
        print("Type 'exit' or press ctrl+c to quit.\n")

        while True:
            try:
                user_message = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                return 0
            if not user_message:
                continue
            if user_message.lower() in {"exit", "quit"}:
                print("Goodbye.")
                return 0

            facts = _retrieve_facts(store, user_message)
            system_prompt = _build_system_prompt(facts)
            if facts:
                print(f"[memory: {len(facts)} fact(s) injected]")

            sys.stdout.write("Assistant: ")
            sys.stdout.flush()
            try:
                _stream_ollama(system_prompt, user_message)
            except (error.URLError, TimeoutError, OSError) as exc:
                print(f"\n[ollama error: {exc}]")
                continue

            try:
                result = ingest_turn(store, user_message)
            except Exception as exc:
                print(f"[memory: ingest error: {exc}]")
                continue
            if result.get("written"):
                print(f"[memory: stored — \"{result['fact']}\"]")
            elif result.get("skipped_reason"):
                print(f"[memory: skipped ({result['skipped_reason']})]")
            print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Akashik + Ollama chat demo")
    parser.add_argument("--reset", action="store_true", help="wipe store before starting")
    args = parser.parse_args()
    return _run(reset=args.reset)


if __name__ == "__main__":
    raise SystemExit(main())
