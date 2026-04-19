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
- **A working end-to-end demo.** `examples/chat_with_memory.py` runs against the real store with the real retrieval stack. Not a scripted replay.

---

## 3. What's not yet proven

- **Belief revision on implied dialogue revisions.** ACMB blind 0.281 vs BM25 ~0.11. Akashik leads, but the lead is narrow because the rule-based contradiction detector (`akashik/contradiction.py`) only covers 8 regex patterns over declarative statements like *"I live in X."* ACMB's revision turns are often descriptive (*"Actually I moved last week"*), which the detector misses. Extending the pattern set is whack-a-mole; the real fix is semantic contradiction detection. Architectural decision pending — see §6.
- **CUAD P@1 on natural legal queries.** Blind P@1: Akashik 0.06 vs GraphRAG 0.14 vs RAG 0.08. The CUAD query set is keyword-only (*"governed laws california"*) — the queries contain neither the party name nor the document identifier, so document scoping is unrecoverable from query text alone. Akashik's entity-filter mechanism can't fire without entity mentions. On a query set written the way a lawyer or paralegal actually writes ("in the Aduro consulting agreement, what law governs?"), we expect the structural lead in context efficiency to translate into a P@1 lead. That rewrite is open work.
- **Scale beyond 50 documents / 25 personas.** Current benchmarks cap at these sizes. No evidence yet of degradation or robustness at 500+ documents or 100+ personas.
- **Consolidation (Layer 5).** Scaffolded only. The spec describes a background semantic/procedural compression loop; the code does not yet implement it.

---

## 4. Benchmark results

### ACMB v0.3 — blind, 25 personas, v0.25.6-ingest

| Metric | Akashik | BM25 | Notes |
|---|---|---|---|
| Fact Recall @k | **0.648** | 0.541 | Akashik leads |
| Belief Revision | **0.281** | ~0.11 | Narrow lead; rule-based detector limits ceiling |
| Fact Precision | **0.219** | 0.171 | Slight lead |
| Temporal Correctness | **0.598** | 0.541 | Structural — no baseline equivalent |
| Distractor Penalty | 0.554 | 0.588 | Mid-pack; lower is better |
| Latency p50 | 3.74ms | 0.73ms | Faster than semantic baselines, slower than pure lexical |

Akashik-hybrid adapters (`bm25_akashik`, `rag_akashik`) used the same adapter path that leaked oracle fields pre-audit. They need blind reruns before being included in the honest table.

### CUAD — blind, 50 contracts, 4-way

| System | P@1 | Context Efficiency | Composite |
|---|---|---|---|
| RAG | 0.08 | 0.029 | 0.065 |
| GraphRAG | 0.14 | 0.109 | 0.135 |
| **Akashik** | 0.06 | **0.230** | 0.111 |
| RAG-Embedding | 0.06 | 0.029 | 0.063 |

**Caveat — query set design.** CUAD queries are keyword-only stems with no entity mentions. This is not how legal professionals actually query their contract stack, and it disproportionately penalizes systems that depend on entity resolution for scoping. Akashik's context-efficiency lead (0.230 vs 0.029–0.109) is structural and survives blind — retrieved spans are tighter regardless of P@1 ranking. P@1 leadership is open work gated on a natural-query rewrite (§6).

**Caveat — inverse oracle in query text.** Several CUAD queries embed the answer as a soft signal (e.g. *"governed laws california"* contains the governing-law jurisdiction). Any retrieval system that does reasonable token matching will get partial lift from this — GraphRAG's 0.14 P@1 is not fully clean either, just less penalized by it than a system built around entity-filter scoping. The natural-query rewrite in §6 fixes this for everyone.

Do not update the README CUAD table until natural queries land.

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
3. **Slot-aware entity extraction.** Only worth pursuing if ACMB becomes product-defining. Current entity extraction is a capitalized-token heuristic; slot-aware extraction (person/place/org/date) would lift recall and precision on structured turns. Defer until ACMB's strategic weight is clearer.
4. **Expression engine audit.** Layer 4 is partial. `--use-expression` exists but is off by default. Need a design review on what the expression engine actually does that scoped reranking doesn't, and whether it's worth keeping as a separable layer.
5. **LongMemEval full rerun.** Post-audit blind numbers not yet collected. Schedule after #1 and #2.

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
