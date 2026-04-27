"""OpenAI answer backend."""

from __future__ import annotations

import os
import time

from akashik.backends.base import AnswerBackend, BackendResponse

DEFAULT_MODEL = "gpt-5.4-mini"


class OpenAIBackend(AnswerBackend):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set.")
        from openai import OpenAI

        self._client = OpenAI(api_key=self._api_key)

    def generate(
        self,
        question: str,
        memory_block: str,
        *,
        max_completion_tokens: int = 500,
    ) -> BackendResponse:
        system_prompt = self._build_system_prompt(memory_block)
        started_at = time.monotonic()
        response = self._client.chat.completions.create(
            model=self.model,
            max_completion_tokens=max_completion_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )
        latency_ms = (time.monotonic() - started_at) * 1000
        answer = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return BackendResponse(
            answer=str(answer).strip(),
            backend="openai",
            model=self.model,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
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
