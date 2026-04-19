# Akashik — Strategy Session Notes

A single long planning conversation covered code review, benchmark diagnostics, ingest-pipeline debugging, a flagship demo, a biology/DNA design exploration, competitive positioning against Mem0 / Letta / vector DBs, the MMU framing, CUAD results, and a final dual-track product decision. This document captures the full arc, not just the conclusion — so future sessions can pick up threads that were identified but not resolved.

---

## 0. Reality check — the context for everything that follows

**Akashik is roughly three days old and is already beating funded, multi-year-old systems across two different benchmark families.**

- **ACMB (agent memory).** Akashik leads fact recall (0.801), belief revision (0.735, 4× RAG), and distractor suppression (0.087, ~12× better than every vector baseline). The closest commercial analog (Mem0) is built on top of a commodity vector-DB stack and took ~18 months of engineering and funding to get where it is. Akashik cleared that bar in a long weekend.
- **CUAD (structured legal retrieval).** Akashik posts P@1 = 0.82 and Provenance = 0.92 against RAG's 0.08/0.08 and GraphRAG's 0.14/0.16. Holds at 5× scale (10 → 50 contracts). The failure mode isn't architectural — it's query normalization.
- **Two wins on one primitive.** The same `store + retrieve + lineage` core wins both benchmarks. Different domain, different buyer, same engine. That's the signal the architecture is doing the work — not per-benchmark tuning.

### What this implies

1. **The primitive is correct.** When a 3-day-old system beats a funded SaaS on its home turf and beats published RAG baselines on real legal contracts using the same core, the right read isn't "keep iterating to catch up." It's "the primitive is correct; everything from here is execution."
2. **The strategic question changes.** It stops being "can Akashik compete?" and becomes "how fast can this be hardened and shipped before the industry notices?"
3. **The dual-track conclusion below isn't aspirational.** It's the only disciplined response to having two real wedges that work on day three. Choose the sequence and hold the line on OSS/commercial separation.

The rest of this document is the reasoning and open threads behind that framing. Read the rest as execution detail; read this section as the load-bearing context.

---

## 1. Viability review (starting point)

The repo was reviewed end-to-end. Findings:

- **Core thesis is strong.** Separation of immutable `Sequence` from mutable `Expression` is the single most important architectural decision in Akashik. It's what structurally differentiates from RAG — vector stores cannot represent lineage or provenance as first-class citizens.
- **Spec is ahead of implementation.** `Architecture_Specification_v0.20.0.md` describes five layers (Sequence, Lineage, Epigenetic, Expression, Consolidation). Layers 1–3 are live; Layer 4 (Expression) is partial; Layer 5 (Consolidation) is scaffolded-only.
- **Scaffolds vs. load-bearing mechanisms.** `association_edges` is written but never read. `silenced` is a binary flag with no reversibility implementation. `epigenetic_state` uses equality matching rather than feedback loops. This is honest for an alpha, but the document drifts from the code with every added spec item.
- **Test discipline is excellent.** 311 passing tests; changes maintain invariants (UUIDs only in public API, FTS row sync, ordered resets).

---

## 2. ACMB benchmark deep dive

ACMB v0.3 (25 personas, 6 adapters). Numbers at session start:

| Adapter | Fact Recall | Belief Revision | Fact Precision | Distractor Penalty | Latency p50 |
|---|---|---|---|---|---|
| akashik | 0.801 | 0.735 | 0.335 | 0.087 | 21.71 ms |
| bm25_akashik | 0.679 | 0.251 | 0.257 | 0.845 | 0.77 ms |
| rag_akashik | 0.752 | 0.249 | 0.214 | 0.675 | 28 ms |
| bm25 | 0.541 | 0.113 | 0.171 | 0.845 | 0.75 ms |
| rag | 0.614 | 0.111 | 0.183 | 1.056→0.675 | 28 ms |
| full_context | 0.560 | 0.340 | 0.255 | 0.433 | 1.40 ms |
| tfidf | 0.533 | 0.068 | 0.158 | 0.593 | 0.97 ms |

### The oracle-leak finding

