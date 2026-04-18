# ACMB v0.1

The Akashik Conversation Memory Benchmark evaluates long-horizon conversational memory in a system-agnostic way. It is designed to test whether a memory system can preserve current state, reject superseded facts, surface open commitments, and recover older facts through noisy later conversation.

## Data Locations

All ACMB data lives under `~/.akashik/`:

```text
~/.akashik/data/benchmarks/acmb/
  personas/
    persona_001.json
    ...
  queries/
    queries_001.json
    ...

~/.akashik/stores/benchmarks/acmb/
  persona_001.db
  persona_002.db
  ...
```

No ACMB JSON or DB files live in the repository.

## Running

```bash
./.venv/bin/python benchmark/acmb/run_acmb.py --adapter akashik
```

`run_acmb.py` generates the hand-authored synthetic personas on first run if the ACMB data directory is empty.

## What ACMB Tests

- `current_state`
  Tests belief revision. A current fact must be retrieved and a superseded fact must not.
- `paraphrase`
  Tests whether a system can recover the right fact when the query wording differs from the stored wording.
- `commitment`
  Tests whether open assistant commitments surface at the right moment.
- `noise_robustness`
  Tests whether early-session facts remain retrievable after several noisy or drifting sessions.

The benchmark is system-agnostic because adapters return benchmark `fact_id` strings, not Akashik internals.

## Persona Schema

Each persona file contains:

- `persona_id`
  Stable benchmark identifier.
- `stable_traits`
  Non-changing background information.
- `facts`
  Ground-truth fact catalog with explicit introduction and supersession turns.
- `commitments`
  Open or closed assistant commitments.
- `sessions`
  Five chronological sessions, each with `session_type` of `normal`, `noise`, `drift`, or `contradiction`.
- `turns`
  Natural-language conversation turns with `ground_truth_facts` and `revises_facts` annotations.

## Query Schema

Each query includes:

- `turn_before`
  The exact turn after which the query fires. The runner streams turns and queries at that point, not after full ingestion.
- `must_include`
  Facts that must be returned.
- `must_exclude`
  Facts that must not be returned.
- `hard_distractors`
  Plausible but wrong facts that count against the system if returned.
- `should_include`
  Helpful supporting facts.
- `expected_current`
  Facts that represent the correct current state.

## Metrics

- `fact_recall`
  Fraction of `must_include` facts returned in top-k.
- `belief_revision_score`
  `1.0` if no `must_exclude` facts appear, else `0.0`.
- `fact_precision`
  Fraction of returned facts that are in `must_include` or `should_include`.
- `temporal_correctness`
  Fraction of queries where `expected_current` is present.
- `distractor_penalty`
  Count of returned `hard_distractors`.

## Adding A New Adapter

Implement the interface in [adapters/base.py](/Users/mlatour/work/akashik/benchmark/acmb/adapters/base.py:1):

- `ingest_turn(turn)`
- `query(query_text, k=10)`

Optionally implement `query_with_scores(query_text, k=10)` if your system exposes confidence scores.

## Current Scope

v0.1 uses five hand-authored synthetic personas. The Akashik adapter is intentionally stubbed in this slice, so the benchmark runner returns zero scores by design until the adapter is wired into real Akashik retrieval.
