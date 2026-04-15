"""Benchmark runner."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from pathlib import Path

from benchmark import DEFAULT_CORPUS_DIR, DEFAULT_QUERIES_PATH, DEFAULT_RESULTS_DIR
from benchmark.corpus import load_corpus
from benchmark.evaluate import aggregate_system_scores, evaluate_gate, evaluate_query
from benchmark.queries import load_queries
from benchmark.report import build_results_payload, render_report, write_json, write_markdown
from benchmark.systems.akashik import AkashikSystem
from benchmark.systems.graphrag import GraphRagSystem
from benchmark.systems.rag import RagSystem


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

        output_dir = Path(results_dir or DEFAULT_RESULTS_DIR).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        payload = build_results_payload(
            corpus_size=len(documents),
            query_count=len(queries),
            per_query_results=per_query_results,
            blind_aggregates=blind_aggregates,
            gate=gate,
        )
        report = render_report(named_aggregates, gate)

        write_json(output_dir / "results.json", payload)
        write_markdown(output_dir / "report.md", report)

        return {
            "results_path": str(output_dir / "results.json"),
            "report_path": str(output_dir / "report.md"),
            "gate": gate,
            "named_aggregates": named_aggregates,
        }
    finally:
        for _, _, system in systems:
            system.close()


def _reset_benchmark_db() -> None:
    benchmark_db = Path("results/benchmark.db")
    if benchmark_db.exists():
        benchmark_db.unlink()


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
