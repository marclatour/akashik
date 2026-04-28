# Akashik

Addressed Cognition — deterministic memory OS for long-lived human–AI relationships.

## What Akashik is for

OpenClaw is essentially a high-performance CPU that currently suffers from Volatile RAM — it clears its head the moment you close the terminal. Akashik provides the Non-Volatile Semantic Storage (the SSD) and the MMU (the Memory Management Unit) to make that data accessible in 87ms.

Akashik turns any local AI assistant from a session-based tool into a lifelong personal AI that actually remembers and evolves with you.

The mental model:

| Component | Role |
|---|---|
| OpenClaw / local LLM | CPU — high-performance local reasoning |
| Akashik fact store | SSD — non-volatile semantic storage, persists forever |
| Akashik expression engine | MMU — memory management unit, right facts in 87ms |
| LLM context window | CPU cache — small, fast, only what's needed right now |

The LLM never stores facts. Akashik never reasons. Hard boundary between them.

## Why deterministic

LLM-based memory systems like Mem0 extract and consolidate facts using an LLM call per conversation turn. On consumer hardware this takes 5-15 seconds per turn. For a system intercepting live conversations, that is architecturally incompatible — you cannot block a conversation waiting for memory extraction.

Akashik's deterministic ingest takes milliseconds. It is not a tradeoff. It is a requirement for the use case.

| Approach | Ingest per turn | Query latency |
|---|---|---|
| Akashik (deterministic) | <10ms | 3.98ms p50 |
| RAG (embedding) | <10ms | ~22ms p50 |
| Mem0 (LLM-assisted) | 5–15 seconds | — |

Mem0's LLM extraction produces richer semantic consolidation but is unsuitable for real-time conversational interception. Akashik's deterministic approach is designed for the 87ms intercept window — invisible to the user, always current, never blocking. See the ACMB table below for comparative quality metrics.

## ACMB benchmark — 7-way blind, 25 personas

| Metric | Akashik | rag_akashik | bm25_akashik | RAG | full_ctx | BM25 | TF-IDF |
|---|---|---|---|---|---|---|---|
| Fact Recall | 0.648 | **0.752** | 0.679 | 0.614 | 0.560 | 0.541 | 0.533 |
| Belief Revision | 0.281 | 0.249 | 0.251 | 0.111 | **0.340** | 0.113 | 0.068 |
| Fact Precision | 0.219 | 0.214 | **0.257** | 0.183 | 0.255 | 0.171 | 0.158 |
| Temporal Correct | 0.598 | **0.702** | 0.629 | 0.614 | 0.520 | 0.541 | 0.533 |
| Distractor Penalty | 0.554 | 0.675 | 0.588 | 0.675 | **0.433** | 0.588 | 0.593 |
| Latency p50 | 3.75ms | 20.95ms | **0.72ms** | 20.86ms | 1.34ms | 0.71ms | 0.90ms |

All numbers are blind post-audit (v0.25.4+). Oracle fields removed from all adapters. Hybrid adapters (`bm25_akashik`, `rag_akashik`) now run on equal footing with baselines. `full_context` leads belief revision (0.340) — it sees the full history; at decade-scale this becomes architecturally infeasible. `rag_akashik` leads recall (0.752) and temporal (0.702). Akashik leads on latency among structured systems (3.75ms) and is the only adapter with real temporal filtering, provenance, and lineage.

Akashik stores content as a fixed hierarchy:

- `corpus`
- `document`
- `section`
- `fact`

The active architecture is the five-layer Addressed Cognition model:

1. Sequence: immutable ground truth
2. Lineage: canonical evolution chains
3. Epigenetic: mutable activation state
4. Expression: context-driven selective readout
5. Consolidation: background semantic/procedural compression

The cold-path retrieval stack remains:

1. exact `content_hash`
2. exact `normalized_hash`
3. SQLite FTS5 keyword search
4. document gate + scoped fact reranking
5. Navigator tie-breaker
6. semantic fallback only when confidence is low

