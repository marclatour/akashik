from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from benchmark.corpus import load_corpus
from benchmark.evaluate import evaluate_query
from benchmark.queries import BenchmarkQuery, load_queries
from benchmark.systems import RetrievedItem


def test_benchmark_corpus_and_queries_validate() -> None:
    documents = load_corpus()
    queries = load_queries(corpus_filenames={document.filename for document in documents})

    assert 10 <= len(documents) <= 20
    assert min(document.word_count for document in documents) >= 500
    assert len(queries) >= 20


def test_evaluate_query_scores_expected_metrics() -> None:
    query = BenchmarkQuery(
        query_id="q1",
        query_text="alpha beta",
        expected_fact="alpha beta",
        expected_source="doc.txt",
        expected_level="fact",
        difficulty="easy",
    )
    results = [
        RetrievedItem(content="alpha beta gamma delta", source="doc.txt", rank=1),
        RetrievedItem(content="noise only", source="other.txt", rank=2),
    ]

    score = evaluate_query(query, results)

    assert score.precision_at_1 == 1.0
    assert score.provenance == 1.0
    assert score.context_efficiency == 0.3333
    assert score.composite == 0.8


def test_benchmark_run_script_writes_outputs(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    results_dir = tmp_path / "results"
    command = [
        sys.executable,
        "benchmark/run.py",
        "--results-dir",
        str(results_dir),
    ]

    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise AssertionError(f"benchmark/run.py failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")

    assert (results_dir / "results.json").exists()
    assert (results_dir / "report.md").exists()
    assert "gate: PASS" in completed.stdout
