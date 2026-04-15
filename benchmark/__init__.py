"""Benchmark harness for retrieval system comparisons."""

from pathlib import Path

BENCHMARK_ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS_DIR = BENCHMARK_ROOT / "corpus"
DEFAULT_QUERIES_PATH = BENCHMARK_ROOT / "queries.json"
DEFAULT_RESULTS_DIR = BENCHMARK_ROOT.parent / "results"

__all__ = [
    "BENCHMARK_ROOT",
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_QUERIES_PATH",
    "DEFAULT_RESULTS_DIR",
]
