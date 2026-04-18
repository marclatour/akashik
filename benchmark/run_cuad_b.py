"""CUAD Mode B runner for natural-language legal queries."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path

from akashik.executor import execute as execute_query
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
CUAD_MODE_B_RESULTS_PATH = "results_cuad_b_50.json"
CUAD_MODE_B_REPORT_PATH = "report_cuad_b_50.md"
CUAD_MODE_B_JSONL_PREFIX = "cuad_b"


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
    entity_secondary_source: str | None = None

    @property
    def difficulty(self) -> str:
        return self.original_difficulty


class ExistingCuadAkashikSystem:
    display_name = "Akashik"

    def __init__(self, db_path: str | Path = CUAD_BENCHMARK_DB_PATH, *, use_expression: bool = False) -> None:
        db_path = Path(db_path)
        if not db_path.exists():
            raise FileNotFoundError(
                f"{db_path} does not exist. Run benchmark/run_cuad.py before benchmark/run_cuad_b.py."
            )
        self._store = Store(db_path)
        self._use_expression = use_expression

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        entity_filter: list[str] | None = None,
    ) -> list[RetrievedItem]:
        response = retrieve(
            query,
            self._store,
            level="fact",
            limit=limit,
            entity_filter=entity_filter,
            use_expression=self._use_expression,
        )
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

    def execute(
        self,
        query: str,
        *,
        limit: int = 5,
        entity_filter: list[str] | None = None,
        clause_type: str | None = None,
        abstention_threshold: float = 0.3,
    ):
        return execute_query(
            self._store,
            query,
            entity_filter=entity_filter,
            clause_type=clause_type,
            top_k=limit,
            abstention_threshold=abstention_threshold,
            use_expression=self._use_expression,
        )


def run_cuad_b(
    *,
    corpus_dir: str | Path | None = None,
    queries_path: str | Path | None = None,
    results_dir: str | Path | None = None,
    use_executor: bool = True,
    use_expression: bool = False,
) -> dict[str, object]:
    documents = load_cuad_corpus(corpus_dir or CUAD_CORPUS_DIR)
    queries = load_cuad_b_queries(
        queries_path or CUAD_MODE_B_QUERIES_PATH,
        corpus_filenames={document.filename for document in documents},
    )

    systems = [
        ("system_a", "RAG", RagSystem(documents)),
        ("system_b", "GraphRAG", GraphRagSystem(documents)),
        ("system_c", "Akashik", ExistingCuadAkashikSystem(CUAD_BENCHMARK_DB_PATH, use_expression=use_expression)),
    ]

    try:
        named_scores: dict[str, list[tuple[CuadModeBQuery, object]]] = {name: [] for _, name, _ in systems}
        per_query_results: list[dict[str, object]] = []
        executor_rows: list[dict[str, object]] = []

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
                "entity_secondary_source": query.entity_secondary_source,
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
                if display_name == "Akashik":
                    executor_result = None
                    if use_executor:
                        executor_result = system.execute(
                            query.query_text,
                            limit=5,
                            entity_filter=query.entity_filter,
                            clause_type=query.clause_type,
                        )
                    executor_rows.append(
                        {
                            "question_id": query.query_id,
                            "question": query.query_text,
                            "question_type": query.clause_type,
                            "answer": query.expected_fact,
                            "executor_answer": executor_result.answer if executor_result else None,
                            "executor_abstained": executor_result.abstained if executor_result else True,
                            "executor_answer_type": executor_result.answer_type if executor_result else "unknown",
                        }
                    )

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
        output_path = _default_output_path()

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
        with output_path.open("w", encoding="utf-8") as handle:
            for row in executor_rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

        return {
            "results_path": str(results_path),
            "report_path": str(report_path),
            "named_aggregates": named_aggregates,
            "failure_analysis": failures,
            "output_path": str(output_path),
            "executor_rows": executor_rows,
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
    if len(queries) != 20:
        raise ValueError(f"CUAD Mode B must contain exactly 20 queries; found {len(queries)}.")

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


def _print_executor_report(rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    answered = sum(1 for row in rows if not row.get("executor_abstained"))
    abstained = sum(1 for row in rows if row.get("executor_abstained"))
    by_answer_type: dict[str, int] = {}
    for row in rows:
        answer_type = str(row.get("executor_answer_type", "unknown"))
        by_answer_type[answer_type] = by_answer_type.get(answer_type, 0) + 1
    print("")
    print("=== Executor Results ===")
    print(f"Answered:    {answered}")
    print(f"Abstained:   {abstained}")
    print("By type:")
    for answer_type in ("factual", "temporal", "preference", "aggregation", "unknown"):
        print(f"  {answer_type:<11} {by_answer_type.get(answer_type, 0)}")


def _default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("/tmp") / f"akashik_{CUAD_MODE_B_JSONL_PREFIX}_{timestamp}.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CUAD Mode B natural-language diagnostics.")
    parser.add_argument("--corpus-dir", default=str(CUAD_CORPUS_DIR))
    parser.add_argument("--queries-path", default=str(CUAD_MODE_B_QUERIES_PATH))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument(
        "--use-executor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the deterministic Executor after Akashik retrieval. Disable with --no-executor.",
    )
    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Keep the JSONL output file after the run.",
    )
    parser.add_argument(
        "--use-expression",
        action="store_true",
        default=os.getenv("AKASHIK_USE_EXPRESSION") == "1",
        help="Enable the opt-in expression engine before the retrieval stack.",
    )
    args = parser.parse_args()

    if not CUAD_BENCHMARK_DB_PATH.exists():
        print(f"Error: CUAD benchmark store not found: {CUAD_BENCHMARK_DB_PATH}")
        print("Run: ./.venv/bin/python benchmark/run_cuad.py")
        return 1

    summary = run_cuad_b(
        corpus_dir=args.corpus_dir,
        queries_path=args.queries_path,
        results_dir=args.results_dir,
        use_executor=args.use_executor,
        use_expression=args.use_expression,
    )
    _print_executor_report(summary["executor_rows"])
    print(f"results: {summary['results_path']}")
    print(f"report: {summary['report_path']}")
    if args.keep_output:
        print(f"Results saved to: {summary['output_path']}")
    else:
        Path(summary["output_path"]).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
