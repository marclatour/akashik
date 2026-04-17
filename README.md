# Akashik 0.10.1

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

Facts now support validity windows, reinforcement tracking, additive two-event temporal delta resolution, ingest-time derived preference facts, and a deterministic Executor layer for cited answers. In `0.10.1`, the Executor classifier gained broader LongMemEval-style pattern coverage for factual, temporal, preference, and aggregation phrasings. By default, retrieval returns only currently valid facts. Historical queries can opt into `as_of=...`.

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
from akashik.executor import execute
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

result = execute(
    store,
    "Where do I live?",
    entity_filters={"instance_id": "demo"},
)
print(result.answer)

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
- `confirmation_count`
- nullable `last_confirmed_at`

Each `ExecutorResult` stores:

- `answer`
- `answer_type`
- `answer_confidence`
- `coverage_confidence`
- `requires_reasoning`
- `abstained`
- `sources`
- `raw_facts`
- nullable `temporal_answer`

`valid_from` is set from `session_date` when present on fact units. `valid_until` is set when a newer contradicting fact supersedes an older one.
Repeated normalized restatements of the same current-valid fact increment `confirmation_count` and update `last_confirmed_at` instead of creating duplicate fact units.

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

Repeated current-valid facts are absorbed as confirmations:

- `confirmation_count` starts at `1`
- `last_confirmed_at` starts at `valid_from`
- restating the same normalized fact in the same `instance_id` increments the existing fact instead of inserting a duplicate

Preference extraction is additive and deterministic:

- only `speaker="user"` turns are eligible
- raw facts are always preserved
- derived preference facts are tagged with `metadata["derived"] = "preference"`
- derived preference facts also store `preference_polarity`, `preference_strength`, and `preference_value`
- exact same value + same polarity reinforces the existing derived fact
- exact same value + opposite polarity closes the older derived fact
- different preference values coexist

## Retrieval

`retrieve()` supports:

- `level="fact" | "section" | "document" | "corpus"`
- `entity_filters={...}` for scoped retrieval
- `document_gate_n` for two-stage document-first retrieval
- `use_navigator`
- `use_semantic`
- `as_of="YYYY-MM-DD"` for historical queries
- `query_date="..."` when recency-aware Navigator scoring should use a question-relative date

Default behavior excludes superseded facts. Historical queries include only facts valid at the requested date.

The Navigator remains additive-only. In `0.9.1` it can also add a small confidence-decay boost based on:

- recent confirmation recency relative to `query_date`
- `confirmation_count` reinforcement, capped at `+0.03`

For instance-scoped conversational queries, `retrieve()` now also attempts a deterministic two-event temporal delta resolution before the standard retrieval stack. When successful, the computed delta is attached to `RetrievalResponse.temporal_answer` while the normal fact retrieval path still runs for provenance.

Derived preference facts live in the same FTS index as raw facts. Retrieval, document gating, Navigator scoring, and semantic fallback remain unaware of whether a fact was raw or derived.

## Executor

`execute()` is a deterministic rules engine over retrieved Akashik facts. It never calls an LLM and never invents unsupported claims.

Current query types:

- factual
- temporal
- preference
- aggregation
- unknown

The Executor always returns:

- a typed answer or an explicit abstention
- `answer_confidence` and `coverage_confidence`
- `raw_facts` for the underlying retrieval set
- source citations with fact UUIDs and session metadata

If evidence is insufficient, the Executor abstains instead of guessing.

`0.10.1` expands classifier coverage with regex-based pattern tables and keeps preference routing ahead of aggregation routing. Unknown queries still fail open to factual lookup rather than returning nothing.

## Where Akashik Sits

Akashik is intended to sit between a local client and an LLM, not inside the model itself.

Typical flow:

```text
Human types message
  ↓
Local client intercepts
  ↓
Akashik retrieves relevant facts
  ↓
Facts + provenance injected into LLM context
  ↓
LLM generates response
  ↓
Human reads response
  ↓
repeat
```

In that flow, Akashik is effectively invisible. Retrieval latency is small relative to an LLM round trip, but it changes the quality of the prompt materially: the model sees a small, precise, cited context instead of a large haystack.

This is also where the planned Executor layer fits. For simple factual queries, Akashik could answer directly without an LLM call at all, while the LLM remains reserved for reasoning, synthesis, or generation. The intended boundary is strict: Akashik stores and retrieves facts with provenance; the LLM reasons over the returned context but does not act as the system of record.
The first deterministic Executor now exists inside Akashik itself; future work is about expanding typed operations, not introducing a generative answer layer into the core path.

## CLI

Default database path: `./akashik.db`

```bash
akashik ingest --file README.md --level document
akashik query --text "local first memory" --level fact
akashik execute "Where do I live?"
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

The LongMemEval runner uses persistent per-instance SQLite stores by default. Stores are cached under:

```text
~/.akashik/stores/benchmarks/{dataset_stem}/{question_id}.db
```

Reuse is automatic unless `--force-reingest` is set.

Oracle:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --data benchmark/longmemeval/data/longmemeval_oracle.json \
  --abstention-threshold 0.3 \
  --use-executor
```

Current oracle baseline with executor enabled:

- Session Recall @10: `0.97`
- Turn Recall: `0.89`
- Executor classifier distribution after `v0.10.1` expansion:
  - `factual`: `97`
  - `temporal`: `80`
  - `preference`: `17`
  - `aggregation`: `78`
  - `unknown`: `228`

S split:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --data benchmark/longmemeval/data/longmemeval_s_cleaned.json \
  --document-gate-n 5 \
  --abstention-threshold 0.3
```

Preference-only rebuild:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --data benchmark/longmemeval/data/longmemeval_s_cleaned.json \
  --document-gate-n 5 \
  --abstention-threshold 0.3 \
  --question-type single-session-preference \
  --force-reingest \
  --keep-output
```

Useful diagnostics:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py --help
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py --dry-run
```

Result output behavior:

- if `--output` is omitted, results go to `/tmp/akashik_lme_{dataset_stem}_{timestamp}.jsonl`
- the output JSONL is deleted after metrics print unless `--keep-output` is set
- when `--keep-output` is set, the runner prints the saved path
- when `--use-executor` is set, the runner prints additive Executor answered/abstained stats and per-type counts
