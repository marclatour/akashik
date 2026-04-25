from __future__ import annotations

import sys
import types

import pytest

from akashik.backends.anthropic import AnthropicBackend


class _FakeUsage:
    input_tokens = 123
    output_tokens = 45


class _TextBlock:
    def __init__(self, text: str):
        self.text = text


class _NonTextBlock:
    def __init__(self, kind: str = "tool_use"):
        self.type = kind


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.usage = _FakeUsage()


class _FakeMessages:
    def __init__(self, content):
        self._content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self._content)


class _FakeAnthropicClient:
    def __init__(self, api_key: str, content):
        self.api_key = api_key
        self.messages = _FakeMessages(content)


def _install_fake_anthropic(monkeypatch, content):
    class _AnthropicFactory:
        def __call__(self, api_key: str):
            return _FakeAnthropicClient(api_key, content)

    module = types.SimpleNamespace(Anthropic=_AnthropicFactory())
    monkeypatch.setitem(sys.modules, "anthropic", module)


def test_missing_api_key_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
        AnthropicBackend(api_key=None)


def test_system_prompt_contains_memory_block_when_present() -> None:
    prompt = AnthropicBackend._build_system_prompt("<AKASHIK_MEMORY>test</AKASHIK_MEMORY>")

    assert "<AKASHIK_MEMORY>test</AKASHIK_MEMORY>" in prompt


def test_system_prompt_excludes_memory_block_when_empty() -> None:
    prompt = AnthropicBackend._build_system_prompt("")

    assert "<AKASHIK_MEMORY>" not in prompt


def test_system_prompt_prefers_current_facts() -> None:
    prompt = AnthropicBackend._build_system_prompt("<AKASHIK_MEMORY>test</AKASHIK_MEMORY>")

    assert "Prefer current facts" in prompt


def test_backend_response_includes_latency_tokens_and_answer(monkeypatch) -> None:
    _install_fake_anthropic(monkeypatch, [_TextBlock("Denver")])
    backend = AnthropicBackend(api_key="test-key")

    response = backend.generate("Where do I live?", "<AKASHIK_MEMORY>memory</AKASHIK_MEMORY>")

    assert response.answer == "Denver"
    assert response.latency_ms >= 0
    assert response.input_tokens == 123
    assert response.output_tokens == 45


def test_multiple_text_blocks_are_concatenated(monkeypatch) -> None:
    _install_fake_anthropic(monkeypatch, [_TextBlock("Denver"), _TextBlock("Colorado")])
    backend = AnthropicBackend(api_key="test-key")

    response = backend.generate("Where do I live?", "<AKASHIK_MEMORY>memory</AKASHIK_MEMORY>")

    assert response.answer == "Denver\nColorado"


def test_non_text_blocks_are_ignored(monkeypatch) -> None:
    _install_fake_anthropic(
        monkeypatch,
        [_NonTextBlock(), _TextBlock("Denver"), _NonTextBlock("thinking")],
    )
    backend = AnthropicBackend(api_key="test-key")

    response = backend.generate("Where do I live?", "<AKASHIK_MEMORY>memory</AKASHIK_MEMORY>")

    assert response.answer == "Denver"
