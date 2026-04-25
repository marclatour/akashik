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
import hashlib
import json
import os
from pathlib import Path
import time

from akashik.judge import (
    CACHE_PATH,
    CONFIDENCE_CACHED,
    CONFIDENCE_DETERMINISTIC,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    JudgeResult,
    judge_answer_with_voting,
)

_DEFAULT_OLLAMA_JUDGE_MODEL = "qwen2.5:1.5b"
_DEFAULT_OPENAI_JUDGE_MODEL = "gpt-4.1-mini"
_OPENAI_JUDGE_PROMPT_TEMPLATE = """You are evaluating whether an answer correctly responds to a question.

Question: {question}
Expected answer: {expected}
Given answer: {answer}

Does the given answer correctly answer the question?
Respond with only YES or NO."""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local QA judging over LongMemEval executor results.")
    parser.add_argument("--results", required=True, help="JSONL results path or glob.")
    parser.add_argument("--data", required=True, help="LongMemEval dataset JSON path.")
    parser.add_argument(
        "--judge-backend",
        choices=["ollama", "openai"],
        default="ollama",
        help="Judge backend. ollama uses local qwen2.5:1.5b. openai uses GPT.",
    )
    parser.add_argument(
        "--judge-model",
        "--model",
        dest="judge_model",
        default=None,
        help="Model for judge backend. Defaults: ollama=qwen2.5:1.5b, openai=gpt-4.1-mini",
    )
    parser.add_argument("--votes", type=int, default=3)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    judge_model = args.judge_model or (
        _DEFAULT_OLLAMA_JUDGE_MODEL if args.judge_backend == "ollama" else _DEFAULT_OPENAI_JUDGE_MODEL
    )
    if args.judge_backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set.")

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
    judge_latency_ms = 0.0
    judge_calls = 0

    for index, row in enumerate(non_abs, start=1):
        item = by_id.get(str(row["question_id"]))
        if item is None:
            continue
        if args.judge_backend == "openai":
            result, latency_delta, call_count_delta = _judge_answer_with_openai_voting(
                question_id=str(row["question_id"]),
                question=_dataset_question_text(item),
                expected=_dataset_answer_text(item),
                answer=row.get("selected_answer") or row.get("executor_answer"),
                model=judge_model,
                votes=args.votes,
                use_cache=not args.no_cache,
            )
            judge_latency_ms += latency_delta
            judge_calls += call_count_delta
        else:
            result = judge_answer_with_voting(
                question_id=str(row["question_id"]),
                question=_dataset_question_text(item),
                expected=_dataset_answer_text(item),
                answer=row.get("selected_answer") or row.get("executor_answer"),
                model=judge_model,
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
        model=judge_model,
        votes=args.votes,
        judge_backend=args.judge_backend,
        judge_latency_ms=judge_latency_ms,
        judge_calls=judge_calls,
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
    judge_backend: str,
    judge_latency_ms: float,
    judge_calls: int,
    model: str,
    votes: int,
) -> None:
    accuracy = (correct / judged) if judged else 0.0
    unparseable_rate = (unparseable / total) if total else 0.0
    print(f"=== QA Accuracy ({judge_backend} Judge: {model}, votes={votes}) ===")
    print(f"Dataset:      {dataset_name}   N={total}")
    print(f"Abstained:    {abstained}  (excluded from accuracy)")
    print(f"Judged:       {judged}")
    print(f"Unparseable:  {unparseable}  ({unparseable_rate:.1%})")
    if judge_calls:
        print(
            f"Judge latency: {judge_latency_ms / 1000:.2f}s total  "
            f"({judge_latency_ms / judge_calls:.1f} ms/call over {judge_calls} calls)"
        )
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


def _normalize(text: str) -> str:
    normalized = (text or "").lower().strip()
    normalized = normalized.replace(",", "")
    normalized = normalized.replace("days", "day")
    normalized = normalized.replace("weeks", "week")
    normalized = normalized.replace("months", "month")
    normalized = normalized.replace("years", "year")
    return " ".join(normalized.split())


def _deterministic_match(expected: str, answer: str | None) -> bool | None:
    if not answer or not answer.strip():
        return None
    normalized_expected = _normalize(expected)
    normalized_answer = _normalize(answer)
    if normalized_expected == normalized_answer:
        return True
    if normalized_expected in normalized_answer or normalized_answer in normalized_expected:
        return True
    return False


