"""Anthropic (Claude) provider implementation."""

import base64
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import anthropic
from anthropic import Anthropic

from entity.messages import (
    AttachmentRef,
    Message,
    MessageBlock,
    MessageBlockType,
    MessageRole,
    ToolCallPayload,
)
from entity.tool_spec import ToolSpec
from runtime.node.agent import ModelProvider
from runtime.node.agent import ModelResponse
from utils.token_tracker import TokenUsage


_DATA_URI_PATTERN = re.compile(r"^data:(?P<mime>[^;,]+)?(?P<b64>;base64)?,(?P<payload>.*)$", re.DOTALL)

# Models that removed the sampling parameters; sending them returns a 400.
_NO_SAMPLING_MODELS = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
)
_SAMPLING_KEYS = ("temperature", "top_p", "top_k")

# Anthropic accepts these image MIME types inline.
_SUPPORTED_IMAGE_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000
# Above this ceiling the SDK needs streaming to avoid HTTP timeouts.
STREAMING_MAX_TOKENS_THRESHOLD = 8192


class AnthropicProvider(ModelProvider):
    """Provider that talks to Claude through the official Anthropic SDK.

    Conversation mapping (DevAll -> Anthropic Messages API):
      SYSTEM     -> top-level ``system`` parameter (all system turns concatenated)
      USER       -> user message with text/image/document blocks
      ASSISTANT  -> assistant message; ``tool_calls`` become ``tool_use`` blocks
      TOOL       -> user message with ``tool_result`` blocks (consecutive ones merged)
    """

    TEXT_INLINE_CHAR_LIMIT = 200_000

    # ------------------------------------------------------------------
    # ModelProvider contract
    # ------------------------------------------------------------------

    def create_client(self) -> Anthropic:
        """Create the Anthropic client, ignoring base URLs meant for other vendors."""
        kwargs: Dict[str, Any] = {}
        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key

        base_url = self._resolve_base_url()
        if base_url:
            kwargs["base_url"] = base_url

        return Anthropic(**kwargs)

    def call_model(
        self,
        client: Anthropic,
        conversation: List[Message],
        timeline: List[Any],
        tool_specs: Optional[List[ToolSpec]] = None,
        **kwargs,
    ) -> ModelResponse:
        """Call Claude with the shared conversation and return a normalized response."""
        system_prompt, messages = self._build_messages(conversation)
        payload = self._build_payload(system_prompt, messages, tool_specs, kwargs)

        if payload.pop("__stream__"):
            with client.messages.stream(**payload) as stream:
                response = stream.get_final_message()
        else:
            response = client.messages.create(**payload)

        self._track_token_usage(response)
        return ModelResponse(message=self._deserialize_response(response), raw_response=response)

    def extract_token_usage(self, response: Any) -> TokenUsage:
        """Extract token usage from an Anthropic response."""
        usage = getattr(response, "usage", None)
        if not usage:
            return TokenUsage()

        input_tokens = getattr(usage, "input_tokens", None) or 0
        output_tokens = getattr(usage, "output_tokens", None) or 0
        cache_creation = getattr(usage, "cache_creation_input_tokens", None)
        cache_read = getattr(usage, "cache_read_input_tokens", None)

        metadata: Dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if cache_creation is not None:
            metadata["cache_creation_input_tokens"] = cache_creation
        if cache_read is not None:
            metadata["cache_read_input_tokens"] = cache_read

        # Cached reads are billed separately and are not part of ``input_tokens``.
        billed_input = input_tokens + (cache_creation or 0) + (cache_read or 0)

        return TokenUsage(
            input_tokens=billed_input,
            output_tokens=output_tokens,
            total_tokens=billed_input + output_tokens,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    def _resolve_base_url(self) -> Optional[str]:
        """Return a usable Anthropic base URL, or None to use the SDK default.

        ``.env`` ships a single ``BASE_URL`` shared by every provider, so a workflow
        that forgets to override it would otherwise point Claude at api.openai.com.
        """
        candidate = (self.base_url or "").strip()
        if not candidate or candidate.startswith("${"):
            candidate = (os.environ.get("ANTHROPIC_BASE_URL") or "").strip()
        if not candidate:
            return None
        foreign = ("api.openai.com", "generativelanguage.googleapis.com")
        if any(host in candidate for host in foreign):
            return None
        return candidate

    def _build_payload(
        self,
        system_prompt: Optional[str],
        messages: List[Dict[str, Any]],
        tool_specs: Optional[List[ToolSpec]],
        call_options: Dict[str, Any],
    ) -> Dict[str, Any]:
        options = dict(self.params or {})
        options.update(call_options or {})

        stream = bool(options.pop("stream", None)) or False
        cache = options.pop("cache", True)
        effort = options.pop("effort", None)
        max_tokens = int(options.pop("max_tokens", DEFAULT_MAX_TOKENS) or DEFAULT_MAX_TOKENS)

        model_name = self.model_name or DEFAULT_MODEL
        payload: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if system_prompt:
            system_block: Dict[str, Any] = {"type": "text", "text": system_prompt}
            payload["system"] = [system_block]

        if tool_specs:
            payload["tools"] = [self._to_anthropic_tool(spec) for spec in tool_specs]

        if cache:
            # Auto-caches the last cacheable block: the shared role prompt and the
            # replayed history stay warm across the many turns of a workflow.
            payload["cache_control"] = {"type": "ephemeral"}

        output_config = options.pop("output_config", None)
        if effort:
            output_config = dict(output_config or {})
            output_config["effort"] = effort
        if output_config:
            payload["output_config"] = output_config

        if self._model_rejects_sampling(model_name):
            for key in _SAMPLING_KEYS:
                options.pop(key, None)

        # Anything left over (thinking, stop_sequences, betas, ...) passes straight through.
        payload.update({key: value for key, value in options.items() if value is not None})

        payload["__stream__"] = stream or max_tokens > STREAMING_MAX_TOKENS_THRESHOLD
        return payload

    @staticmethod
    def _model_rejects_sampling(model_name: str) -> bool:
        return any(model_name.startswith(prefix) for prefix in _NO_SAMPLING_MODELS)

    @staticmethod
    def _to_anthropic_tool(spec: ToolSpec) -> Dict[str, Any]:
        return {
            "name": spec.name,
            "description": spec.description or "",
            "input_schema": spec.parameters or {"type": "object", "properties": {}},
        }

    # ------------------------------------------------------------------
    # Conversation serialization
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        conversation: List[Message],
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        system_parts: List[str] = []
        messages: List[Dict[str, Any]] = []

        for item in conversation:
            if not isinstance(item, Message):
                continue

            if item.role is MessageRole.SYSTEM:
                text = item.text_content().strip()
                if text:
                    system_parts.append(text)
                continue

            if item.role is MessageRole.TOOL:
                self._append_content(messages, "user", [self._to_tool_result(item)])
                continue

            if item.role is MessageRole.ASSISTANT:
                content = self._assistant_content(item)
                if content:
                    self._append_content(messages, "assistant", content)
                continue

            content = self._content_blocks(item)
            if content:
                self._append_content(messages, "user", content)

        # The Messages API requires the first turn to come from the user.
        if messages and messages[0]["role"] != "user":
            messages.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continue."}]})
        if not messages:
            messages = [{"role": "user", "content": [{"type": "text", "text": "Continue."}]}]

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        return system_prompt, messages

    @staticmethod
    def _append_content(messages: List[Dict[str, Any]], role: str, content: List[Dict[str, Any]]) -> None:
        """Append content, merging into the previous turn when the role repeats.

        Parallel tool results must arrive as one user turn; splitting them teaches
        the model to stop issuing parallel calls.
        """
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
            return
        messages.append({"role": role, "content": content})

    def _assistant_content(self, message: Message) -> List[Dict[str, Any]]:
        """Rebuild an assistant turn, replaying the original blocks when we have them."""
        raw_blocks = message.metadata.get("anthropic_content") if message.metadata else None
        if raw_blocks:
            replay = [self._strip_nulls(block) for block in raw_blocks if isinstance(block, dict)]
            if replay:
                return replay

        content = self._content_blocks(message)
        for call in message.tool_calls or []:
            content.append(
                {
                    "type": "tool_use",
                    "id": call.id or call.function_name,
                    "name": call.function_name,
                    "input": self._parse_arguments(call.arguments),
                }
            )
        return content

    def _to_tool_result(self, message: Message) -> Dict[str, Any]:
        content = self._content_blocks(message, allow_documents=False)
        if not content:
            content = [{"type": "text", "text": ""}]
        result: Dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": message.tool_call_id or "",
            "content": content,
        }
        if message.metadata.get("is_error"):
            result["is_error"] = True
        return result

    def _content_blocks(self, message: Message, *, allow_documents: bool = True) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for block in message.blocks():
            rendered = self._render_block(block, allow_documents=allow_documents)
            if rendered:
                blocks.append(rendered)
        return blocks

    def _render_block(self, block: MessageBlock, *, allow_documents: bool) -> Optional[Dict[str, Any]]:
        if block.type is MessageBlockType.TEXT:
            text = block.text or ""
            if not text.strip():
                return None
            return {"type": "text", "text": text[: self.TEXT_INLINE_CHAR_LIMIT]}

        attachment = block.attachment
        if attachment is not None:
            mime = (attachment.mime_type or "").lower()
            payload = self._attachment_bytes(attachment)

            if block.type is MessageBlockType.IMAGE and payload and mime in _SUPPORTED_IMAGE_MIME:
                return {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": payload},
                }

            if allow_documents and payload and mime == "application/pdf":
                return {
                    "type": "document",
                    "source": {"type": "base64", "media_type": mime, "data": payload},
                }

        described = block.describe()
        if not described or not described.strip():
            return None
        return {"type": "text", "text": described[: self.TEXT_INLINE_CHAR_LIMIT]}

    @staticmethod
    def _attachment_bytes(attachment: AttachmentRef) -> Optional[str]:
        """Return base64 payload for an attachment, from its data URI or local file."""
        if attachment.data_uri:
            match = _DATA_URI_PATTERN.match(attachment.data_uri)
            if match:
                payload = match.group("payload")
                if match.group("b64"):
                    return payload
                return base64.standard_b64encode(payload.encode("utf-8")).decode("utf-8")

        local_path = attachment.local_path
        if local_path and os.path.isfile(local_path):
            try:
                with open(local_path, "rb") as handle:
                    return base64.standard_b64encode(handle.read()).decode("utf-8")
            except OSError:
                return None
        return None

    @staticmethod
    def _parse_arguments(arguments: Any) -> Dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments
        if not arguments:
            return {}
        try:
            parsed = json.loads(arguments)
        except (TypeError, ValueError):
            return {"input": str(arguments)}
        return parsed if isinstance(parsed, dict) else {"input": parsed}

    @classmethod
    def _strip_nulls(cls, value: Any) -> Any:
        """Drop null-valued keys so replayed blocks match the request schema."""
        if isinstance(value, dict):
            return {k: cls._strip_nulls(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [cls._strip_nulls(item) for item in value]
        return value

    # ------------------------------------------------------------------
    # Response deserialization
    # ------------------------------------------------------------------

    def _deserialize_response(self, response: Any) -> Message:
        text_parts: List[str] = []
        thinking_parts: List[str] = []
        tool_calls: List[ToolCallPayload] = []

        for block in getattr(response, "content", None) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif block_type == "thinking":
                thinking = getattr(block, "thinking", "") or ""
                if thinking:
                    thinking_parts.append(thinking)
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCallPayload(
                        id=getattr(block, "id", "") or getattr(block, "name", ""),
                        function_name=getattr(block, "name", "") or "",
                        arguments=json.dumps(getattr(block, "input", None) or {}, ensure_ascii=False),
                    )
                )

        metadata: Dict[str, Any] = {}
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason:
            metadata["stop_reason"] = stop_reason
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            if details is not None:
                metadata["refusal"] = {
                    "category": getattr(details, "category", None),
                    "explanation": getattr(details, "explanation", None),
                }
        if thinking_parts:
            metadata["thinking"] = "\n\n".join(thinking_parts)

        # Keep the original blocks so the next turn can replay thinking/tool_use verbatim.
        raw_content = self._dump_content(response)
        if raw_content:
            metadata["anthropic_content"] = raw_content

        content = "".join(text_parts)
        return Message(
            role=MessageRole.ASSISTANT,
            content=[MessageBlock.text_block(content)] if content else [],
            tool_calls=tool_calls,
            metadata=metadata,
        )

    @staticmethod
    def _dump_content(response: Any) -> List[Dict[str, Any]]:
        dumped: List[Dict[str, Any]] = []
        for block in getattr(response, "content", None) or []:
            if hasattr(block, "model_dump"):
                try:
                    dumped.append(block.model_dump(mode="json", exclude_none=True))
                    continue
                except Exception:
                    pass
            if isinstance(block, dict):
                dumped.append(block)
        return dumped

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def _track_token_usage(self, response: Any) -> None:
        token_tracker = getattr(self.config, "token_tracker", None)
        if not token_tracker:
            return

        usage = self.extract_token_usage(response)
        if usage.input_tokens == 0 and usage.output_tokens == 0 and not usage.metadata:
            return

        node_id = getattr(self.config, "node_id", "ALL")
        usage.node_id = node_id
        usage.model_name = self.model_name
        usage.workflow_id = token_tracker.workflow_id
        usage.provider = "anthropic"

        token_tracker.record_usage(node_id, self.model_name, usage, provider="anthropic")
