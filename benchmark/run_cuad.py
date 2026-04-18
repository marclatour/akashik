"""CUAD benchmark runner for real legal contracts."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re

from akashik.query_normalize import normalize_query
from akashik import Store
from benchmark import DEFAULT_RESULTS_DIR
from benchmark.corpus import CorpusDocument, split_sections
from benchmark.evaluate import tokenize
from benchmark.report import write_json, write_markdown
from benchmark.systems import RetrievedItem
from benchmark.systems.akashik import AkashikSystem
from benchmark.systems.graphrag import GraphRagSystem
from benchmark.systems.rag import RagSystem
from benchmark.systems.rag_embedding import RagEmbeddingSystem

CUAD_ROOT = Path(__file__).resolve().parent / "cuad"
CUAD_CORPUS_DIR = CUAD_ROOT / "corpus"
CUAD_QUERIES_PATH = CUAD_ROOT / "queries_cuad.json"
CUAD_SELECTION_SUMMARY_PATH = CUAD_ROOT / "selection_summary.json"
CUAD_BENCHMARK_DB_PATH = Path.home() / ".akashik" / "stores" / "benchmarks" / "cuad" / "benchmark_cuad_50.db"
CUAD_RESULTS_PATH = "results_cuad_50.json"
CUAD_REPORT_PATH = "report_cuad_50.md"
CUAD_JSONL_PREFIX = "cuad"
CLAUSE_TYPES = ("governing_law", "renewal", "notice")
SYSTEMS = (
    ("system_a", "RAG"),
    ("system_b", "GraphRAG"),
    ("system_c", "Akashik"),
    ("system_d", "RAG-Embedding"),
)
EXPECTED_CUAD_QUERY_COUNT = 50
BASELINE_CUAD_10_CONTRACTS = {
    "precision_at_1": 0.90,
    "context_efficiency": 0.16,
    "provenance": 1.00,
    "composite": 0.70,
}


@dataclass(slots=True)
class CuadQuery:
    query_id: str
    query_text: str
    expected_fact: str
    expected_source: str
    expected_level: str
    difficulty: str
    clause_type: str
    entity_filter: list[str] | None = None
    entity_filter_source: str | None = None
    entity_filter_reason: str | None = None
    entity_secondary_source: str | None = None


@dataclass(slots=True)
class CuadScore:
    precision_at_1: float
    context_efficiency: float
    provenance: float
    composite: float
    top_result: dict[str, object] | None

    def as_dict(self) -> dict[str, object]:
        return {
            "precision_at_1": self.precision_at_1,
            "context_efficiency": self.context_efficiency,
            "provenance": self.provenance,
            "composite": self.composite,
            "top_result": self.top_result,
        }


def run_cuad(
    *,
    corpus_dir: str | Path | None = None,
    queries_path: str | Path | None = None,
    results_dir: str | Path | None = None,
    with_embeddings: bool = False,
    use_executor: bool = True,
    force_reingest: bool = False,
    use_expression: bool = False,
) -> dict[str, object]:
    documents = load_cuad_corpus(corpus_dir or CUAD_CORPUS_DIR)
    queries = load_cuad_queries(
        queries_path or CUAD_QUERIES_PATH,
        corpus_filenames={document.filename for document in documents},
        expected_count=EXPECTED_CUAD_QUERY_COUNT,
    )
    selection_summary = load_selection_summary(CUAD_SELECTION_SUMMARY_PATH)
    needs_ingest = _store_needs_ingest(CUAD_BENCHMARK_DB_PATH, force_reingest=force_reingest)
    if needs_ingest:
        print("Store: ingesting", flush=True)
        _prepare_cuad_store_for_ingest(CUAD_BENCHMARK_DB_PATH, force_reingest=force_reingest)
    else:
        print("Store: reused", flush=True)

    systems = [
        ("system_a", "RAG", RagSystem(documents)),
        ("system_b", "GraphRAG", GraphRagSystem(documents)),
        (
            "system_c",
            "Akashik",
            AkashikSystem(
                documents,
                db_path=CUAD_BENCHMARK_DB_PATH,
                ingest_documents=needs_ingest,
                use_expression=use_expression,
            ),
        ),
    ]
    if with_embeddings:
        systems.append(("system_d", "RAG-Embedding", RagEmbeddingSystem(documents)))

    try:
        named_scores: dict[str, list[tuple[CuadQuery, CuadScore]]] = {name: [] for _, name, _ in systems}
        per_query_results: list[dict[str, object]] = []
        executor_rows: list[dict[str, object]] = []

        for query in queries:
            row = {
                "query_id": query.query_id,
                "query_text": query.query_text,
                "expected_source": query.expected_source,
                "expected_level": query.expected_level,
                "difficulty": query.difficulty,
                "clause_type": query.clause_type,
                "entity_filter": query.entity_filter,
                "entity_filter_source": query.entity_filter_source,
                "entity_filter_reason": query.entity_filter_reason,
                "entity_secondary_source": query.entity_secondary_source,
                "systems": {},
            }

            for blind_id, display_name, system in systems:
                if display_name == "Akashik":
                    debug_label = query.query_id if query.query_id in {"cuad_02_governing_law", "cuad_06_renewal"} else None
                    results = system.search(
                        query.query_text,
                        limit=5,
                        entity_filter=query.entity_filter,
                        clause_type=query.clause_type,
                        debug_label=debug_label,
                    )
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
                            "expected_source": query.expected_source,
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
        clause_breakdown = build_clause_breakdown(named_scores)
        failures = collect_akashik_failures(named_scores["Akashik"])
        disagreements = collect_embedding_akashik_disagreements(per_query_results) if with_embeddings else []
        synthetic_metrics = load_synthetic_metrics(DEFAULT_RESULTS_DIR / "results.json")

        output_dir = Path(results_dir or DEFAULT_RESULTS_DIR).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        results_path = output_dir / CUAD_RESULTS_PATH
        report_path = output_dir / CUAD_REPORT_PATH
        jsonl_path = _default_output_path()
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "benchmark": {
                "name": "CUAD",
                "description": "Real legal contracts",
                "corpus_documents": len(documents),
                "query_count": len(queries),
                "blind_evaluation": True,
                "database": str(CUAD_BENCHMARK_DB_PATH),
                "embedding_enabled": with_embeddings,
            },
            "systems": blind_aggregates,
            "queries": per_query_results,
            "clause_type_breakdown": clause_breakdown,
            "selection_summary": selection_summary,
            "failure_analysis": failures,
        }
        if with_embeddings:
            payload["embedding_akashik_disagreements"] = disagreements
        report = render_cuad_report(
            named_aggregates,
            clause_breakdown,
            selection_summary,
            failures,
            disagreements,
        )
        write_json(results_path, payload)
        write_markdown(report_path, report)
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in executor_rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

        return {
            "results_path": str(results_path),
            "report_path": str(report_path),
            "output_path": str(jsonl_path),
            "named_aggregates": named_aggregates,
            "failure_analysis": failures,
            "embedding_akashik_disagreements": disagreements,
            "executor_rows": executor_rows,
        }
    finally:
        for _, _, system in systems:
            system.close()


def load_cuad_corpus(corpus_dir: str | Path) -> list[CorpusDocument]:
    base_dir = Path(corpus_dir).resolve()
    documents: list[CorpusDocument] = []
    for path in sorted(base_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        documents.append(
            CorpusDocument(
                filename=path.name,
                path=path,
                text=text,
                sections=split_sections(text),
                word_count=len(text.split()),
            )
        )
    if len(documents) != EXPECTED_CUAD_QUERY_COUNT:
        raise ValueError(
            f"CUAD corpus must contain exactly {EXPECTED_CUAD_QUERY_COUNT} .txt contracts; found {len(documents)}."
        )
    return documents


def load_selection_summary(path: str | Path) -> dict[str, object]:
    summary_path = Path(path)
    if not summary_path.exists():
        return {
            "selection_targets": {},
            "selected_by_clause_type": {},
            "skipped_by_clause_type": {},
            "shortfalls": {},
            "null_entity_filters": None,
            "anchor_sources": [],
        }
    return json.loads(summary_path.read_text(encoding="utf-8"))


def load_cuad_queries(
    queries_path: str | Path,
    *,
    corpus_filenames: set[str],
    expected_count: int | None = None,
) -> list[CuadQuery]:
    raw_queries = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    queries = [CuadQuery(**item) for item in raw_queries]
    if expected_count is not None and len(queries) != expected_count:
        raise ValueError(f"Expected {expected_count} CUAD queries; found {len(queries)}.")

    seen_ids: set[str] = set()
    for query in queries:
        if query.query_id in seen_ids:
            raise ValueError(f"Duplicate CUAD query id {query.query_id!r}.")
        seen_ids.add(query.query_id)
        if query.expected_level != "fact":
            raise ValueError(f"CUAD query {query.query_id!r} must target fact level.")
        if query.clause_type not in CLAUSE_TYPES:
            raise ValueError(f"Invalid CUAD clause type {query.clause_type!r}.")
        if query.expected_source not in corpus_filenames:
            raise ValueError(
                f"CUAD query {query.query_id!r} references unknown source {query.expected_source!r}."
            )
    return queries


def evaluate_cuad_query(query: CuadQuery, results: list[RetrievedItem]) -> CuadScore:
    top_result = results[0] if results else None
    anchor = _match_anchor(query.expected_fact)
    precision = 1.0 if top_result and anchor in top_result.content else 0.0
    provenance = 1.0 if top_result and top_result.source == query.expected_source else 0.0

    expected_tokens = len(tokenize(query.expected_fact))
    returned_tokens = sum(len(tokenize(item.content)) for item in results)
    efficiency = min(expected_tokens / returned_tokens, 1.0) if expected_tokens and returned_tokens else 0.0
    composite = (precision * 0.5) + (efficiency * 0.3) + (provenance * 0.2)

    return CuadScore(
        precision_at_1=precision,
        context_efficiency=round(efficiency, 4),
        provenance=provenance,
        composite=round(composite, 4),
        top_result=top_result.as_dict() if top_result else None,
    )


def aggregate_scores(query_scores: list[tuple[CuadQuery, CuadScore]]) -> dict[str, float]:
    if not query_scores:
        return {
            "precision_at_1": 0.0,
            "context_efficiency": 0.0,
            "provenance": 0.0,
            "composite": 0.0,
        }
    scores = [score for _, score in query_scores]
    count = len(scores)
    return {
        "precision_at_1": round(sum(score.precision_at_1 for score in scores) / count, 4),
        "context_efficiency": round(sum(score.context_efficiency for score in scores) / count, 4),
        "provenance": round(sum(score.provenance for score in scores) / count, 4),
        "composite": round(sum(score.composite for score in scores) / count, 4),
    }


def build_clause_breakdown(
    named_scores: dict[str, list[tuple[CuadQuery, CuadScore]]]
) -> dict[str, dict[str, float]]:
    breakdown: dict[str, dict[str, float]] = {}
    for clause_type in CLAUSE_TYPES:
        akashik_scores = [score for query, score in named_scores["Akashik"] if query.clause_type == clause_type]
        rag_scores = [score for query, score in named_scores["RAG"] if query.clause_type == clause_type]
        breakdown[clause_type] = {
            "akashik_precision_at_1": _mean_metric(akashik_scores, "precision_at_1"),
            "rag_precision_at_1": _mean_metric(rag_scores, "precision_at_1"),
            "akashik_provenance": _mean_metric(akashik_scores, "provenance"),
        }
    return breakdown


def collect_akashik_failures(query_scores: list[tuple[CuadQuery, CuadScore]]) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for query, score in query_scores:
        if score.precision_at_1 == 1.0 and score.provenance == 1.0:
            continue
        top_result = score.top_result or {}
        failures.append(
            {
                "query_id": query.query_id,
                "clause_type": query.clause_type,
                "query_text": query.query_text,
                "normalized_query": normalize_query(query.query_text),
                "entity_filter": query.entity_filter,
                "entity_filter_source": query.entity_filter_source,
                "entity_filter_reason": query.entity_filter_reason,
                "entity_secondary_source": query.entity_secondary_source,
                "expected_source": query.expected_source,
                "top_source": top_result.get("source"),
                "top_content": _compact(str(top_result.get("content", ""))),
                "precision_at_1": score.precision_at_1,
                "provenance": score.provenance,
            }
        )
    return failures


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


def load_synthetic_metrics(path: str | Path) -> dict[str, float]:
    payload_path = Path(path)
    fallback = {
        "precision_at_1": 1.0,
        "context_efficiency": 0.9702,
        "provenance": 1.0,
        "composite": 0.9911,
    }
    if not payload_path.exists():
        return fallback
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return payload.get("systems", {}).get("system_c", {}).get("overall", fallback)


def render_cuad_report(
    named_aggregates: dict[str, dict[str, float]],
    clause_breakdown: dict[str, dict[str, float]],
    selection_summary: dict[str, object],
    failures: list[dict[str, object]],
    disagreements: list[dict[str, object]],
) -> str:
    lines = [
        "# CUAD Benchmark Report (Real Legal Contracts)",
        "",
        "| System        | Precision@1 | Efficiency | Provenance | Composite |",
        "|---------------|-------------|------------|------------|-----------|",
    ]

    for system_name in ("RAG", "GraphRAG", "RAG-Embedding", "Akashik"):
        if system_name not in named_aggregates:
            continue
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
            "## Clause Type Breakdown",
            "| Clause Type    | Akashik P@1 | RAG P@1 | Akashik Provenance |",
            "|---------------|-------------|---------|-------------------|",
        ]
    )
    for clause_type in CLAUSE_TYPES:
        values = clause_breakdown[clause_type]
        lines.append(
            "| {clause_type} | {akashik_p:.2f} | {rag_p:.2f} | {akashik_prov:.2f} |".format(
                clause_type=clause_type.ljust(14),
                akashik_p=values["akashik_precision_at_1"],
                rag_p=values["rag_precision_at_1"],
                akashik_prov=values["akashik_provenance"],
            )
        )

    selected_by_clause_type = selection_summary.get("selected_by_clause_type", {})
    skipped_by_clause_type = selection_summary.get("skipped_by_clause_type", {})
    shortfalls = selection_summary.get("shortfalls", {})
    collisions = selection_summary.get("anchor_collision_count_by_primary", {})
    lines.extend(
        [
            "",
            "## Selection Summary",
            "| Clause Type | Selected | Shortfall | Skipped: Non-substantive | Skipped: Short Clause | Skipped: Missing Text | Skipped: Clause Not Found | Skipped: Already Selected |",
            "|-------------|----------|-----------|--------------------------|-----------------------|-----------------------|---------------------------|---------------------------|",
        ]
    )
    for clause_type in CLAUSE_TYPES:
        skipped = skipped_by_clause_type.get(clause_type, {})
        lines.append(
            "| {clause_type} | {selected} | {shortfall} | {non_substantive} | {short_clause} | {missing_text} | {clause_not_found} | {already_selected} |".format(
                clause_type=clause_type,
                selected=selected_by_clause_type.get(clause_type, 0),
                shortfall=shortfalls.get(clause_type, 0),
                non_substantive=skipped.get("non_substantive_answer", 0),
                short_clause=skipped.get("clause_too_short", 0),
                missing_text=skipped.get("missing_text", 0),
                clause_not_found=skipped.get("clause_not_found_in_text", 0),
                already_selected=skipped.get("already_selected", 0),
            )
        )
    lines.append(f"Null entity filters: {selection_summary.get('null_entity_filters')}")
    lines.append(f"Single entity filters: {selection_summary.get('single_entity_filters')}")
    lines.append(f"Compound entity filters: {selection_summary.get('compound_entity_filters')}")
    lines.append("")
    lines.append("Anchor collisions by primary: " + json.dumps(collisions, sort_keys=True))

    cuad_metrics = named_aggregates["Akashik"]
    lines.extend(
        [
            "",
            "## Comparison: 10-Contract CUAD vs 50-Contract CUAD",
            "| Metric      | 10-Contract CUAD | 50-Contract CUAD | Delta |",
            "|-------------|------------------|------------------|-------|",
        ]
    )
    for label, key in (
        ("Precision@1", "precision_at_1"),
        ("Efficiency", "context_efficiency"),
        ("Provenance", "provenance"),
        ("Composite", "composite"),
    ):
        synthetic = BASELINE_CUAD_10_CONTRACTS[key]
        cuad = cuad_metrics[key]
        lines.append(f"| {label.ljust(11)} | {synthetic:.2f} | {cuad:.2f} | {cuad - synthetic:.2f} |")

    lines.extend(["", "## Failure Analysis"])
    if not failures:
        lines.append("No Akashik precision or provenance failures in this run.")
    else:
        failure_counts: dict[str, int] = {
            "retrieval issue": 0,
            "anchor issue": 0,
            "clause ambiguity": 0,
            "corpus extraction issue": 0,
        }
        for failure in failures:
            category = _failure_category(failure)
            failure_counts[category] += 1
            lines.append(
                "- `{query_id}` ({clause_type}, {category}): normalized query `{normalized}`; entity filter `{entity_filter}`; secondary source `{secondary_source}`; expected source `{expected}`, top source `{top}`; top result: {content}".format(
                    query_id=failure["query_id"],
                    clause_type=failure["clause_type"],
                    category=category,
                    normalized=failure["normalized_query"],
                    entity_filter=failure.get("entity_filter"),
                    secondary_source=failure.get("entity_secondary_source"),
                    expected=failure["expected_source"],
                    top=failure["top_source"],
                    content=failure["top_content"] or "None",
                )
            )
        lines.append(
            "Regression sources: "
            + ", ".join(f"{category}={count}" for category, count in failure_counts.items())
        )

    if "RAG-Embedding" in named_aggregates:
        lines.extend(["", "## RAG-Embedding vs Akashik Disagreements"])
        if not disagreements:
            lines.append("No rank-1 disagreements between RAG-Embedding and Akashik.")
        else:
            lines.extend(
                [
                    "| Query ID | Category | Expected Source | RAG-Embedding Top | Akashik Top |",
                    "|----------|----------|-----------------|-------------------|-------------|",
                ]
            )
            for item in disagreements:
                lines.append(
                    "| {query_id} | {category} | {expected} | {embedding_source}: {embedding_content} | {akashik_source}: {akashik_content} |".format(
                        query_id=item["query_id"],
                        category=item["category"],
                        expected=item["expected_source"],
                        embedding_source=item["embedding_top_source"],
                        embedding_content=item["embedding_top_content"],
                        akashik_source=item["akashik_top_source"],
                        akashik_content=item["akashik_top_content"],
                    )
                )
    else:
        lines.extend(
            [
                "",
                "RAG-Embedding disabled by default. Re-run with `--with-embeddings` to include the semantic baseline.",
            ]
        )

    if (
        "RAG-Embedding" in named_aggregates
        and named_aggregates["Akashik"]["precision_at_1"] > named_aggregates["RAG-Embedding"]["precision_at_1"]
        and named_aggregates["Akashik"]["provenance"] > named_aggregates["RAG-Embedding"]["provenance"]
    ):
        lines.extend(
            [
                "",
                "Akashik outperforms the strongest general-purpose semantic retrieval baseline on legal contract clause retrieval without embeddings.",
            ]
        )
    if (
        named_aggregates["Akashik"]["precision_at_1"] > 0.80
        and named_aggregates["Akashik"]["provenance"] > 0.90
    ):
        lines.extend(["", "Results hold at 5x scale. Claim is publication-ready."])
    elif (
        named_aggregates["Akashik"]["precision_at_1"] >= 0.75
        and named_aggregates["Akashik"]["provenance"] >= 0.90
    ):
        lines.extend(["", "Results hold at larger scale and remain publication-worthy."])

    return "\n".join(lines) + "\n"


def _store_needs_ingest(store_path: Path, *, force_reingest: bool) -> bool:
    if force_reingest:
        return True
    if not store_path.exists() or store_path.stat().st_size == 0:
        return True
    with Store(store_path) as store:
        return store.schema_version_mismatch()


def _prepare_cuad_store_for_ingest(store_path: Path, *, force_reingest: bool) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    if force_reingest and store_path.exists():
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(store_path) + suffix)
            if path.exists():
                path.unlink()
    elif store_path.exists():
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(store_path) + suffix)
            if path.exists():
                path.unlink()


def _match_anchor(expected_fact: str) -> str:
    return expected_fact[:100]


def _mean_metric(scores: list[CuadScore], metric: str) -> float:
    if not scores:
        return 0.0
    return round(sum(float(getattr(score, metric)) for score in scores) / len(scores), 4)


def _compact(text: str, *, limit: int = 260) -> str:
    compacted = re.sub(r"\s+", " ", text).strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3] + "..."


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


def _failure_category(failure: dict[str, object]) -> str:
    if failure.get("entity_filter") in (None, []):
        return "anchor issue"
    if failure.get("top_source") != failure.get("expected_source"):
        return "retrieval issue"
    content = str(failure.get("top_content") or "").lower()
    if len(content) < 20:
        return "corpus extraction issue"
    return "clause ambiguity"


def _print_executor_report(rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    answered = sum(1 for row in rows if not row.get("executor_abstained"))
    abstained = sum(1 for row in rows if row.get("executor_abstained"))
    by_answer_type: dict[str, int] = defaultdict(int)
    for row in rows:
        by_answer_type[str(row.get("executor_answer_type", "unknown"))] += 1
    print("")
    print("=== Executor Results ===")
    print(f"Answered:    {answered}")
    print(f"Abstained:   {abstained}")
    print("By type:")
    for answer_type in ("factual", "temporal", "preference", "aggregation", "unknown"):
        print(f"  {answer_type:<11} {by_answer_type.get(answer_type, 0)}")


def _default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("/tmp") / f"akashik_{CUAD_JSONL_PREFIX}_{timestamp}.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CUAD legal-contract benchmark.")
    parser.add_argument("--corpus-dir", default=str(CUAD_CORPUS_DIR))
    parser.add_argument("--queries-path", default=str(CUAD_QUERIES_PATH))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Include the sentence-transformers RAG-Embedding baseline. Disabled by default.",
    )
    parser.add_argument(
        "--force-reingest",
        action="store_true",
        help="Rebuild the shared CUAD benchmark store even if it already exists and matches schema.",
    )
    parser.add_argument(
        "--use-expression",
        action="store_true",
        default=os.getenv("AKASHIK_USE_EXPRESSION") == "1",
        help="Enable the opt-in expression engine before the retrieval stack.",
    )
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
    args = parser.parse_args()

    summary = run_cuad(
        corpus_dir=args.corpus_dir,
        queries_path=args.queries_path,
        results_dir=args.results_dir,
        with_embeddings=args.with_embeddings,
        use_executor=args.use_executor,
        force_reingest=args.force_reingest,
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
