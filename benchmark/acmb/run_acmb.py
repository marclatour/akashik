from __future__ import annotations

"""
ACMB v0.1 benchmark runner.
Usage: ./.venv/bin/python benchmark/acmb/run_acmb.py --adapter akashik
"""

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import glob
import inspect
import json
import os
import time
from pathlib import Path

from benchmark.acmb.evaluate_acmb import evaluate_benchmark, evaluate_persona, resolve_fact_ids
from benchmark.acmb.generate_personas import main as generate_personas_main

DEFAULT_PERSONAS_DIR = os.path.expanduser("~/.akashik/data/benchmarks/acmb/personas")
DEFAULT_QUERIES_DIR = os.path.expanduser("~/.akashik/data/benchmarks/acmb/queries")
DEFAULT_STORES_DIR = os.path.expanduser("~/.akashik/stores/benchmarks/acmb")


def load_personas(personas_dir: str) -> list[dict]:
    paths = sorted(glob.glob(f"{personas_dir}/persona_*.json"))
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]


def load_queries(queries_dir: str) -> dict[str, list[dict]]:
    paths = sorted(glob.glob(f"{queries_dir}/queries_*.json"))
    result: dict[str, list[dict]] = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        result[data["persona_id"]] = data["queries"]
    return result


def ensure_acmb_data(personas_dir: str, queries_dir: str) -> None:
    personas = sorted(glob.glob(f"{personas_dir}/persona_*.json"))
    queries = sorted(glob.glob(f"{queries_dir}/queries_*.json"))
    if personas and queries:
        return
    generate_personas_main()


def get_adapter(name: str, store_path: str):
    if name == "akashik":
        from benchmark.acmb.adapters.akashik_adapter import AkashikAdapter

        return AkashikAdapter(store_path=store_path)
    if name == "rag":
        from benchmark.acmb.adapters.rag_adapter import RagAdapter

        return RagAdapter()
    if name == "full_context":
        from benchmark.acmb.adapters.full_context_adapter import FullContextAdapter

        return FullContextAdapter()
    raise ValueError(f"Unknown adapter: {name}")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round((len(ordered) - 1) * percentile)), len(ordered) - 1)
    return ordered[index]


def _query_adapter(adapter, query_text: str, *, k: int, as_of: str) -> list[str]:
    try:
        signature = inspect.signature(adapter.query)
    except (TypeError, ValueError):
        signature = None
    if signature is not None and "as_of" in signature.parameters:
        return adapter.query(query_text, k=k, as_of=as_of)
    return adapter.query(query_text, k=k)


def _ingest_turn(adapter, turn: dict, *, commitments: list[dict]) -> None:
    try:
        signature = inspect.signature(adapter.ingest_turn)
    except (TypeError, ValueError):
        signature = None
    if signature is not None and "commitments" in signature.parameters:
        adapter.ingest_turn(turn, commitments=commitments)
        return
    adapter.ingest_turn(turn)


