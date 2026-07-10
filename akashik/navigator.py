"""Rule-based fact reranking for structural retrieval signals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from akashik.schema import MemoryUnit


@dataclass(frozen=True, slots=True)
class NavigatorConfig:
    heading_weight: float = 0.4
    specificity_weight: float = 0.4
    recency_weight: float = 0.2
    decay_max_boost: float = 0.06


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_DIGIT_RE = re.compile(r"\d")
_VERB_SIGNALS = {
    "agree",
    "agreed",
    "agrees",
    "are",
    "had",
    "has",
    "have",
    "is",
    "may",
    "must",
    "provide",
    "provided",
    "provides",
    "shall",
    "was",
    "were",
    "will",
}
_SPECIFICITY_JURISDICTIONS = {
    "australia",
    "california",
    "canada",
    "delaware",
    "england",
    "federal",
    "france",
    "germany",
    "ireland",
    "israel",
    "kansas",
    "new york",
    "ontario",
    "texas",
}
_SPECIFICITY_CONDITIONALS = (
    "for purposes of",
    "with respect to",
    "in the event",
    "provided that",
    "subject to",
    "notwithstanding",
    "except as",
)
_SPECIFICITY_PARTIES = {
    "agent",
    "client",
    "company",
    "contractor",
    "licensee",
    "licensor",
    "parties",
    "party",
    "supplier",
    "vendor",
}
_SPECIFICITY_OBLIGATIONS = (
    "shall",
    "must",
    "will not",
    "is required",
    "agrees to",
    "undertakes",
)
_CLAUSE_TYPE_TOKENS = {
    "governing_law": {"applicable", "govern", "governed", "governing", "jurisdiction", "law", "laws"},
    "renewal": {"automatic", "perpetual", "renew", "renewal", "renewed", "term"},
    "notice": {"days", "expiration", "notice", "notices", "terminate", "terminated", "written"},
    "termination": {"cancel", "cancellation", "expiration", "terminate", "terminated", "termination"},
    "payment": {"fee", "fees", "invoice", "payable", "payment", "payments"},
    "confidentiality": {"confidential", "confidentiality", "disclosure", "nonpublic"},
    "indemnification": {"indemnification", "indemnified", "indemnifies", "indemnify"},
    "liability": {"damages", "liability", "liable", "limitation"},
    "assignment": {"assign", "assignment", "transfer"},
}
_TOKEN_CANONICAL = {
    "governed": "govern",
    "governing": "govern",
    "laws": "law",
    "notices": "notice",
    "payments": "payment",
    "renewed": "renewal",
    "renew": "renewal",
    "terminated": "termination",
    "terminate": "termination",
}
_LABEL_SCORE_CAP = 0.1


def _canonical_token(token: str) -> str:
    return _TOKEN_CANONICAL.get(token, token)


_CLAUSE_TYPE_CANONICAL_TOKENS = {
    clause_type: {_canonical_token(token) for token in tokens}
    for clause_type, tokens in _CLAUSE_TYPE_TOKENS.items()
}


def is_label_like(content: str) -> bool:
    tokens = _tokens(content)
    if not tokens or len(tokens) > 6:
        return False
    if _DIGIT_RE.search(content or ""):
        return False
    for token in tokens:
        if token in _VERB_SIGNALS:
            return False
    return True


def score_specificity(content: str) -> float:
    tokens = _tokens(content)
    if len(tokens) < 8:
        return 0.0

    normalized = " ".join(tokens)
    score = 0.0
    if any(_contains_phrase(normalized, jurisdiction) for jurisdiction in _SPECIFICITY_JURISDICTIONS):
        score += 0.25
    if any(marker in normalized for marker in _SPECIFICITY_CONDITIONALS):
        score += 0.25
    if any(token in _SPECIFICITY_PARTIES for token in tokens):
        score += 0.25
    if any(marker in normalized for marker in _SPECIFICITY_OBLIGATIONS):
        score += 0.25
    return min(score, 1.0)


def score_recency(metadata: dict) -> float:
    return 0.0 if metadata.get("superseded_by") else 1.0


def score_heading_match(section_heading: str | None, query: str) -> float:
    clause_type = infer_clause_type(query)
    if not clause_type or not section_heading:
        return 0.0

    heading_tokens = {_canonical_token(token) for token in _tokens(section_heading)}
    query_tokens = {_canonical_token(token) for token in _tokens(query)}
    clause_tokens = _CLAUSE_TYPE_CANONICAL_TOKENS[clause_type]
    query_clause_tokens = query_tokens & clause_tokens
    if not heading_tokens:
        return 0.0
    if query_clause_tokens and query_clause_tokens <= heading_tokens:
        return 1.0
    return 0.5 if heading_tokens & clause_tokens else 0.0


def infer_clause_type(query: str) -> str | None:
    query_tokens = {_canonical_token(token) for token in _tokens(query)}
    if not query_tokens:
        return None

    scores = {
        clause_type: len(query_tokens & clause_tokens)
        for clause_type, clause_tokens in _CLAUSE_TYPE_CANONICAL_TOKENS.items()
    }
    best_clause_type = max(scores, key=scores.get)
    return best_clause_type if scores[best_clause_type] > 0 else None


def rank_facts(
    facts: list[MemoryUnit],
    query: str,
    query_date: date | None = None,
    config: NavigatorConfig | None = None,
) -> list[tuple[MemoryUnit, float]]:
    active_config = config or NavigatorConfig()
    scored = [(fact, _navigator_score(fact, query, query_date, active_config)) for fact in facts]
    return sorted(scored, key=lambda item: item[1], reverse=True)


def _navigator_score(
    fact: MemoryUnit,
    query: str,
    query_date: date | None,
    config: NavigatorConfig,
) -> float:
    label_like = is_label_like(fact.content)
    heading_match = 0.0 if label_like else score_heading_match(fact.section_heading, query)
    specificity = score_specificity(fact.content)
    recency = score_recency(fact.metadata)
    decay_score = _decay_score(fact, query_date)
    score = (
        (config.heading_weight * heading_match)
        + (config.specificity_weight * specificity)
        + (config.recency_weight * recency)
        + min(decay_score, config.decay_max_boost)
    )
    return min(score, _LABEL_SCORE_CAP) if label_like else score


def _decay_score(
    fact: MemoryUnit,
    query_date: date | None,
) -> float:
    if query_date is None or not fact.last_confirmed_at:
        return 0.0
    try:
        confirmed_date = date.fromisoformat(fact.last_confirmed_at)
    except ValueError:
        return 0.0

    confirmation_count = max(int(fact.confirmation_count or 1), 1)
    reinforcement_bonus = min(confirmation_count - 1, 3) * 0.01
    age_days = max((query_date - confirmed_date).days, 0)
    if age_days <= 30:
        recency_bonus = 0.03
    elif age_days <= 90:
        recency_bonus = 0.02
    elif age_days <= 365:
        recency_bonus = 0.01
    else:
        recency_bonus = 0.0
    return min(reinforcement_bonus + recency_bonus, 0.06)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None
