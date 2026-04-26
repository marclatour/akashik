"""Run the LongMemEval retrieval-only benchmark."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import concurrent.futures
from collections import defaultdict
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib import error, request

from akashik.answer_contract import (
    answer_prompt,
    contract_to_answer_text,
    parse_answer_contract,
    validate_answer_contract,
)
from akashik.backends.base import BackendResponse
from akashik.executor import execute as execute_query
from akashik.memory_block import format_memory_block
from akashik.parse_temporal_scope import parse_temporal_scope
from akashik.parse_temporal_scope import _parse_question_date
from akashik.reader import read_context
from akashik.retrieve import retrieve, score_documents
from akashik.schema import RetrievalResponse, RetrievalResult
from akashik.store import AKASHIK_SCHEMA_VERSION, Store
from akashik.temporal_resolver import classify_temporal_query
from benchmark.longmemeval.ingest_adapter import ingest_instance

LOGGER = logging.getLogger(__name__)
TOP_K = 10
LONGMEMEVAL_DATA_ROOT = Path.home() / ".akashik" / "data" / "benchmarks" / "longmemeval"
_OLLAMA_URL = "http://localhost:11434/api/generate"
_DEFAULT_ANSWER_MODEL = "qwen2.5:1.5b"
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
_DEFAULT_OPENAI_MODEL = "gpt-4o"


def _generate_ollama_response(model: str, prompt: str) -> BackendResponse | None:
    payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "prompt": prompt,
            "options": {"temperature": 0, "seed": 0},
        }
    ).encode("utf-8")
    http_request = request.Request(
        _OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started_at = time.monotonic()
    try:
        with request.urlopen(http_request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        LOGGER.warning("ollama call failed: %s", exc)
        return None
    value = body.get("response")
    answer = str(value).strip() if value is not None else ""
    return BackendResponse(
        answer=answer,
        backend="ollama",
        model=model,
        latency_ms=(time.monotonic() - started_at) * 1000,
        input_tokens=None,
        output_tokens=None,
    )


def _generate_answer_with_contract(
    *,
    model: str,
    question: str,
    question_type: str,
    results,
    deterministic_answer: str | None,
    deterministic_answer_type: str | None,
    deterministic_abstained: bool | None,
) -> dict[str, object]:
    packet = read_context(
        question,
        list(results[:TOP_K]),
        question_type=question_type or None,
    )
    response = _generate_ollama_response(model, answer_prompt(packet))
    raw_contract = response.answer if response is not None else None
    parsed_contract = parse_answer_contract(raw_contract or "")
    contract_valid = False
    contract_error: str | None = None
    contract_fact_ids: list[str] = []

    if response is None:
        contract_error = "generation failed"
    elif parsed_contract is None:
        contract_error = "invalid JSON or schema"
    else:
        contract_fact_ids = list(parsed_contract.fact_ids)
        contract_valid, contract_error = validate_answer_contract(parsed_contract, packet)

    if contract_valid and parsed_contract is not None and parsed_contract.confidence != "abstain":
        final_answer = contract_to_answer_text(parsed_contract)
        final_answer_type = parsed_contract.answer_type
        final_abstained = False
    elif deterministic_answer and deterministic_answer.strip():
        final_answer = deterministic_answer
        final_answer_type = deterministic_answer_type or "unknown"
        final_abstained = bool(deterministic_abstained)
    else:
        final_answer = "I don't know."
        final_answer_type = "unknown"
        final_abstained = True

    return {
        "reader_fact_ids": [fact.fact_id for fact in packet.facts],
        "reader_dropped_fact_ids": list(packet.dropped_fact_ids),
        "reader_rationale": list(packet.rationale),
        "generated_answer_facts": [fact.content for fact in packet.facts],
        "answer_contract_raw": raw_contract,
        "answer_contract_valid": contract_valid,
        "answer_contract_error": contract_error,
        "answer_contract_fact_ids": contract_fact_ids,
        "generated_answer": final_answer,
        "generated_answer_type": (
            parsed_contract.answer_type if contract_valid and parsed_contract is not None else None
        ),
        "selected_answer": final_answer,
        "selected_answer_type": final_answer_type,
        "selected_answer_abstained": final_abstained,
        "backend": "ollama",
        "backend_model": model,
        "backend_latency_ms": response.latency_ms if response is not None else 0.0,
        "backend_input_tokens": response.input_tokens if response is not None else None,
        "backend_output_tokens": response.output_tokens if response is not None else None,
        "memory_block": None,
    }


def _generate_answer_with_anthropic(
    *,
    model: str,
    question: str,
    question_type: str,
    results,
    deterministic_answer: str | None,
    deterministic_answer_type: str | None,
    deterministic_abstained: bool | None,
) -> dict[str, object]:
    packet = read_context(
        question,
        list(results[:TOP_K]),
        question_type=question_type or None,
    )
    memory_block = format_memory_block(packet)

    response: BackendResponse | None = None
    try:
        from akashik.backends.anthropic import AnthropicBackend

        response = AnthropicBackend(model=model).generate(question, memory_block)
    except Exception as exc:
        LOGGER.warning("anthropic call failed: %s", exc)

    generated_answer = (response.answer if response is not None else "").strip()
    if generated_answer:
        final_answer = generated_answer
        final_answer_type = "unknown"
        final_abstained = generated_answer.lower() == "i don't know."
    elif deterministic_answer and deterministic_answer.strip():
        final_answer = deterministic_answer
        final_answer_type = deterministic_answer_type or "unknown"
        final_abstained = bool(deterministic_abstained)
    else:
        final_answer = "I don't know."
        final_answer_type = "unknown"
        final_abstained = True

    return {
        "reader_fact_ids": [fact.fact_id for fact in packet.facts],
        "reader_dropped_fact_ids": list(packet.dropped_fact_ids),
        "reader_rationale": list(packet.rationale),
        "generated_answer_facts": [fact.content for fact in packet.facts],
        "answer_contract_raw": None,
        "answer_contract_valid": None,
        "answer_contract_error": None,
        "answer_contract_fact_ids": [],
        "generated_answer": final_answer,
        "generated_answer_type": None,
        "selected_answer": final_answer,
        "selected_answer_type": final_answer_type,
        "selected_answer_abstained": final_abstained,
        "backend": "anthropic",
        "backend_model": model,
        "backend_latency_ms": response.latency_ms if response is not None else 0.0,
        "backend_input_tokens": response.input_tokens if response is not None else None,
        "backend_output_tokens": response.output_tokens if response is not None else None,
        "memory_block": memory_block,
    }


def _generate_answer_with_openai(
    *,
    model: str,
    question: str,
    question_type: str,
    results,
    deterministic_answer: str | None,
    deterministic_answer_type: str | None,
    deterministic_abstained: bool | None,
) -> dict[str, object]:
    packet = read_context(
        question,
        list(results[:TOP_K]),
        question_type=question_type or None,
    )
    memory_block = format_memory_block(packet)

    response: BackendResponse | None = None
    try:
        from akashik.backends.openai import OpenAIBackend

        response = OpenAIBackend(model=model).generate(question, memory_block)
    except Exception as exc:
        LOGGER.warning("openai call failed: %s", exc)

    generated_answer = (response.answer if response is not None else "").strip()
    if generated_answer:
        final_answer = generated_answer
        final_answer_type = "unknown"
        final_abstained = generated_answer.lower() == "i don't know."
    elif deterministic_answer and deterministic_answer.strip():
        final_answer = deterministic_answer
        final_answer_type = deterministic_answer_type or "unknown"
        final_abstained = bool(deterministic_abstained)
    else:
        final_answer = "I don't know."
        final_answer_type = "unknown"
        final_abstained = True

    return {
        "reader_fact_ids": [fact.fact_id for fact in packet.facts],
        "reader_dropped_fact_ids": list(packet.dropped_fact_ids),
        "reader_rationale": list(packet.rationale),
        "generated_answer_facts": [fact.content for fact in packet.facts],
        "answer_contract_raw": None,
        "answer_contract_valid": None,
        "answer_contract_error": None,
        "answer_contract_fact_ids": [],
        "generated_answer": final_answer,
        "generated_answer_type": None,
        "selected_answer": final_answer,
        "selected_answer_type": final_answer_type,
        "selected_answer_abstained": final_abstained,
        "backend": "openai",
        "backend_model": model,
        "backend_latency_ms": response.latency_ms if response is not None else 0.0,
        "backend_input_tokens": response.input_tokens if response is not None else None,
        "backend_output_tokens": response.output_tokens if response is not None else None,
        "memory_block": memory_block,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LongMemEval retrieval evaluation.")
    parser.add_argument(
        "--data",
        default=str(LONGMEMEVAL_DATA_ROOT / "longmemeval_s_cleaned.json"),
        help="Path to LongMemEval JSON dataset.",
    )
    parser.add_argument("--store", default="/tmp/longmemeval.db", help="SQLite store path.")
    parser.add_argument("--abstention-threshold", default=0.3, type=float)
    parser.add_argument("--output", help="JSONL output path.")
    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Keep the JSONL output file after the run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N instances. Useful for faster diagnostics.",
    )
    parser.add_argument("--document-gate-n", type=int, default=5)
    parser.add_argument(
        "--force-reingest",
        action="store_true",
        help="Rebuild per-instance stores even if they already exist and match schema.",
    )
    parser.add_argument(
        "--question-type",
        default="",
        help="Only evaluate instances whose question_type matches this value.",
    )
    parser.add_argument(
        "--per-instance-store",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use a fresh SQLite store per instance. Disable for shared-store debugging.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run a single synthetic instance smoke test without writing an output file.",
    )
    parser.add_argument(
        "--use-executor",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the deterministic Executor after retrieval and report additive executor stats. Disable with --no-executor.",
    )
    parser.add_argument(
        "--use-expression",
        action="store_true",
        default=os.getenv("AKASHIK_USE_EXPRESSION") == "1",
        help="Enable the opt-in expression engine before the retrieval stack.",
    )
    parser.add_argument(
        "--generate-answers",
        action="store_true",
        help="Generate end-to-end answers via the selected backend.",
    )
    parser.add_argument(
        "--backend",
        choices=["ollama", "anthropic", "openai"],
        default="ollama",
        help="Answer generation backend",
    )
    parser.add_argument(
        "--answer-model",
        default=None,
        help="Backend model used when --generate-answers is set.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers. Default: 75%% of CPU cores. Use 1 for sequential.",
    )
    parser.add_argument(
        "--diverse-retrieval",
        action="store_true",
        default=False,
        help="Use retrieve_diverse() instead of retrieve() for session-diverse results.",
    )
    parser.add_argument(
        "--diverse-pool",
        type=int,
        default=100,
        help="Candidate pool size for retrieve_diverse. Default: 100.",
    )
    parser.add_argument(
        "--diverse-top-sessions",
        type=int,
        default=5,
        help="Top N sessions to draw from. Default: 5.",
    )
    parser.add_argument(
        "--diverse-facts-per-session",
        type=int,
        default=3,
        help="Facts per session. Default: 3.",
    )
    args = parser.parse_args()
    workers = args.workers if args.workers is not None else max(1, int((os.cpu_count() or 2) * 0.75))
    default_models = {
        "ollama": _DEFAULT_ANSWER_MODEL,
        "anthropic": _DEFAULT_ANTHROPIC_MODEL,
        "openai": _DEFAULT_OPENAI_MODEL,
    }
    resolved_answer_model = args.answer_model or default_models[args.backend]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.dry_run:
        return _run_dry_run(args.abstention_threshold)

    data_path = Path(args.data)
    if not data_path.exists():
        expected_path = LONGMEMEVAL_DATA_ROOT / data_path.name
        print(f"Error: data file not found: {expected_path}")
        print("Download from: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned")
        print(f"Place at: {LONGMEMEVAL_DATA_ROOT}/")
        return 1

    instances = json.loads(data_path.read_text(encoding="utf-8"))
    if args.question_type:
        instances = [
            instance
            for instance in instances
            if str(instance.get("question_type", "")) == args.question_type
        ]
    if args.limit:
        instances = instances[: args.limit]
    output_path = Path(args.output) if args.output else _default_output_path(data_path.stem)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    failed_instances = 0
    emitted: list[dict[str, object]] = []
    started_at = time.monotonic()
    stores_reused = 0
    stores_created = 0
    summary_printed = False
    verbose_instance_progress = bool(args.question_type or args.force_reingest)
    with output_path.open("w", encoding="utf-8") as handle:
        if args.per_instance_store:
            store_plans = _build_store_plans(
                instances,
                dataset_stem=data_path.stem,
                force_reingest=args.force_reingest,
            )
            planned_reused = sum(1 for _instance, _path, needs_ingest in store_plans if not needs_ingest)
            planned_created = len(store_plans) - planned_reused
            ingest_plans = [
                (index, instance, store_path, needs_ingest)
                for index, (instance, store_path, needs_ingest) in enumerate(store_plans, start=1)
                if needs_ingest
            ]
            reused_plans = [
                (index, instance, store_path, needs_ingest)
                for index, (instance, store_path, needs_ingest) in enumerate(store_plans, start=1)
                if not needs_ingest
            ]
            effective_workers = workers if planned_created > 0 else 1
            if effective_workers != workers:
                LOGGER.info("All stores reused - dropping to 1 worker for retrieval")
            if not summary_printed:
                _print_store_summary(planned_reused, planned_created)
                summary_printed = True
            completed_rows: list[tuple[int, dict[str, object]]] = []

            def _record_result(
                *,
                index: int,
                question_id: str,
                needs_ingest: bool,
                line: dict[str, object] | None,
                elapsed_seconds: float,
                progress_index: int,
            ) -> None:
                nonlocal stores_created, stores_reused, failed_instances
                if needs_ingest:
                    stores_created += 1
                else:
                    stores_reused += 1
                if line is None:
                    failed_instances += 1
                else:
                    completed_rows.append((index, line))
                if verbose_instance_progress:
                    _print_instance_progress(
                        index=index,
                        total=len(instances),
                        question_id=question_id,
                        action="ingesting" if needs_ingest else "reusing",
                        elapsed_seconds=elapsed_seconds,
                        succeeded=line is not None,
                    )
                else:
                    _print_progress(index=progress_index, total=len(instances), started_at=started_at)

            completed_count = 0
            if effective_workers == 1:
                for index, instance, store_path, needs_ingest in [
                    (index, instance, store_path, needs_ingest)
                    for index, (instance, store_path, needs_ingest) in enumerate(store_plans, start=1)
                ]:
                    instance_started_at = time.monotonic()
                    question_id = str(instance.get("question_id", f"instance_{index}"))
                    line = _process_with_persistent_store(
                        store_path,
                        instance,
                        abstention_threshold=args.abstention_threshold,
                        document_gate_n=args.document_gate_n,
                        use_executor=args.use_executor,
                        use_expression=args.use_expression,
                        needs_ingest=needs_ingest,
                        force_reingest=args.force_reingest,
                        generate_answers=args.generate_answers,
                        answer_model=resolved_answer_model,
                        backend_name=args.backend,
                        diverse_retrieval=args.diverse_retrieval,
                        diverse_pool=args.diverse_pool,
                        diverse_top_sessions=args.diverse_top_sessions,
                        diverse_facts_per_session=args.diverse_facts_per_session,
                    )
                    completed_count += 1
                    _record_result(
                        index=index,
                        question_id=question_id,
                        needs_ingest=needs_ingest,
                        line=line,
                        elapsed_seconds=time.monotonic() - instance_started_at,
                        progress_index=completed_count,
                    )
            else:
                with concurrent.futures.ProcessPoolExecutor(max_workers=effective_workers) as executor:
                    futures = {
                        executor.submit(
                            _process_store_plan,
                            index,
                            store_path,
                            instance,
                            abstention_threshold=args.abstention_threshold,
                            document_gate_n=args.document_gate_n,
                            use_executor=args.use_executor,
                            use_expression=args.use_expression,
                            needs_ingest=needs_ingest,
                            force_reingest=args.force_reingest,
                            generate_answers=args.generate_answers,
                            answer_model=resolved_answer_model,
                            backend_name=args.backend,
                            diverse_retrieval=args.diverse_retrieval,
                            diverse_pool=args.diverse_pool,
                            diverse_top_sessions=args.diverse_top_sessions,
                            diverse_facts_per_session=args.diverse_facts_per_session,
                        ): (index, needs_ingest)
                        for index, instance, store_path, needs_ingest in ingest_plans
                    }
                    for future in concurrent.futures.as_completed(futures):
                        index, question_id, needs_ingest, line, elapsed_seconds = future.result()
                        completed_count += 1
                        _record_result(
                            index=index,
                            question_id=question_id,
                            needs_ingest=needs_ingest,
                            line=line,
                            elapsed_seconds=elapsed_seconds,
                            progress_index=completed_count,
                        )
                for index, instance, store_path, needs_ingest in reused_plans:
                    instance_started_at = time.monotonic()
                    question_id = str(instance.get("question_id", f"instance_{index}"))
                    line = _process_with_persistent_store(
                        store_path,
                        instance,
                        abstention_threshold=args.abstention_threshold,
                        document_gate_n=args.document_gate_n,
                        use_executor=args.use_executor,
                        use_expression=args.use_expression,
                        needs_ingest=needs_ingest,
                        force_reingest=args.force_reingest,
                        generate_answers=args.generate_answers,
                        answer_model=resolved_answer_model,
                        backend_name=args.backend,
                        diverse_retrieval=args.diverse_retrieval,
                        diverse_pool=args.diverse_pool,
                        diverse_top_sessions=args.diverse_top_sessions,
                        diverse_facts_per_session=args.diverse_facts_per_session,
                    )
                    completed_count += 1
                    _record_result(
                        index=index,
                        question_id=question_id,
                        needs_ingest=needs_ingest,
                        line=line,
                        elapsed_seconds=time.monotonic() - instance_started_at,
                        progress_index=completed_count,
                    )
            for _index, line in sorted(completed_rows, key=lambda item: item[0]):
                emitted.append(line)
                handle.write(json.dumps(line, sort_keys=True) + "\n")
        else:
            with Store(args.store) as store:
                for index, instance in enumerate(instances, start=1):
                    instance_started_at = time.monotonic()
                    question_id = str(instance.get("question_id", f"instance_{index}"))
                    line = _process_instance(
                        store,
                        instance,
                        abstention_threshold=args.abstention_threshold,
                        document_gate_n=args.document_gate_n,
                        use_executor=args.use_executor,
                        use_expression=args.use_expression,
                        generate_answers=args.generate_answers,
                        answer_model=resolved_answer_model,
                        backend_name=args.backend,
                        diverse_retrieval=args.diverse_retrieval,
                        diverse_pool=args.diverse_pool,
                        diverse_top_sessions=args.diverse_top_sessions,
                        diverse_facts_per_session=args.diverse_facts_per_session,
                    )
                    if line is None:
                        failed_instances += 1
                    else:
                        emitted.append(line)
                        handle.write(json.dumps(line, sort_keys=True) + "\n")
                    if not summary_printed:
                        _print_store_summary(0, 0)
                        summary_printed = True
                    if verbose_instance_progress:
                        _print_instance_progress(
                            index=index,
                            total=len(instances),
                            question_id=question_id,
                            action="reusing",
                            elapsed_seconds=time.monotonic() - instance_started_at,
                            succeeded=line is not None,
                        )
                    else:
                        _print_progress(index=index, total=len(instances), started_at=started_at)
        if instances:
            _finish_progress()

    try:
        _print_report(
            dataset_name=data_path.name,
            rows=emitted,
            threshold=args.abstention_threshold,
            failed_instances=failed_instances,
            stores_reused=stores_reused,
            stores_created=stores_created,
        )
    finally:
        if args.keep_output:
            print(f"Results saved to: {output_path}")
        else:
            try:
                output_path.unlink(missing_ok=True)
            except OSError as exc:
                LOGGER.warning("could not delete output file %s: %s", output_path, exc)
    return 0


def _run_dry_run(abstention_threshold: float) -> int:
    from tests.test_longmemeval_ingest import SYNTHETIC_INSTANCE

    with Store(":memory:") as store:
        line = _process_instance(
            store,
            SYNTHETIC_INSTANCE,
            abstention_threshold=abstention_threshold,
            document_gate_n=5,
            use_executor=False,
            use_expression=False,
        )
    print(json.dumps(line, sort_keys=True))
    return 0


def _process_with_persistent_store(
    store_path: Path,
    instance: dict,
    *,
    abstention_threshold: float,
    document_gate_n: int,
    use_executor: bool,
    use_expression: bool,
    needs_ingest: bool,
    force_reingest: bool = False,
    generate_answers: bool = False,
    answer_model: str = _DEFAULT_ANSWER_MODEL,
    backend_name: str = "ollama",
    diverse_retrieval: bool = False,
    diverse_pool: int = 100,
    diverse_top_sessions: int = 5,
    diverse_facts_per_session: int = 3,
) -> dict[str, object] | None:
    if force_reingest and store_path.exists():
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(store_path) + suffix)
            if path.exists():
                path.unlink()
                LOGGER.debug("deleted %s for reingest", path)
    store = Store(store_path)
    try:
        if needs_ingest and not force_reingest:
            _reset_store_contents(store)
        return _process_instance(
            store,
            instance,
            abstention_threshold=abstention_threshold,
            document_gate_n=document_gate_n,
            use_executor=use_executor,
            use_expression=use_expression,
            generate_answers=generate_answers,
            answer_model=answer_model,
            backend_name=backend_name,
            diverse_retrieval=diverse_retrieval,
            diverse_pool=diverse_pool,
            diverse_top_sessions=diverse_top_sessions,
            diverse_facts_per_session=diverse_facts_per_session,
        )
    finally:
        store.close()


def _process_store_plan(
    index: int,
    store_path: Path,
    instance: dict,
    *,
    abstention_threshold: float,
    document_gate_n: int,
    use_executor: bool,
    use_expression: bool,
    needs_ingest: bool,
    force_reingest: bool = False,
    generate_answers: bool = False,
    answer_model: str = _DEFAULT_ANSWER_MODEL,
    backend_name: str = "ollama",
    diverse_retrieval: bool = False,
    diverse_pool: int = 100,
    diverse_top_sessions: int = 5,
    diverse_facts_per_session: int = 3,
) -> tuple[int, str, bool, dict[str, object] | None, float]:
    started_at = time.monotonic()
    question_id = str(instance.get("question_id", f"instance_{index}"))
    line = _process_with_persistent_store(
        store_path,
        instance,
        abstention_threshold=abstention_threshold,
        document_gate_n=document_gate_n,
        use_executor=use_executor,
        use_expression=use_expression,
        needs_ingest=needs_ingest,
        force_reingest=force_reingest,
        generate_answers=generate_answers,
        answer_model=answer_model,
        backend_name=backend_name,
        diverse_retrieval=diverse_retrieval,
        diverse_pool=diverse_pool,
        diverse_top_sessions=diverse_top_sessions,
        diverse_facts_per_session=diverse_facts_per_session,
    )
    return index, question_id, needs_ingest, line, max(time.monotonic() - started_at, 0.0)


def _process_instance(
    store,
    instance: dict,
    *,
    abstention_threshold: float,
    document_gate_n: int,
    use_executor: bool,
    use_expression: bool,
    generate_answers: bool = False,
    answer_model: str = _DEFAULT_ANSWER_MODEL,
    backend_name: str = "ollama",
    diverse_retrieval: bool = False,
    diverse_pool: int = 100,
    diverse_top_sessions: int = 5,
    diverse_facts_per_session: int = 3,
) -> dict[str, object] | None:
    question_id = str(instance.get("question_id", ""))
    try:
        ingest_instance(store, instance)
    except Exception:
        LOGGER.exception("Failed to ingest instance %s", question_id)
        return None

    question_text = str(instance.get("question", ""))
    temporal_query = classify_temporal_query(question_text)
    temporal_scope = None
    if temporal_query is None:
        temporal_scope = parse_temporal_scope(
            question_text,
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
        response = _retrieve_response(
            store,
            question_text,
            retrieval_filters=retrieval_filters,
            document_gate_n=document_gate_n,
            question_date=str(instance.get("question_date", "")),
            use_expression=use_expression,
            diverse_retrieval=diverse_retrieval,
            diverse_pool=diverse_pool,
            diverse_top_sessions=diverse_top_sessions,
            diverse_facts_per_session=diverse_facts_per_session,
        )
    except Exception:
        LOGGER.exception("Failed to retrieve for instance %s", question_id)
        return None

    if temporal_query is not None and response.temporal_answer is None:
        LOGGER.warning("Unsupported multi-expression temporal query: %s", question_text)
    if response.temporal_answer is not None:
        LOGGER.debug("instance %s temporal_answer=%s", question_id, response.temporal_answer)

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
    output = {
        "question_id": question_id,
        "question_type": question_type,
        "retrieved_session_ids": retrieved_session_ids,
        "top_confidence": top_confidence,
        "abstained": abstained,
        "answer_session_ids": list(instance.get("answer_session_ids", [])),
        "temporal_resolved": response.temporal_answer is not None,
    }
    if use_executor:
        executor_result = execute_query(
            store,
            question_text,
            entity_filters=retrieval_filters,
            query_date=str(instance.get("question_date", "")),
            top_k=TOP_K,
            abstention_threshold=abstention_threshold,
            use_expression=use_expression,
        )
        output["executor_answer"] = executor_result.answer
        output["executor_abstained"] = executor_result.abstained
        output["executor_answer_type"] = executor_result.answer_type
    deterministic_answer = output.get("executor_answer")
    deterministic_answer_type = str(output.get("executor_answer_type", "unknown"))
    deterministic_abstained = bool(output.get("executor_abstained", False))
    expression_stats = getattr(
        store,
        "_last_expression_stats",
        {"candidate_pool": 0, "expressed": 0, "bypassed_retrieval": False},
    )
    output["expression_candidate_pool"] = int(expression_stats.get("candidate_pool", 0))
    output["expression_expressed"] = int(expression_stats.get("expressed", 0))
    output["expression_hit"] = bool(expression_stats.get("bypassed_retrieval", False))
    if generate_answers:
        output["executor_answer_deterministic"] = deterministic_answer
        if backend_name == "anthropic":
            generated = _generate_answer_with_anthropic(
                model=answer_model,
                question=question_text,
                question_type=question_type,
                results=results,
                deterministic_answer=(
                    str(deterministic_answer)
                    if deterministic_answer is not None
                    else None
                ),
                deterministic_answer_type=deterministic_answer_type,
                deterministic_abstained=deterministic_abstained,
            )
        elif backend_name == "openai":
            generated = _generate_answer_with_openai(
                model=answer_model,
                question=question_text,
                question_type=question_type,
                results=results,
                deterministic_answer=(
                    str(deterministic_answer)
                    if deterministic_answer is not None
                    else None
                ),
                deterministic_answer_type=deterministic_answer_type,
                deterministic_abstained=deterministic_abstained,
            )
        else:
            generated = _generate_answer_with_contract(
                model=answer_model,
                question=question_text,
                question_type=question_type,
                results=results,
                deterministic_answer=(
                    str(deterministic_answer)
                    if deterministic_answer is not None
                    else None
                ),
                deterministic_answer_type=deterministic_answer_type,
                deterministic_abstained=deterministic_abstained,
            )
        output.update(generated)
        output["generated_answer_model"] = answer_model
        output["executor_answer"] = str(generated["selected_answer"])
        output["executor_abstained"] = bool(generated["selected_answer_abstained"])
        output["executor_answer_type"] = str(generated["selected_answer_type"])
    return output


def _retrieve_response(
    store,
    question_text: str,
    *,
    retrieval_filters: dict[str, str | list[str]],
    document_gate_n: int,
    question_date: str,
    use_expression: bool,
    diverse_retrieval: bool,
    diverse_pool: int,
    diverse_top_sessions: int,
    diverse_facts_per_session: int,
) -> RetrievalResponse:
    if not diverse_retrieval:
        return retrieve(
            question_text,
            store,
            level="fact",
            limit=TOP_K,
            entity_filters=retrieval_filters,
            document_gate_n=document_gate_n,
            query_date=question_date,
            use_expression=use_expression,
        )

    from akashik import retrieve_diverse

    units = retrieve_diverse(
        store,
        question_text,
        limit=TOP_K,
        pool=diverse_pool,
        top_sessions=diverse_top_sessions,
        facts_per_session=diverse_facts_per_session,
        threshold=0.0,
        document_gate_n=document_gate_n,
    )
    results = [
        RetrievalResult(
            unit=unit,
            confidence=round(max(0.8 - (index * 0.05), 0.0), 3),
            parent_chain=store.fetch_parent_chain(unit.id),
        )
        for index, unit in enumerate(units[:TOP_K])
    ]
    return RetrievalResponse(
        results=results,
        confidence=results[0].confidence if results else 0.0,
        temporal_answer=None,
    )


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
    stores_reused: int,
    stores_created: int,
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
    abstention_rows = [row for row in rows if str(row["question_id"]).endswith("_abs")]
    temporal_delta_rows = [
        row for row in non_abstention_rows if str(row.get("question_type", "")) == "temporal-reasoning"
    ]
    temporal_delta_resolved = sum(1 for row in temporal_delta_rows if row.get("temporal_resolved"))
    expression_rows = [row for row in rows if "expression_hit" in row]

    print("=== LongMemEval Results ===")
    print(f"Dataset:   {dataset_name}   N={total}")
    print(f"Threshold: {threshold}")
    print("")
    print(f"Session Recall @10:     {session_recall:.2f}")
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
        print(
            f"{question_type:<28} session={session_metric:.2f}  n={len(subset)}"
        )
    print(f"Temporal deltas resolved: {temporal_delta_resolved}/{len(temporal_delta_rows)} two-event queries")
    if expression_rows:
        expression_hits = sum(1 for row in expression_rows if row.get("expression_hit"))
        average_pool = _safe_divide(
            sum(int(row.get("expression_candidate_pool", 0)) for row in expression_rows),
            len(expression_rows),
        )
        average_expressed = _safe_divide(
            sum(int(row.get("expression_expressed", 0)) for row in expression_rows),
            len(expression_rows),
        )
        print("")
        print("=== Expression Engine Stats ===")
        print(
            f"Expression hits (bypassed retrieval): {expression_hits} / {len(expression_rows)} "
            f"({_safe_divide(expression_hits, len(expression_rows)):.2%})"
        )
        print(f"Average candidate pool size: {average_pool:.2f}")
        print(f"Average expressed facts returned: {average_expressed:.2f}")
    executor_rows = [row for row in rows if "executor_answer_type" in row]
    if executor_rows:
        answered = sum(1 for row in executor_rows if not row.get("executor_abstained"))
        abstained = sum(1 for row in executor_rows if row.get("executor_abstained"))
        by_answer_type: dict[str, int] = defaultdict(int)
        for row in executor_rows:
            by_answer_type[str(row.get("executor_answer_type", "unknown"))] += 1
        print("")
        print("=== Executor Results ===")
        print(f"Answered:    {answered}")
        print(f"Abstained:   {abstained}")
        print("By type:")
        for answer_type in ("factual", "temporal", "preference", "aggregation", "unknown"):
            print(f"  {answer_type:<11} {by_answer_type.get(answer_type, 0)}")
    print(f"Stores reused:   {stores_reused}")
    print(f"Stores created:  {stores_created}")
    print(f"Failed instances: {failed_instances}")


def _safe_divide(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _instance_store_path(dataset_stem: str, question_id: str) -> Path:
    safe_question_id = "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in question_id)
    root = Path.home() / ".akashik" / "stores" / "benchmarks" / dataset_stem
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{safe_question_id}.db"

def _build_store_plans(
    instances: list[dict],
    *,
    dataset_stem: str,
    force_reingest: bool,
) -> list[tuple[dict, Path, bool]]:
    plans: list[tuple[dict, Path, bool]] = []
    for instance in instances:
        question_id = str(instance.get("question_id", ""))
        store_path = _instance_store_path(dataset_stem, question_id)
        needs_ingest = _store_needs_ingest(store_path, force_reingest=force_reingest)
        plans.append((instance, store_path, needs_ingest))
    return plans


def _store_needs_ingest(store_path: Path, *, force_reingest: bool) -> bool:
    if force_reingest:
        return True
    if not store_path.exists() or store_path.stat().st_size == 0:
        return True
    try:
        conn = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
        try:
            stored = int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()
        return stored != AKASHIK_SCHEMA_VERSION
    except sqlite3.OperationalError:
        return True


def _reset_store_contents(store: Store) -> None:
    with store.transaction():
        store._conn.execute("INSERT INTO memory_units_fts(memory_units_fts) VALUES('delete-all')")
        store._conn.execute("DELETE FROM commitments")
        store._conn.execute("DELETE FROM acmb_fact_id_index")
        store._conn.execute("DELETE FROM fact_context_index")
        store._conn.execute("DELETE FROM epigenetic_state")
        for level in ("fact", "section", "document", "corpus"):
            store._conn.execute("DELETE FROM memory_units WHERE level = ?", (level,))


def _print_store_summary(stores_reused: int, stores_created: int) -> None:
    if stores_created == 0:
        print(
            f"Stores: {stores_reused} reused, {stores_created} to create — retrieval-only mode",
            flush=True,
        )
        return
    print(
        f"Stores: {stores_reused} reused, {stores_created} to create — ingesting missing stores",
        flush=True,
    )


def _print_instance_progress(
    *,
    index: int,
    total: int,
    question_id: str,
    action: str,
    elapsed_seconds: float,
    succeeded: bool,
) -> None:
    status = f"done ({elapsed_seconds:.1f}s)" if succeeded else f"failed ({elapsed_seconds:.1f}s)"
    print(f"[{index}/{total}] {action} {question_id}... {status}", flush=True)


def _print_progress(*, index: int, total: int, started_at: float) -> None:
    if total == 0 or index % 10 != 0:
        return
    elapsed_seconds = max(time.monotonic() - started_at, 0.0)
    rate = elapsed_seconds / index if index else 0.0
    remaining_seconds = max((total - index) * rate, 0.0)
    percent = int((index / total) * 100)
    message = (
        f"{'.' * min(index // 10, 10)} {index}/{total} ({percent}%) | "
        f"elapsed {_format_duration(elapsed_seconds)} | eta {_format_duration(remaining_seconds)}"
    )
    end = "\r" if sys.stdout.isatty() else "\n"
    print(message, end=end, flush=True)


def _finish_progress() -> None:
    if sys.stdout.isatty():
        print("")


def _format_duration(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


def _default_output_path(dataset_stem: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("/tmp") / f"akashik_lme_{dataset_stem}_{timestamp}.jsonl"


if __name__ == "__main__":
    raise SystemExit(main())
