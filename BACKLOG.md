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

### Reader/Executor Layer

Problem: the temporal delta resolver, belief revision system, and preference synthesis all produce value that retrieval-only evaluation cannot measure. No layer exists to reason over retrieved facts and produce cited answers.

Idea: an Executor layer that receives top-N retrieved facts plus provenance and produces a cited, traceable answer. First version: rules engine handling typed operations (compare, chain, flag, compute delta). Future: typed reasoning layer. Never a generative LLM in the core path — cited answers only, every claim traceable to a source fact address.

Why it matters: the temporal delta resolver currently computes correct answers the benchmark cannot score. The Executor is the layer that turns retrieved facts into verifiable answers. Also makes preference synthesis measurable — session is retrieved correctly, Executor synthesizes the implicit preference.

Constraints:
- Executor never sees full corpus.
- Receives top-N facts plus provenance only.
- Outputs must be cited.
- No hallucination possible by construction.

Open questions:
- What typed operations are needed for `v1.0.0`?
- How does the Executor handle conflicting facts?
- How does cited answer format interact with downstream LLM consumers?

### Ingest-Time Preference Extraction

Problem: single-session-preference session recall is `0.23` on LongMemEval-S. The query-to-evidence keyword gap is structurally unbridgeable with FTS alone. Queries are generic; evidence sessions are specific.

Idea: at ingest time, extract `(user, prefers, X)` triples from conversational turns using deterministic rule-based patterns. Store as derived fact units alongside raw facts. When a preference query arrives, it matches the derived fact rather than the raw session content. No LLM required for extraction if patterns are constrained to high-frequency preference expressions.

Why it matters: closes the preference gap deterministically. Extends the contradiction system already built in `v0.9.0` — preference triples follow the same `(entity, attribute, value)` model as location and employer facts.

Constraints:
- Rule-based extraction only for `v1.x`.
- LLM extraction optional later.
- Derived facts clearly tagged as derived, not raw.
- Raw facts always preserved.

Open questions:
- What pattern coverage is needed to meaningfully move preference recall?
- How are implicit preferences ("I've been really into jazz lately") distinguished from explicit ones ("I prefer jazz")?

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
