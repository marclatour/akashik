# Akashik 0.1.0

Akashik is a local-first structured memory library in Python. It stores text as a fixed hierarchy:

- `corpus`
- `document`
- `section`
- `fact`

Retrieval is deterministic and follows a strict order:

1. Exact `content_hash`
2. Exact `normalized_hash`
3. SQLite FTS5 keyword search
4. Parent/child traversal to the requested level

No vector search, embeddings, web service, or ML dependencies are included in `0.1.0`.

## Install

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
```

## CLI

Default database path: `./akashik.db`

```bash
akashik ingest --file README.md --level document
akashik query --text "local first memory" --level fact
akashik show --id <uuid>
akashik stats
```

## Data Model

Each memory unit stores:

- `id` as a UUID string
- `level`
- `content`
- `content_hash`
- `normalized_hash`
- `parent_id`
- `metadata` as JSON with `source`, `timestamp`, `tags`
- `embedding` as a nullable reserved field

## Ingestion

`ingest_file()` reads a text document and creates:

- one `document` from the full file
- one `section` per blank-line-separated paragraph
- one `fact` per sentence-like split inside each section

## Testing

```bash
./.venv/bin/python -m pytest
```
