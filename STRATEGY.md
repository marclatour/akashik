# Akashik — Strategy

Internal planning document. Honest, specific, no hedging.

---

## 1. What Akashik is

Akashik is a local-first, deterministic structured-memory library for long-lived human–AI relationships. Content is stored as an immutable hierarchy (`corpus → document → section → fact`), facts carry lineage and validity intervals, and retrieval is a deterministic stack (exact hash → normalized hash → FTS5 keyword → scoped reranking → semantic fallback only on low-confidence). No embeddings in the hot path. No LLM in the ingest path. SQLite + FTS5 is the whole substrate.

It is not a vector DB. It is not an LLM-extraction memory system. It is the non-volatile semantic storage layer a local assistant wires *below* the context window — the SSD+MMU to the LLM's CPU.

---

## 2. What's real today

The properties below held under **blind** benchmark conditions after the v0.25.4 oracle-leak audit (ACMB adapter no longer reads ground-truth fields; CUAD harness no longer passes Akashik-only query hints).

- **Fact recall leadership on agent-memory traffic.** ACMB blind (25 personas, v0.25.6): Akashik 0.648 vs BM25 0.541. Lead is +0.107 absolute, ~20% relative — on a benchmark designed around multi-session persona recall.
- **Temporal correctness is structural.** ACMB blind 0.598 vs baselines at 0.541. `valid_from` / `valid_until` and `as_of` filtering are first-class in the schema; vector baselines have no equivalent.
- **Context efficiency on structured documents.** CUAD blind (50 contracts): Akashik context-efficiency 0.230 vs GraphRAG 0.109 vs RAG 0.029. Retrieved spans are roughly 2× tighter than the best graph baseline and ~8× tighter than vector RAG.
- **Sub-5ms p50 query latency.** ACMB blind p50 3.74ms. Faster than every semantic baseline (RAG ~22ms); within 5ms of pure lexical BM25 (0.73ms). Fits inside an interactive intercept window.
- **Deterministic ingest.** Sub-10ms per turn. No LLM call in the hot path. Reproducible — same input, same store, byte-identical facts.
- **Provenance and lineage are first-class.** Every fact carries `parent_id`, `valid_from`, `valid_until`, `confirmation_count`, `last_confirmed_at`, and a metadata dict. Supersession sets `valid_until` rather than deleting. The audit trail is the data model, not an add-on.
- **Long-context session recall and end-to-end QA.** LongMemEval blind (470 instances, v0.25.10): Session Recall @10 = **0.97** (Oracle) / **0.79** (S split). End-to-end QA accuracy with qwen2.5:1.5b local CPU: **46%** (Oracle) / **42%** (S split). Single-session accuracy 0.66-0.84 - strong. Temporal and multi-session accuracy limited by 1.5b model capability, not retrieval. Hardware: M1 MacBook Air, 8GB RAM, no internet connection.
- **A working end-to-end demo.** `examples/chat_with_memory.py` runs against the real store with the real retrieval stack. Not a scripted replay.

### Ingest Architecture

Two ingest modes exist and must remain distinct:

**Real-time conversational ingest**
- One turn at a time, 1-5 facts per turn
- Per-row FTS sync is correct - low volume, immediate consistency needed
- `begin_bulk_ingest()` / `end_bulk_ingest()` NOT used
- Latency target: `<10ms` per turn

**Bulk corpus onboarding**
- User imports ChatGPT history, email archive, Obsidian vault, medical records
- `begin_bulk_ingest()` / `end_bulk_ingest()` required
- FTS5 deferred rebuild: one B-tree rebuild vs 4000 incremental updates
- `PRAGMA synchronous=NORMAL` + 64MB cache during ingest
- 700x speedup measured: 500 LongMemEval instances in 3m24s vs ~41 hours
- Latency target: `<1 minute` for typical personal corpus

The first corpus import is the moment a user trusts or abandons the system. 40 minutes vs 1 minute is a product decision, not an engineering detail.

The `begin_bulk_ingest()` / `end_bulk_ingest()` API is the correct abstraction boundary. Conversational turns never call it. Import jobs always call it.

---

## 3. What's not yet proven

