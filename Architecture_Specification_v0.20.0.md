# Addressed Cognition
## Architecture Specification v0.20.0
### Akashik Memory System

Authored by Claude, GPT, Codex | Reviewed by Grok, Gemini | Mandated by Marc | April 2026

## Purpose

Addressed Cognition is the long-horizon memory architecture for Akashik. It is designed to solve a problem that no existing AI memory system has solved cleanly: maintain a complete, provenance-preserving record of a human's cognitive history across years or decades, and express only the right subset of that history into an LLM's context window in under 100ms, on consumer hardware, with no cloud dependency, and no hallucinated or corrupted memory.

This document is the north star for all Akashik development from `v0.20.0` forward. It supersedes `AGENTS.md` as the architectural reference.

## The Problem

Current AI memory systems fail in one of four ways:

1. Context windows are too expensive and flat. Stuffing conversation history into a prompt does not scale past weeks, let alone decades. Attention is `O(n²)`.
2. Vector databases treat all facts as equidistant points in embedding space. There is no time, no causality, no decay, no reinforcement. Everything is equally retrievable, which means nothing is reliably retrievable.
3. Summarization loses detail and provenance. A summary of a decade of conversation is not a memory system. It is a lossy compression with no reconstruction path.
4. Fine-tuning mixes truth into model weights. Correction becomes retraining. Hallucination and ground truth are indistinguishable.

The real problem is not "find similar text." It is: what was true then, what is true now, what changed, what did the user commit to, what should be injected into this specific conversation moment, and how do you answer all of that in under 100ms regardless of how large the corpus has grown?

That is a versioned state reconstruction problem, not a retrieval problem.

## Core Thesis

Memory is not retrieval. Memory is activation.

The system enforces one hard separation:

**Sequence (immutable truth) ≠ Expression (contextual relevance)**

Facts are stored permanently and immutably. Expression state is maintained separately and changes continuously. Retrieval is replaced by expression: given the current conversation context, which facts are active right now? Those are transcribed into the context packet. Everything else stays dark.

## The Five Layers

### Layer 1 — Sequence: Immutable Ground Truth

Every fact is an immutable sequence with a cryptographic address. Content, hash, provenance, lineage pointer, and timestamps are written once and never modified. New knowledge creates a new sequence node. Nothing overwrites the old one.

This is the system of record. Nothing in any other layer may alter it.

Each sequence node contains:

- `id` — UUID, public, permanent
- `content` — raw fact text
- `content_hash` — SHA-256 of content
- `normalized_hash` — hash of lowercased, whitespace-collapsed content
- `lineage_parent_id` — pointer to the fact this supersedes, if any
- `parent_id` — structural parent in the corpus hierarchy
- `level` — `corpus / document / section / fact`
- `section_heading` — optional
- `provenance` — source, session, speaker, turn reference
- `ingested_at` — timestamp
- `source_metadata` — arbitrary JSON for domain-specific context

The sequence layer is append-only. No updates. No deletes. Ever.

### Layer 2 — Lineage: Canonical Evolution Model

Facts evolve. Lineage is the canonical model for that evolution: facts form ancestry chains where new knowledge creates a new node pointing to what it supersedes, and current state is always the active leaf.

```text
"User lives in Chicago" (2021)
        ↓
"User lives in New York" (2023)
        ↓
"User lives in Boston" (2025)  ← current leaf
```

Rules:

- New knowledge creates a new node with `lineage_parent_id` pointing to what it supersedes
- Prior nodes remain intact and permanently reconstructible
- Current state is the active leaf, the node with no lineage child
- Historical state is reconstructed by traversing the chain backward
- Contradiction closure is lineage branching: two competing facts point to the same parent; the expression layer determines which branch is active
- Lineage chains are acyclic

On validity fields: Existing `valid_from` and `valid_until` fields are not removed. They remain as cached temporal indexes for efficient time-range queries and migration sanity. Lineage is the canonical evolution model; validity fields are derived temporal indexes. Where they conflict, lineage is authoritative.

Migration path: existing facts become leaf nodes with `lineage_parent_id = NULL`. Existing validity windows are preserved as-is and updated going forward as lineage chains are written.

### Layer 3 — Epigenetic: Mutable Expression State

Each sequence node carries a separate, mutable epigenetic record. This layer controls whether and when a sequence is expressed into context. It lives in a separate table, keyed to the sequence id.

The epigenetic record contains:

| Field | Type | Description |
|---|---|---|
| `activation_weight` | float | Current relevance score; rises on access and reinforcement, decays over time |
| `consolidation_tier` | enum | `episodic / semantic / procedural` |
| `promoter_conditions` | JSON | Contextual triggers that activate this fact; see v0.20.0 schema below |
| `repressor_conditions` | JSON | Conditions that silence this fact; see v0.20.0 schema below |
| `decay_rate` | float | Rate of activation weight decay per day without access |
| `reinforcement_count` | int | Explicit user confirmations of this fact |
| `soft_reinforcement_count` | int | Implicit reinforcements; assistant restatements not corrected by users |
| `silenced` | bool | Hard suppression flag |
| `silence_until` | timestamp | Temporary suppression with automatic expiry |
| `last_expressed_at` | timestamp | Last time this fact was included in a context packet |
| `association_edges` | JSON | Weighted edges to co-retrieved facts |

The sequence is truth. The epigenetic layer is access behavior.

Consolidation tiers:

- `episodic` — specific events with time and context. High specificity, time-bound, decays unless reinforced.
- `semantic` — abstracted stable facts derived from episodic patterns. Low decay, high retrieval priority for general context injection.
- `procedural` — behavioral patterns derived from repeated episodic evidence. Very low decay, injected in almost every context packet.

v0.20.0 promoter/repressor schema — constrained first version:

To avoid an unbounded policy language, v0.20.0 constrains promoter and repressor conditions to a fixed schema. Free-form extensions are deferred to v0.21.0+.

```json
{
  "entities": ["car", "subaru"],
  "topics": ["maintenance", "vehicles"],
  "thread": "personal",
  "domain": "automotive",
  "silence_until": null
}
```

Promoters activate a fact when any listed entity, topic, thread, or domain is present in the current context. Repressors silence a fact under matching conditions. `silence_until` supports temporary suppression with automatic expiry. This schema is intentionally small; expand only after `v0.20.0` is validated.

### Layer 4 — Expression: Context-Driven Selective Readout

Retrieval is replaced by expression as the primary memory access mechanism.

When a user message arrives, the expression engine does not scan the full corpus. It operates over a bounded candidate pool, constructed from entity, topic, thread, and domain indexes built at ingest time. The candidate pool is the set of facts associated with entities and topics present in the current context, typically hundreds of facts, not hundreds of thousands.

Expression process:

1. Parse current context — extract entities, topics, domain, thread, intent
2. Resolve candidate pool from entity/topic/thread indexes — bounded set, not full corpus
3. Evaluate promoter conditions across candidate epigenetic records
4. Check repressor conditions — silence matching facts
5. Rank by activation weight — recently reinforced, frequently accessed facts rank higher
6. Traverse association edges — spreading activation surfaces related facts that co-occur with top-ranked facts
7. Select top-N active facts — target `20–50`, hard cap independent of corpus size
8. Build bounded context packet with citations

The 100ms design target is achievable because expression never touches the full corpus; it touches the bounded candidate pool derived from the current context's entity and topic scope.

The existing retrieval stack is the cold path fallback, firing only when expression returns insufficient results:

1. Exact `content_hash`
2. Exact `normalized_hash`
3. FTS5 keyword search
4. Local embedding similarity (`multi-qa-mpnet-base-dot-v1`, threshold `0.45`)
5. Semantic fallback (fail-open)

Search is fallback infrastructure, not the primary mechanism.

Context packet structure:

```json
{
  "active_facts": [],
  "recent_deltas": [],
  "open_commitments": [],
  "associations": [],
  "citations": []
}
```

Packet size is bounded and independent of corpus size.

### Layer 5 — Consolidation: Background Biological-Clock Process

Episodic facts accumulate continuously. Without consolidation, the candidate pool grows with corpus size even in the expression model. Consolidation solves this by compressing episodic history into higher-level sequence nodes that express instantly and keep the candidate pool compact.

Process:

The consolidation worker runs during low-activity periods. It:

1. Scans episodic facts with high reinforcement count and recurring patterns
2. Derives semantic facts from consistent episodic evidence and writes new sequence nodes at semantic tier
3. Derives procedural facts from repeated behavioral patterns and writes new sequence nodes at procedural tier
4. Writes derived facts with `lineage_parent_id` pointing to source episodic nodes
5. Checkpoints old episodic chains by writing a summary sequence node spanning a span of episodic history, with pointers to all source nodes
6. Updates association edges from co-retrieval patterns in the session log
7. Promotes derived facts in the epigenetic layer to semantic or procedural consolidation tier

