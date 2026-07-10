"""Strict answer contract for Reader-backed answer generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from akashik.reader import ReaderPacket

ALLOWED_CONFIDENCE = {"high", "medium", "low", "abstain"}
ALLOWED_ANSWER_TYPES = {"direct", "temporal", "preference", "aggregation", "unknown"}
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class AnswerContract:
    answer: str
    confidence: str
    fact_ids: list[str]
    answer_type: str
    abstain_reason: str | None = None


def answer_prompt(packet: ReaderPacket) -> str:
    valid_ids_block = "\n".join(f"- {fact.fact_id}" for fact in packet.facts) or "- (none)"
    return (
        "You are answering a question using ONLY the evidence provided.\n\n"
        "Rules:\n"
        "- Return ONLY valid JSON.\n"
        "- Do not include markdown.\n"
        "- Do not include commentary outside JSON.\n"
        "- Every non-abstain answer MUST cite at least one fact_id from the evidence.\n"
        "- You MUST copy fact_ids exactly from the Valid fact_ids list above. Do not invent or paraphrase them.\n"
        '- If the evidence is insufficient, return confidence "abstain".\n'
        '- If confidence is "abstain", abstain_reason must explain why (e.g. "insufficient evidence to answer").\n'
        "- Keep the answer concise.\n\n"
        "JSON schema:\n"
        "{\n"
        '  "answer": "string",\n'
        '  "confidence": "high|medium|low|abstain",\n'
        '  "fact_ids": ["fact id strings from evidence"],\n'
        '  "answer_type": "direct|temporal|preference|aggregation|unknown",\n'
        '  "abstain_reason": "string or null"\n'
        "}\n\n"
        "Question:\n"
        f"{packet.query}\n\n"
        "Valid fact_ids (copy these exactly, do not invent others):\n"
        f"{valid_ids_block}\n\n"
        f"{packet.context_text}"
    )


def parse_answer_contract(raw: str) -> AnswerContract | None:
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    fenced = _FENCED_JSON_RE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    required = {"answer", "confidence", "fact_ids", "answer_type", "abstain_reason"}
    if not required.issubset(data):
        return None
    if data.get("confidence") == "abstain" and not data.get("abstain_reason"):
        data["abstain_reason"] = "insufficient evidence"
    fact_ids = data["fact_ids"]
    if not isinstance(fact_ids, list):
        return None
    abstain_reason = data["abstain_reason"]
    if abstain_reason is not None:
        abstain_reason = str(abstain_reason)
    return AnswerContract(
        answer=str(data["answer"]),
        confidence=str(data["confidence"]),
        fact_ids=[str(item) for item in fact_ids],
        answer_type=str(data["answer_type"]),
        abstain_reason=abstain_reason,
    )


def validate_answer_contract(
    contract: AnswerContract,
    packet: ReaderPacket,
) -> tuple[bool, str | None]:
    if contract.confidence not in ALLOWED_CONFIDENCE:
        return False, f"invalid confidence: {contract.confidence}"
    if contract.answer_type not in ALLOWED_ANSWER_TYPES:
        return False, f"invalid answer_type: {contract.answer_type}"
    if len(contract.answer) > 1000:
        return False, "answer too long"
    packet_fact_ids = {fact.fact_id for fact in packet.facts}
    invalid_fact_ids = [fact_id for fact_id in contract.fact_ids if fact_id not in packet_fact_ids]
    if invalid_fact_ids:
        return False, f"unknown fact_ids: {', '.join(invalid_fact_ids)}"
    if contract.confidence == "abstain":
        if not (contract.abstain_reason or "").strip():
            return False, "abstain_reason required when confidence=abstain"
        return True, None
    if not contract.answer.strip():
        return False, "answer required when confidence is not abstain"
    if not contract.fact_ids:
        return False, "fact_ids required when confidence is not abstain"
    return True, None


def contract_to_answer_text(contract: AnswerContract) -> str:
    if contract.confidence == "abstain":
        return "I don't know."
    return contract.answer
