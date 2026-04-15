"""Mode B benchmark runner for natural language queries."""

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
from benchmark import BENCHMARK_ROOT, DEFAULT_CORPUS_DIR, DEFAULT_RESULTS_DIR
from benchmark.corpus import load_corpus
from benchmark.evaluate import aggregate_system_scores, evaluate_query
from benchmark.report import write_json, write_markdown
from benchmark.systems import RetrievedItem
from benchmark.systems.graphrag import GraphRagSystem
from benchmark.systems.rag import RagSystem

MODE_B_QUERIES_PATH = BENCHMARK_ROOT / "queries_mode_b.json"
BENCHMARK_DB_PATH = Path("results/benchmark.db")


@dataclass(slots=True)
class ModeBQuery:
    query_id: str
    query_text: str
    expected_fact: str
    expected_source: str
    expected_level: str
    original_difficulty: str
    difficulty_mode_b: str

    @property
    def difficulty(self) -> str:
        return self.original_difficulty


class ExistingAkashikSystem:
    display_name = "Akashik"

    def __init__(self, db_path: str | Path = BENCHMARK_DB_PATH) -> None:
        db_path = Path(db_path)
        if not db_path.exists():
            raise FileNotFoundError(
                f"{db_path} does not exist. Run benchmark/run.py before benchmark/run_mode_b.py."
            )
        self._store = Store(db_path)

    def search(self, query: str, *, limit: int = 5) -> list[RetrievedItem]:
        response = retrieve(query, self._store, level="fact", limit=limit)
        results: list[RetrievedItem] = []
        for index, result in enumerate(response.results, start=1):
            results.append(
                RetrievedItem(
                    content=result.unit.content,
                    source=_source_name(result.unit.source),
                    rank=index,
                    confidence=result.confidence,
                    parent_chain=[
                        {
                            "level": parent.level,
                            "content": parent.content,
                            "source": _source_name(parent.source),
                        }
                        for parent in result.parent_chain
                    ],
                )
            )
        return results

    def close(self) -> None:
        self._store.close()


def run_mode_b(
    *,
    corpus_dir: str | Path | None = None,
    queries_path: str | Path | None = None,
    results_dir: str | Path | None = None,
    mode_a_results_path: str | Path | None = None,
) -> dict[str, object]:
    documents = load_corpus(corpus_dir or DEFAULT_CORPUS_DIR)
    queries = load_mode_b_queries(
        queries_path or MODE_B_QUERIES_PATH,
        corpus_filenames={document.filename for document in documents},
    )
    mode_a_scores = load_mode_a_akashik_scores(mode_a_results_path or DEFAULT_RESULTS_DIR / "results.json")

    systems = [
        ("system_a", "RAG", RagSystem(documents)),
        ("system_b", "GraphRAG", GraphRagSystem(documents)),
        ("system_c", "Akashik", ExistingAkashikSystem(BENCHMARK_DB_PATH)),
    ]

    try:
        named_scores: dict[str, list[tuple[ModeBQuery, object]]] = {name: [] for _, name, _ in systems}
        per_query_results: list[dict[str, object]] = []
        gaps: list[dict[str, object]] = []

        for query in queries:
            row = {
                "query_id": query.query_id,
                "query_text": query.query_text,
                "difficulty_mode_b": query.difficulty_mode_b,
                "original_difficulty": query.original_difficulty,
                "expected_source": query.expected_source,
                "expected_level": query.expected_level,
                "systems": {},
            }

            query_scores: dict[str, float] = {}
            for blind_id, display_name, system in systems:
                results = system.search(query.query_text, limit=5)
                score = evaluate_query(query, results)
                named_scores[display_name].append((query, score))
                query_scores[display_name] = score.composite
                row["systems"][blind_id] = score.as_dict()
                row["systems"][blind_id]["results"] = [item.as_dict() for item in results]

            mode_a_akashik = mode_a_scores.get(query.query_id, 0.0)
            mode_b_akashik = query_scores["Akashik"]
            gaps.append(
                {
                    "query_id": query.query_id,
                    "mode_a_akashik": mode_a_akashik,
                    "mode_b_akashik": mode_b_akashik,
                    "gap": round(mode_a_akashik - mode_b_akashik, 4),
                    "rag_mode_b": query_scores["RAG"],
                }
            )
            per_query_results.append(row)

        named_aggregates = {
            display_name: aggregate_system_scores(scores)["overall"]
            for _, display_name, _ in systems
            for scores in [named_scores[display_name]]
        }

        output_dir = Path(results_dir or DEFAULT_RESULTS_DIR).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "benchmark": {
                "mode": "B",
                "description": "Natural language query variants",
                "query_count": len(queries),
                "uses_existing_benchmark_db": str(BENCHMARK_DB_PATH),
            },
            "systems": named_aggregates,
            "queries": per_query_results,
            "gap_analysis": gaps,
        }
        report = render_mode_b_report(named_aggregates, gaps)

        results_path = output_dir / "results_mode_b.json"
        report_path = output_dir / "report_mode_b.md"
        write_json(results_path, payload)
        write_markdown(report_path, report)

        return {
            "results_path": str(results_path),
            "report_path": str(report_path),
            "named_aggregates": named_aggregates,
            "gap_analysis": gaps,
        }
    finally:
        for _, _, system in systems:
            system.close()


