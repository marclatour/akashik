# ACMB — Akashik Conversation Memory Benchmark

A system-agnostic benchmark for conversational memory systems. Tests whether a memory system can maintain correct, current, and provenance-preserving memory across multi-session conversations.

## What ACMB tests

- **Fact recall** — does the system surface relevant facts?
- **Belief revision** — does it suppress superseded facts and surface current truth?
- **Commitment tracking** — does it remember what the assistant promised?
- **Noise robustness** — does it surface facts introduced sessions ago despite noise?
- **Temporal correctness** — does it handle historical queries correctly?
- **Distractor suppression** — does it avoid returning stale or irrelevant facts?

## Personas

v0.1 personas (001-005): basic recall, simple revision, mild noise
v0.3 personas (006-025): dense contradiction chains, implicit revision, multi-entity collision, delayed commitments, strong noise

Data lives under `~/.akashik/data/benchmarks/acmb/`.

## Adapters

| Adapter | Description |
|---|---|
| `akashik` | Akashik structured memory — persistent, validity-aware |
| `rag` | Embedding retrieval baseline — no persistence |
| `rag_akashik` | RAG + Akashik commitment detection |
| `bm25` | BM25 lexical retrieval baseline — no persistence |
| `bm25_akashik` | BM25 + Akashik commitment detection |
| `full_context` | Recency baseline — most recent turns, no retrieval |

## How to run

```bash
# run all personas against Akashik
./.venv/bin/python benchmark/acmb/run_acmb.py --adapter akashik

# run with verbose miss analysis
./.venv/bin/python benchmark/acmb/run_acmb.py --adapter akashik --verbose

# compare against RAG baseline
./.venv/bin/python benchmark/acmb/run_acmb.py --adapter rag

# adjust match threshold for text-to-fact resolution
./.venv/bin/python benchmark/acmb/run_acmb.py --adapter akashik --match-threshold 0.4

# experimental: associative activation stage (akashik/association.py), off by default
AKASHIK_ACMB_ASSOCIATION=1 ./.venv/bin/python benchmark/acmb/run_acmb.py --adapter akashik

# pre-flight validation
bash scripts/check_acmb.sh
```

## Six-way capability comparison (v0.1 personas)

| Capability | BM25 | RAG | Full-ctx | bm25_akashik | rag_akashik | Akashik |
|---|---|---|---|---|---|---|
| Retrieval | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Persistence | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| Commitment detection | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| Belief revision | ✗ | ✗ | ✗ | 0.500 | 0.550 | **0.950** |
| Distractor suppression | 0.500 | 0.500 | 0.000 | 0.500 | 0.500 | **0.000** |
| Provenance | ✗ | ✗ | ✗ | ✗ | ✗ | **1.00** |
| Latency p50 (query) | 0.41ms | 37ms | 0.81ms | 0.44ms | 34.61ms | 2.17ms |

BM25, RAG, and full-context are retrieval baselines with no persistence. They reset between runs and lose all state when the process ends. Akashik is the only system in the comparison that provides persistent, versioned, provenance-preserving memory.

## Adding a new adapter

Implement the two-method interface in `benchmark/acmb/adapters/base.py`:

```python
def ingest_turn(self, turn: dict) -> None:
    """Ingest one conversation turn."""

def query(self, query_text: str, k: int = 10) -> list[str]:
    """Return up to k retrieved text snippets."""
```

Register in `benchmark/acmb/run_acmb.py` `get_adapter()`.