Consolidation is additive. It never rewrites source sequences. Originals remain permanently reconstructible. The identity frame, the consolidated procedural and semantic layer, expresses in milliseconds. The full episodic history is dark by default, reconstructible on demand.

## Fact Structure — Complete Schema

### Sequence table (immutable)

```sql
CREATE TABLE memory_units (
    id                  TEXT PRIMARY KEY,
    content             TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    normalized_hash     TEXT NOT NULL,
    lineage_parent_id   TEXT REFERENCES memory_units(id),
    parent_id           TEXT REFERENCES memory_units(id),
    level               TEXT NOT NULL,
    section_heading     TEXT,
    provenance          TEXT,
    valid_from          TEXT,
    valid_until         TEXT,
    ingested_at         TEXT NOT NULL,
    source_metadata     TEXT
);
```

### Epigenetic table (mutable)

```sql
CREATE TABLE epigenetic_state (
    fact_id                  TEXT PRIMARY KEY REFERENCES memory_units(id),
    activation_weight        REAL DEFAULT 1.0,
    consolidation_tier       TEXT DEFAULT 'episodic',
    promoter_conditions      TEXT,
    repressor_conditions     TEXT,
    decay_rate               REAL DEFAULT 0.01,
    reinforcement_count      INTEGER DEFAULT 0,
    soft_reinforcement_count INTEGER DEFAULT 0,
    silenced                 INTEGER DEFAULT 0,
    silence_until            TEXT,
    last_expressed_at        TEXT,
    association_edges        TEXT
);
```

### Interaction log (assistant turns — provenance only, never truth)

```sql
CREATE TABLE interaction_log (
    id                  TEXT PRIMARY KEY,
    turn_id             TEXT NOT NULL,
    session_id          TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    actor               TEXT NOT NULL,
    raw_content         TEXT NOT NULL,
    retrieved_fact_ids  TEXT,
    context_packet_hash TEXT,
    user_correction     INTEGER,
    user_confirmed      INTEGER
);
```

## Interaction Model

Human turns are ingested as episodic sequence facts with full provenance. Facts, preferences, corrections, intents, and commitments are extracted and written to the sequence layer.

Assistant turns are logged to the interaction log as provenance records: what was retrieved, what context was used, what was said. Assistant output is never written to the sequence layer. The LLM is not the system of record.

Explicit reinforcement occurs when the user directly confirms a fact. This increments `reinforcement_count` and increases `activation_weight`. This is the strong signal.

Soft reinforcement occurs when the assistant restates a fact and the user does not correct it. Silence is not confirmation. This increments `soft_reinforcement_count` only, and increases `activation_weight` by a smaller amount than explicit confirmation. Soft reinforcement accumulates toward explicit reinforcement thresholds but never substitutes for them in high-confidence contexts.

User corrections trigger lineage branching on the corrected fact. The correction creates a new sequence node with `lineage_parent_id` pointing to the incorrect fact, and the epigenetic layer silences the prior leaf.

## Invariants

- The sequence layer is append-only and immutable — no updates, no deletes, ever
- Lineage chains are acyclic — leaves are current truth, ancestors are reconstructible history
- Lineage is the canonical evolution model — validity fields are cached temporal indexes only
- The epigenetic layer never modifies sequence content, hashes, or provenance
- Expression operates over a bounded candidate pool, not the full corpus
- Expression never fires on silenced or fully decayed facts
- Consolidation is additive — derived facts point to source sequences, originals are never removed
- Suppression is reversible — silenced facts can be reactivated
- The LLM is never in the write path for sequence or epigenetic layers
- Provenance is preserved through all layers and all tiers
- Context packet size is bounded and independent of corpus size
- Historical state is always reconstructible by lineage traversal

## Design Targets

These are design targets for the expression-first architecture, not measured guarantees under the new system. They will be validated as implementation progresses.

| Operation | Target |
|---|---|
| Sequence write (per-turn ingest) | `< 10ms` |
| Expression over candidate pool | `< 50ms` |
| Cold path retrieval fallback | `< 100ms` (currently measured at `87ms` on M1 Air 8GB) |
| Full intercept flow (expression + cold path if needed) | `< 100ms` |
| Consolidation worker (background) | non-blocking, runs during idle periods |

## Known Limitations

This architecture does not solve everything. Known failure modes:

- Noisy ingest — reliable fact extraction from ambiguous or messy natural language is an unsolved problem. Rule-based extraction has hard ceilings; LLM-assisted extraction violates the sequence layer invariant if not sandboxed correctly
- Entity resolution drift — names and references drift across years. "My car" in 2021 and "the Subaru" in 2024 may or may not refer to the same entity. Resolution errors pollute lineage chains
- Multi-hop reasoning — complex reasoning over multiple retrieved facts remains delegated to the Executor and LLM
- Promoter/repressor condition design — specifying correct conditions for each fact domain requires either manual curation or a reliable automated process. The v0.20.0 constrained schema mitigates this but does not solve it
- Consolidation correctness — the consolidation worker derives higher-level facts from episodic patterns. Incorrect derivations pollute the semantic layer. Consolidation must be conservative, auditable, and reversible
- Soft reinforcement signal quality — user silence is a weak signal. Over-weighting soft reinforcement risks amplifying incorrect facts that the user simply did not bother to correct

This system fails in ways you can inspect. Every failure has a traceable cause in the sequence or epigenetic layer. That is a deliberate design property.

## What This Preserves From Current Akashik

| Current | v0.20.0 |
|---|---|
| `corpus/document/section/fact` hierarchy | unchanged, sequence layer |
| UUID public IDs | unchanged |
| `content_hash / normalized_hash` | unchanged |
| `valid_from / valid_until` | preserved as cached temporal indexes; lineage is canonical |
| `confirmation_count / last_confirmed_at` | become `reinforcement_count / last_expressed_at` in epigenetic table |
| FTS5 retrieval stack | unchanged, cold path fallback |
| Navigator tiebreaker | unchanged, operates over expressed facts |
| Executor | unchanged, operates over context packet |
| Local judge | unchanged, evaluation only |
| All existing tests | valid against sequence layer |

## Migration Path From Current Codebase

Each step is independently testable and reversible. No big-bang migration.

1. Add `lineage_parent_id` to `memory_units` — nullable, existing rows `NULL`
2. Create `epigenetic_state` table — populate from existing `confirmation_count`, `last_confirmed_at`
3. Create `interaction_log` table
4. Add no-op expression engine — returns empty, falls through to existing retrieval stack immediately
5. Add activation weight update on every retrieval hit — soft reinforcement from access
6. Add association edge writes to session log
7. Existing retrieval stack unchanged throughout

## Version Milestone Targets

- `v0.20.0-alpha` — `lineage_parent_id` added. `epigenetic_state` table created. `interaction_log` table created. No-op expression engine with fallthrough to current retrieval stack. Soft activation weight updates on retrieval. Association edge writes. All existing tests pass.
- `v0.20.0` — Expression engine v1: activation weight ranking over candidate pool from entity/topic indexes. Per-turn incremental ingest path. Constrained promoter/repressor schema (`entity / topic / thread / domain / silence_until`).
- `v0.21.0` — Consolidation worker v1. Episodic → semantic derivation. Checkpoint writes. Association graph queries in expression engine.
- `v0.22.0` — Full context-driven expression. ACMB conversational benchmark v1. Promoter/repressor condition expansion.
- `v0.23.0` — Consolidation tier promotion tuning. Entity resolution improvements. Multi-session spreading activation.

## Positioning

Akashik is not a vector database. It is not a chatbot memory buffer. It is not a retrieval system.

Akashik is a deterministic, versioned memory operating system for long-lived human–AI relationships.

OpenClaw is essentially a high-performance CPU that currently suffers from Volatile RAM — it clears its head the moment you close the terminal. Akashik provides the Non-Volatile Semantic Storage (the SSD) and the MMU (the Memory Management Unit) to make that data accessible in 87ms.

Akashik turns any local AI assistant from a session-based tool into a lifelong personal AI that actually remembers and evolves with you.

The primary use case is local AI assistants and agents. Akashik gives them memory that persists across sessions, evolves with the user over years, and injects only the right context at the right moment — without cloud dependency, without hallucinated memory, and without the context window explosion that makes long-term local AI impractical today.

| Component | Role |
|---|---|
| OpenClaw / local LLM | CPU — high-performance local reasoning |
| Akashik fact store | SSD — non-volatile semantic storage, persists forever |
| Akashik expression engine | MMU — memory management unit, right facts in 87ms |
| LLM context window | CPU cache — small, fast, only what's needed right now |

The LLM is the CPU. Akashik is the memory. The CPU computes. The memory never hallucinates.

## One-Line Summary

Store everything as immutable truth. Express only what matters now.

---

Addressed Cognition v0.20.0 | Akashik Memory System | April 2026