def load_mode_b_queries(
    queries_path: str | Path,
    *,
    corpus_filenames: set[str],
) -> list[ModeBQuery]:
    raw_queries = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    queries = [ModeBQuery(**item) for item in raw_queries]
    if len(queries) != 10:
        raise ValueError(f"Mode B must contain exactly 10 queries; found {len(queries)}.")

    seen_ids: set[str] = set()
    for query in queries:
        if query.query_id in seen_ids:
            raise ValueError(f"Duplicate Mode B query id {query.query_id!r}.")
        seen_ids.add(query.query_id)
        if query.difficulty_mode_b != "natural":
            raise ValueError(f"Mode B query {query.query_id!r} must set difficulty_mode_b='natural'.")
        if query.expected_source not in corpus_filenames:
            raise ValueError(
                f"Mode B query {query.query_id!r} references unknown source {query.expected_source!r}."
            )
        if query.expected_fact.lower() in query.query_text.lower():
            raise ValueError(
                f"Mode B query {query.query_id!r} contains the full expected fact as a substring."
            )
    return queries


def load_mode_a_akashik_scores(path: str | Path) -> dict[str, float]:
    payload_path = Path(path)
    if not payload_path.exists():
        return {}
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return {
        row["query_id"]: row["systems"]["system_c"]["composite"]
        for row in payload.get("queries", [])
        if "system_c" in row.get("systems", {})
    }


def render_mode_b_report(
    named_aggregates: dict[str, dict[str, float]],
    gaps: list[dict[str, object]],
) -> str:
    lines = [
        "# Mode B Benchmark Report (Natural Language Queries)",
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

    lines.extend(
        [
            "",
            "## Gap Analysis",
            "| Query ID | Mode A Akashik | Mode B Akashik | Gap  | RAG Mode B |",
            "|----------|---------------|----------------|------|------------|",
        ]
    )
    for gap in gaps:
        lines.append(
            "| {query_id} | {mode_a:.2f} | {mode_b:.2f} | {gap_value:.2f} | {rag:.2f} |".format(
                query_id=gap["query_id"],
                mode_a=gap["mode_a_akashik"],
                mode_b=gap["mode_b_akashik"],
                gap_value=gap["gap"],
                rag=gap["rag_mode_b"],
            )
        )

    akashik_composite = named_aggregates["Akashik"]["composite"]
    rag_composite = named_aggregates["RAG"]["composite"]
    interpretation = interpret_mode_b(akashik_composite, rag_composite)
    lines.extend(["", "## Interpretation", *[f"- {line}" for line in interpretation]])
    return "\n".join(lines) + "\n"


def interpret_mode_b(akashik_composite: float, rag_composite: float) -> list[str]:
    if akashik_composite > 0.80:
        primary = "Akashik Mode B composite is above 0.80; architecture is robust and 0.2.0 is optimization."
    elif akashik_composite > 0.70:
        primary = "Akashik Mode B composite is above 0.70; a query normalization layer is sufficient for 0.2.0."
    elif akashik_composite >= 0.50:
        primary = "Akashik Mode B composite is 0.50-0.80; query normalization likely closes the gap."
    else:
        primary = "Akashik Mode B composite is below 0.50; semantic fallback is required for 0.2.0."

    comparison = (
        "RAG Mode B is above Akashik Mode B; document this natural language retrieval gap."
        if rag_composite > akashik_composite
        else "Akashik Mode B remains above RAG Mode B on composite."
    )
    return [primary, comparison]


def _source_name(source: str) -> str:
    return Path(source).name if source else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mode B natural-language benchmark diagnostics.")
    parser.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS_DIR))
    parser.add_argument("--queries-path", default=str(MODE_B_QUERIES_PATH))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--mode-a-results", default=str(DEFAULT_RESULTS_DIR / "results.json"))
    args = parser.parse_args()

    try:
        summary = run_mode_b(
            corpus_dir=args.corpus_dir,
            queries_path=args.queries_path,
            results_dir=args.results_dir,
            mode_a_results_path=args.mode_a_results,
        )
        print(f"results: {summary['results_path']}")
        print(f"report: {summary['report_path']}")
    except Exception as exc:
        print(f"mode_b_error: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
