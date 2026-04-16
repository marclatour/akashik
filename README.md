# Akashik 0.9.0

Akashik is a local-first deterministic memory layer for text corpora. It stores content as a fixed hierarchy:

- `corpus`
- `document`
- `section`
- `fact`

Retrieval is structure-first, not embedding-first. The default stack is:

1. exact `content_hash`
2. exact `normalized_hash`
3. SQLite FTS5 keyword search
4. document gate + scoped fact reranking
5. Navigator tie-breaker
6. semantic fallback only when confidence is low

Facts now support validity windows. By default, retrieval returns only currently valid facts. Historical queries can opt into `as_of=...`.

## Install

```bash
./.venv/bin/python -m pip install -e ".[dev]"
```

Benchmark extras:

```bash
./.venv/bin/python -m pip install -e ".[benchmark]"
```

## Library

```python
from akashik.ingest import ingest_text
from akashik.retrieve import retrieve
from akashik.store import Store

store = Store("akashik.db")

ingest_text(
    store,
    "I live in Chicago",
    metadata={"instance_id": "demo", "session_date": "2022-01-01"},
)
ingest_text(
    store,
    "I moved to New York",
    metadata={"instance_id": "demo", "session_date": "2024-06-01"},
)

current = retrieve(
    "where do I live",
    store,
    level="fact",
    entity_filters={"instance_id": "demo"},
)

historical = retrieve(
    "where do I live",
    store,
    level="fact",
    entity_filters={"instance_id": "demo"},
    as_of="2023-01-01",
)
```

## Data Model

Each `MemoryUnit` stores:

- UUID `id`
- `level`
- raw `content`
- `content_hash`
- `normalized_hash`
- `parent_id`
- `metadata` JSON
- nullable `embedding`
- nullable `section_heading`
- nullable `valid_from`
- nullable `valid_until`

`valid_from` is set from `session_date` when present on fact units. `valid_until` is set when a newer contradicting fact supersedes an older one.

## Ingestion

`ingest_file()` and `ingest_text()` split content deterministically:

- one `document` per input text
- one `section` per blank-line block
- one `fact` per sentence-like split

Rule-based contradiction detection currently covers a small, explicit pattern table for high-frequency first-person facts such as:

- location
- employer
- role
- school
- age
- vehicle
- preference
- name

Unmatched facts are stored normally and do not participate in belief revision.

## Retrieval

`retrieve()` supports:

- `level="fact" | "section" | "document" | "corpus"`
- `entity_filters={...}` for scoped retrieval
- `document_gate_n` for two-stage document-first retrieval
- `use_navigator`
- `use_semantic`
- `as_of="YYYY-MM-DD"` for historical queries

Default behavior excludes superseded facts. Historical queries include only facts valid at the requested date.

## CLI

Default database path: `./akashik.db`

```bash
akashik ingest --file README.md --level document
akashik query --text "local first memory" --level fact
akashik show --id <uuid>
akashik stats
```

## Tests

```bash
./.venv/bin/python -m pytest
```

## Synthetic Benchmark

Mode A:

```bash
./.venv/bin/python benchmark/run.py
```

Mode B:

```bash
./.venv/bin/python benchmark/run_mode_b.py
```

Outputs:

- `results/results.json`
- `results/report.md`
- `results/results_mode_b.json`
- `results/report_mode_b.md`

Embedding-based RAG is optional:

```bash
./.venv/bin/python benchmark/run.py --with-embeddings
```

After running `benchmark/run.py`, inspect the benchmark store with:

```bash
akashik --db results/benchmark.db query --text "..." --level fact
```

## CUAD Benchmark

Prepare the CUAD corpus and queries:

```bash
./.venv/bin/python benchmark/cuad/prepare.py
```

Run Mode A:

```bash
./.venv/bin/python benchmark/run_cuad.py
```

Run Mode B:

```bash
./.venv/bin/python benchmark/run_cuad_b.py
```

## LongMemEval

The LongMemEval runner uses per-instance SQLite stores by default to keep ingestion and FTS cost flat.

Oracle:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --data benchmark/longmemeval/data/longmemeval_oracle.json \
  --abstention-threshold 0.3 \
  --output benchmark/longmemeval/results_oracle.jsonl
```

S split:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --data benchmark/longmemeval/data/longmemeval_s_cleaned.json \
  --document-gate-n 5 \
  --abstention-threshold 0.3 \
  --output benchmark/longmemeval/results_s.jsonl
```

Useful diagnostics:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py --help
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py --dry-run
```
