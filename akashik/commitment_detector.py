"""
Deterministic commitment detector.
Detects when an assistant turn contains a commitment to help.
No LLM, no embeddings — pattern matching only.
"""

from __future__ import annotations

COMMITMENT_PATTERNS = [
    "i'll help",
    "i can help",
    "let me help",
    "i'll find",
    "i can find",
    "i'll draft",
    "i can draft",
    "i'll compare",
    "i can compare",
    "i'll sketch",
    "i can sketch",
    "i'll look",
    "i can look",
    "happy to help",
    "i can assist",
    "i'll assist",
    "i'll work on",
    "i can work on",
]

COMMITMENT_META_QUERIES = [
    "what did you say",
    "what did you offer",
    "what follow-up",
    "what follow",
    "what were you going to",
    "what were you helping",
    "what did you promise",
    "what did you volunteer",
    "what help did you offer",
    "what did you agree",
    "what gear",
    "what planning",
    "what tool",
    "what recovery",
    "what comparison",
    "help me with",
    "assist with",
    "follow up",
    "you offered",
    "you said you'd",
    "you said you would",
]

_TRAILING_SPLIT_MARKERS = (" if ", " when ", " so ", " but ", " and ")
_PATTERN_REWRITES = {
    "i'll help": "help",
    "i can help": "help",
    "let me help": "help",
    "i'll find": "find",
    "i can find": "find",
    "i'll draft": "draft",
    "i can draft": "draft",
    "i'll compare": "compare",
    "i can compare": "compare",
    "i'll sketch": "sketch",
    "i can sketch": "sketch",
    "i'll look": "look",
    "i can look": "look",
    "happy to help": "help",
    "i can assist": "assist",
    "i'll assist": "assist",
    "i'll work on": "work on",
    "i can work on": "work on",
}


def detect_commitment(text: str) -> str | None:
    """
    Returns a normalized commitment description if the text contains
    a commitment pattern, otherwise None.
    Strips the trigger phrase and trims to first sentence.
    """

    text_lower = text.lower()
    for pattern in COMMITMENT_PATTERNS:
        if pattern not in text_lower:
            continue
        index = text_lower.find(pattern)
        action = text[index:].strip()
        for end in (".", "!", "?", "\n"):
            position = action.find(end)
            if position > 0:
                action = action[:position]
        action_lower = action.lower()
        replacement = _PATTERN_REWRITES.get(pattern, "")
        if action_lower.startswith(pattern):
            remainder = action[len(pattern) :].strip()
            action = f"{replacement} {remainder}".strip() if replacement else remainder
            action_lower = action.lower()
        for marker in _TRAILING_SPLIT_MARKERS:
            marker_index = action_lower.find(marker)
            if marker_index > 0:
                action = action[:marker_index].strip()
                action_lower = action.lower()
                break
        return action.strip() or None
    return None


def is_closure(text: str) -> bool:
    """
    Returns True if the text suggests a commitment was fulfilled.
    Guards against false positives when user adds a follow-up request.
    """

    text_lower = text.lower()
    if "but" in text_lower:
        return False
    closure_phrases = [
        "thanks",
        "thank you",
        "that worked",
        "got it",
        "perfect",
        "all set",
        "great",
        "done",
        "sorted",
    ]
    return any(phrase in text_lower for phrase in closure_phrases)
