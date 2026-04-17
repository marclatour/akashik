"""Local YES/NO answer judge for evaluation-only workflows."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)

JUDGE_PROMPT_TEMPLATE = """You are a strict answer evaluator.

Question: {question}
Expected answer: {expected}
System answer: {answer}

Does the system answer correctly respond to the question given the
expected answer? Minor wording differences are acceptable. The meaning
must match.

Respond with ONLY one word: YES or NO"""

MAX_RETRIES = 2
TIMEOUT_S = 30
CACHE_PATH = Path.home() / ".akashik" / "judge_cache.jsonl"

CONFIDENCE_DETERMINISTIC = "deterministic"
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_CACHED = "cached"

_INSTALL_INSTRUCTIONS = (
    "Ollama is unavailable. Install and start it locally:\n"
    "  brew install ollama\n"
    "  ollama serve &\n"
    "  ollama pull qwen2.5:1.5b\n"
    "  ollama run qwen2.5:1.5b \"Respond with only the word READY\""
)


@dataclass(slots=True)
class JudgeResult:
    question_id: str
    question: str
    expected: str
    answer: str | None
    judgment: bool | None
    abstained: bool
    confidence: str
    raw_responses: list[str]
    from_cache: bool


class OllamaUnavailableError(Exception):
    """Raised when Ollama service or model is unavailable."""


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    t = t.replace(",", "")
    t = t.replace("days", "day")
    t = t.replace("weeks", "week")
    t = t.replace("months", "month")
    t = t.replace("years", "year")
    return " ".join(t.split())


def _deterministic_match(expected: str, answer: str | None) -> bool | None:
    if not answer or not answer.strip():
        return None
    e = _normalize(expected)
    a = _normalize(answer)
    if e == a:
        return True
    if e in a or a in e:
        return True
    return False


def _parse_judgment(response: str) -> bool | None:
    clean = (response or "").strip().lower()
    if clean.startswith("yes"):
        return True
    if clean.startswith("no"):
        return False
    return None


def _cache_key(question: str, expected: str, answer: str | None) -> str:
    return hashlib.sha256(f"{question}|{expected}|{answer or ''}".encode()).hexdigest()


def _load_cache() -> dict[str, bool | None]:
    cache: dict[str, bool | None] = {}
    if CACHE_PATH.exists():
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


def judge_answer(
    question_id: str,
    question: str,
    expected: str,
    answer: str | None,
    model: str = "qwen2.5:1.5b",
    use_cache: bool = True,
) -> JudgeResult:
    return judge_answer_with_voting(
        question_id=question_id,
        question=question,
        expected=expected,
        answer=answer,
        model=model,
        votes=1,
        use_cache=use_cache,
    )


def judge_answer_with_voting(
    question_id: str,
    question: str,
    expected: str,
    answer: str | None,
    model: str = "qwen2.5:1.5b",
    votes: int = 3,
    use_cache: bool = True,
) -> JudgeResult:
    deterministic = _deterministic_match(expected, answer)
    if deterministic is None:
        return JudgeResult(
            question_id=question_id,
            question=question,
            expected=expected,
            answer=answer,
            judgment=None,
            abstained=True,
            confidence=CONFIDENCE_LOW,
            raw_responses=[],
            from_cache=False,
        )
    if deterministic is True:
        return JudgeResult(
            question_id=question_id,
            question=question,
            expected=expected,
            answer=answer,
            judgment=True,
            abstained=False,
            confidence=CONFIDENCE_DETERMINISTIC,
            raw_responses=[],
            from_cache=False,
        )

    key = _cache_key(question, expected, answer)
    if use_cache:
        cache = _load_cache()
        if key in cache:
            cached = cache[key]
            return JudgeResult(
                question_id=question_id,
                question=question,
                expected=expected,
                answer=answer,
                judgment=cached,
                abstained=cached is None,
                confidence=CONFIDENCE_CACHED,
                raw_responses=[],
                from_cache=True,
            )

    raw_responses: list[str] = []
    parsed_votes: list[bool] = []
    for _ in range(max(votes, 1)):
        response = _call_with_retries(question=question, expected=expected, answer=answer or "", model=model)
        raw_responses.append(response)
        parsed = _parse_judgment(response)
        if parsed is not None:
            parsed_votes.append(parsed)

    judgment, confidence = _summarize_votes(parsed_votes, votes=max(votes, 1))
    if use_cache:
        _save_to_cache(key, judgment)
    return JudgeResult(
        question_id=question_id,
        question=question,
        expected=expected,
        answer=answer,
        judgment=judgment,
        abstained=judgment is None,
        confidence=confidence,
        raw_responses=raw_responses,
        from_cache=False,
    )


def _call_with_retries(*, question: str, expected: str, answer: str, model: str) -> str:
    prompt = JUDGE_PROMPT_TEMPLATE.format(question=question, expected=expected, answer=answer)
    last_response = ""
    for _ in range(MAX_RETRIES + 1):
        response = _ollama_generate(model=model, prompt=prompt)
        last_response = response
        if _parse_judgment(response) is not None:
            return response
    LOGGER.warning("Judge returned unparseable response after retries: %r", last_response)
    return last_response


def _ollama_generate(*, model: str, prompt: str) -> str:
    try:
        import ollama
    except Exception as exc:
        raise OllamaUnavailableError(_INSTALL_INSTRUCTIONS) from exc

    try:
        response = ollama.generate(
            model=model,
            prompt=prompt,
            options={"temperature": 0},
        )
    except Exception as exc:
        raise OllamaUnavailableError(_INSTALL_INSTRUCTIONS) from exc
    if isinstance(response, dict):
        return str(response.get("response", ""))
    return str(getattr(response, "response", ""))


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
