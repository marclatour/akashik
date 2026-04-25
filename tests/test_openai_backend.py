from __future__ import annotations

import sys
import types

import pytest

from akashik.backends.openai import OpenAIBackend


class _FakeUsage:
    prompt_tokens = 123
    completion_tokens = 45


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content: str):
        self.completions = _FakeCompletions(content)


class _FakeOpenAIClient:
    def __init__(self, api_key: str, content: str):
        self.api_key = api_key
        self.chat = _FakeChat(content)


def _install_fake_openai(monkeypatch, content: str):
    class _OpenAIFactory:
        def __call__(self, api_key: str):
            return _FakeOpenAIClient(api_key, content)

    module = types.SimpleNamespace(OpenAI=_OpenAIFactory())
    monkeypatch.setitem(sys.modules, "openai", module)


def test_missing_api_key_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY not set"):
        OpenAIBackend(api_key=None)


def test_system_prompt_contains_memory_block_when_present() -> None:
    prompt = OpenAIBackend._build_system_prompt("<AKASHIK_MEMORY>test</AKASHIK_MEMORY>")

    assert "<AKASHIK_MEMORY>test</AKASHIK_MEMORY>" in prompt


def test_system_prompt_excludes_memory_block_when_empty() -> None:
    prompt = OpenAIBackend._build_system_prompt("")

    assert "<AKASHIK_MEMORY>" not in prompt


def test_system_prompt_prefers_current_facts() -> None:
    prompt = OpenAIBackend._build_system_prompt("<AKASHIK_MEMORY>test</AKASHIK_MEMORY>")

    assert "Prefer current facts" in prompt


def test_backend_response_includes_latency_tokens_and_answer(monkeypatch) -> None:
    _install_fake_openai(monkeypatch, "Denver")
    backend = OpenAIBackend(api_key="test-key")

    response = backend.generate("Where do I live?", "<AKASHIK_MEMORY>memory</AKASHIK_MEMORY>")

    assert response.answer == "Denver"
    assert response.latency_ms >= 0
    assert response.input_tokens == 123
    assert response.output_tokens == 45


def test_backend_response_strips_answer(monkeypatch) -> None:
    _install_fake_openai(monkeypatch, "  Denver  ")
    backend = OpenAIBackend(api_key="test-key")

    response = backend.generate("Where do I live?", "<AKASHIK_MEMORY>memory</AKASHIK_MEMORY>")

    assert response.answer == "Denver"


def test_generate_sends_system_and_user_messages(monkeypatch) -> None:
    _install_fake_openai(monkeypatch, "Denver")
    backend = OpenAIBackend(api_key="test-key")

    response = backend.generate("Where do I live?", "<AKASHIK_MEMORY>memory</AKASHIK_MEMORY>")

    assert response.answer == "Denver"
    create_calls = backend._client.chat.completions.calls
    assert len(create_calls) == 1
    assert create_calls[0]["messages"][0]["role"] == "system"
    assert create_calls[0]["messages"][1]["role"] == "user"
