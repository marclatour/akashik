from __future__ import annotations

"""
ACMB evaluator — system-agnostic.
Given returned fact_ids and a query spec, computes all ACMB metrics.
"""


def evaluate_query(returned_ids: list[str], query: dict, k: int = 10) -> dict:
    returned_set = set(returned_ids[:k])
    must_include = set(query.get("must_include", []))
    must_exclude = set(query.get("must_exclude", []))
    should_include = set(query.get("should_include", []))
    hard_distractors = set(query.get("hard_distractors", []))
    expected_current = set(query.get("expected_current", []))

    fact_recall = len(must_include & returned_set) / len(must_include) if must_include else 1.0
    belief_revision = 1.0 if (not (must_exclude & returned_set) and must_include.issubset(returned_set)) else 0.0
    precision_numerator = len((must_include | should_include) & returned_set)
    fact_precision = precision_numerator / len(returned_set) if returned_set else 0.0
    distractor_penalty = float(len(hard_distractors & returned_set))
    current_state_correct = 1.0 if expected_current and expected_current.issubset(returned_set) else 0.0

    return {
        "query_id": query["query_id"],
        "query_type": query["query_type"],
        "fact_recall": fact_recall,
        "belief_revision_score": belief_revision,
        "fact_precision": fact_precision,
        "must_include_hit": must_include.issubset(returned_set),
        "must_exclude_clean": not (must_exclude & returned_set),
        "distractor_penalty": distractor_penalty,
        "current_state_correct": current_state_correct,
    }


def evaluate_persona(returned_by_query: dict[str, list[str]], queries: list[dict], k: int = 10) -> dict:
    results = [
        evaluate_query(returned_by_query.get(query["query_id"], []), query, k)
        for query in queries
    ]
    return {
        "fact_recall": sum(result["fact_recall"] for result in results) / len(results),
        "belief_revision_score": sum(result["belief_revision_score"] for result in results) / len(results),
        "fact_precision": sum(result["fact_precision"] for result in results) / len(results),
        "temporal_correctness": sum(result["current_state_correct"] for result in results) / len(results),
        "distractor_penalty": sum(result["distractor_penalty"] for result in results) / len(results),
        "per_query": results,
    }


def evaluate_benchmark(all_persona_results: list[dict]) -> dict:
    return {
        "fact_recall": sum(result["fact_recall"] for result in all_persona_results) / len(all_persona_results),
        "belief_revision_score": (
            sum(result["belief_revision_score"] for result in all_persona_results) / len(all_persona_results)
        ),
        "fact_precision": sum(result["fact_precision"] for result in all_persona_results) / len(all_persona_results),
        "temporal_correctness": (
            sum(result["temporal_correctness"] for result in all_persona_results) / len(all_persona_results)
        ),
        "distractor_penalty": (
            sum(result["distractor_penalty"] for result in all_persona_results) / len(all_persona_results)
        ),
        "n_personas": len(all_persona_results),
    }