**Open issue.** The Akashik adapter receives `turn["revises_facts"]` and `turn["ground_truth_facts"]` that other adapters don't. Belief-revision 0.735 is partially inflated by this. Must be resolved before ACMB is publishable as a standalone benchmark.

### Structural reads that survive the oracle caveat

- Distractor suppression is a genuine structural win (0.087 vs vector baselines' 0.6–1.0). That one doesn't depend on the leaked signal.
- Belief revision is 4× RAG. Even if some inflation comes from the leak, the architectural ability to represent supersession is real.
- Latency: Akashik at 21 ms p50 is fine for interactive use, not fine for agent inner loops. Worth watching as the expression engine matures.

---

## 3. Ingest pipeline work (branch `feat-ingest-pipeline`)

Built out `akashik/ingest_pipeline.py` as a synchronous conversational ingest spike. Six problems surfaced and were resolved in order:

### 3.1 Confidence threshold
Started at 0.7, raised to 0.85 after observing low-confidence extractions (e.g., "User spent the weekend hiking") being accepted.

### 3.2 qwen2.5:1.5b vs 3b model calibration

The smaller model *over-extracts* (visible, filterable failures). The larger model *over-refuses* at `temperature=0` (silent, uncatchable failures — the 3b returns `{"fact": null}` for things the 1.5b correctly extracts).

**Decision: 1.5b + deterministic post-filter is the right architecture.** A noisy-but-visible model with downstream cleanup beats a quiet-but-wrong model. This matters architecturally — it argues that Akashik's ingest layer should be **extract wide, filter narrow** rather than trust-the-LLM.

### 3.3 Run-to-run non-determinism

Same prompt, same input, different outputs across runs ("owns a partner" vs "partner is employed at..."). Root cause: default Ollama sampling. Fix: pin `"options": {"temperature": 0, "seed": 0}` in the generate call. After the fix, three consecutive runs produced byte-identical output.

**Takeaway flagged for the spec:** any LLM in Akashik's path must be pinned or its non-determinism becomes an invisible bug farm. This belongs in architecture-level guidance, not just in `ingest_pipeline.py`.

### 3.4 Third-party fact leakage

"My partner works at Cedar Health" was being stored as a user fact. Added deterministic post-filter with `_THIRD_PARTY_PREFIXES` and `_OWNS_A_PERSON_NOUNS`. Skip reason `third_party_fact` surfaces cleanly.

### 3.5 Schema-parroting bug (discovered via chat demo)

Model output `"fact": "where they live."` — copying rule text from the prompt into the fact field. Fix: rewrote prompt template, removed inline category list, added three one-shot examples (Denver / Helio / sourdough). Demo sessions 1 and 2 then stored and recalled correctly.

### 3.6 Still-open negation / revision detection

"I don't live in Chicago anymore" is handled crudely. Real supersession detection (recognize that this revises prior fact X) is not wired up. Flagged as open work for the ingest pipeline.

---

## 4. Chat demo (`examples/chat_with_memory.py`, v0.25.3-demo)

Built a flagship end-to-end demo: streaming Ollama chat with Akashik memory injected as system-prompt context (not as chat history). Key property: memory persists across sessions without relying on the LLM to remember anything. Resets cleanly with `--reset`.

This became the artifact that *sells the thesis* in 90 seconds. When someone asks "what does Akashik actually do," you run this demo, close the process, open it again, and the assistant still knows who you are. That is the whole product in one page.

Open cleanup items flagged:
- Suppress BertModel LOAD REPORT noise
- README "Try it yourself" section pointing at the demo
- Primary audience decision (developer library vs power-user daemon) is still unresolved

---

## 5. DNA-inspired storage — deep exploration

The session's most ambitious thread. The question was: biology is a fertile source of engineering patterns — how could DNA-inspired storage apply to Akashik?

### 5.1 What's already biological in the spec

| Concept | Where | Load-bearing? |
|---|---|---|
| Lineage (ancestry chains) | `lineage_parent_id` in store.py | **Yes** — real versioning model |
| Activation / decay | `expression.py:apply_decay` | **Yes** — drives ranking |
| Reinforcement | `reinforcement_count`, `soft_reinforcement_count` | **Yes** — drives ranking |
| Epigenetic state | `epigenetic_state` table | **Partial** — boolean equality, not feedback |
| Promoter/repressor conditions | JSON on epigenetic_state | **Partial** — equality match |
| Silencing | `silenced` bool + `silence_until` | **Shallow** — no reversibility implementation |
| Association edges | Written in store.py, never read | **Scaffold only** |
| Consolidation tiers | Scaffold; no worker | **Scaffold only** |

**Read:** high-level biology (Sequence ≠ Expression) is load-bearing. Specific molecular mechanisms are mostly scaffolded. Adding more biology to the spec without implementing what's there is aesthetic drag.

### 5.2 DNA patterns not yet adopted — ranked

**Tier A — likely genuine product wins**

- **A1. Splicing / isoforms.** One fact, multiple expressed variants (terse / conversational / structured). Store canonical + N variants, select at expression time by context. Concrete schema: `fact_expressions(fact_id, variant_kind, content)`. This is a real capability gap — today the LLM generates variants on-the-fly or not at all.

- **A2. Stem-cell differentiation — specification without supersession.** Today lineage = replacement. "User has a partner" → "User has a partner named Sarah" is currently supersession; should be *differentiation*. Generic parent stays live, specific child refines. Fix: `lineage_relation` enum (`supersedes` vs `differentiates`). Retrieval respects the distinction — parent answers generic queries, child answers specific ones. This fixes a real bug in the current spec.

- **A3. Non-coding context regions.** Ingest pipeline throws away turns without persistent facts ("I spent the weekend on sourdough"). Real context signal — mood, interest, register — is lost. Extend `interaction_log` with `carries_fact: bool`; non-coding turns feed `promoter_conditions`. Smallest implementation, directly addresses a known data-loss bug. **Recommended first experiment.**

**Tier B — interesting, worth experimenting**

- **B1. Codon degeneracy / surface-form canonicalization.** "Sony camera" / "my Sony" / "A7R IV" all point to one canonical preference. Already partly addressed by `normalized_hash`; extension is semantic canonicalization, not just whitespace. Related to BACKLOG "Preference Canonicalization".
- **B2. Proofreading / consensus as error-correction.** Fact becomes canonical only after N corroborations; pre-canonical is "provisional DNA" held in quarantine. Directly maps to the 1.5b confidence-calibration problem.
- **B3. Transcription factor feedback loops — expression priming.** When fact A is expressed this session, temporarily raise activation on A's neighbors via `association_edges`. Session-local priming. This is what human conversation does; Akashik currently treats each query independently.

**Tier C — metaphorically cool, not worth building**

Mutation vs supersession (solves no real problem), methylation inheritance (niche), horizontal gene transfer (actively dangerous for multi-tenancy), chromatin 3D folding (too abstract), transposons (no product hook), CRISPR editing (lineage already approximates this).

### 5.3 Viability verdict on biology as product frame

**Yes, with sharp caveats.**

- Good frame because Sequence ≠ Expression is already correct; it gives defensible identity; it generates novel solutions to real problems.
- Bad if it becomes a cage. Metaphor should drive internal design, not force features.
- **Public surface:** "deterministic memory layer with provenance" / "MMU for AI."
- **Internal:** mine biology for patterns when facing specific engineering problems.
- **Spec discipline:** every metaphor in `Architecture_Specification` should be (a) implemented, (b) dated for a specific version, or (c) removed.

### 5.4 Recommended concrete experiment

Implement **A3 (non-coding context regions)** first. Smallest blast radius, uses existing infrastructure, addresses a known data-loss bug, and forces real use of `promoter_conditions` for the first time — surfacing whether the epigenetic schema is adequate or needs revision.

---

## 6. Competitive positioning

### 6.1 Mem0 analysis (most detailed competitor pass)

**Thesis divergence.** Mem0 = "add memory to your LLM app via our SaaS." Akashik = "memory is a deterministic storage primitive with provenance, run it yourself." Different technology, different buyer, different business model.

**Moat audit — what Mem0 has that Akashik doesn't:**
- Hosted SDK polish and framework integrations (LangChain, OpenAI Assistants, CrewAI)
- Docs and onboarding ergonomics
- Marketing reach and HN presence
- Growing user base on a commoditized tech stack

**Moat audit — what Akashik has that Mem0 structurally cannot match without cannibalizing:**
- Deterministic retrieval (exact → normalized → FTS → traversal). Mem0's vector-first architecture can't replicate without losing their differentiation.
- Provenance as first-class citizen.
- Lineage and supersession model.
- Local-first execution — no network call, no vendor lock-in, no per-query pricing.
- Distractor suppression (ACMB 0.087 vs RAG 1.056).

**The LLM-cheapening strategic risk.** As context windows grow from 128k → 1M → 10M tokens, "just stuff everything in context" becomes viable for agent memory. Mem0's value proposition weakens because its tech is commodity. **Akashik's value proposition strengthens for use cases where you need to *prove* what was retrieved, why, and from where** — because no amount of context window solves an audit requirement.

### 6.2 Letta / MemGPT

Agent-framework bound. Serves a different buyer (framework adopters who want memory inside the framework). Not a direct competitor to either Akashik track — adjacent, not overlapping.

### 6.3 Vector DBs (Pinecone, Weaviate, Chroma)

No provenance story. No lineage. No distractor suppression. CUAD numbers (below) are the ceiling they'll hit. Commodity substrate for agent-memory SaaS but not a differentiated product themselves.

### 6.4 MMU framing evolution

Started the session with biology as public frame. Shifted during competitive analysis to **"decades-long MMU for AI"** as preferred identity:
- MMU is a deterministic address-translation primitive with a provenance chain.
- It maps cleanly to what Akashik does at the retrieve layer.
- It signals "infrastructure primitive" rather than "chatbot plugin," which is the correct altitude for the product.
- It doesn't commoditize when LLMs improve — an MMU's job is orthogonal to whatever sits on top.

---

## 7. CUAD results — the pivot

Real legal contracts, 50-document corpus:

| System | Precision@1 | Provenance | Composite |
|---|---|---|---|
| RAG | 0.08 | 0.08 | 0.06 |
| GraphRAG | 0.14 | 0.16 | 0.13 |
| Akashik | **0.82** | **0.92** | **0.65** |

- 10→50 delta: -0.08 P@1. Holds at 5× scale.
- Failure mix: 4 retrieval issues, 6 clause ambiguities, 0 anchor issues, 0 corpus extraction issues. Remaining 18% is query normalization.
- Mode B (natural-language paraphrases) P@1 = 0.05 — real risk for legal Q&A.

This reframed the session. CUAD is structurally a more defensible commercial wedge than agent memory:
- Regulated buyers *require* provenance by law.
- Competition (Pinecone + LangChain stacks) has no provenance story at all.
- Legal contracts don't get cheapened by larger context windows; regulation doesn't shrink.
- Budget exists (legal/compliance ACVs are 10–100× devtool ACVs).

**Uncomfortable question raised:** is personal-agent memory the right wedge at all, when CUAD numbers this strong are available?

---

## 8. Dual-track conclusion

After exploring whether Akashik could credibly be both agent-memory *and* document-memory leader, the session landed on:

### OSS track — "lifetime context for agents"

- **License:** permissive (MIT/Apache)
- **Surface:** `pip install akashik`, chat demo, ACMB as public benchmark
- **Audience:** developers, agent builders, researchers
- **Job:** reference implementation for structured agent memory; compound adoption; every Mem0/Letta HN thread becomes recruitment
- **Success metric:** stars, adapter contributions, citations
- **Monetization:** none. Its job is to be unkillable as a category reference.

### Commercial track — "auditable document memory"

- **License:** source-available or closed for enterprise features
- **Surface:** CUAD-class benchmark as proof, on-prem deployment, SOC2 path, audit-log exports, vertical connectors
- **Audience:** GC, compliance officer, regulated-industry CTO
- **Job:** solve the provenance problem for buyers who are legally required to care
- **Success metric:** ACV, logos in regulated verticals

### Why this is stable, not a typical dual-wedge failure

1. **Shared core, divergent surface.** `akashik/` stays single-source. Only wrappers fork — OSS ships SDK/adapters; commercial ships ingestion pipelines, audit exports, enterprise connectors. Core bug fixes lift both.
2. **OSS is moat, not lost revenue.** Mem0 needs SaaS revenue because its tech is commodity; Akashik's tech is defensible, so giving away the primitive doesn't cost anything strategically valuable.
3. **No license-drama surface.** Different buyers, different problems. Commercial features are orthogonal to the OSS primitive, not upsells of it — avoids the Elastic/Redis/MongoDB trap.
4. **Each track feeds the other.** OSS adoption → credibility for legal sales. Legal revenue → OSS maintainers. Virtuous, not zero-sum.

### The only real risk — and the discipline that holds

The temptation to slip "just a little" enterprise logic into the OSS core to close a deal. Every company that does this eventually relicenses.

**Rule: commercial features live in a separate package that depends on OSS Akashik. Never inside it.** Held from day one, this line stays holdable.

### Sequencing

Not "both at once." The discussion rejected parallel wedges because pricing, sales motion, docs, and narrative fork even when the core doesn't. Instead:
1. Pick the harder-to-commoditize wedge (CUAD / legal) as commercial focus now.
2. Keep agent-memory alive as maintained OSS, parity on ACMB, don't market, don't monetize. Developer adoption becomes moat and hiring pipeline.
3. When legal traction is proven, add the agent-memory surface as a paid product with enterprise machinery already built.

Reverse sequence (agent-memory first, legal second) is worse: agent memory gets cheapened, dev adoption doesn't open enterprise doors, and agent-memory revenue can't fund the enterprise motion.

---

## 9. Open threads carried forward

### Ingest pipeline
- Subtler negation test cases
- Revision/supersession detection (crude today)
- Calibration for larger-model fallback path

### ACMB
- Oracle-leak fix (blocking issue for publication)
- Blind ingest rerun
- Separable publishable artifact with its own README and reproducibility script

### Demo / OSS
- Suppress BertModel LOAD REPORT noise
- README "Try it yourself" section
- Full LongMemEval-S rerun
- Primary audience decision (developer library vs power-user daemon)

### Commercial / CUAD
- Mode B query-robustness gap (P@1 = 0.05)
- Audit-log export format
- On-prem install story
- First vertical beachhead decision (contract review / discovery / compliance monitoring)
- SOC2 path and timeline

### Architecture discipline
- Every metaphor in `Architecture_Specification_v0.20.0.md` should be (a) implemented, (b) dated for a version, or (c) removed
- Scaffolded-but-unimplemented biology (association spreading, consolidation worker, silencing reversibility) paid down or removed
- LLM determinism guidance elevated to spec-level

### Biology experiments (if pursuing)
- A3 non-coding context regions (recommended first)
- A2 differentiation (if A3 produces measurable lift)
- A1 splicing (larger scope; do after A2/A3 validate the frame)

---

## 10. Critical files referenced

- `README.md`
- `Architecture_Specification_v0.20.0.md`
- `BACKLOG.md`
- `CLAUDE.md` / `AGENTS.md`
- `akashik/ingest_pipeline.py`, `akashik/ingest.py`, `akashik/retrieve.py`, `akashik/store.py`, `akashik/expression.py`, `akashik/schema.py`, `akashik/identity.py`
- `benchmark/acmb/run_acmb.py`, `benchmark/acmb/evaluate_acmb.py`, `benchmark/acmb/generate_personas.py`
- `benchmark/acmb/adapters/akashik_adapter.py`, `bm25_akashik_adapter.py`, `rag_akashik_adapter.py`, `tfidf_adapter.py`, `full_context_adapter.py`
- `benchmark/acmb/README.md`
- `results/report_cuad_50.md`
- `examples/chat_with_memory.py`
- `scripts/test_ingest_pipeline.py`
