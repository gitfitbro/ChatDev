"""Tests for the Anthropic provider's conversation mapping and response parsing."""

import json
from types import SimpleNamespace

import pytest

from entity.configs.node.agent import AgentConfig
from entity.messages import Message, MessageBlock, MessageRole, ToolCallPayload
from entity.tool_spec import ToolSpec
from runtime.node.agent.providers.anthropic_provider import AnthropicProvider


def build_provider(**overrides) -> AnthropicProvider:
    config = AgentConfig(
        provider="anthropic",
        base_url=overrides.pop("base_url", ""),
        name=overrides.pop("name", "claude-opus-5"),
        api_key="test-key",
        params=overrides.pop("params", {}),
        path="test",
    )
    return AnthropicProvider(config)


def test_system_turns_are_hoisted_out_of_messages():
    provider = build_provider()
    system, messages = provider._build_messages(
        [
            Message(role=MessageRole.SYSTEM, content="You are Programmer."),
            Message(role=MessageRole.SYSTEM, content="Be terse."),
            Message(role=MessageRole.USER, content="Write a snake game."),
        ]
    )

    assert system == "You are Programmer.\n\nBe terse."
    assert messages == [
        {"role": "user", "content": [{"type": "text", "text": "Write a snake game."}]}
    ]


def test_first_turn_is_forced_to_user_role():
    provider = build_provider()
    _, messages = provider._build_messages(
        [Message(role=MessageRole.ASSISTANT, content="I already started.")]
    )

    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_parallel_tool_results_merge_into_one_user_turn():
    provider = build_provider()
    assistant = Message(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=[
            ToolCallPayload(id="call_1", function_name="read_file", arguments='{"path": "a.py"}'),
            ToolCallPayload(id="call_2", function_name="read_file", arguments='{"path": "b.py"}'),
        ],
    )
    _, messages = provider._build_messages(
        [
            Message(role=MessageRole.USER, content="Read both files."),
            assistant,
            Message(role=MessageRole.TOOL, content="contents of a", tool_call_id="call_1"),
            Message(role=MessageRole.TOOL, content="contents of b", tool_call_id="call_2"),
        ]
    )

    assert [msg["role"] for msg in messages] == ["user", "assistant", "user"]

    tool_uses = [block for block in messages[1]["content"] if block["type"] == "tool_use"]
    assert [block["id"] for block in tool_uses] == ["call_1", "call_2"]
    assert tool_uses[0]["input"] == {"path": "a.py"}

    results = messages[2]["content"]
    assert len(results) == 2
    assert [block["tool_use_id"] for block in results] == ["call_1", "call_2"]


def test_assistant_turn_replays_original_blocks_when_available():
    provider = build_provider()
    raw = [
        {"type": "thinking", "thinking": "let me check", "signature": "sig"},
        {"type": "tool_use", "id": "call_1", "name": "ls", "input": {}, "cache_control": None},
    ]
    message = Message(
        role=MessageRole.ASSISTANT,
        content="",
        metadata={"anthropic_content": raw},
        tool_calls=[ToolCallPayload(id="call_1", function_name="ls", arguments="{}")],
    )

    content = provider._assistant_content(message)

    assert content[0]["type"] == "thinking"
    assert content[0]["signature"] == "sig"
    # Null-valued keys are stripped so the replay matches the request schema.
    assert "cache_control" not in content[1]


def test_sampling_params_are_dropped_for_models_that_reject_them():
    provider = build_provider(name="claude-opus-5", params={"temperature": 0.7, "max_tokens": 2048})
    payload = provider._build_payload("sys", [{"role": "user", "content": []}], None, {})

    assert "temperature" not in payload
    assert payload["max_tokens"] == 2048
    assert payload["model"] == "claude-opus-5"


def test_sampling_params_ride_in_extra_body_never_as_top_level_kwargs():
    """The SDK types no temperature/top_p/top_k and has no **kwargs.

    Asserting `payload["temperature"] == 0.7` - as this test used to - passes while
    client.messages.create(**payload) raises TypeError before any request is made.
    """
    provider = build_provider(name="claude-haiku-4-5", params={"temperature": 0.7, "top_p": 0.9})
    payload = provider._build_payload("sys", [{"role": "user", "content": []}], None, {})

    assert "temperature" not in payload
    assert "top_p" not in payload
    assert payload["extra_body"] == {"temperature": 0.7, "top_p": 0.9}


