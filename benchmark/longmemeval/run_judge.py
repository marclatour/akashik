"""Post-process LongMemEval executor outputs with a local YES/NO judge."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import glob
import json
from pathlib import Path
import time

from akashik.judge import (
    CACHE_PATH,
    CONFIDENCE_CACHED,
    CONFIDENCE_DETERMINISTIC,
    judge_answer_with_voting,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local QA judging over LongMemEval executor results.")
    parser.add_argument("--results", required=True, help="JSONL results path or glob.")
    parser.add_argument("--data", required=True, help="LongMemEval dataset JSON path.")
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--votes", type=int, default=3)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    result_paths = sorted(glob.glob(args.results))
    if not result_paths:
        raise SystemExit(f"No result files matched: {args.results}")
    rows = []
    for path in result_paths:
        with open(path, encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())

    data = json.load(open(args.data, encoding="utf-8"))
    by_id = {_dataset_question_id(item): item for item in data}
    non_abs = [row for row in rows if not str(row["question_id"]).endswith("_abs")]
    cache_entries = 0
    if not args.no_cache and CACHE_PATH.exists():
        cache_entries = sum(1 for _ in CACHE_PATH.read_text(encoding="utf-8").splitlines() if _.strip())
    print(f"Cache: {cache_entries} entries loaded")

    judged = 0
    abstained = 0
    unparseable = 0
    deterministic = 0
    cached = 0
    model_judged = 0
    correct = 0
    by_type: dict[str, list[tuple[dict, object]]] = defaultdict(list)
    by_confidence: dict[str, list[bool | None]] = defaultdict(list)
    started_at = time.monotonic()

    for index, row in enumerate(non_abs, start=1):
        item = by_id.get(str(row["question_id"]))
        if item is None:
            continue
        result = judge_answer_with_voting(
            question_id=str(row["question_id"]),
            question=_dataset_question_text(item),
            expected=_dataset_answer_text(item),
            answer=row.get("executor_answer"),
            model=args.model,
            votes=args.votes,
            use_cache=not args.no_cache,
        )
        question_type = str(row.get("question_type") or _dataset_question_type(item))
        by_type[question_type].append((row, result))
        by_confidence[result.confidence].append(result.judgment)
        if result.abstained:
            abstained += 1
        else:
            judged += 1
            if result.judgment is True:
                correct += 1
        if result.judgment is None:
            unparseable += 1
        if result.confidence == CONFIDENCE_DETERMINISTIC:
            deterministic += 1
        elif result.confidence == CONFIDENCE_CACHED:
            cached += 1
        else:
            model_judged += 1

        if index % 10 == 0:
            acc_so_far = (correct / judged) if judged else 0.0
            print(
                f"Judged {index}/{len(non_abs)} | acc so far: {acc_so_far:.2f} | "
                f"det: {deterministic} | model: {model_judged} | "
                f"elapsed {str(timedelta(seconds=int(time.monotonic() - started_at)))}"
            )

    _print_report(
        dataset_name=Path(args.data).name,
        total=len(non_abs),
        judged=judged,
        abstained=abstained,
        unparseable=unparseable,
        correct=correct,
        deterministic=deterministic,
        model_judged=model_judged,
        cached=cached,
        by_type=by_type,
        by_confidence=by_confidence,
        model=args.model,
        votes=args.votes,
    )
    return 0


def _print_report(
    *,
    dataset_name: str,
    total: int,
    judged: int,
    abstained: int,
    unparseable: int,
    correct: int,
    deterministic: int,
    model_judged: int,
    cached: int,
    by_type: dict[str, list[tuple[dict, object]]],
    by_confidence: dict[str, list[bool | None]],
    model: str,
    votes: int,
) -> None:
    accuracy = (correct / judged) if judged else 0.0
    unparseable_rate = (unparseable / total) if total else 0.0
    print(f"=== QA Accuracy (Local Judge: {model}, votes={votes}) ===")
    print(f"Dataset:      {dataset_name}   N={total}")
    print(f"Abstained:    {abstained}  (excluded from accuracy)")
    print(f"Judged:       {judged}")
    print(f"Unparseable:  {unparseable}  ({unparseable_rate:.1%})")
    if unparseable_rate > 0.05:
        print("WARNING: unparseable rate >5%; prompt may need tightening")
    print("")
    print(
        f"Overall QA Accuracy:  {accuracy:.2f}  "
        f"(deterministic: {deterministic}, model: {model_judged}, cached: {cached})"
    )
    print("")
    print("--- Per question type ---")
    ordered = [
        "single-session-user",
        "single-session-assistant",
        "single-session-preference",
        "temporal-reasoning",
        "knowledge-update",
        "multi-session",
    ]
    dynamic_order = ordered + sorted(
        question_type for question_type in by_type.keys() if question_type not in ordered
    )
    for question_type in dynamic_order:
        subset = by_type.get(question_type, [])
        answered = [result for _row, result in subset if not result.abstained]
        correct_subset = sum(1 for _row, result in subset if result.judgment is True)
        acc = (correct_subset / len(answered)) if answered else 0.0
        abstained_subset = sum(1 for _row, result in subset if result.abstained)
        print(f"{question_type:<28} acc={acc:.2f}  n={len(answered)}  abstained={abstained_subset}")
    print("")
    print("--- By confidence tier ---")
    for tier in ("deterministic", "high", "medium", "low", "cached"):
        judgments = by_confidence.get(tier, [])
        correct_count = sum(1 for value in judgments if value is True)
        print(f"{tier:<13} {correct_count} correct / {len(judgments)} total")


def _dataset_question_id(item: dict[str, object]) -> str:
    return str(item.get("question_id") or item.get("query_id") or "")


def _dataset_question_text(item: dict[str, object]) -> str:
    return str(item.get("question") or item.get("query_text") or "")


def _dataset_answer_text(item: dict[str, object]) -> str:
    return str(item.get("answer") or item.get("expected_fact") or "")


def _dataset_question_type(item: dict[str, object]) -> str:
    return str(item.get("question_type") or item.get("clause_type") or "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
