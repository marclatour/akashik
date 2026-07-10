"""Conformance tests against the real openai-agents SDK.

Skipped entirely when the SDK is not installed. These verify what the
fake-module tests cannot: the structural Session protocol check, and a
complete Runner turn persisting real SDK item shapes (user message,
function call, function output, assistant message) through the session.
"""

from __future__ import annotations

import asyncio

import pytest

agents = pytest.importorskip("agents")

from agents import Agent, Runner  # noqa: E402
from agents.memory.session import Session  # noqa: E402
from agents.models.interface import Model  # noqa: E402
from agents.run import RunConfig  # noqa: E402

from akashik.ingest import commit_fact  # noqa: E402
from akashik.integrations.openai_agents import (  # noqa: E402
    MEMORY_BLOCK_PREFIX,
    AkashikEvidenceSession,
    build_tools,
    make_memory_callback,
)
from akashik.store import Store  # noqa: E402


class _ScriptedModel(Model):
    """Returns queued ModelResponses; records every input it was shown."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.seen_inputs = []

    async def get_response(self, *args, **kwargs):
        model_input = kwargs.get("input", args[1] if len(args) > 1 else None)
        self.seen_inputs.append(model_input)
        return self._responses.pop(0)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError


def _message_response(text: str):
    from agents.items import ModelResponse
    from agents.usage import Usage
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText

    message = ResponseOutputMessage(
        id="msg_1",
        content=[ResponseOutputText(text=text, type="output_text", annotations=[])],
        role="assistant",
        status="completed",
        type="message",
    )
    return ModelResponse(output=[message], usage=Usage(), response_id=None)


def _tool_call_response(name: str, arguments: str):
    from agents.items import ModelResponse
    from agents.usage import Usage
    from openai.types.responses import ResponseFunctionToolCall

    call = ResponseFunctionToolCall(
        id="fc_1",
        call_id="call_1",
        name=name,
        arguments=arguments,
        type="function_call",
    )
    return ModelResponse(output=[call], usage=Usage(), response_id=None)


def test_session_satisfies_runtime_protocol(tmp_path) -> None:
    with Store(tmp_path / "s.db") as store:
        session = AkashikEvidenceSession("s1", store)
        assert isinstance(session, Session)


def test_full_runner_turn_roundtrips_real_item_shapes(tmp_path) -> None:
    with Store(tmp_path / "s.db") as store:
        commit_fact(store, "The launch is Friday", fact_type="decision", project="show")

        model = _ScriptedModel(
            [
                _tool_call_response("akashik_recall", '{"query": "launch"}'),
                _message_response("The launch is Friday."),
            ]
        )
        agent = Agent(
            name="assistant",
            instructions="Use memory.",
            model=model,
            tools=build_tools(store, project="show"),
        )
        session = AkashikEvidenceSession("turn_1", store)
        run_config = RunConfig(
            session_input_callback=make_memory_callback(store, project="show"),
            tracing_disabled=True,
        )

        result = asyncio.run(
            Runner.run(
                agent,
                "when is the launch?",
                session=session,
                run_config=run_config,
            )
        )
        assert result.final_output == "The launch is Friday."

        # The callback injected exactly one memory block into the model input.
        first_input = model.seen_inputs[0]
        blocks = [
            item
            for item in first_input
            if isinstance(item, dict)
            and str(item.get("content", "")).startswith(MEMORY_BLOCK_PREFIX)
        ]
        assert len(blocks) == 1
        assert "launch is Friday" in blocks[0]["content"]

        # The session persisted real SDK item shapes through the store.
        items = asyncio.run(session.get_items())
        types = {item.get("type") or item.get("role") for item in items}
        assert "function_call" in types
        assert "function_call_output" in types
        assert "user" in types or "message" in types

        # A second turn on the same session sees the prior transcript.
        model2 = _ScriptedModel([_message_response("Yes, Friday.")])
        agent2 = agent.clone(model=model2)
        result2 = asyncio.run(
            Runner.run(
                agent2,
                "are you sure?",
                session=session,
                run_config=run_config,
            )
        )
        assert result2.final_output == "Yes, Friday."
        history_texts = str(model2.seen_inputs[0])
        assert "when is the launch?" in history_texts
