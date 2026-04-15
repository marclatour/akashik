"""CUAD Mode B runner for natural-language legal queries."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from dataclasses import dataclass
import json
from pathlib import Path

from akashik import Store, retrieve
from benchmark import DEFAULT_RESULTS_DIR
from benchmark.run_cuad import (
    CLAUSE_TYPES,
    CUAD_BENCHMARK_DB_PATH,
    CUAD_CORPUS_DIR,
    CUAD_ROOT,
    aggregate_scores,
    collect_akashik_failures,
    evaluate_cuad_query,
    load_cuad_corpus,
)
from benchmark.report import write_json, write_markdown
from benchmark.systems import RetrievedItem
from benchmark.systems.graphrag import GraphRagSystem
from benchmark.systems.rag import RagSystem

CUAD_MODE_B_QUERIES_PATH = CUAD_ROOT / "queries_cuad_b.json"
CUAD_MODE_B_RESULTS_PATH = "results_cuad_b.json"
CUAD_MODE_B_REPORT_PATH = "report_cuad_b.md"


@dataclass(slots=True)
class CuadModeBQuery:
    query_id: str
    query_text: str
    expected_fact: str
    expected_source: str
    expected_level: str
    original_query_id: str
    original_difficulty: str
    difficulty_mode_b: str
    clause_type: str
    entity_filter: list[str] | None = None
    entity_filter_source: str | None = None
    entity_filter_reason: str | None = None

    @property
    def difficulty(self) -> str:
        return self.original_difficulty


class ExistingCuadAkashikSystem:
    display_name = "Akashik"

    def __init__(self, db_path: str | Path = CUAD_BENCHMARK_DB_PATH) -> None:
        db_path = Path(db_path)
        if not db_path.exists():
            raise FileNotFoundError(
                f"{db_path} does not exist. Run benchmark/run_cuad.py before benchmark/run_cuad_b.py."
            )
        self._store = Store(db_path)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        entity_filter: list[str] | None = None,
    ) -> list[RetrievedItem]:
        response = retrieve(query, self._store, level="fact", limit=limit, entity_filter=entity_filter)
        results: list[RetrievedItem] = []
        for index, result in enumerate(response.results, start=1):
            results.append(
                RetrievedItem(
                    content=result.unit.content,
                    source=Path(result.unit.source).name if result.unit.source else "",
                    rank=index,
                    confidence=result.confidence,
                    parent_chain=[
                        {
                            "level": parent.level,
                            "content": parent.content,
                            "source": Path(parent.source).name if parent.source else "",
                        }
                        for parent in result.parent_chain
                    ],
                )
            )
        return results

    def close(self) -> None:
        self._store.close()


def run_cuad_b(
    *,
    corpus_dir: str | Path | None = None,
    queries_path: str | Path | None = None,
    results_dir: str | Path | None = None,
) -> dict[str, object]:
    documents = load_cuad_corpus(corpus_dir or CUAD_CORPUS_DIR)
    queries = load_cuad_b_queries(
        queries_path or CUAD_MODE_B_QUERIES_PATH,
        corpus_filenames={document.filename for document in documents},
    )

    systems = [
        ("system_a", "RAG", RagSystem(documents)),
        ("system_b", "GraphRAG", GraphRagSystem(documents)),
        ("system_c", "Akashik", ExistingCuadAkashikSystem(CUAD_BENCHMARK_DB_PATH)),
    ]

    try:
        named_scores: dict[str, list[tuple[CuadModeBQuery, object]]] = {name: [] for _, name, _ in systems}
        per_query_results: list[dict[str, object]] = []

        for query in queries:
            row = {
                "query_id": query.query_id,
                "query_text": query.query_text,
                "expected_source": query.expected_source,
                "expected_level": query.expected_level,
                "original_query_id": query.original_query_id,
                "original_difficulty": query.original_difficulty,
                "difficulty_mode_b": query.difficulty_mode_b,
                "clause_type": query.clause_type,
                "entity_filter": query.entity_filter,
                "entity_filter_source": query.entity_filter_source,
                "entity_filter_reason": query.entity_filter_reason,
                "systems": {},
            }

            for blind_id, display_name, system in systems:
                if display_name == "Akashik":
                    results = system.search(query.query_text, limit=5, entity_filter=query.entity_filter)
                else:
                    results = system.search(query.query_text, limit=5)
                score = evaluate_cuad_query(query, results)
                named_scores[display_name].append((query, score))
                row["systems"][blind_id] = score.as_dict()
                row["systems"][blind_id]["results"] = [item.as_dict() for item in results]

            per_query_results.append(row)

        named_aggregates = {
            display_name: aggregate_scores(scores)
            for _, display_name, _ in systems
            for scores in [named_scores[display_name]]
        }
        blind_aggregates = {
            blind_id: named_aggregates[display_name]
            for blind_id, display_name, _ in systems
        }
        failures = collect_akashik_failures(named_scores["Akashik"])

        output_dir = Path(results_dir or DEFAULT_RESULTS_DIR).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        results_path = output_dir / CUAD_MODE_B_RESULTS_PATH
        report_path = output_dir / CUAD_MODE_B_REPORT_PATH

        payload = {
            "benchmark": {
                "name": "CUAD Mode B",
                "description": "Natural-language legal queries",
                "query_count": len(queries),
                "uses_existing_benchmark_db": str(CUAD_BENCHMARK_DB_PATH),
            },
            "systems": blind_aggregates,
            "queries": per_query_results,
            "failure_analysis": failures,
        }
        report = render_cuad_b_report(named_aggregates, failures)
        write_json(results_path, payload)
        write_markdown(report_path, report)

        return {
            "results_path": str(results_path),
            "report_path": str(report_path),
            "named_aggregates": named_aggregates,
            "failure_analysis": failures,
        }
    finally:
        for _, _, system in systems:
            system.close()


def load_cuad_b_queries(
    queries_path: str | Path,
    *,
    corpus_filenames: set[str],
) -> list[CuadModeBQuery]:
    raw_queries = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    queries = [CuadModeBQuery(**item) for item in raw_queries]
    if len(queries) != 5:
        raise ValueError(f"CUAD Mode B must contain exactly 5 queries; found {len(queries)}.")

    seen_ids: set[str] = set()
    for query in queries:
        if query.query_id in seen_ids:
            raise ValueError(f"Duplicate CUAD Mode B query id {query.query_id!r}.")
        seen_ids.add(query.query_id)
        if query.expected_source not in corpus_filenames:
            raise ValueError(
                f"CUAD Mode B query {query.query_id!r} references unknown source {query.expected_source!r}."
            )
        if query.clause_type not in CLAUSE_TYPES:
            raise ValueError(f"Invalid CUAD clause type {query.clause_type!r}.")
        if query.difficulty_mode_b != "natural":
            raise ValueError(f"CUAD Mode B query {query.query_id!r} must be marked natural.")
    return queries


def render_cuad_b_report(
    named_aggregates: dict[str, dict[str, float]],
    failures: list[dict[str, object]],
) -> str:
    lines = [
        "# CUAD Mode B Benchmark Report (Natural Legal Queries)",
        "",
        "| System   | Precision@1 | Efficiency | Provenance | Composite |",
        "|----------|-------------|------------|------------|-----------|",
    ]

    for system_name in ("RAG", "GraphRAG", "Akashik"):
        aggregate = named_aggregates[system_name]
        lines.append(
            "| {name} | {precision:.2f} | {efficiency:.2f} | {provenance:.2f} | {composite:.2f} |".format(
                name=system_name.ljust(8),
                precision=aggregate["precision_at_1"],
                efficiency=aggregate["context_efficiency"],
                provenance=aggregate["provenance"],
                composite=aggregate["composite"],
            )
        )

    lines.extend(["", "## Failure Analysis"])
    if not failures:
        lines.append("No Akashik precision or provenance failures in this run.")
    else:
        for failure in failures:
            lines.append(
                "- `{query_id}` ({clause_type}): normalized query `{normalized}`; expected source `{expected}`, top source `{top}`; top result: {content}".format(
                    query_id=failure["query_id"],
                    clause_type=failure["clause_type"],
                    normalized=failure["normalized_query"],
                    expected=failure["expected_source"],
                    top=failure["top_source"],
                    content=failure["top_content"] or "None",
                )
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CUAD Mode B natural-language diagnostics.")
    parser.add_argument("--corpus-dir", default=str(CUAD_CORPUS_DIR))
    parser.add_argument("--queries-path", default=str(CUAD_MODE_B_QUERIES_PATH))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    summary = run_cuad_b(
        corpus_dir=args.corpus_dir,
        queries_path=args.queries_path,
        results_dir=args.results_dir,
    )
    print(f"results: {summary['results_path']}")
    print(f"report: {summary['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
