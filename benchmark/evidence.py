"""Benchmark evidence tooling: manifest, README table generation, drift check.

Published benchmark numbers in README.md live between marker comments and
are generated from raw artifacts under benchmarks/evidence/<date>/ — never
edited by hand. Commands:

    ./.venv/bin/python -m benchmark.evidence manifest   # (re)build manifest.json
    ./.venv/bin/python -m benchmark.evidence tables     # rewrite README blocks
    ./.venv/bin/python -m benchmark.evidence check      # fail if README drifted

`check` is pure stdlib over repo files and runs in CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "benchmarks" / "evidence"
README_PATH = REPO_ROOT / "README.md"

ACMB_ADAPTER_COLUMNS = [
    ("akashik", "Akashik"),
    ("rag_akashik", "rag_akashik"),
    ("bm25_akashik", "bm25_akashik"),
    ("rag", "RAG"),
    ("full_context", "full_ctx"),
    ("bm25", "BM25"),
    ("tfidf", "TF-IDF"),
]
ACMB_METRIC_ROWS = [
    ("fact_recall", "Fact Recall"),
    ("belief_revision_score", "Belief Revision"),
    ("fact_precision", "Fact Precision"),
    ("temporal_correctness", "Temporal Correct"),
    ("distractor_penalty", "Distractor Penalty"),
]
CUAD_SYSTEMS = [("system_a", "RAG"), ("system_b", "GraphRAG"), ("system_c", "Akashik")]
QA_TYPE_ROWS = [
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "knowledge-update",
    "temporal-reasoning",
    "multi-session",
]
# Historical April 2026 results, kept verbatim for the dated comparison
# column. These predate the evidence system; the July column is computed
# from tracked verdict artifacts.
QA_APRIL_2026 = {
    "single-session-user": {"oracle_qwen": 0.81, "oracle_gpt": 0.84, "s_qwen": 0.86, "s_gpt": 0.84},
    "single-session-assistant": {"oracle_qwen": 0.84, "oracle_gpt": 0.88, "s_qwen": 0.79, "s_gpt": 0.86},
    "single-session-preference": {"oracle_qwen": 0.90, "oracle_gpt": 0.93, "s_qwen": 0.57, "s_gpt": 0.87},
    "knowledge-update": {"oracle_qwen": 0.67, "oracle_gpt": 0.86, "s_qwen": 0.61, "s_gpt": 0.75},
    "temporal-reasoning": {"oracle_qwen": 0.35, "oracle_gpt": 0.41, "s_qwen": 0.31, "s_gpt": 0.39},
    "multi-session": {"oracle_qwen": 0.29, "oracle_gpt": 0.45, "s_qwen": 0.32, "s_gpt": 0.36},
    "overall": {"oracle_qwen": 0.54, "oracle_gpt": 0.64, "s_qwen": 0.51, "s_gpt": 0.59},
}
TRACKED_PACKAGES = ("sentence-transformers", "openai-agents", "rank-bm25", "scikit-learn", "ollama")


def latest_evidence_dir() -> Path:
    candidates = sorted(path for path in EVIDENCE_ROOT.iterdir() if path.is_dir())
    if not candidates:
        raise SystemExit(f"No evidence directories under {EVIDENCE_ROOT}")
    return candidates[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ------------------------------------------------------------------ #
# Metric computation from raw artifacts                               #
# ------------------------------------------------------------------ #
def acmb_metrics(evidence_dir: Path) -> dict[str, dict]:
    metrics: dict[str, dict] = {}
    for path in sorted((evidence_dir / "acmb").glob("acmb_*.json")):
        payload = _load_json(path)
        metrics[str(payload["adapter"])] = {
            **{key: round(float(payload["summary"][key]), 3) for key, _ in ACMB_METRIC_ROWS},
            "latency_p50_ms": payload["latency_ms"]["p50"],
            "latency_p95_ms": payload["latency_ms"]["p95"],
            "n_personas": payload["n_personas"],
        }
    return metrics


def session_recall(recall_jsonl: Path) -> dict:
    rows = _jsonl_rows(recall_jsonl)
    scored = [row for row in rows if not str(row.get("question_id", "")).endswith("_abs")]
    hits = sum(
        1
        for row in scored
        if set(row.get("answer_session_ids", [])) & set(row.get("retrieved_session_ids", []))
    )
    return {
        "recall_at_10": round(hits / len(scored), 4) if scored else 0.0,
        "n_scored": len(scored),
        "n_excluded_abs": len(rows) - len(scored),
    }


def recall_metrics(evidence_dir: Path) -> dict[str, dict]:
    metrics = {}
    for split, filename in (("oracle", "recall_oracle.jsonl"), ("s", "recall_s.jsonl")):
        path = evidence_dir / "longmemeval" / filename
        if path.exists():
            metrics[split] = session_recall(path)
    return metrics


def qa_metrics(evidence_dir: Path) -> dict:
    summary = _load_json(evidence_dir / "qa_oracle" / "verdicts" / "all_summary.json")
    per_type = {
        question_type: entry["accuracy"] for question_type, entry in summary["per_type"].items()
    }
    return {
        "per_type": per_type,
        "overall": summary["overall_accuracy"],
        "judged": summary["judged"],
        "judge_model": summary["judge_model"],
        "votes": summary["votes"],
    }


def cuad_metrics(evidence_dir: Path) -> dict[str, dict]:
    metrics = {}
    for mode, filename in (("a", "results_cuad_50.json"), ("b", "results_cuad_b_50.json")):
        payload = _load_json(evidence_dir / "cuad" / filename)
        metrics[mode] = {
            label: {
                "precision_at_1": payload["systems"][key]["precision_at_1"],
                "context_efficiency": payload["systems"][key]["context_efficiency"],
                "composite": payload["systems"][key]["composite"],
            }
            for key, label in CUAD_SYSTEMS
        }
    return metrics


def headline_metrics(evidence_dir: Path) -> dict:
    return {
        "acmb": acmb_metrics(evidence_dir),
        "longmemeval_recall": recall_metrics(evidence_dir),
        "longmemeval_qa_oracle": qa_metrics(evidence_dir),
        "cuad": cuad_metrics(evidence_dir),
    }


# ------------------------------------------------------------------ #
# Manifest                                                            #
# ------------------------------------------------------------------ #
def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _package_versions() -> dict[str, str]:
    from importlib import metadata

    versions = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def _ollama_info() -> dict:
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as response:
            tags = json.load(response)
        return {
            "models": [
                {"name": model["name"], "digest": model.get("digest", "")}
                for model in tags.get("models", [])
            ]
        }
    except Exception:
        return {"models": [], "note": "ollama unreachable at manifest time"}


def _dataset_hashes() -> list[dict]:
    home = Path.home() / ".akashik" / "data" / "benchmarks"
    datasets = [
        home / "longmemeval" / "longmemeval_oracle.json",
        home / "longmemeval" / "longmemeval_s_cleaned.json",
    ]
    entries = []
    for path in datasets:
        if path.exists():
            entries.append(
                {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
            )
    return entries


def cmd_manifest(evidence_dir: Path) -> None:
    files = []
    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append(
            {
                "path": str(path.relative_to(evidence_dir)),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "evidence_version": 1,
        "evidence_date": evidence_dir.name,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {
            "git_commit": _git_commit(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "packages": _package_versions(),
            "ollama": _ollama_info(),
        },
        "datasets": _dataset_hashes(),
        "headline_metrics": headline_metrics(evidence_dir),
        "files": files,
    }
    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Manifest written: {manifest_path} ({len(files)} artifacts)")


# ------------------------------------------------------------------ #
# README table generation                                             #
# ------------------------------------------------------------------ #
def _caption(evidence_dir: Path, sources: str) -> str:
    return (
        f"*Generated from `benchmarks/evidence/{evidence_dir.name}/{sources}` "
        f"by `benchmark.evidence tables` — do not edit by hand.*"
    )


def render_acmb_table(evidence_dir: Path) -> str:
    metrics = acmb_metrics(evidence_dir)
    header = "| Metric | " + " | ".join(label for _key, label in ACMB_ADAPTER_COLUMNS) + " |"
    divider = "|---" * (len(ACMB_ADAPTER_COLUMNS) + 1) + "|"
    lines = [header, divider]
    for metric_key, metric_label in ACMB_METRIC_ROWS:
        cells = [f"{metrics[adapter][metric_key]:.3f}" for adapter, _ in ACMB_ADAPTER_COLUMNS]
        lines.append(f"| {metric_label} | " + " | ".join(cells) + " |")
    for latency_key, latency_label in (
        ("latency_p50_ms", "Latency p50"),
        ("latency_p95_ms", "Latency p95"),
    ):
        cells = [f"{metrics[adapter][latency_key]:.2f}ms" for adapter, _ in ACMB_ADAPTER_COLUMNS]
        lines.append(f"| {latency_label} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(_caption(evidence_dir, "acmb/"))
    return "\n".join(lines)


def render_recall_table(evidence_dir: Path) -> str:
    metrics = recall_metrics(evidence_dir)
    lines = [
        "| Split | Session Recall @10 | Scored instances |",
        "|---|---|---|",
    ]
    for split, label in (("oracle", "Oracle"), ("s", "S (noisy haystack)")):
        entry = metrics.get(split)
        if entry is None:
            continue
        lines.append(f"| {label} | {entry['recall_at_10']:.2f} | {entry['n_scored']} |")
    lines.append("")
    lines.append(_caption(evidence_dir, "longmemeval/"))
    return "\n".join(lines)


def render_qa_table(evidence_dir: Path) -> str:
    verified = qa_metrics(evidence_dir)
    lines = [
        "| Category | Apr 2026 Oracle qwen | Apr 2026 Oracle GPT-5.4-mini | Apr 2026 S qwen | Apr 2026 S GPT-5.4-mini | Jul 2026 verified Oracle qwen |",
        "|---|---|---|---|---|---|",
    ]
    for question_type in QA_TYPE_ROWS:
        april = QA_APRIL_2026[question_type]
        july = verified["per_type"].get(question_type)
        july_cell = f"{july:.2f}" if july is not None else "—"
        lines.append(
            f"| {question_type} | {april['oracle_qwen']:.2f} | {april['oracle_gpt']:.2f} "
            f"| {april['s_qwen']:.2f} | {april['s_gpt']:.2f} | {july_cell} |"
        )
    april_overall = QA_APRIL_2026["overall"]
    lines.append(
        f"| **Overall** | **{april_overall['oracle_qwen']:.2f}** | **{april_overall['oracle_gpt']:.2f}** "
        f"| **{april_overall['s_qwen']:.2f}** | **{april_overall['s_gpt']:.2f}** | **{verified['overall']:.2f}** |"
    )
    lines.append("")
    lines.append(
        f"*Jul 2026 column computed from {verified['judged']} judged answers "
        f"({verified['judge_model']}, {verified['votes']} votes) in "
        f"`qa_oracle/verdicts/`; Apr 2026 columns are historical (pre-evidence-system).*"
    )
    lines.append("")
    lines.append(_caption(evidence_dir, "qa_oracle/verdicts/"))
    return "\n".join(lines)


def _render_cuad_mode(evidence_dir: Path, mode: str) -> str:
    metrics = cuad_metrics(evidence_dir)[mode]
    lines = [
        "| System | P@1 | Context Efficiency | Composite |",
        "|---|---|---|---|",
    ]
    for _key, label in CUAD_SYSTEMS:
        entry = metrics[label]
        strong = "**" if label == "Akashik" else ""
        lines.append(
            f"| {label} | {entry['precision_at_1']:.2f} | {strong}{entry['context_efficiency']:.2f}{strong} "
            f"| {strong}{entry['composite']:.2f}{strong} |"
        )
    lines.append("")
    filename = "results_cuad_50.json" if mode == "a" else "results_cuad_b_50.json"
    lines.append(_caption(evidence_dir, f"cuad/{filename}"))
    return "\n".join(lines)


def render_cuad_a_table(evidence_dir: Path) -> str:
    return _render_cuad_mode(evidence_dir, "a")


def render_cuad_b_table(evidence_dir: Path) -> str:
    return _render_cuad_mode(evidence_dir, "b")


TABLES = {
    "acmb-7way": render_acmb_table,
    "longmemeval-recall": render_recall_table,
    "longmemeval-qa": render_qa_table,
    "cuad-mode-a": render_cuad_a_table,
    "cuad-mode-b": render_cuad_b_table,
}


def _marker_bounds(readme: str, table_id: str) -> tuple[int, int]:
    begin = f"<!-- BEGIN GENERATED: {table_id} -->"
    end = f"<!-- END GENERATED: {table_id} -->"
    start = readme.find(begin)
    stop = readme.find(end)
    if start == -1 or stop == -1:
        raise SystemExit(f"README markers missing for table {table_id!r}")
    return start + len(begin), stop


def cmd_tables(evidence_dir: Path) -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    for table_id, renderer in TABLES.items():
        content = "\n" + renderer(evidence_dir) + "\n"
        start, stop = _marker_bounds(readme, table_id)
        readme = readme[:start] + content + readme[stop:]
    README_PATH.write_text(readme, encoding="utf-8")
    print(f"README tables regenerated from {evidence_dir}")


def cmd_check(evidence_dir: Path) -> int:
    readme = README_PATH.read_text(encoding="utf-8")
    drifted = []
    for table_id, renderer in TABLES.items():
        expected = "\n" + renderer(evidence_dir) + "\n"
        start, stop = _marker_bounds(readme, table_id)
        if readme[start:stop] != expected:
            drifted.append(table_id)
    if drifted:
        print(f"README tables drifted from evidence: {', '.join(drifted)}")
        print("Regenerate with: ./.venv/bin/python -m benchmark.evidence tables")
        return 1
    print(f"README tables match evidence in {evidence_dir.name}: OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["manifest", "tables", "check"])
    parser.add_argument(
        "--evidence-dir",
        default=None,
        help="Evidence date directory; defaults to the latest under benchmarks/evidence/.",
    )
    args = parser.parse_args()
    evidence_dir = Path(args.evidence_dir) if args.evidence_dir else latest_evidence_dir()

    if args.command == "manifest":
        cmd_manifest(evidence_dir)
        return 0
    if args.command == "tables":
        cmd_tables(evidence_dir)
        return 0
    return cmd_check(evidence_dir)


if __name__ == "__main__":
    sys.exit(main())
