"""Run the LongMemEval retrieval-only benchmark."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from collections import defaultdict
import json
import logging
from pathlib import Path

from akashik.parse_temporal_scope import parse_temporal_scope
from akashik.parse_temporal_scope import _parse_question_date
from akashik.retrieve import retrieve, score_documents
from akashik.store import Store
from benchmark.longmemeval.ingest_adapter import ingest_instance

LOGGER = logging.getLogger(__name__)
TOP_K = 10


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LongMemEval retrieval evaluation.")
    parser.add_argument("--data", help="Path to LongMemEval JSON dataset.")
    parser.add_argument("--store", default="/tmp/longmemeval.db", help="SQLite store path.")
    parser.add_argument("--abstention-threshold", default=0.3, type=float)
    parser.add_argument("--output", help="JSONL output path.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N instances. Useful for faster diagnostics.",
    )
    parser.add_argument("--document-gate-n", type=int, default=5)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run a single synthetic instance smoke test without writing an output file.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.dry_run:
        return _run_dry_run(args.abstention_threshold)

    if not args.data:
        parser.error("--data is required unless --dry-run is set")
    if not args.output:
        parser.error("--output is required unless --dry-run is set")

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: data file not found: {args.data}")
        print("Download from: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned")
        return 1

    instances = json.loads(data_path.read_text(encoding="utf-8"))
    if args.limit:
        instances = instances[: args.limit]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    failed_instances = 0
    emitted: list[dict[str, object]] = []
    with Store(args.store) as store, output_path.open("w", encoding="utf-8") as handle:
        for index, instance in enumerate(instances, start=1):
            line = _process_instance(
                store,
                instance,
                abstention_threshold=args.abstention_threshold,
                document_gate_n=args.document_gate_n,
            )
            if line is None:
                failed_instances += 1
                continue
            emitted.append(line)
            handle.write(json.dumps(line, sort_keys=True) + "\n")
            if index % 10 == 0:
                print(".", end="", flush=True)
        if instances:
            print("")

    _print_report(
        dataset_name=data_path.name,
        rows=emitted,
        threshold=args.abstention_threshold,
        failed_instances=failed_instances,
    )
    return 0


def _run_dry_run(abstention_threshold: float) -> int:
    from tests.test_longmemeval_ingest import SYNTHETIC_INSTANCE

    with Store(":memory:") as store:
        line = _process_instance(
            store,
            SYNTHETIC_INSTANCE,
            abstention_threshold=abstention_threshold,
            document_gate_n=5,
        )
    print(json.dumps(line, sort_keys=True))
    return 0


def _process_instance(
    store,
    instance: dict,
    *,
    abstention_threshold: float,
    document_gate_n: int,
) -> dict[str, object] | None:
    question_id = str(instance.get("question_id", ""))
    try:
        ingest_instance(store, instance)
    except Exception:
        LOGGER.exception("Failed to ingest instance %s", question_id)
        return None

    temporal_scope = parse_temporal_scope(
        str(instance.get("question", "")),
        str(instance.get("question_date", "")),
    )
    entity_filters: dict[str, str | list[str]] = {"instance_id": question_id}
    question_type = str(instance.get("question_type", ""))
    if question_type == "single-session-user":
        entity_filters["speaker"] = "user"
    elif question_type == "single-session-assistant":
        entity_filters["speaker"] = "assistant"
    if temporal_scope is not None:
        entity_filters["session_date_start"] = str(temporal_scope[0])
        entity_filters["session_date_end"] = str(temporal_scope[1])
    retrieval_filters = {
        key: value
        for key, value in entity_filters.items()
        if not key.startswith("session_date_")
    }
    gated_doc_ids: list[str] = []
    if document_gate_n > 0:
        gated_doc_ids = score_documents(
            store,
            str(instance.get("question", "")),
            retrieval_filters,
            top_n=document_gate_n,
        )
        LOGGER.debug(
            "instance %s: correct sessions %s, gate selected %s",
            question_id,
            list(instance.get("answer_session_ids", [])),
            gated_doc_ids,
        )

    try:
        response = retrieve(
            str(instance.get("question", "")),
            store,
            level="fact",
            limit=TOP_K,
            entity_filters=retrieval_filters,
            document_gate_n=document_gate_n,
        )
    except Exception:
        LOGGER.exception("Failed to retrieve for instance %s", question_id)
        return None

    results = response.results
    if temporal_scope is not None:
        results = _filter_results_by_session_date(
            results,
            start=entity_filters["session_date_start"],
            end=entity_filters["session_date_end"],
            question_id=question_id,
        )

    top_confidence = results[0].confidence if results else 0.0
    abstained = (not results) or (top_confidence < abstention_threshold)
    retrieved_session_ids = _retrieved_session_ids(results[:TOP_K])
    has_answer_hit = any(result.unit.metadata.get("has_answer") == "true" for result in results[:TOP_K])

    return {
        "question_id": question_id,
        "question_type": question_type,
        "retrieved_session_ids": retrieved_session_ids,
        "top_confidence": top_confidence,
        "abstained": abstained,
        "has_answer_hit": has_answer_hit,
        "answer_session_ids": list(instance.get("answer_session_ids", [])),
    }


def _filter_results_by_session_date(results, *, start: str, end: str, question_id: str):
    # TODO: push date range filtering into the retrieval layer so scoped FTS never sees out-of-range sessions.
    start_date = _parse_question_date(start)
    end_date = _parse_question_date(end)
    filtered = [
        result
        for result in results
        if _result_in_session_date_range(result, start_date, end_date)
    ]
    removed = len(results) - len(filtered)
    if removed:
        LOGGER.info("Filtered %s out-of-range results for %s", removed, question_id)
    return filtered


def _result_in_session_date_range(result, start_date, end_date) -> bool:
    session_date = str(result.unit.metadata.get("session_date", "")).strip()
    if not session_date:
        return False
    try:
        normalized = _parse_question_date(session_date)
    except ValueError:
        return False
    return start_date <= normalized <= end_date


def _retrieved_session_ids(results) -> list[str]:
    session_ids: list[str] = []
    for result in results:
        session_id = str(result.unit.metadata.get("session_id", "")).strip()
        if not session_id or session_id in session_ids:
            continue
        session_ids.append(session_id)
    return session_ids


def _print_report(
    *,
    dataset_name: str,
    rows: list[dict[str, object]],
    threshold: float,
    failed_instances: int,
) -> None:
    non_abstention_rows = [row for row in rows if not str(row["question_id"]).endswith("_abs")]
    total = len(non_abstention_rows)
    session_recall = _safe_divide(
        sum(
            1
            for row in non_abstention_rows
            if set(row["answer_session_ids"]) & set(row["retrieved_session_ids"])
        ),
        total,
    )
    turn_recall = _safe_divide(sum(1 for row in non_abstention_rows if row["has_answer_hit"]), total)
    abstention_rows = [row for row in rows if str(row["question_id"]).endswith("_abs")]

    print("=== LongMemEval Results ===")
    print(f"Dataset:   {dataset_name}   N={total}")
    print(f"Threshold: {threshold}")
    print("")
    print(f"Session Recall @10:     {session_recall:.2f}")
    print(f"Turn Recall:            {turn_recall:.2f}")
    print(
        f"Abstention:             N={len(abstention_rows)} instances excluded from metrics "
        "(reader-layer concern, no generator in pipeline)"
    )
    print("")
    print("--- Per question type ---")

    by_type: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in non_abstention_rows:
        by_type[str(row["question_type"])].append(row)

    ordered_types = [
        "single-session-user",
        "single-session-assistant",
        "single-session-preference",
        "temporal-reasoning",
        "knowledge-update",
        "multi-session",
    ]
    for question_type in ordered_types:
        subset = by_type.get(question_type, [])
        session_metric = _safe_divide(
            sum(1 for row in subset if set(row["answer_session_ids"]) & set(row["retrieved_session_ids"])),
            len(subset),
        )
        turn_metric = _safe_divide(sum(1 for row in subset if row["has_answer_hit"]), len(subset))
        print(
            f"{question_type:<28} session={session_metric:.2f}  "
            f"turn={turn_metric:.2f}  n={len(subset)}"
        )
    print(f"Failed instances: {failed_instances}")


def _safe_divide(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


if __name__ == "__main__":
    raise SystemExit(main())