- **Belief revision on implied dialogue revisions.** ACMB blind 0.281 vs BM25 ~0.11. Akashik leads, but the lead is narrow because the rule-based contradiction detector (`akashik/contradiction.py`) only covers 8 regex patterns over declarative statements like *"I live in X."* ACMB's revision turns are often descriptive (*"Actually I moved last week"*), which the detector misses. Extending the pattern set is whack-a-mole; the real fix is semantic contradiction detection. Architectural decision pending — see §6.
- **CUAD P@1 on natural legal queries.** Blind P@1: Akashik 0.06 vs GraphRAG 0.14 vs RAG 0.08. The CUAD query set is keyword-only (*"governed laws california"*) — the queries contain neither the party name nor the document identifier, so document scoping is unrecoverable from query text alone. Akashik's entity-filter mechanism can't fire without entity mentions. On a query set written the way a lawyer or paralegal actually writes ("in the Aduro consulting agreement, what law governs?"), we expect the structural lead in context efficiency to translate into a P@1 lead. That rewrite is open work.
- **Preference recall.** LongMemEval `single-session-preference` = **0.23** (n=30) — the one weak cell in the LongMemEval table. Preference turns are soft-phrased ("I usually go with…", "lately I've been…") and the FTS-first retrieval path doesn't surface them well. Same shape as the belief-revision ceiling — descriptive language is where lexical retrieval hits its floor.
- **Expression engine is inert.** LongMemEval run: **0/500** expression hits, zero candidate-pool contribution. `--use-expression` is off by default and when it is on, it fires on no queries. Layer 4 needs a design review (see §6) — either make it earn its place or retire it.
- **Scale beyond 50 documents / 25 personas / 500 sessions.** LongMemEval at 470 instances closed the single-user scale question. Multi-user scale (100+ personas, cross-user isolation, long-horizon growth) is still open.
- **Consolidation (Layer 5).** Scaffolded only. The spec describes a background semantic/procedural compression loop; the code does not yet implement it.

---

## 4. Benchmark results

### ACMB v0.3 — 7-way blind, 25 personas, v0.25.9

| Metric | Akashik | rag_akashik | bm25_akashik | RAG | full_ctx | BM25 | TF-IDF |
|---|---|---|---|---|---|---|---|
| Fact Recall | 0.648 | **0.752** | 0.679 | 0.614 | 0.560 | 0.541 | 0.533 |
| Belief Revision | 0.281 | 0.249 | 0.251 | 0.111 | **0.340** | 0.113 | 0.068 |
| Fact Precision | 0.219 | 0.214 | **0.257** | 0.183 | 0.255 | 0.171 | 0.158 |
| Temporal Correct | 0.598 | **0.702** | 0.629 | 0.614 | 0.520 | 0.541 | 0.533 |
| Distractor Penalty | 0.554 | 0.675 | 0.588 | 0.675 | **0.433** | 0.588 | 0.593 |
| Latency p50 | 3.75ms | 20.95ms | **0.72ms** | 20.86ms | 1.34ms | 0.71ms | 0.90ms |

### CUAD — blind, 50 contracts, 4-way

| System | P@1 | Context Efficiency | Composite |
|---|---|---|---|
| RAG | 0.08 | 0.029 | 0.065 |
| GraphRAG | 0.14 | 0.109 | 0.135 |
| **Akashik** | 0.06 | **0.230** | 0.111 |
| RAG-Embedding | 0.06 | 0.029 | 0.063 |

Context efficiency 0.230 is structural and confirmed blind. P@1 leadership blocked on natural query rewrite (open work — §6 item 1).

**Caveat — query set design.** CUAD queries are keyword-only stems with no entity mentions. This is not how legal professionals actually query their contract stack, and it disproportionately penalizes systems that depend on entity resolution for scoping. Akashik's context-efficiency lead (0.230 vs 0.029–0.109) is structural and survives blind — retrieved spans are tighter regardless of P@1 ranking. P@1 leadership is open work gated on a natural-query rewrite (§6).

**Caveat — inverse oracle in query text.** Several CUAD queries embed the answer as a soft signal (e.g. *"governed laws california"* contains the governing-law jurisdiction). Any retrieval system that does reasonable token matching will get partial lift from this — GraphRAG's 0.14 P@1 is not fully clean either, just less penalized by it than a system built around entity-filter scoping. The natural-query rewrite in §6 fixes this for everyone.

### LongMemEval — blind, 470 instances, v0.25.9

| Dataset | Session Recall @10 | Notes |
|---|---|---|
| Oracle | **0.97** | Confirmed blind post-audit |
| S split | **0.79** | Confirmed blind post-audit |

