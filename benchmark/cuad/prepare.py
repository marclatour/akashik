"""Prepare the CUAD benchmark corpus and query sets."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import ast
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CUAD_ROOT = Path(__file__).resolve().parent
AKASHIK_DATA_ROOT = Path.home() / ".akashik" / "data" / "benchmarks" / "cuad"
MASTER_CLAUSES_PATH = AKASHIK_DATA_ROOT / "master_clauses.csv"
CUAD_JSON_PATH = AKASHIK_DATA_ROOT / "CUAD_v1.json"
CORPUS_DIR = CUAD_ROOT / "corpus"
QUERIES_A_PATH = CUAD_ROOT / "queries_cuad.json"
QUERIES_B_PATH = CUAD_ROOT / "queries_cuad_b.json"
SELECTION_SUMMARY_PATH = CUAD_ROOT / "selection_summary.json"

ANSWER_FIELDS = (
    "Governing Law-Answer",
    "Renewal Term-Answer",
    "Notice Period To Terminate Renewal- Answer",
)

CLAUSE_FIELDS = {
    "governing_law": ("Governing Law", "Governing Law-Answer"),
    "renewal": ("Renewal Term", "Renewal Term-Answer"),
    "notice": (
        "Notice Period To Terminate Renewal",
        "Notice Period To Terminate Renewal- Answer",
    ),
}

CLAUSE_TARGETS = {
    "governing_law": 17,
    "renewal": 17,
    "notice": 16,
}
MODE_B_TARGETS = {
    "governing_law": 7,
    "renewal": 7,
    "notice": 6,
}
_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"\b[\w/-]+\b", re.UNICODE)
_ANCHOR_SKIP_TOKENS = {
    "agreement",
    "and",
    "co",
    "contract",
    "copy",
    "corp",
    "dated",
    "ex",
    "execution",
    "exhibit",
    "inc",
    "license",
    "llc",
    "ltd",
    "the",
    "this",
}


@dataclass(slots=True)
class PreparedContract:
    filename: str
    source_filename: str
    entity_filter: list[str] | None
    entity_filter_source: str | None
    entity_anchor_null_reason: str | None
    entity_secondary_source: str | None
    text: str
    clauses: dict[str, str]
    answers: dict[str, str]


def prepare() -> dict[str, object]:
    _ensure_source_data_exists()
    contexts = _load_cuad_contexts()
    selected, selection_summary = _select_contracts(contexts)
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    for stale_file in CORPUS_DIR.glob("*.txt"):
        stale_file.unlink()

    contracts = [contract for contract, _ in selected]
    for contract in contracts:
        (CORPUS_DIR / contract.filename).write_text(contract.text, encoding="utf-8")

    mode_a_queries = _build_mode_a_queries(selected)
    mode_b_queries = _build_mode_b_queries(mode_a_queries)

    QUERIES_A_PATH.write_text(json.dumps(mode_a_queries, indent=2), encoding="utf-8")
    QUERIES_B_PATH.write_text(json.dumps(mode_b_queries, indent=2), encoding="utf-8")
    SELECTION_SUMMARY_PATH.write_text(json.dumps(selection_summary, indent=2), encoding="utf-8")

    return {
        "contracts": len(contracts),
        "mode_a_queries": len(mode_a_queries),
        "mode_b_queries": len(mode_b_queries),
        "selected_by_clause_type": selection_summary["selected_by_clause_type"],
        "shortfalls": selection_summary["shortfalls"],
        "corpus_dir": str(CORPUS_DIR),
        "queries_cuad": str(QUERIES_A_PATH),
        "queries_cuad_b": str(QUERIES_B_PATH),
        "selection_summary": str(SELECTION_SUMMARY_PATH),
    }


def _ensure_source_data_exists() -> None:
    missing = [path for path in (CUAD_JSON_PATH, MASTER_CLAUSES_PATH) if not path.exists()]
    if not missing:
        return
    print("Error: CUAD source data not found at ~/.akashik/data/benchmarks/cuad/")
    print("Download CUAD_v1.json and master_clauses.csv from:")
    print("  https://www.atticusprojectai.org/cuad")
    print("Then place them at ~/.akashik/data/benchmarks/cuad/")
    raise SystemExit(1)


def _load_cuad_contexts() -> dict[str, str]:
    raw = json.loads(CUAD_JSON_PATH.read_text(encoding="utf-8"))
    contexts: dict[str, str] = {}
    for item in raw["data"]:
        paragraphs = item.get("paragraphs") or []
        context = "\n\n".join(paragraph.get("context", "") for paragraph in paragraphs)
        contexts[item["title"]] = _clean_contract_text(context)
    return contexts


def _select_contracts(contexts: dict[str, str]) -> tuple[list[tuple[PreparedContract, str]], dict[str, object]]:
    rows: list[dict[str, str]] = []
    with MASTER_CLAUSES_PATH.open(newline="", encoding="utf-8-sig") as handle:
        rows = sorted(csv.DictReader(handle), key=lambda row: row["Filename"].lower())

    selected: list[tuple[PreparedContract, str]] = []
    selected_filenames: set[str] = set()
    skipped_by_clause_type = {
        clause_type: {
            "already_selected": 0,
            "missing_text": 0,
            "non_substantive_answer": 0,
            "clause_too_short": 0,
            "clause_not_found_in_text": 0,
        }
        for clause_type in CLAUSE_FIELDS
    }
    anchor_sources: list[dict[str, str | None]] = []

    for clause_type, target in CLAUSE_TARGETS.items():
        clause_field, answer_field = CLAUSE_FIELDS[clause_type]
        for row in rows:
            if len([1 for _, selected_clause_type in selected if selected_clause_type == clause_type]) >= target:
                break
            if row["Filename"] in selected_filenames:
                skipped_by_clause_type[clause_type]["already_selected"] += 1
                continue

            title = _json_title_for_filename(row["Filename"])
            text = contexts.get(title)
            if not text:
                skipped_by_clause_type[clause_type]["missing_text"] += 1
                continue

            answer = _normalize_inline_text(row.get(answer_field, ""))
            if not _substantive(answer):
                skipped_by_clause_type[clause_type]["non_substantive_answer"] += 1
                continue

            clause = _normalize_inline_text(_first_clause(row.get(clause_field, "")))
            if len(clause) < 50:
                skipped_by_clause_type[clause_type]["clause_too_short"] += 1
                continue
            if clause not in text:
                skipped_by_clause_type[clause_type]["clause_not_found_in_text"] += 1
                continue

            entity_anchor, entity_anchor_source, null_reason = _select_entity_anchor(row)
            contract = PreparedContract(
                filename=_safe_filename(row["Filename"]),
                source_filename=row["Filename"],
                entity_filter=[entity_anchor] if entity_anchor else None,
                entity_filter_source=entity_anchor_source,
                entity_anchor_null_reason=null_reason,
                entity_secondary_source=None,
                text=text,
                clauses={clause_type: clause},
                answers={clause_type: answer},
            )
            selected.append((contract, clause_type))
            selected_filenames.add(row["Filename"])

    anchor_collision_count_by_primary = _apply_compound_anchors(selected)
    for index, (contract, clause_type) in enumerate(selected, start=1):
        anchor_sources.append(
            {
                "query_id": f"cuad_{index:02d}_{clause_type}",
                "filename": contract.filename,
                "clause_type": clause_type,
                "entity_filter": contract.entity_filter,
                "entity_filter_source": contract.entity_filter_source,
                "entity_filter_reason": contract.entity_anchor_null_reason,
                "entity_secondary_source": contract.entity_secondary_source,
            }
        )

    selected_by_clause_type = {
        clause_type: len([1 for _, selected_clause_type in selected if selected_clause_type == clause_type])
        for clause_type in CLAUSE_FIELDS
    }
    shortfalls = {
        clause_type: max(CLAUSE_TARGETS[clause_type] - selected_by_clause_type[clause_type], 0)
        for clause_type in CLAUSE_FIELDS
    }
    summary = {
        "selection_targets": CLAUSE_TARGETS,
        "selected_by_clause_type": selected_by_clause_type,
        "skipped_by_clause_type": skipped_by_clause_type,
        "shortfalls": shortfalls,
        "null_entity_filters": sum(1 for item in anchor_sources if item["entity_filter"] is None),
        "compound_entity_filters": sum(
            1 for item in anchor_sources if isinstance(item["entity_filter"], list) and len(item["entity_filter"]) > 1
        ),
        "single_entity_filters": sum(
            1 for item in anchor_sources if isinstance(item["entity_filter"], list) and len(item["entity_filter"]) == 1
        ),
        "anchor_collision_count_by_primary": anchor_collision_count_by_primary,
        "anchor_sources": anchor_sources,
    }
    return selected, summary


def _build_mode_a_queries(selected: list[tuple[PreparedContract, str]]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for index, (contract, clause_type) in enumerate(selected, start=1):
        clause = contract.clauses[clause_type]
        answer = contract.answers[clause_type]
        queries.append(
            {
                "query_id": f"cuad_{index:02d}_{clause_type}",
                "query_text": _build_mode_a_query(
                    clause_type,
                    answer,
                    clause,
                ),
                "expected_fact": _truncate_expected_fact(clause),
                "expected_source": contract.filename,
                "expected_level": "fact",
                "difficulty": "medium",
                "clause_type": clause_type,
                "entity_filter": contract.entity_filter,
                "entity_filter_source": contract.entity_filter_source,
                "entity_filter_reason": contract.entity_anchor_null_reason,
                "entity_secondary_source": contract.entity_secondary_source,
            }
        )
    return queries


def _build_mode_a_query(
    clause_type: str,
    answer: str,
    clause: str,
) -> str:
    answer_terms = " ".join(_query_tokens(answer))
    clause_lower = clause.lower()
    if clause_type == "governing_law":
        terms = ["governed", "laws"]
        if "jurisdiction" in clause_lower:
            terms.append("jurisdiction")
        terms.extend(_query_tokens(answer))
        return " ".join(dict.fromkeys(token for token in terms if token))
    if clause_type == "renewal":
        terms = ["renewal", "term", *answer_terms.split()]
        if "successive" in clause_lower:
            terms.insert(0, "successive")
        return " ".join(dict.fromkeys(token for token in terms if token))
    if clause_type == "notice":
        return " ".join(
            dict.fromkeys(["terminate", "renewal", *answer_terms.split(), "written", "notice"])
        )
    raise ValueError(f"Unknown clause type {clause_type!r}.")


def _build_mode_b_queries(mode_a_queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    templates = {
        "governing_law": [
            "Which place's rules control this deal?",
            "What legal forum applies to this arrangement?",
        ],
        "renewal": [
            "Does this arrangement keep going after the first period?",
            "Is there an automatic extension after the initial run?",
        ],
        "notice": [
            "How much warning is needed before stopping another extension?",
            "What advance warning is required to avoid another cycle?",
        ],
    }
    used_by_type = {clause_type: 0 for clause_type in templates}
    mode_b: list[dict[str, Any]] = []

    for clause_type, target in MODE_B_TARGETS.items():
        for source in [query for query in mode_a_queries if query["clause_type"] == clause_type][:target]:
            template_index = used_by_type[clause_type] % len(templates[clause_type])
            used_by_type[clause_type] += 1

            mode_b.append(
                {
                    "query_id": f"{source['query_id']}_b",
                    "query_text": templates[clause_type][template_index],
                    "expected_fact": source["expected_fact"],
                    "expected_source": source["expected_source"],
                    "expected_level": source["expected_level"],
                    "original_query_id": source["query_id"],
                    "original_difficulty": source["difficulty"],
                    "difficulty_mode_b": "natural",
                    "clause_type": clause_type,
                    "entity_filter": source.get("entity_filter"),
                    "entity_filter_source": source.get("entity_filter_source"),
                    "entity_filter_reason": source.get("entity_filter_reason"),
                    "entity_secondary_source": source.get("entity_secondary_source"),
                }
            )
    return mode_b


def _clean_contract_text(context: str) -> str:
    context = context.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n+", context):
        lines = [_normalize_inline_text(line) for line in paragraph.splitlines()]
        lines = [line for line in lines if line and not _is_page_artifact(line)]
        if not lines:
            continue
        paragraphs.append(_normalize_inline_text(" ".join(lines)))
    return "\n\n".join(paragraphs).strip() + "\n"


def _is_page_artifact(line: str) -> bool:
    lower = line.lower()
    return bool(
        re.fullmatch(r"-?\s*\d+\s*-?", line)
        or re.fullmatch(r"page\s+\d+(\s+of\s+\d+)?", lower)
        or re.fullmatch(r"exhibit\s+[\w.\-()]+", lower)
    )


def _first_clause(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value
    if isinstance(parsed, list) and parsed:
        return str(parsed[0])
    return ""


def _substantive(value: str) -> bool:
    normalized = _normalize_inline_text(value)
    return bool(normalized) and normalized.lower() not in {"yes", "no", "n/a", "na", "none"}


def _json_title_for_filename(filename: str) -> str:
    return re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)


def _safe_filename(filename: str) -> str:
    base = _json_title_for_filename(filename)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-") or "contract"
    if len(safe) > 160:
        digest = hashlib.sha1(safe.encode("utf-8")).hexdigest()[:8]
        safe = f"{safe[:151]}_{digest}"
    return f"{safe}.txt"


def _normalize_inline_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.replace("\u00a0", " ")).strip()


def _query_tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text) if token.strip()]


def _select_entity_anchor(row: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    sources = (
        ("document_name", row.get("Document Name-Answer", "")),
        ("party", row.get("Parties-Answer", "")),
        ("filename", row.get("Filename", "")),
    )
    for source_name, value in sources:
        anchor = _first_anchor_token(value)
        if anchor:
            return anchor, source_name, None
    return None, None, "no meaningful anchor token"


def _apply_compound_anchors(selected: list[tuple[PreparedContract, str]]) -> dict[str, int]:
    primary_counts: dict[str, int] = {}
    for contract, _ in selected:
        primary = _primary_entity_filter(contract)
        if primary:
            primary_counts[primary] = primary_counts.get(primary, 0) + 1

    collisions = {
        primary: count
        for primary, count in sorted(primary_counts.items())
        if count > 1
    }
    for contract, _ in selected:
        primary = _primary_entity_filter(contract)
        if not primary or primary_counts.get(primary, 0) <= 1:
            continue
        secondary, secondary_source = _secondary_anchor_token(contract.source_filename)
        if not secondary or secondary == primary:
            contract.entity_anchor_null_reason = "compound anchor collision but no secondary token"
            continue
        contract.entity_filter = [primary, secondary]
        contract.entity_secondary_source = secondary_source
    return collisions


def _primary_entity_filter(contract: PreparedContract) -> str | None:
    if not contract.entity_filter:
        return None
    return contract.entity_filter[0]


def _secondary_anchor_token(filename: str) -> tuple[str | None, str | None]:
    company_prefix = _company_prefix_from_filename(filename)
    if company_prefix:
        return company_prefix, "company_prefix"
    year = _year_from_filename(filename)
    if year:
        return year, "year"
    exhibit = _exhibit_number_from_filename(filename)
    if exhibit:
        return exhibit, "exhibit_number"
    return None, None


def _company_prefix_from_filename(filename: str) -> str | None:
    stem = _json_title_for_filename(filename)
    parts = re.split(r"[_\s.-]+", stem)
    prefix_parts: list[str] = []
    for part in parts:
        if not part:
            continue
        if re.search(r"\d", part):
            break
        cleaned = re.sub(r"[^a-z]", "", part.lower())
        if cleaned:
            prefix_parts.append(cleaned)
    prefix = "".join(prefix_parts)
    return prefix if len(prefix) >= 4 else None


def _year_from_filename(filename: str) -> str | None:
    match = re.search(r"(?:19|20)\d{2}", filename)
    return match.group(0) if match else None


def _exhibit_number_from_filename(filename: str) -> str | None:
    match = re.search(r"\bex[-_ .]*([0-9]+(?:\.[0-9]+)*)", filename, flags=re.IGNORECASE)
    if not match:
        return None
    return re.sub(r"[^a-z0-9]", "", f"ex{match.group(1)}".lower())


def _first_anchor_token(text: str) -> str | None:
    for raw_token in _TOKEN_RE.findall(text or ""):
        token = _clean_anchor_token(raw_token)
        if token:
            return token
    return None


def _clean_anchor_token(token: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", token.lower())
    if len(cleaned) < 4:
        return ""
    if cleaned in _ANCHOR_SKIP_TOKENS:
        return ""
    if any(character.isdigit() for character in cleaned):
        return ""
    return cleaned


def _truncate_expected_fact(clause: str) -> str:
    return clause[:200]


def main() -> int:
    argparse.ArgumentParser(description="Prepare the CUAD benchmark corpus and query sets.").parse_args()
    summary = prepare()
    print(f"contracts: {summary['contracts']}")
    print(f"mode_a_queries: {summary['mode_a_queries']}")
    print(f"mode_b_queries: {summary['mode_b_queries']}")
    print(f"corpus_dir: {summary['corpus_dir']}")
    print(f"queries_cuad: {summary['queries_cuad']}")
    print(f"queries_cuad_b: {summary['queries_cuad_b']}")
    print(f"selected_by_clause_type: {summary['selected_by_clause_type']}")
    print(f"shortfalls: {summary['shortfalls']}")
    print(f"selection_summary: {summary['selection_summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
