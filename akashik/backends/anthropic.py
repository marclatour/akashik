"""Anthropic answer backend."""

from __future__ import annotations

import os
import time

from akashik.backends.base import AnswerBackend, BackendResponse

DEFAULT_MODEL = "claude-sonnet-4-5"


class AnthropicBackend(AnswerBackend):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. "
                "Export the key or pass api_key to AnthropicBackend."
            )
        from anthropic import Anthropic

        self._client = Anthropic(api_key=self._api_key)

    def generate(
        self,
        question: str,
        memory_block: str,
        *,
        max_tokens: int = 500,
    ) -> BackendResponse:
        system_prompt = self._build_system_prompt(memory_block)

        started_at = time.monotonic()
        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": question}],
        )
        latency_ms = (time.monotonic() - started_at) * 1000

        text_parts: list[str] = []
        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                text_parts.append(str(text))
        answer = "\n".join(text_parts).strip()
        usage = getattr(message, "usage", None)

        return BackendResponse(
            answer=answer,
            backend="anthropic",
            model=self.model,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

    @staticmethod
    def _build_system_prompt(memory_block: str) -> str:
        if not memory_block:
            return (
                "You are a helpful assistant. "
                "If you don't have enough information to answer, "
                "say 'I don't know.'"
            )
        return (
            "You are a helpful assistant with access to the user's memory.\n\n"
            f"{memory_block}\n\n"
            "Answer the user's question based on the memory above. "
            "Prefer current facts over historical facts when they conflict. "
            "If the memory doesn't contain enough information, "
            "say 'I don't know.' "
            "Be concise."
        )