def test_the_payload_only_contains_keys_the_sdk_actually_accepts():
    """Guards the whole class of bug, not just the sampling case."""
    import inspect
    import anthropic

    accepted = set(inspect.signature(anthropic.Anthropic(api_key="x").messages.create).parameters)
    provider = build_provider(params={"temperature": 0.7, "max_tokens": 2048, "effort": "high"})
    payload = provider._build_payload("sys", [{"role": "user", "content": []}], None, {})
    payload.pop("__stream__")

    unknown = set(payload) - accepted
    assert not unknown, f"payload keys the SDK cannot accept: {unknown}"


def test_effort_is_nested_under_output_config():
    provider = build_provider(params={"effort": "high"})
    payload = provider._build_payload(None, [{"role": "user", "content": []}], None, {})

    assert payload["output_config"] == {"effort": "high"}
    assert "effort" not in payload


def test_large_max_tokens_forces_streaming():
    small = build_provider(params={"max_tokens": 4096})
    large = build_provider(params={"max_tokens": 64000})

    assert small._build_payload(None, [], None, {})["__stream__"] is False
    assert large._build_payload(None, [], None, {})["__stream__"] is True


@pytest.mark.parametrize(
    "base_url",
    ["", "https://api.openai.com/v1", "https://generativelanguage.googleapis.com", "${BASE_URL}"],
)
def test_foreign_base_urls_fall_back_to_the_sdk_default(base_url, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    provider = build_provider(base_url=base_url)

    assert provider._resolve_base_url() is None


def test_explicit_anthropic_base_url_is_honoured():
    provider = build_provider(base_url="https://claude.internal.example/v1")

    assert provider._resolve_base_url() == "https://claude.internal.example/v1"


def test_tool_specs_convert_to_anthropic_schema():
    provider = build_provider()
    spec = ToolSpec(
        name="write_file",
        description="Write a file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    payload = provider._build_payload(None, [], [spec], {})

    assert payload["tools"] == [
        {
            "name": "write_file",
            "description": "Write a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]


def test_response_deserialization_splits_text_thinking_and_tool_calls():
    provider = build_provider()
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="considering options"),
            SimpleNamespace(type="text", text="Here is the plan."),
            SimpleNamespace(type="tool_use", id="call_9", name="write_file", input={"path": "x.py"}),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=120, output_tokens=45),
    )

    message = provider._deserialize_response(response)

    assert message.role is MessageRole.ASSISTANT
    assert message.text_content() == "Here is the plan."
    assert message.metadata["thinking"] == "considering options"
    assert message.metadata["stop_reason"] == "tool_use"
    assert len(message.tool_calls) == 1
    assert json.loads(message.tool_calls[0].arguments) == {"path": "x.py"}


def test_token_usage_counts_cached_reads_as_input():
    provider = build_provider()
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_creation_input_tokens=500,
            cache_read_input_tokens=1000,
        )
    )

    usage = provider.extract_token_usage(response)

    assert usage.input_tokens == 1600
    assert usage.output_tokens == 20
    assert usage.total_tokens == 1620
    assert usage.metadata["cache_read_input_tokens"] == 1000


def test_image_attachments_become_base64_image_blocks():
    from entity.messages import AttachmentRef, MessageBlockType

    provider = build_provider()
    attachment = AttachmentRef(
        attachment_id="img-1",
        mime_type="image/png",
        data_uri="data:image/png;base64,QUJD",
    )
    message = Message(
        role=MessageRole.USER,
        content=[
            MessageBlock(type=MessageBlockType.IMAGE, attachment=attachment),
            MessageBlock.text_block("What is this?"),
        ],
    )

    blocks = provider._content_blocks(message)

    assert blocks[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
    }
    assert blocks[1] == {"type": "text", "text": "What is this?"}
