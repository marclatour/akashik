# Backlog

## Ideas

### Rust Core For Bulk Ingest Throughput

Problem: bulk ingest is the binding performance constraint. Retrieval is already fast (milliseconds). First-time corpus onboarding at scale (law firm ingesting 10 years of contracts, user importing decade of AI conversations) can take tens of minutes on Python + SQLite single-thread.

Idea: rewrite the store write path in Rust. Batched WAL writes, parallel document ingest, zero-copy SHA-256 hashing. Python stays for CLI, benchmark runners, and ingest adapter logic. Rust handles store writes and FTS index maintenance via PyO3 bindings.

Why it matters: makes large corpus onboarding practical. A 10M-fact corpus should ingest in minutes, not hours. Retrieval path is already fast enough — this is purely a write throughput problem.

Constraints:
- SQLite stays as the storage engine.
- No new storage dependencies.
- Must pass all existing tests.
- Do not implement before `v1.0.0`.

Open questions:
- Does FTS5 write throughput benefit from Rust, or is SQLite the bottleneck regardless?
- What is the PyO3 interface surface?

### Decentralized Node Mesh

Problem: Akashik is currently single-node. The Addressed Cognition thesis implies a distributed addressed memory fabric — every device runs its own Fact Store, facts replicate by address, the Navigator routes across nodes.

Idea: each device runs a local Fact Store with its own SQLite instance. Facts are identified by SHA-256 address globally — two nodes holding the same fact converge without conflict (content-addressed deduplication is already built in). The Navigator routes queries across nodes using the same hierarchical routing logic used within a single node. No central server. No cloud dependency. A person's cognitive record lives on their devices, not in a data center.

Why it matters: scales from one laptop to enterprise mesh. An organization's knowledge graph is distributed across every employee's local store. Local-first is not just a design principle — it is the architecture. Every device is a node. Massive compute, decentralized.

Constraints:
- No central coordination required for fact storage.
- Replication is pull-based by address.
- Navigator mesh routing is a separate layer from fact storage.
- Does not require Rust core first but benefits from it at scale.

Open questions:
- How does the Navigator discover peer nodes?
- How are entity scopes maintained across nodes?
- What is the conflict resolution model when the same `(entity, attribute)` fact exists on two nodes with different timestamps?

### Executor Expansion

Problem: the first deterministic Executor exists, but it currently covers only factual lookup, two-event temporal deltas, simple preference summaries, and basic aggregations. Richer cited operations are still missing.

Idea: expand the Executor with more typed operations such as compare, chain, contradiction flagging, and conflict-aware answer synthesis. Keep every operation deterministic, cited, and bounded to retrieved top-N facts.

Why it matters: retrieval-only evaluation now leaves value on the table in a different way. The next gain is not "can Akashik answer at all" but "how many structured questions can the Executor answer faithfully without handing off to an LLM."

Constraints:
- Executor never sees full corpus.
- Outputs remain fully cited and traceable to fact UUIDs.
- No generative LLM in the core execution path.
- Raw retrieval results must remain available alongside the executed answer.

Open questions:
- What typed operations are required for `v1.0.0`?
- How should the Executor represent conflicting but still-valid evidence?
- What cited answer format is most useful to downstream LLM consumers?

### Preference Canonicalization

Problem: ingest-time preference extraction now exists, but semantically identical values such as `"Sony"`, `"Sony camera"`, and `"Sony A7R IV"` still fragment into separate exact-match preference groups.

Idea: add a deterministic canonicalization layer for derived preference values. Normalize surface variants into a stable preference key while preserving the raw extracted value for provenance.

Why it matters: the current preference extractor closes part of the keyword gap, but ranking still splits reinforcement across near-duplicate values. Canonicalization would make preference summaries and future Executor synthesis materially stronger without introducing embeddings.

Constraints:
- Canonicalization must be deterministic and auditable.
- Raw extracted values remain preserved in metadata.
- No LLM or embedding clustering in the core path.

Open questions:
- What normalization rules are safe without over-collapsing distinct products?
- Should canonicalization happen at ingest time or only during Executor grouping?
- How should model/version relationships like `"Sony"` vs `"Sony A7R IV"` be represented?

### Aggregation Queries

Problem: "which airline did I fly most in March and April" requires set operations over multiple retrieved facts, not point-to-point delta computation. Currently unsupported, falls back to unscoped FTS.

