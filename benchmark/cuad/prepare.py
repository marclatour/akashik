"""Prepare a small CUAD benchmark corpus and query set."""

from __future__ import annotations

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ast
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

CUAD_ROOT = Path(__file__).resolve().parent
MASTER_CLAUSES_PATH = CUAD_ROOT / "master_clauses.csv"
CUAD_JSON_PATH = CUAD_ROOT / "CUAD_v1.json"
CORPUS_DIR = CUAD_ROOT / "corpus"
QUERIES_A_PATH = CUAD_ROOT / "queries_cuad.json"
QUERIES_B_PATH = CUAD_ROOT / "queries_cuad_b.json"

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

CLAUSE_PLAN = (
    "governing_law",
    "governing_law",
    "governing_law",
    "governing_law",
    "renewal",
    "renewal",
    "renewal",
    "notice",
    "notice",
    "notice",
)

MODE_B_SOURCE_INDEXES = (0, 1, 4, 7, 8)
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
    entity_anchor: str | None
    entity_anchor_source: str | None
    entity_anchor_null_reason: str | None
    text: str
    clauses: dict[str, str]
    answers: dict[str, str]


def prepare() -> dict[str, object]:
    contexts = _load_cuad_contexts()
    contracts = _select_contracts(contexts, count=10)
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    for stale_file in CORPUS_DIR.glob("*.txt"):
        stale_file.unlink()

    for contract in contracts:
        (CORPUS_DIR / contract.filename).write_text(contract.text, encoding="utf-8")

    mode_a_queries = _build_mode_a_queries(contracts)
    mode_b_queries = _build_mode_b_queries(mode_a_queries)

    QUERIES_A_PATH.write_text(json.dumps(mode_a_queries, indent=2), encoding="utf-8")
    QUERIES_B_PATH.write_text(json.dumps(mode_b_queries, indent=2), encoding="utf-8")

    return {
        "contracts": len(contracts),
        "mode_a_queries": len(mode_a_queries),
        "mode_b_queries": len(mode_b_queries),
        "corpus_dir": str(CORPUS_DIR),
        "queries_cuad": str(QUERIES_A_PATH),
        "queries_cuad_b": str(QUERIES_B_PATH),
    }


def _load_cuad_contexts() -> dict[str, str]:
    raw = json.loads(CUAD_JSON_PATH.read_text(encoding="utf-8"))
    contexts: dict[str, str] = {}
    for item in raw["data"]:
        paragraphs = item.get("paragraphs") or []
        context = "\n\n".join(paragraph.get("context", "") for paragraph in paragraphs)
        contexts[item["title"]] = _clean_contract_text(context)
    return contexts


def _select_contracts(contexts: dict[str, str], *, count: int) -> list[PreparedContract]:
    selected: list[PreparedContract] = []
    with MASTER_CLAUSES_PATH.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if not all(_substantive(row.get(field, "")) for field in ANSWER_FIELDS):
                continue

            title = _json_title_for_filename(row["Filename"])
            text = contexts.get(title)
            if not text:
                continue

            clauses: dict[str, str] = {}
            answers: dict[str, str] = {}
            for clause_type, (clause_field, answer_field) in CLAUSE_FIELDS.items():
                clause = _first_clause(row.get(clause_field, ""))
                clause = _normalize_inline_text(clause)
                answer = _normalize_inline_text(row.get(answer_field, ""))
                if not clause or clause not in text:
                    clauses = {}
                    break
                clauses[clause_type] = clause
                answers[clause_type] = answer

            if not clauses:
                continue

            entity_anchor, entity_anchor_source, null_reason = _select_entity_anchor(row)
            selected.append(
                PreparedContract(
                    filename=_safe_filename(row["Filename"]),
                    source_filename=row["Filename"],
                    entity_anchor=entity_anchor,
                    entity_anchor_source=entity_anchor_source,
                    entity_anchor_null_reason=null_reason,
                    text=text,
                    clauses=clauses,
                    answers=answers,
                )
            )
            if len(selected) == count:
                return selected

    raise RuntimeError(f"Could not find {count} CUAD contracts with matching substantive clauses.")


def _build_mode_a_queries(contracts: list[PreparedContract]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for index, (contract, clause_type) in enumerate(zip(contracts, CLAUSE_PLAN, strict=True), start=1):
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
                "entity_filter": [contract.entity_anchor] if contract.entity_anchor else None,
                "entity_filter_source": contract.entity_anchor_source,
                "entity_filter_reason": contract.entity_anchor_null_reason,
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

    for index in MODE_B_SOURCE_INDEXES:
        source = mode_a_queries[index]
        clause_type = source["clause_type"]
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
    summary = prepare()
    print(f"contracts: {summary['contracts']}")
    print(f"mode_a_queries: {summary['mode_a_queries']}")
    print(f"mode_b_queries: {summary['mode_b_queries']}")
    print(f"corpus_dir: {summary['corpus_dir']}")
    print(f"queries_cuad: {summary['queries_cuad']}")
    print(f"queries_cuad_b: {summary['queries_cuad_b']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