| Type | Oracle | S blind | Delta |
|---|---|---|---|
| single-session-preference | 1.00 | 0.23 | −0.77 |
| single-session-assistant | 1.00 | 0.80 | −0.20 |
| multi-session | 0.96 | 0.76 | −0.20 |
| temporal-reasoning | 0.94 | 0.80 | −0.14 |
| knowledge-update | 0.97 | 0.93 | −0.04 |
| single-session-user | 0.97 | 0.91 | −0.06 |

### LongMemEval - end-to-end QA, qwen2.5:1.5b local CPU, v0.25.10

| Dataset | Session Recall @10 | QA Accuracy | Model | Hardware |
|---|---|---|---|---|
| Oracle | 0.97 | **0.46** | qwen2.5:1.5b | M1 Air, 8GB, local CPU |
| S split | 0.79 | **0.42** | qwen2.5:1.5b | M1 Air, 8GB, local CPU |

Per-type QA accuracy (Oracle):

| Type | Retrieval Recall | QA Accuracy | Gap | Notes |
|---|---|---|---|---|
| single-session-user | 0.97 | 0.84 | -0.13 | Strong |
| single-session-preference | 1.00 | 0.83 | -0.17 | Strong |
| single-session-assistant | 1.00 | 0.73 | -0.27 | Good |
| knowledge-update | 0.97 | 0.51 | -0.46 | Model bottleneck |
| temporal-reasoning | 0.94 | 0.26 | -0.68 | Model bottleneck - date math |
| multi-session | 0.96 | 0.20 | -0.76 | Model bottleneck - synthesis |

The retrieval-to-accuracy gap on temporal and multi-session is a 1.5b model limitation, not a memory architecture limitation. Retrieval is near-ceiling (0.94-0.96); the model cannot do date math or cross-session synthesis at this scale.

**Competitive context - LongMemEval-S end-to-end, canonical published results only:**

| System | S Split Accuracy | Model | Source |
|---|---|---|---|
| EmergenceMem | 86% | GPT-4o | Emergence AI, June 2025 |
| TiMem | 76.88% | GPT-4o-mini | Li et al., Jan 2026, arXiv |
| Zep/Graphiti | 71.2% | GPT-4o | Rasmussen et al., Jan 2025, arXiv |
| Full context baseline | ~60% | GPT-4o | Wu et al., 2024 |
| Llama 3.1-8B (no memory system) | 42-45% | Llama 3.1-8B | Wu et al., 2024 - raw model, no retrieval |
| **Akashik** | **42%** | **qwen2.5:1.5b** | **This repo, April 2026 - local CPU, no API** |

These are not directly comparable - all systems above Akashik use cloud APIs with GPT-4o-class models. The comparison is included for orientation only.

The most meaningful row is Llama 3.1-8B at 42-45% with no memory system. Akashik + qwen2.5:1.5b matches that score with a model 5x smaller. The retrieval is compensating for the model size disadvantage - which is the architectural thesis.

> Akashik delivers 42% S split QA accuracy fully on-device with a 1.5B model, matching a raw 8B model with no memory system. The remaining gap to cloud systems is primarily model-bound, not memory-bound. Swap in a stronger local model and the numbers move.

---

## 5. What was found and fixed

A fairness audit in April 2026 identified oracle leakage in both ACMB and CUAD adapters:

- **ACMB.** The Akashik adapter read `turn["ground_truth_facts"]` (appending commitment descriptions to stored content), wrote an `acmb_fact_id_index` mapping ground-truth fact IDs to memory-unit IDs, and consumed `turn["revises_facts"]` to close superseded facts via a private oracle path. No other adapter had access to any of these signals.
- **CUAD.** The harness passed `entity_filter` and `clause_type` to Akashik at query time — both derived from CUAD ground-truth fields — but passed raw query text to RAG and GraphRAG. 35 of 50 queries carried compound entity filters. The executor post-processing step ran for Akashik only.

Both were removed. ACMB now routes turns through the real content-inferred contradiction pipeline; CUAD now passes `query.query_text` uniformly to all three systems.

**Nothing referencing the inflated numbers has been published externally.** The numbers in `strategy.md` prior to v0.25.4-audit (Recall 0.801, Belief Revision 0.735, CUAD P@1 0.82) appeared in this internal document only. The audit was caught and fixed before any external claim was made.