def _parse_judgment(response: str) -> bool | None:
    cleaned = (response or "").strip().lower()
    if cleaned.startswith("yes"):
        return True
    if cleaned.startswith("no"):
        return False
    return None


def _cache_key(
    *,
    backend: str,
    model: str,
    question: str,
    expected: str,
    answer: str | None,
) -> str:
    key = f"{backend}|{model}|{question}|{expected}|{answer or ''}"
    return hashlib.sha256(key.encode()).hexdigest()


def _load_cache() -> dict[str, bool | None]:
    cache: dict[str, bool | None] = {}
    if not CACHE_PATH.exists():
        return cache
    for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        cache[str(entry["key"])] = entry["judgment"]
    return cache


def _save_to_cache(key: str, judgment: bool | None) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"key": key, "judgment": judgment}) + "\n")


def _judge_answer_with_openai_voting(
    *,
    question_id: str,
    question: str,
    expected: str,
    answer: str | None,
    model: str,
    votes: int,
    use_cache: bool,
) -> tuple[JudgeResult, float, int]:
    deterministic = _deterministic_match(expected, answer)
    if deterministic is None:
        return (
            JudgeResult(
                question_id=question_id,
                question=question,
                expected=expected,
                answer=answer,
                judgment=None,
                abstained=True,
                confidence=CONFIDENCE_LOW,
                raw_responses=[],
                from_cache=False,
            ),
            0.0,
            0,
        )
    if deterministic is True:
        return (
            JudgeResult(
                question_id=question_id,
                question=question,
                expected=expected,
                answer=answer,
                judgment=True,
                abstained=False,
                confidence=CONFIDENCE_DETERMINISTIC,
                raw_responses=[],
                from_cache=False,
            ),
            0.0,
            0,
        )

    key = _cache_key(
        backend="openai",
        model=model,
        question=question,
        expected=expected,
        answer=answer,
    )
    if use_cache:
        cache = _load_cache()
        if key in cache:
            cached = cache[key]
            return (
                JudgeResult(
                    question_id=question_id,
                    question=question,
                    expected=expected,
                    answer=answer,
                    judgment=cached,
                    abstained=cached is None,
                    confidence=CONFIDENCE_CACHED,
                    raw_responses=[],
                    from_cache=True,
                ),
                0.0,
                0,
            )

    raw_responses: list[str] = []
    parsed_votes: list[bool] = []
    total_latency_ms = 0.0
    total_calls = 0
    for _ in range(max(votes, 1)):
        response, latency_ms = _openai_generate_judgment(
            model=model,
            question=question,
            expected=expected,
            answer=answer or "",
        )
        total_latency_ms += latency_ms
        total_calls += 1
        raw_responses.append(response)
        parsed = _parse_judgment(response)
        if parsed is not None:
            parsed_votes.append(parsed)

    judgment, confidence = _summarize_votes(parsed_votes, votes=max(votes, 1))
    if use_cache:
        _save_to_cache(key, judgment)
    return (
        JudgeResult(
            question_id=question_id,
            question=question,
            expected=expected,
            answer=answer,
            judgment=judgment,
            abstained=judgment is None,
            confidence=confidence,
            raw_responses=raw_responses,
            from_cache=False,
        ),
        total_latency_ms,
        total_calls,
    )


def _openai_generate_judgment(
    *,
    model: str,
    question: str,
    expected: str,
    answer: str,
) -> tuple[str, float]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = _OPENAI_JUDGE_PROMPT_TEMPLATE.format(
        question=question,
        expected=expected,
        answer=answer,
    )
    started_at = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=5,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = (time.monotonic() - started_at) * 1000
    content = response.choices[0].message.content or ""
    return str(content).strip(), latency_ms


def _summarize_votes(parsed_votes: list[bool], *, votes: int) -> tuple[bool | None, str]:
    if not parsed_votes:
        return (None, CONFIDENCE_LOW)
    yes_votes = sum(1 for vote in parsed_votes if vote)
    no_votes = sum(1 for vote in parsed_votes if not vote)
    if votes == 1:
        return (parsed_votes[0], CONFIDENCE_LOW)
    if yes_votes == votes:
        return (True, CONFIDENCE_HIGH)
    if no_votes == votes:
        return (False, CONFIDENCE_HIGH)
    if yes_votes > no_votes:
        return (True, CONFIDENCE_MEDIUM)
    if no_votes > yes_votes:
        return (False, CONFIDENCE_MEDIUM)
    return (False, CONFIDENCE_LOW)


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