Addressed Cognition is the active development branch. The north-star design document is [ARCHITECTURE.md](ARCHITECTURE.md). Existing stores are migrated automatically on first open. The current branch keeps the existing retrieval stack intact and adds an opt-in expression engine that can fire before retrieval when explicitly enabled.

Expression engine controls:

- `--use-expression` on supported benchmark runners
- `AKASHIK_USE_EXPRESSION=1` to enable expression in those runners by default
- `AKASHIK_EXPRESSION_THRESHOLD` default `2.0`
- `AKASHIK_MAX_EXPRESSED_FACTS` default `20`

Benchmark results below still reflect the cold path unless noted otherwise. Expression-engine benchmark deltas are pending.

## Install

```bash
./.venv/bin/python -m pip install -e ".[dev]"
```

Linux users: install CPU-only PyTorch before other dependencies to avoid downloading the full CUDA stack:

```bash
./.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
./.venv/bin/python -m pip install -e ".[dev,benchmark]"
```

Benchmark extras:

```bash
./.venv/bin/python -m pip install -e ".[benchmark]"
```

Local judge dependency:

```bash
./.venv/bin/python -m pip install ollama
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

`retrieve_diverse(store, query, ...)` is also available as a thin helper over `retrieve()` when callers want a session-diversified fact list from a broader candidate pool without changing the core retrieval stack.

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

## Local Judge

`akashik.judge` is evaluation-only. It never runs in retrieval, routing, Navigator scoring, semantic fallback, or Executor inference.

Current local judge design:

- Ollama-hosted `qwen2.5:1.5b`
- deterministic exact/substring fast-path before any model call
- strict `YES` / `NO` prompt
- cached judgments in `~/.akashik/judge_cache.jsonl`
- optional majority voting for more conservative scoring

Use it as a post-processing benchmark tool, not as part of the product pipeline.

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

CUAD has two modes over the same 50-contract corpus and the same shared store. The difference is the query formulation:

- Mode A: clause-style benchmark queries
- Mode B: natural-language paraphrases of those same queries

This is a query robustness test, not a corpus-noise test.

Prepare the CUAD corpus and queries:

```bash
./.venv/bin/python benchmark/cuad/prepare.py
```

Run Mode A:

```bash
./.venv/bin/python benchmark/run_cuad.py
```

Current blind baseline (4-way, no oracle hints):

| System | P@1 | Context Efficiency | Composite |
|---|---|---|---|
| RAG | 0.08 | 0.029 | 0.065 |
| GraphRAG | 0.14 | 0.109 | 0.135 |
| Akashik | 0.06 | **0.230** | 0.111 |
| RAG-Embedding | 0.06 | 0.029 | 0.063 |

Note: query set is keyword-only stems with no entity mentions. Akashik's context efficiency (0.230) is structural and holds blind — retrieved spans are 2–8× tighter than baselines. P@1 leadership requires natural queries with entity mentions (open work).

Run Mode B:

```bash
./.venv/bin/python benchmark/run_cuad_b.py
```

Mode B numbers pending blind rerun.

Interpretation:

- Mode A asks whether Akashik can retrieve the right clause when the query is close to the benchmark label
- Mode B asks whether Akashik survives informal legal paraphrasing against the same store
- the Mode A/B gap is a query normalization and paraphrase robustness problem, not a store-structure problem

Keep the executor JSONL for local judging:

```bash
./.venv/bin/python benchmark/run_cuad.py --keep-output
./.venv/bin/python benchmark/run_cuad_b.py --keep-output
```

CUAD runner behavior now matches LongMemEval:

- `--use-executor` is enabled by default for both `run_cuad.py` and `run_cuad_b.py`
- disable it explicitly with `--no-executor`
- if `--keep-output` is omitted, the JSONL goes to `/tmp/akashik_cuad_{timestamp}.jsonl` or `/tmp/akashik_cuad_b_{timestamp}.jsonl` and is deleted after metrics print
- if `--keep-output` is set, the runner prints the saved JSONL path

Judge CUAD outputs after a kept run:

```bash
./.venv/bin/python benchmark/longmemeval/run_judge.py \
  --results '/tmp/akashik_cuad_*.jsonl' \
  --data benchmark/cuad/queries_cuad.json \
  --votes 3

