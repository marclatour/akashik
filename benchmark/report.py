"""Benchmark result formatting helpers."""

from __future__ import annotations

import json
from pathlib import Path


def build_results_payload(
    *,
    corpus_size: int,
    query_count: int,
    per_query_results: list[dict[str, object]],
    blind_aggregates: dict[str, dict[str, object]],
    gate: dict[str, object],
) -> dict[str, object]:
    return {
        "benchmark": {
            "corpus_documents": corpus_size,
            "query_count": query_count,
            "blind_evaluation": True,
        },
        "systems": blind_aggregates,
        "queries": per_query_results,
        "gate": gate,
    }


def render_report(
    named_aggregates: dict[str, dict[str, dict[str, dict[str, float]]]],
    gate: dict[str, object],
    disagreements: list[dict[str, object]] | None = None,
) -> str:
    lines = [
        "# Benchmark Report",
        "",
        "| System        | Precision@1 | Efficiency | Provenance | Composite | Easy | Medium | Hard |",
        "|---------------|-------------|------------|------------|-----------|------|--------|------|",
    ]

    for system_name in ("RAG", "GraphRAG", "RAG-Embedding", "Akashik"):
        aggregate = named_aggregates[system_name]
        overall = aggregate["overall"]
        by_difficulty = aggregate["by_difficulty"]
        lines.append(
            "| {name} | {precision:.2f} | {efficiency:.2f} | {provenance:.2f} | {composite:.2f} | {easy:.2f} | {medium:.2f} | {hard:.2f} |".format(
                name=system_name.ljust(8),
                precision=overall["precision_at_1"],
                efficiency=overall["context_efficiency"],
                provenance=overall["provenance"],
                composite=overall["composite"],
                easy=by_difficulty["easy"]["composite"],
                medium=by_difficulty["medium"]["composite"],
                hard=by_difficulty["hard"]["composite"],
            )
        )

    lines.extend(
        [
            "",
            "Difficulty columns are average composite scores by difficulty.",
            "",
            f"Gate status: {'PASS' if gate['passed'] else 'FAIL'}",
        ]
    )

    if gate["reasons"]:
        lines.append("")
        lines.append("## Gate Failure Reasons")
        lines.extend([f"- {reason}" for reason in gate["reasons"]])

    diagnostics = gate["diagnostics"]
    if diagnostics["akashik_hard_precision_misses"] or diagnostics["akashik_provenance_misses"]:
        lines.append("")
        lines.append("## Diagnostics")
        for miss in diagnostics["akashik_hard_precision_misses"]:
            lines.append(
                f"- Akashik hard miss {miss['query_id']}: expected {miss['expected_source']}, got {miss['top_source']}."
            )
        for miss in diagnostics["akashik_provenance_misses"]:
            lines.append(
                f"- Akashik provenance miss {miss['query_id']}: expected {miss['expected_source']}, got {miss['top_source']}."
            )

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

    return "\n".join(lines) + "\n"


def write_json(path: str | Path, payload: dict[str, object]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(path: str | Path, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")
