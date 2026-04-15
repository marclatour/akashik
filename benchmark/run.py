"""Benchmark runner."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from pathlib import Path
import re

from benchmark import DEFAULT_CORPUS_DIR, DEFAULT_QUERIES_PATH, DEFAULT_RESULTS_DIR
from benchmark.corpus import load_corpus
from benchmark.evaluate import aggregate_system_scores, evaluate_gate, evaluate_query
from benchmark.queries import load_queries
from benchmark.report import build_results_payload, render_report, write_json, write_markdown
from benchmark.systems.akashik import AkashikSystem
from benchmark.systems.graphrag import GraphRagSystem
from benchmark.systems.rag import RagSystem
from benchmark.systems.rag_embedding import RagEmbeddingSystem


def run_benchmark(
    *,
    corpus_dir: str | Path | None = None,
    queries_path: str | Path | None = None,
    results_dir: str | Path | None = None,
) -> dict[str, object]:
    _reset_benchmark_db()
    documents = load_corpus(corpus_dir or DEFAULT_CORPUS_DIR)
    queries = load_queries(
        queries_path or DEFAULT_QUERIES_PATH,
        corpus_filenames={document.filename for document in documents},
    )

    systems = [
        ("system_a", "RAG", RagSystem(documents)),
        ("system_b", "GraphRAG", GraphRagSystem(documents)),
        ("system_c", "Akashik", AkashikSystem(documents)),
        ("system_d", "RAG-Embedding", RagEmbeddingSystem(documents)),
    ]

    try:
        named_scores: dict[str, list[tuple[object, object]]] = {name: [] for _, name, _ in systems}
        blind_aggregates: dict[str, dict[str, object]] = {}
        per_query_results: list[dict[str, object]] = []

        for query in queries:
            row = {
                "query_id": query.query_id,
                "query_text": query.query_text,
                "difficulty": query.difficulty,
                "expected_source": query.expected_source,
                "expected_level": query.expected_level,
                "systems": {},
            }

            for blind_id, display_name, system in systems:
                results = system.search(query.query_text, limit=5)
                score = evaluate_query(query, results)
                named_scores[display_name].append((query, score))
                row["systems"][blind_id] = score.as_dict()
                row["systems"][blind_id]["results"] = [item.as_dict() for item in results]

            per_query_results.append(row)

        named_aggregates = {
            display_name: aggregate_system_scores(scores)
            for _, display_name, _ in systems
            for scores in [named_scores[display_name]]
        }
        blind_aggregates = {
            blind_id: named_aggregates[display_name]
            for blind_id, display_name, _ in systems
        }
        gate = evaluate_gate(named_scores, named_aggregates)
        disagreements = collect_embedding_akashik_disagreements(per_query_results)

        output_dir = Path(results_dir or DEFAULT_RESULTS_DIR).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        payload = build_results_payload(
            corpus_size=len(documents),
            query_count=len(queries),
            per_query_results=per_query_results,
            blind_aggregates=blind_aggregates,
            gate=gate,
        )
        payload["embedding_akashik_disagreements"] = disagreements
        report = render_report(named_aggregates, gate, disagreements)

        write_json(output_dir / "results.json", payload)
        write_markdown(output_dir / "report.md", report)

        return {
            "results_path": str(output_dir / "results.json"),
            "report_path": str(output_dir / "report.md"),
            "gate": gate,
            "named_aggregates": named_aggregates,
            "embedding_akashik_disagreements": disagreements,
        }
    finally:
        for _, _, system in systems:
            system.close()


def _reset_benchmark_db() -> None:
    benchmark_db = Path("results/benchmark.db")
    if benchmark_db.exists():
        benchmark_db.unlink()


def collect_embedding_akashik_disagreements(per_query_results: list[dict[str, object]]) -> list[dict[str, object]]:
    disagreements: list[dict[str, object]] = []
    for row in per_query_results:
        systems = row["systems"]
        embedding = systems["system_d"]
        akashik = systems["system_c"]
        embedding_top = embedding.get("top_result") or {}
        akashik_top = akashik.get("top_result") or {}
        if _same_rank_one(embedding_top, akashik_top):
            continue
        disagreements.append(
            {
                "query_id": row["query_id"],
                "expected_source": row["expected_source"],
                "embedding_top_source": embedding_top.get("source"),
                "embedding_top_content": _compact(str(embedding_top.get("content", "")), limit=80),
                "akashik_top_source": akashik_top.get("source"),
                "akashik_top_content": _compact(str(akashik_top.get("content", "")), limit=80),
                "category": _disagreement_category(embedding, akashik),
            }
        )
    return disagreements


def _same_rank_one(left: dict[str, object], right: dict[str, object]) -> bool:
    return left.get("source") == right.get("source") and left.get("content") == right.get("content")


def _disagreement_category(embedding: dict[str, object], akashik: dict[str, object]) -> str:
    embedding_precision = float(embedding.get("precision_at_1", 0.0))
    akashik_precision = float(akashik.get("precision_at_1", 0.0))
    embedding_provenance = float(embedding.get("provenance", 0.0))
    akashik_provenance = float(akashik.get("provenance", 0.0))
    if embedding_precision == 1.0 and akashik_precision == 0.0:
        return "semantic_win"
    if akashik_provenance == 1.0 and embedding_provenance == 0.0:
        return "scope_win"
    if embedding_precision == 0.0 and akashik_precision == 0.0:
        return "both_wrong"
    return "benchmark_ambiguity"


def _compact(text: str, *, limit: int) -> str:
    compacted = re.sub(r"\s+", " ", text).strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Akashik benchmark harness.")
    parser.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS_DIR))
    parser.add_argument("--queries-path", default=str(DEFAULT_QUERIES_PATH))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    summary = run_benchmark(
        corpus_dir=args.corpus_dir,
        queries_path=args.queries_path,
        results_dir=args.results_dir,
    )

    gate = summary["gate"]
    print(f"results: {summary['results_path']}")
    print(f"report: {summary['report_path']}")
    print(f"gate: {'PASS' if gate['passed'] else 'FAIL'}")
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