Commits: `9cd8aeb` (ACMB + CUAD strip), `cbd572d` (LongMemEval strip), `v0.25.4-audit` (tag). Subsequent `v0.25.6-ingest` added `ingest_turn_fact()`, a turn-level API that replaced the per-turn `ingest_text()` abuse and yielded an unexpected +0.10 recall / +0.10 temporal lift purely from cleaner fact-graph hierarchy (single section per persona vs one section per turn).

---

## 6. Open work (priority order)

1. **Natural CUAD queries (Option B).** Rewrite the 50-query set to include party names and document identifiers — the way a paralegal actually queries. Expected outcome: Akashik's context-efficiency lead translates into a P@1 lead. Blocks the CUAD section of any external positioning.
2. **Semantic contradiction detection — decision taken.** Option (a) accepted as pattern hygiene: 9 additional declarative branches added in v0.25.9-contradiction (joined, stepped into, upgraded to, replaced with, finally switched to, etc.). ACMB rerun confirmed belief revision unchanged at 0.281 — the new patterns don't appear in the persona set, confirming the rule-based ceiling is ~0.281 on this benchmark. Option (b) (small LLM on declarative turns) is a named deferred project — build only if ACMB becomes product-defining, ship behind a feature flag, never wired in silently. Option (c) ruled out.
3. **Preference ranking boost under distractor load.** LongMemEval blind run confirmed preference recall collapses 1.00 → 0.23 under full haystack noise. Facts are in the store (Oracle = 1.00); they are buried at ranking time. Fix: scoring boost for preference-tagged facts in `retrieve.py` when query looks like a preference question. Targeted, cheap, no schema changes.
4. **End-to-end LongMemEval with stronger local model.** qwen2.5:1.5b is the floor. Temporal (0.26 Oracle) and multi-session (0.20 Oracle) accuracy are model-bound — retrieval is already at 0.94-0.96 on those types. Running the same pipeline with qwen2.5:7b or llama3:8b would isolate how much of the gap closes with a stronger model. The Llama 3.1-8B baseline (42-45% with no memory system) is the reference point — Akashik + a stronger model should clear it meaningfully. Low-effort experiment, high-value data point.
5. **Slot-aware entity extraction.** Only worth pursuing if ACMB becomes product-defining. Current entity extraction is a capitalized-token heuristic; slot-aware extraction (person/place/org/date) would lift recall and precision on structured turns. Defer until ACMB's strategic weight is clearer.
6. **Preference-turn retrieval.** LongMemEval `single-session-preference` = 0.23 is the visible weak cell. Soft-phrased language ("I usually", "lately", "these days") sits below the FTS floor. Candidates: (a) preference-slot extractor that promotes such turns on ingest, (b) widen semantic fallback trigger to include soft-phrasing lexical markers. Both are cheap experiments — run both, pick the winner.
7. **Expression engine — repair or retire.** LongMemEval reports 0/500 firings. `--use-expression` is off by default and inert when on. Either identify the query shape it *should* hit and fix triggering, or delete the layer and flatten the stack. Keeping dead code in the retrieval path is an ongoing tax.
8. **LongMemEval rerun — done (v0.25.9, 2026-04-21).** 470 instances, blind, post-audit. Session Recall @10 = 0.79. Per-type table in §2. Integrate into README only after #4 ships or is explicitly deferred, so the preference weak spot has context.

---

## 7. What we don't do

Durable "do not relitigate" list. Decisions taken; treat as settled.

- **No LLM in the ingest hot path.** The deterministic ingest is the product. Breaking this for one subset of turns (e.g. contradiction detection) is an architectural change, not a feature addition — requires explicit re-decision in §6.
- **No embeddings in the retrieval hot path.** Semantic fallback is opt-in, fires only on low-confidence FTS results, and is bounded. Vector search is not the primary mechanism.
- **No oracle fields consumed by adapters.** Adapters read what a real runtime reads — raw turn content and actor/turn identifiers. Ground-truth signals are for evaluators only.
- **No public API changes that expose internal row IDs.** UUIDs only in the public surface. `fts_rowid` is an implementation detail.
- **No consolidation of benchmarks into one "combined score."** ACMB measures agent memory. CUAD measures structured-document retrieval. LongMemEval measures long-context recall. They test different properties; collapsing them hides the signal.
- **No external claims before blind reruns.** Pre-audit numbers are not referenced in any external document. README tables are updated only with blind numbers.
- **No relitigation of the hierarchy.** `corpus → document → section → fact` is fixed. Alternative shapes are out of scope for v0.x.
