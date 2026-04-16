# Backlog

## Ideas

### Hierarchical Consolidation As A Background Process

Problem: decade-scale corpora will eventually accumulate enough atomic facts that retrieval quality and routing cost degrade even when the deterministic hierarchy is working correctly.

Idea: add a background consolidation pass that rolls older fact clusters into higher-order summaries such as eras, projects, or stable life periods while preserving the underlying immutable facts and provenance chain.

Why it matters: this would help keep routing closer to `O(log n)`, reduce fragmentation in large personal-memory corpora, and give the Navigator a higher-level structural layer to descend through before searching atomic facts.

Constraints:
- Must preserve raw fact immutability and provenance.
- Must remain local-first and deterministic by default.
- Should not replace atomic retrieval; it should act as an additional hierarchy layer.

Open questions:
- What consolidation unit should be introduced first: era, project, relationship, or location period?
- Should consolidation run on a schedule, on corpus size thresholds, or after ingest bursts?
- How should consolidated summaries participate in retrieval without overshadowing current-valid atomic facts?