def _verbose_query_output(
    *,
    enabled: bool,
    persona_id: str,
    query: dict,
    returned_texts: list[str],
    matched_fact_ids: list[str],
) -> None:
    if not enabled:
        return
    must_include = query.get("must_include", [])
    missed = [fact_id for fact_id in must_include if fact_id not in matched_fact_ids]
    print(f"\n[{persona_id}::{query['query_id']}] {query['query_text']}")
    print(f"  returned_texts={returned_texts}")
    print(f"  matched_fact_ids={matched_fact_ids}")
    print(f"  missed_must_include={missed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="akashik")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--personas-dir", default=DEFAULT_PERSONAS_DIR)
    parser.add_argument("--queries-dir", default=DEFAULT_QUERIES_DIR)
    parser.add_argument("--stores-dir", default=DEFAULT_STORES_DIR)
    parser.add_argument("--match-threshold", type=float, default=0.5)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--keep-output", action="store_true")
    args = parser.parse_args()

    ensure_acmb_data(args.personas_dir, args.queries_dir)
    personas = load_personas(args.personas_dir)
    queries = load_queries(args.queries_dir)
    print(f"ACMB v0.1 | adapter={args.adapter} | k={args.k} | personas={len(personas)}")

    all_results = []
    latency_ms: list[float] = []
    for persona in personas:
        persona_id = persona["persona_id"]
        persona_queries = queries.get(persona_id, [])
        pending = {query["query_id"]: query for query in persona_queries}
        returned_by_query: dict[str, list[str]] = {}
        store_path = os.path.join(args.stores_dir, f"{persona_id}.db")
        adapter = get_adapter(args.adapter, store_path)
        adapter.reset()
        query_latencies: list[float] = []

        for session in persona["sessions"]:
            current_date = session["simulated_date"]
            for turn in session["turns"]:
                _ingest_turn(
                    adapter,
                    {**turn, "simulated_date": current_date},
                    commitments=persona.get("commitments", []),
                )
                for query in persona_queries:
                    if query["query_id"] in returned_by_query:
                        continue
                    if turn["turn_id"] != query["turn_before"]:
                        continue
                    started = time.perf_counter()
                    returned_texts = _query_adapter(
                        adapter,
                        query["query_text"],
                        k=args.k,
                        as_of=current_date,
                    )
                    all_facts = persona.get("facts", []) + [
                        {
                            "fact_id": commitment["commitment_id"],
                            "natural_language": commitment["description"],
                        }
                        for commitment in persona.get("commitments", [])
                    ]
                    matched_fact_ids = resolve_fact_ids(
                        returned_texts,
                        all_facts,
                        threshold=args.match_threshold,
                    )
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latency_ms.append(elapsed_ms)
                    query_latencies.append(elapsed_ms)
                    returned_by_query[query["query_id"]] = matched_fact_ids
                    _verbose_query_output(
                        enabled=args.verbose,
                        persona_id=persona_id,
                        query=query,
                        returned_texts=returned_texts,
                        matched_fact_ids=matched_fact_ids,
                    )
                    pending.pop(query["query_id"], None)

        for query in pending.values():
            started = time.perf_counter()
            returned_texts = _query_adapter(
                adapter,
                query["query_text"],
                k=args.k,
                as_of=persona["sessions"][-1]["simulated_date"],
            )
            all_facts = persona.get("facts", []) + [
                {
                    "fact_id": commitment["commitment_id"],
                    "natural_language": commitment["description"],
                }
                for commitment in persona.get("commitments", [])
            ]
            matched_fact_ids = resolve_fact_ids(
                returned_texts,
                all_facts,
                threshold=args.match_threshold,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            latency_ms.append(elapsed_ms)
            query_latencies.append(elapsed_ms)
            returned_by_query[query["query_id"]] = matched_fact_ids
            _verbose_query_output(
                enabled=args.verbose,
                persona_id=persona_id,
                query=query,
                returned_texts=returned_texts,
                matched_fact_ids=matched_fact_ids,
            )

        result = evaluate_persona(returned_by_query, persona_queries, k=args.k)
        result["persona_id"] = persona_id
        all_results.append(result)
        print(
            f"  {persona_id}: recall={result['fact_recall']:.2f} "
            f"revision={result['belief_revision_score']:.2f} "
            f"precision={result['fact_precision']:.2f} "
            f"temporal={result['temporal_correctness']:.2f} "
            f"distractors={result['distractor_penalty']:.2f}"
        )

    summary = evaluate_benchmark(all_results)
    print("\n=== ACMB v0.1 Results ===")
    print(f"Adapter:               {args.adapter}")
    print(f"Personas:              {summary['n_personas']}")
    print(f"Fact Recall @k:        {summary['fact_recall']:.3f}")
    print(f"Belief Revision Score: {summary['belief_revision_score']:.3f}")
    print(f"Fact Precision:        {summary['fact_precision']:.3f}")
    print(f"Temporal Correctness:  {summary['temporal_correctness']:.3f}")
    print(f"Distractor Penalty:    {summary['distractor_penalty']:.3f}")
    print(f"Query Latency p50:     {_percentile(latency_ms, 0.50):.2f}ms")
    print(f"Query Latency p95:     {_percentile(latency_ms, 0.95):.2f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