./.venv/bin/python benchmark/longmemeval/run_judge.py \
  --results '/tmp/akashik_cuad_b_*.jsonl' \
  --data benchmark/cuad/queries_cuad_b.json \
  --votes 3
```

## LongMemEval — validated results (April 2026)

LongMemEval uses one runner with two dataset regimes over the same question set:

- Oracle: only evidence sessions are provided
- S: full noisy haystack, roughly 53 sessions per instance

This is a noise robustness test, not a query paraphrase test.

The LongMemEval runner uses persistent per-instance SQLite stores by default. Stores are cached under:

```text
~/.akashik/stores/benchmarks/{dataset_stem}/{question_id}.db
```

Reuse is automatic unless `--force-reingest` is set.

Oracle:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --data benchmark/longmemeval/data/longmemeval_oracle.json \
  --abstention-threshold 0.3
```

Session Recall @10: **0.97** Oracle / **0.92** S split (diverse retrieval)

### QA Accuracy with diverse retrieval (pool=100, top_sessions=8, facts_per_session=5)

| Category | Oracle qwen | Oracle GPT-5.4-mini | S qwen | S GPT-5.4-mini |
|---|---|---|---|---|
| single-session-user | 0.81 | 0.84 | 0.86 | 0.84 |
| single-session-assistant | 0.84 | 0.88 | 0.79 | 0.86 |
| single-session-preference | 0.90 | 0.93 | 0.57 | 0.87 |
| knowledge-update | 0.67 | 0.86 | 0.61 | 0.75 |
| temporal-reasoning | 0.35 | 0.41 | 0.31 | 0.39 |
| multi-session | 0.29 | 0.45 | 0.32 | 0.36 |
| **Overall** | **0.54** | **0.64** | **0.51** | **0.59** |
| Deterministic path | 1.00 | 1.00 | 1.00 | 1.00 |

Multi-session QA baseline (standard retrieval, any model): **0.06**
Multi-session QA with diverse retrieval + qwen2.5:1.5b: **0.29** (+4.8x)
Multi-session QA with diverse retrieval + GPT-5.4-mini: **0.45** (+7.5x)

Diverse retrieval is the primary architectural lever. The retrieval architecture moves
multi-session QA regardless of model. Frontier model adds synthesis quality on top.
Deterministic executor path is 100% correct across all configurations.

Run with diverse retrieval:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --data ~/.akashik/data/benchmarks/longmemeval/longmemeval_oracle.json \
  --diverse-retrieval \
  --diverse-top-sessions 8 \
  --diverse-facts-per-session 5 \
  --generate-answers \
  --backend openai \
  --answer-model gpt-5.4-mini \
  --keep-output
```

Useful diagnostics:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py --help
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py --dry-run
```

Optional diversified retrieval for multi-session diagnostics:

```bash
./.venv/bin/python benchmark/longmemeval/run_longmemeval.py \
  --question-type multi-session \
  --diverse-retrieval \
  --diverse-pool 100 \
  --diverse-top-sessions 5 \
  --diverse-facts-per-session 3
```

Result output behavior:

- if `--output` is omitted, results go to `/tmp/akashik_lme_{dataset_stem}_{timestamp}.jsonl`
- the output JSONL is deleted after metrics print unless `--keep-output` is set
- when `--keep-output` is set, the runner prints the saved path
- `--use-executor` is enabled by default; disable it explicitly with `--no-executor`
- when executor is enabled, the runner prints additive Executor answered/abstained stats and per-type counts

Judge post-processing:

```bash
./.venv/bin/python benchmark/longmemeval/run_judge.py \
  --results '/tmp/akashik_lme_longmemeval_oracle_*.jsonl' \
  --data benchmark/longmemeval/data/longmemeval_oracle.json \
  --votes 3
```
