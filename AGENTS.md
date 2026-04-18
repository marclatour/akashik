# Akashik Agent Guide

This repository contains `akashik`, a local-first structured memory library in Python.

## Purpose

Akashik stores and retrieves text memories with deterministic lookup, not vector search. The hierarchy is fixed:

- `corpus`
- `document`
- `section`
- `fact`

## Setup

Create a virtualenv and install the package in editable mode:

```bash
./.venv/bin/python -m pip install -e ".[dev]"
```

Run tests with:

```bash
./.venv/bin/python -m pytest
```

## Key Files

- `akashik/schema.py`: dataclasses and level definitions
- `akashik/identity.py`: normalization and hashing
- `akashik/store.py`: SQLite schema, inserts, FTS5 sync, lookups
- `akashik/ingest.py`: file ingestion and document/section/fact splitting
- `akashik/retrieve.py`: strict retrieval order and level projection
- `akashik/cli.py`: Click CLI
- `tests/`: identity, store, and retrieval coverage

## Non-Negotiable Invariants

- Public IDs are UUID strings.
- `parent_id` references always use UUID strings.
- SQLite FTS5 uses an internal integer `fts_rowid` only for `content_rowid` addressing.
- The internal integer row ID is an implementation detail and must never be exposed in the public API.
- Every insert into `memory_units` must also write the matching FTS row in the same transaction.
- Any table with a foreign key referencing `memory_units` must be cleared before deleting from `memory_units` in reset or reingest paths.
- Retrieval order must remain:
  1. exact `content_hash`
  2. exact `normalized_hash`
  3. FTS5 keyword search
  4. parent/child traversal by level
- `normalized_hash` is based only on lowercasing and collapsing whitespace.
- No embeddings or vector search in `0.1.0`.

## CLI Contract

Supported commands:

```bash
akashik ingest --file <path> --level document
akashik query --text "your query" --level fact
akashik show --id <uuid>
akashik stats
```

Default database path is `./akashik.db`.

## Documentation Rules

- Keep `README.md` current as features, CLI behavior, benchmarks, and workflows change.
- If a change adds or alters a runnable script, benchmark, or command flow, update the matching `README.md` example in the same change.
- Use `./.venv/bin/python ...` in documentation and command examples instead of bare `python ...`.

## Notes For Changes

- If you modify `store.py`, preserve transactional consistency between `memory_units` and `memory_units_fts`.
- For tables that depend on `memory_units`, reset ordering must be child tables first and `memory_units` last; insert ordering remains the inverse within the same transaction.
- If you change ingestion splitting, keep it deterministic and update retrieval tests accordingly.
- If you touch retrieval ranking, exact and normalized matches must always outrank FTS.
- If a change affects output shape, update both CLI behavior and tests.