Idea: after two-event delta resolver (`v0.9.2`), add aggregation resolver. Detect aggregation query pattern, retrieve all matching facts within temporal scope, group by entity value, count, return dominant value with provenance.

Why it matters: closes the remaining class of unsupported temporal queries in LongMemEval. Also directly useful for cognitive record use case ("what did I work on most in Q3 2024").

Constraints:
- Deterministic only.
- No LLM.
- Aggregation is a set operation over the existing fact store — no new storage required.

Open questions:
- What is the expected recall improvement on temporal-reasoning bucket?
- How does aggregation interact with validity windows?

### Hierarchical Consolidation

Problem: at million-fact scale, the Navigator needs higher-order summary units (Era/Domain/Topic) to keep routing `O(log n)`. As the corpus grows, flat fact retrieval degrades in ranking quality even if speed stays acceptable.

Idea: a background consolidation process periodically summarizes atomic facts into addressable higher-order units. Era summaries aggregate facts by time period. Domain summaries aggregate by topic. These summary units are first-class addressed facts — SHA-256 hashed, versioned, retrievable. The Navigator routes to the summary first, then descends to atomic facts.

Why it matters: keeps the architecture correct at decade scale. Without consolidation, a 10M-fact corpus eventually overwhelms the document gate even with hierarchical routing.

Constraints:
- Consolidation is a background process, never blocks retrieval.
- Summary units are derived, clearly tagged, never replace raw facts.
- Requires era/domain/topic taxonomy — either declared or discovered via clustering.

Open questions:
- What triggers consolidation (fact count threshold, time-based, manual)?
- How are summary units invalidated when constituent facts are superseded?
- Does this require the Rust core first?

### Navigator ML Scorer

Problem: the rule-based Navigator captures useful structural priors, but there is likely still ranking headroom in how those signals are combined and weighted across corpora.

Idea: add a discriminative Navigator ML scorer using logistic regression over structural features. This remains non-generative and explainable. If the model is unavailable or uncertain, fail open to the current rule-based Navigator.

Why it matters: this could improve within-scope fact ranking while preserving the architecture's core boundary: no generative model in retrieval, no semantic model deciding facts, and no opaque end-to-end reranker.

Constraints:
- Discriminative only, not generative.
- Feature-based and explainable.
- Must fail open to the rule-based Navigator.
- No change to the retrieval priority stack if the scorer is absent or disabled.

Open questions:
- Which existing Navigator features should become the first regression feature set?
- How should model calibration interact with the current additive tie-break threshold?
- Is logistic regression enough, or does the feature space eventually justify a stronger but still interpretable model?

### Corpus Store Layout + `akashik setup` Command

Problem: the default store path (`./akashik.db`) is a flat single file that does not scale and conflicts with the per-instance store pattern proven by LongMemEval. There is no concept of named corpora or a canonical store location for production use.

Idea: adopt a per-corpus, per-document store layout under `~/.akashik/`:

```text
~/.akashik/
  stores/
    corpora/
      my_conversations/
        {session_id}.db
      legal_corpus/
        {document_id}.db
    benchmarks/
      cuad/
        benchmark_cuad_50.db
      longmemeval_s_cleaned/
        {question_id}.db
  data/
    benchmarks/
      cuad/
        queries_cuad.json
        queries_cuad_b.json
      longmemeval/
        longmemeval_oracle.json
        longmemeval_s_cleaned.json
  config/
    defaults.toml
  logs/
    benchmark.log
```

Add an `akashik setup` CLI command that creates the `~/.akashik/` directory structure, sets the default store root, and optionally downloads benchmark data.

Change the default store path in `store.py` and `cli.py` from `./akashik.db` to `~/.akashik/stores/corpora/default.db`.

Why it matters: makes Akashik usable as a production tool, not just a benchmark runner. A user importing their AI conversation history needs a named corpus with per-session stores, not a flat `.db` file in whatever directory they ran the CLI from. It is consistent with the local-first, user-owns-their-data philosophy.

Constraints:
- Backward compatible — existing `./akashik.db` files still openable.
- Per-document store pattern already proven by LongMemEval.
- No cloud sync or remote paths.
- Setup command must work offline.

Open questions:
- How does `akashik ingest` know which corpus to write to: named corpus flag (`--corpus my_conversations`) or interactive selection?
- Should corpus names be user-defined or derived from source path?
- How does `akashik query` scope to a specific corpus?
- What is the migration path for users with existing `./akashik.db` files?
