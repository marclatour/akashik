"""Benchmark scoring logic."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from benchmark.queries import BenchmarkQuery, DIFFICULTIES
from benchmark.systems import RetrievedItem

_TOKEN_RE = re.compile(r"\b\w+\b")


@dataclass(slots=True)
class QueryScore:
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


def evaluate_query(query: BenchmarkQuery, results: list[RetrievedItem]) -> QueryScore:
    top_result = results[0] if results else None
    precision = 0.0
    provenance = 0.0

    if top_result and query.expected_fact in top_result.content:
        precision = 1.0
    if top_result and top_result.source == query.expected_source:
        provenance = 1.0

    expected_tokens = len(tokenize(query.expected_fact))
    returned_tokens = sum(len(tokenize(item.content)) for item in results)
    efficiency = 0.0
    if expected_tokens and returned_tokens:
        efficiency = min(expected_tokens / returned_tokens, 1.0)

    composite = (precision * 0.5) + (efficiency * 0.3) + (provenance * 0.2)
    return QueryScore(
        precision_at_1=precision,
        context_efficiency=round(efficiency, 4),
        provenance=provenance,
        composite=round(composite, 4),
        top_result=top_result.as_dict() if top_result else None,
    )


def aggregate_system_scores(
    query_scores: list[tuple[BenchmarkQuery, QueryScore]]
) -> dict[str, dict[str, dict[str, float]]]:
    overall_metrics = _mean_metrics([score for _, score in query_scores])
    by_difficulty: dict[str, dict[str, float]] = {}

    grouped: dict[str, list[QueryScore]] = defaultdict(list)
    for query, score in query_scores:
        grouped[query.difficulty].append(score)

    for difficulty in DIFFICULTIES:
        by_difficulty[difficulty] = _mean_metrics(grouped[difficulty])

    return {"overall": overall_metrics, "by_difficulty": by_difficulty}


def evaluate_gate(
    named_scores: dict[str, list[tuple[BenchmarkQuery, QueryScore]]],
    named_aggregates: dict[str, dict[str, dict[str, dict[str, float]]]],
) -> dict[str, object]:
    akashik_hard_precision = named_aggregates["Akashik"]["by_difficulty"]["hard"]["precision_at_1"]
    rag_hard_precision = named_aggregates["RAG"]["by_difficulty"]["hard"]["precision_at_1"]
    akashik_provenance = named_aggregates["Akashik"]["overall"]["provenance"]
    rag_provenance = named_aggregates["RAG"]["overall"]["provenance"]
    hard_precision_passed = akashik_hard_precision > rag_hard_precision
    provenance_passed = akashik_provenance > rag_provenance

    reasons: list[str] = []
    if not hard_precision_passed:
        reasons.append(
            f"Hard Precision@1 gate failed: Akashik={akashik_hard_precision:.2f}, RAG={rag_hard_precision:.2f}."
        )

    if not provenance_passed:
        reasons.append(
            f"Overall provenance gate failed: Akashik={akashik_provenance:.2f}, RAG={rag_provenance:.2f}."
        )

    hard_misses = [] if hard_precision_passed else _collect_misses(named_scores["Akashik"], difficulty="hard")
    rag_hard_hits = [] if hard_precision_passed else _collect_hits(named_scores["RAG"], difficulty="hard")
    provenance_misses = [] if provenance_passed else _collect_provenance_misses(named_scores["Akashik"])

    return {
        "passed": not reasons,
        "checks": {
            "akashik_vs_rag_hard_precision": {
                "akashik": round(akashik_hard_precision, 4),
                "rag": round(rag_hard_precision, 4),
                "passed": hard_precision_passed,
            },
            "akashik_vs_rag_overall_provenance": {
                "akashik": round(akashik_provenance, 4),
                "rag": round(rag_provenance, 4),
                "passed": provenance_passed,
            },
        },
        "reasons": reasons,
        "diagnostics": {
            "akashik_hard_precision_misses": hard_misses,
            "rag_hard_precision_hits": rag_hard_hits,
            "akashik_provenance_misses": provenance_misses,
        },
    }


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _mean_metrics(scores: list[QueryScore]) -> dict[str, float]:
    if not scores:
        return {
            "precision_at_1": 0.0,
            "context_efficiency": 0.0,
            "provenance": 0.0,
            "composite": 0.0,
        }

    count = len(scores)
    return {
        "precision_at_1": round(sum(score.precision_at_1 for score in scores) / count, 4),
        "context_efficiency": round(sum(score.context_efficiency for score in scores) / count, 4),
        "provenance": round(sum(score.provenance for score in scores) / count, 4),
        "composite": round(sum(score.composite for score in scores) / count, 4),
    }


def _collect_misses(
    query_scores: list[tuple[BenchmarkQuery, QueryScore]],
    *,
    difficulty: str,
) -> list[dict[str, object]]:
    misses: list[dict[str, object]] = []
    for query, score in query_scores:
        if query.difficulty != difficulty or score.precision_at_1 == 1.0:
            continue
        misses.append(
            {
                "query_id": query.query_id,
                "expected_source": query.expected_source,
                "top_source": score.top_result["source"] if score.top_result else None,
                "top_content": score.top_result["content"] if score.top_result else None,
            }
        )
    return misses


def _collect_hits(
    query_scores: list[tuple[BenchmarkQuery, QueryScore]],
    *,
    difficulty: str,
) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for query, score in query_scores:
        if query.difficulty != difficulty or score.precision_at_1 != 1.0:
            continue
        hits.append(
            {
                "query_id": query.query_id,
                "source": score.top_result["source"] if score.top_result else None,
            }
        )
    return hits


def _collect_provenance_misses(
    query_scores: list[tuple[BenchmarkQuery, QueryScore]]
) -> list[dict[str, object]]:
    misses: list[dict[str, object]] = []
    for query, score in query_scores:
        if score.provenance == 1.0:
            continue
        misses.append(
            {
                "query_id": query.query_id,
                "expected_source": query.expected_source,
                "top_source": score.top_result["source"] if score.top_result else None,
            }
        )
    return misses
