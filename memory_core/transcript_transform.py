"""Replay transcript transforms in front of a provider converter.

Ported (packages/ai/src and src/agents at v2026.9.6):

- ``transformMessages`` (``transcript-transform.ts``) and ``transformProviderMessages``
  (``provider-transcript-transform.ts``): the provider-style projection (cross-model thinking and
  tool-call projection, async result relocation, missing-result synthesis, image placeholders);
- ``transformTransportMessages`` (``src/agents/transport-message-transform.ts``): the
  transport-style projection, ending in the shared tool-use/result pairing repair;
- ``resolveModelBoundThinkingReplayMode`` (``anthropic-model-contract.ts``) with the Claude model
  identity resolvers of ``llm-core/src/model-contracts/anthropic.ts``;
- ``replay-turn-classification.ts`` (``resolveFailedAssistantReplay`` and friends).

Messages are JSON dicts. Where upstream would throw a ``TypeError`` on a malformed block (a
thinking block without a string ``thinking``, a tool call without a string ``id``) the port raises
``TypeError`` too.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim, js_truthy
from memory_core.compaction_replay import ReplayModel
from memory_core.replay_repair import (
    SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY,
    is_synthetic_missing_tool_result,
    repair_tool_use_result_pairing,
)
from memory_core.tool_result_text import is_image_with_media_payload

NON_VISION_USER_IMAGE_PLACEHOLDER = "(image omitted: model does not support images)"
NON_VISION_TOOL_IMAGE_PLACEHOLDER = "(tool image omitted: model does not support images)"
IMAGE_OMISSION = "(image omitted: model does not support images)"
VIDEO_OMISSION = "(video omitted: provider does not support video input)"
STREAM_ERROR_FALLBACK_TEXT = "[assistant turn failed before producing content]"
FAILED_ASSISTANT_REPLAY_TEXT = (
    "[This turn failed before it completed. Do not redo its work without confirming with the "
    "user first.]"
)

_SYNTHETIC_TOOL_RESULT_APIS = frozenset(
    {
        "anthropic-messages",
        "openclaw-anthropic-messages-transport",
        "bedrock-converse-stream",
        "google-generative-ai",
        "openclaw-google-generative-ai-transport",
        "openai-responses",
        "openai-chatgpt-responses",
        "azure-openai-responses",
        "openclaw-openai-responses-transport",
        "openclaw-openai-chatgpt-responses-transport",
        "openclaw-azure-openai-responses-transport",
    }
)
_OPENAI_RESPONSES_ABORTED_OUTPUT_APIS = frozenset(
    {
        "openai-responses",
        "openai-chatgpt-responses",
        "azure-openai-responses",
        "openclaw-openai-responses-transport",
        "openclaw-openai-chatgpt-responses-transport",
        "openclaw-azure-openai-responses-transport",
    }
)

Message = dict[str, Any]
NormalizeToolCallId = Callable[[str, "TransportModel", Mapping[str, Any]], str]


TransportModel = ReplayModel


# --- replay turn classification -------------------------------------------------------------


def _as_record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _is_blank(text: Any) -> bool:
    return isinstance(text, str) and not js_trim(text)


def has_only_assistant_reasoning_content(message: Mapping[str, Any]) -> bool:
    """``hasOnlyAssistantReasoningContent``: only provider reasoning and blank text."""

    if message.get("role") != "assistant":
        return False
    raw = message.get("content")
    content = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    has_thinking = False
    for block in content:
        if not block or not isinstance(block, dict | list):
            return False
        if not isinstance(block, dict) or "type" not in block:
            return False
        if block["type"] in ("thinking", "redacted_thinking"):
            has_thinking = True
            continue
        if block["type"] == "text" and "text" in block and _is_blank(block["text"]):
            continue
        return False
    return has_thinking


def is_reasoning_only_length_assistant_turn(message: Mapping[str, Any]) -> bool:
    return message.get("stopReason") == "length" and has_only_assistant_reasoning_content(message)


def is_stream_error_fallback_content(content: Any) -> bool:
    if content is None:
        return True
    if isinstance(content, str):
        trimmed = js_trim(content)
        return not trimmed or trimmed == STREAM_ERROR_FALLBACK_TEXT
    if isinstance(content, list):
        for value in content:
            block = _as_record(value)
            if not (
                block
                and block.get("type") in ("text", "input_text", "output_text")
                and isinstance(block.get("text"), str)
                and is_stream_error_fallback_content(block["text"])
            ):
                return False
        return True
    return False


def resolve_failed_assistant_replay(message: Mapping[str, Any], *, pairing_aware: bool) -> str:
    """``resolveFailedAssistantReplay``: ``keep``, ``drop`` or ``marker``."""

    if message.get("role") != "assistant" or message.get("stopReason") not in ("error", "aborted"):
        return "keep"
    raw = message.get("content")
    content = raw if isinstance(raw, list) else []
    if any((_as_record(block) or {}).get("type") == "toolCall" for block in content):
        return "keep" if pairing_aware else "drop"
    for block in content:
        record = _as_record(block)
        if (
            record
            and record.get("type") == "text"
            and isinstance(record.get("text"), str)
            and not is_stream_error_fallback_content(record["text"])
        ):
            return "marker"
    return "drop"


# --- model-bound thinking replay -------------------------------------------------------------

_SEPARATORS = re.compile(f"[._{JS_SPACE_CLASS}]+")


def _lower_or_empty(value: Any) -> str:
    return js_trim(value).lower() if isinstance(value, str) else ""


def _normalize_claude_model_id(model_id: Any) -> str:
    normalized = js_trim(model_id).lower() if isinstance(model_id, str) else ""
    unprefixed = (
        normalized[len("anthropic/") :] if normalized.startswith("anthropic/") else normalized
    )
    return _SEPARATORS.sub("-", unprefixed)


def _normalize_api(api: Any) -> str:
    normalized = _lower_or_empty(api)
    return (
        "anthropic-messages"
        if normalized == "openclaw-anthropic-messages-transport"
        else normalized
    )


def resolve_claude_model_identity(ref: Mapping[str, Any]) -> str:
    params = ref.get("params")
    canonical = params.get("canonicalModelId") if isinstance(params, Mapping) else None
    normalized = _normalize_claude_model_id(
        canonical if isinstance(canonical, str) else ref.get("id")
    )
    match = re.search(r"(?:^|[-/])(claude-[^/]+)\Z", normalized)
    return match.group(1) if match else normalized


def _identity_from(ref: Mapping[str, Any], family: str) -> str | None:
    normalized = resolve_claude_model_identity(ref)
    match = re.search(rf"(?:^|-)claude-{family}(?=\Z|[^a-z0-9])", normalized)
    if not match:
        return None
    return normalized[match.start() + (1 if match.group(0).startswith("-") else 0) :]


def resolve_claude_fable5_model_identity(ref: Mapping[str, Any]) -> str | None:
    return _identity_from(ref, "fable-5")


def resolve_claude_mythos5_model_identity(ref: Mapping[str, Any]) -> str | None:
    return _identity_from(ref, "mythos-5")


def resolve_claude_sonnet5_model_identity(ref: Mapping[str, Any]) -> str | None:
    return _identity_from(ref, "sonnet-5")


def resolve_claude_opus55_model_identity(ref: Mapping[str, Any]) -> str | None:
    normalized = resolve_claude_model_identity(ref)
    if normalized == "opus-5-5":
        return "claude-opus-5-5"
    return normalized if re.match(r"claude-opus-5-5(?=\Z|[^a-z0-9])", normalized) else None


def resolve_claude_opus5_model_identity(ref: Mapping[str, Any]) -> str | None:
    normalized = resolve_claude_model_identity(ref)
    opus55 = resolve_claude_opus55_model_identity(ref)
    if opus55:
        return opus55
    if normalized in ("opus", "opus-5"):
        return "claude-opus-5"
    return _identity_from(ref, "opus-5")


def _has_concrete_response_model(ref: Mapping[str, Any]) -> bool:
    response = _normalize_claude_model_id(ref.get("responseModelId"))
    return len(response) > 0 and response != _normalize_claude_model_id(ref.get("modelId"))


def _replay_model_bound_identity(ref: Mapping[str, Any]) -> str | None:
    if _normalize_api(ref.get("api")) != "anthropic-messages":
        return None
    model_ref = (
        {"id": ref.get("responseModelId")}
        if _has_concrete_response_model(ref)
        else {"id": ref.get("modelId"), "params": ref.get("modelParams")}
    )
    for label, resolver in (
        ("fable", resolve_claude_fable5_model_identity),
        ("mythos", resolve_claude_mythos5_model_identity),
        ("opus", resolve_claude_opus5_model_identity),
        ("sonnet", resolve_claude_sonnet5_model_identity),
    ):
        identity = resolver(model_ref)
        if identity:
            return f"{label}:{identity}"
    return None


def _reads_prior_claude_thinking(identity: str | None) -> bool:
    return identity is not None and bool(
        re.match(r"fable:claude-fable-5-1(?=\Z|[^a-z0-9])", identity)
    )


def _is_claude_replay_source(ref: Mapping[str, Any]) -> bool:
    model_id = (
        ref.get("responseModelId") if _has_concrete_response_model(ref) else ref.get("modelId")
    )
    return bool(re.search(r"(?:^|[-/])claude-", _normalize_claude_model_id(model_id)))


def resolve_model_bound_thinking_replay_mode(
    source: Mapping[str, Any], target: Mapping[str, Any]
) -> str:
    """``resolveModelBoundThinkingReplayMode``: ``default``, ``preserve`` or ``drop``.

    ``source`` and ``target`` carry ``provider``, ``api``, ``modelId`` and optionally
    ``responseModelId`` / ``modelParams``.
    """

    source_api = _normalize_api(source.get("api"))
    target_api = _normalize_api(target.get("api"))
    source_identity = _replay_model_bound_identity(source)
    target_identity = _replay_model_bound_identity(target)
    same_route = (
        _lower_or_empty(source.get("provider")) == _lower_or_empty(target.get("provider"))
        and source_api == target_api
        and _normalize_claude_model_id(source.get("modelId"))
        == _normalize_claude_model_id(target.get("modelId"))
    )
    if not source_identity and not target_identity:
        return "default"
    if (
        source_api == target_api
        and _reads_prior_claude_thinking(target_identity)
        and _is_claude_replay_source(source)
    ):
        return "preserve"
    if (
        not source_identity
        and not _has_concrete_response_model(source)
        and target_identity
        and same_route
    ):
        return "preserve"
    return "preserve" if source_api == target_api and source_identity == target_identity else "drop"


def _replay_mode_for(message: Mapping[str, Any], model: TransportModel) -> str:
    return resolve_model_bound_thinking_replay_mode(
        {
            "provider": message.get("provider"),
            "api": message.get("api"),
            "modelId": message.get("model"),
            "responseModelId": message.get("responseModel"),
        },
        {
            "provider": model.provider,
            "api": model.api,
            "modelId": model.id,
            "modelParams": model.params,
        },
    )


def _same_route_model(message: Mapping[str, Any], model: TransportModel) -> bool:
    return (
        message.get("provider") == model.provider
        and message.get("api") == model.api
        and message.get("model") == model.id
    )


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} is not a string")
    return value


# --- provider-style transform ----------------------------------------------------------------


def _replace_images_with_placeholder(content: Any, placeholder: str) -> list[Any]:
    if not isinstance(content, list):
        raise TypeError("content is not iterable")
    result: list[Any] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "image":
            result.append(block)
            continue
        previous = result[-1] if result else None
        repeated = (
            isinstance(previous, dict)
            and previous.get("type") == "text"
            and previous.get("text") == placeholder
        )
        if is_image_with_media_payload(block) and not repeated:
            result.append({"type": "text", "text": placeholder})
    return result


def _transform_assistant(
    message: Message,
    model: TransportModel,
    tool_call_id_map: dict[str, str],
    normalize_tool_call_id: NormalizeToolCallId | None,
) -> Message:
    replay_mode = _replay_mode_for(message, model)
    same_model = replay_mode == "preserve" or _same_route_model(message, model)
    raw = message.get("content")
    blocks = [{"type": "text", "text": raw}] if isinstance(raw, str) else raw
    if not isinstance(blocks, list):
        raise TypeError("content is not iterable")
    content: list[Any] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise TypeError("Cannot read properties of a non-object content block")
        kind = block.get("type")
        if kind == "thinking":
            if replay_mode == "drop":
                continue
            if js_truthy(block.get("redacted")):
                if same_model:
                    content.append(block)
                continue
            if same_model and js_truthy(block.get("thinkingSignature")):
                content.append(block)
                continue
            thinking = block.get("thinking")
            if thinking is None or (isinstance(thinking, str) and not js_trim(thinking)):
                continue
            _require_str(thinking, "block.thinking.trim")
            content.append(block if same_model else {"type": "text", "text": thinking})
            continue
        if kind == "text":
            content.append(block if same_model else {"type": "text", "text": block.get("text")})
            continue
        # Pairing uses these ids as shared keys, before model-specific normalization runs.
        block_id = _require_str(block.get("id"), "block.id")
        trimmed_id = js_trim(block_id)
        if same_model:
            content.append(block if trimmed_id == block_id else {**block, "id": trimmed_id})
            continue
        unsigned = {k: v for k, v in block.items() if k not in ("thoughtSignature", "async")}
        new_id = (
            normalize_tool_call_id(trimmed_id, model, message) if normalize_tool_call_id else None
        )
        if new_id is None:
            new_id = trimmed_id
        if new_id != trimmed_id:
            tool_call_id_map[trimmed_id] = new_id
        content.append(unsigned if new_id == block_id else {**unsigned, "id": new_id})
    return {**message, "content": content}


def transform_messages(
    messages: Sequence[Message],
    model: TransportModel,
    normalize_tool_call_id: NormalizeToolCallId | None = None,
) -> list[Message]:
    """``transformMessages`` (transcript-transform.ts)."""

    tool_call_id_map: dict[str, str] = {}
    # Other model contracts require ordinary adjacent call/results. Preserve real delayed
    # outcomes before stripping the source model's async capability.
    async_owners: dict[str, Message] = {}
    relocated: dict[int, list[Message]] = {}
    moved: set[int] = set()
    for message in messages:
        if message.get("role") == "assistant":
            same_model = _same_route_model(message, model)
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "toolCall":
                    block_id = js_trim(_require_str(block.get("id"), "block.id"))
                    if js_truthy(block.get("async")) and not same_model:
                        async_owners[block_id] = message
                    else:
                        async_owners.pop(block_id, None)
        elif message.get("role") == "toolResult":
            result_id = js_trim(_require_str(message.get("toolCallId"), "message.toolCallId"))
            owner = async_owners.get(result_id)
            if owner is not None:
                relocated.setdefault(id(owner), []).append(message)
                moved.add(id(message))
                del async_owners[result_id]
    if moved:
        source: list[Message] = []
        for message in messages:
            if id(message) in moved:
                continue
            source.append(message)
            if message.get("role") == "assistant":
                source.extend(relocated.get(id(message), []))
    else:
        source = list(messages)
    supports_images = "image" in model.input
    result: list[Message] = []
    pending_async_calls: dict[str, Message] = {}
    pending_tool_calls: list[Message] = []
    existing_tool_result_ids: set[str] = set()

    def flush_tool_calls() -> None:
        nonlocal pending_tool_calls, existing_tool_result_ids
        for call in pending_tool_calls:
            if call.get("id") not in existing_tool_result_ids:
                result.append(
                    {
                        "role": "toolResult",
                        "toolCallId": call.get("id"),
                        "toolName": call.get("name"),
                        "content": [{"type": "text", "text": "No result provided"}],
                        "isError": True,
                        "timestamp": int(time.time() * 1000),
                    }
                )
        pending_tool_calls = []
        existing_tool_result_ids = set()

    for original in source:
        message = original
        if message.get("content") is None:
            message = {**message, "content": []}
        if message.get("role") == "assistant":
            failed_replay = resolve_failed_assistant_replay(message, pairing_aware=False)
            message = _transform_assistant(message, model, tool_call_id_map, normalize_tool_call_id)
            flush_tool_calls()
            if failed_replay == "drop":
                continue
            if failed_replay == "marker":
                result.append(
                    {**message, "content": [{"type": "text", "text": FAILED_ASSISTANT_REPLAY_TEXT}]}
                )
                continue
            pending_tool_calls = []
            for block in message["content"]:
                if block.get("type") != "toolCall":
                    continue
                if js_truthy(block.get("async")):
                    pending_async_calls[block["id"]] = block
                    continue
                pending_tool_calls.append(block)
        else:
            if not supports_images and not isinstance(message.get("content"), str):
                message = {
                    **message,
                    "content": _replace_images_with_placeholder(
                        message["content"],
                        NON_VISION_USER_IMAGE_PLACEHOLDER
                        if message.get("role") == "user"
                        else NON_VISION_TOOL_IMAGE_PLACEHOLDER,
                    ),
                }
            if message.get("role") == "toolResult":
                trimmed_id = js_trim(_require_str(message.get("toolCallId"), "message.toolCallId"))
                tool_call_id = tool_call_id_map.get(trimmed_id, trimmed_id)
                if tool_call_id != message.get("toolCallId"):
                    message = {**message, "toolCallId": tool_call_id}
                existing_tool_result_ids.add(tool_call_id)
                pending_async_calls.pop(tool_call_id, None)
            else:
                flush_tool_calls()
        result.append(message)
    # Async calls may own results after later assistant fragments. Only a closed history without
    # their result needs the ordinary missing-result repair.
    pending_tool_calls.extend(pending_async_calls.values())
    flush_tool_calls()
    return result


def _project_user_media_for_transport(
    content: list[Any], supports_images: bool, supports_video: bool
) -> list[Any]:
    result: list[Any] = []
    for block in content:
        if not isinstance(block, dict):
            raise TypeError("Cannot read properties of a non-object content block")
        kind = block.get("type")
        if (
            kind == "text"
            or (kind == "image" and supports_images)
            or (kind == "video" and supports_video)
        ):
            result.append(block)
            continue
        text = VIDEO_OMISSION if kind == "video" else IMAGE_OMISSION
        previous = result[-1] if result else None
        data = _require_str(block.get("data"), "block.data.trim")
        if js_trim(data) and not (
            isinstance(previous, dict)
            and previous.get("type") == "text"
            and previous.get("text") == text
        ):
            result.append({"type": "text", "text": text})
    return result


def transform_provider_messages(
    messages: Sequence[Message],
    model: TransportModel,
    normalize_tool_call_id: NormalizeToolCallId | None = None,
) -> list[Message]:
    """``transformProviderMessages``: media projection, then :func:`transform_messages`."""

    target = TransportModel(
        provider=model.provider,
        api=model.api,
        id=model.id,
        base_url=model.base_url,
        input=tuple(kind for kind in model.input if kind != "video"),
        reasoning=model.reasoning,
        compat=model.compat,
        params=model.params,
    )
    projected: list[Message] = []
    for message in messages:
        if message.get("role") != "user" or not isinstance(message.get("content"), list):
            projected.append(message)
            continue
        projected.append(
            {
                **message,
                "content": _project_user_media_for_transport(
                    message["content"],
                    "image" in model.input,
                    model.api == "openai-completions" and "video" in model.input,
                ),
            }
        )
    return transform_messages(projected, target, normalize_tool_call_id)


# --- transport-style transform ---------------------------------------------------------------


def transform_transport_messages(
    messages: Sequence[Message],
    model: TransportModel,
    normalize_tool_call_id: NormalizeToolCallId | None = None,
    *,
    normalize_same_model_tool_call_ids: bool = False,
    preserve_cross_model_tool_call_thought_signature: bool = False,
    preserve_unframed_tool_results: bool = False,
) -> list[Message]:
    """``transformTransportMessages`` (transport-message-transform.ts)."""

    allow_synthetic = model.api in _SYNTHETIC_TOOL_RESULT_APIS
    synthetic_text = (
        "aborted" if model.api in _OPENAI_RESPONSES_ABORTED_OUTPUT_APIS else "No result provided"
    )
    tool_call_id_map: dict[str, str] = {}
    has_cross_model_async_calls = False
    transformed: list[Message] = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            transformed.append(msg)
            continue
        if role == "toolResult":
            content = msg.get("content")
            normalize_repair_text = is_synthetic_missing_tool_result(msg) and (
                not isinstance(content, list)
                or len(content) != 1
                or not isinstance(content[0], dict)
                or content[0].get("type") != "text"
                or content[0].get("text") != synthetic_text
            )
            if normalize_repair_text:
                details = msg.get("details")
                result = {
                    **msg,
                    "content": [{"type": "text", "text": synthetic_text}],
                    "details": {
                        **(details if isinstance(details, dict) else {}),
                        SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY: True,
                    },
                }
            else:
                result = msg
            normalized_id = tool_call_id_map.get(msg.get("toolCallId"))  # type: ignore[arg-type]
            if normalized_id and normalized_id != msg.get("toolCallId"):
                transformed.append({**result, "toolCallId": normalized_id})
            else:
                transformed.append(result)
            continue
        if role != "assistant":
            transformed.append(msg)
            continue
        replay_mode = _replay_mode_for(msg, model)
        is_same_model = replay_mode == "preserve" or _same_route_model(msg, model)
        raw = msg.get("content")
        source_content = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
        content_out: list[Any] = []
        for block in source_content:
            if not isinstance(block, dict):
                raise TypeError("Cannot read properties of a non-object content block")
            kind = block.get("type")
            if kind == "thinking":
                if replay_mode == "drop":
                    continue
                if js_truthy(block.get("redacted")):
                    if is_same_model:
                        content_out.append(block)
                    continue
                if is_same_model and js_truthy(block.get("thinkingSignature")):
                    content_out.append(block)
                    continue
                thinking = _require_str(block.get("thinking"), "block.thinking.trim")
                if not js_trim(thinking):
                    continue
                content_out.append(block if is_same_model else {"type": "text", "text": thinking})
                continue
            if kind == "text":
                content_out.append(
                    block if is_same_model else {"type": "text", "text": block.get("text")}
                )
                continue
            if kind != "toolCall":
                content_out.append(block)
                continue
            call = block
            if not is_same_model and js_truthy(block.get("async")):
                has_cross_model_async_calls = True
                call = {k: v for k, v in call.items() if k != "async"}
            if (
                not is_same_model
                and js_truthy(block.get("thoughtSignature"))
                and not preserve_cross_model_tool_call_thought_signature
            ):
                call = {k: v for k, v in call.items() if k != "thoughtSignature"}
            if (not is_same_model or normalize_same_model_tool_call_ids) and normalize_tool_call_id:
                normalized = normalize_tool_call_id(block.get("id"), model, msg)  # type: ignore[arg-type]
                if normalized != block.get("id"):
                    tool_call_id_map[block.get("id")] = normalized  # type: ignore[index]
                    call = {**call, "id": normalized}
            content_out.append(call)
        transformed.append({**msg, "content": content_out})
    # Pairing-aware transports must let shared repair see errored tool-call frames and their
    # adjacent results together; pre-filtering the call can misattribute its result to an older
    # turn that reused the same provider id.
    requires_pairing = allow_synthetic or has_cross_model_async_calls
    kept: list[Message] = []
    for index, replay_message in enumerate(transformed):
        original = messages[index] if index < len(messages) else None
        if original is not None:
            if is_reasoning_only_length_assistant_turn(original):
                continue
            decision = resolve_failed_assistant_replay(original, pairing_aware=requires_pairing)
            if decision == "drop":
                continue
            if decision == "marker":
                replay_message = {
                    **replay_message,
                    "content": [{"type": "text", "text": FAILED_ASSISTANT_REPLAY_TEXT}],
                }
        kept.append(replay_message)
    if not requires_pairing:
        return kept
    # The local transport transform can synthesize missing results, but it does not move
    # displaced real results back before an intervening user turn; shared repair handles both and
    # drops aborted/error turns together with their owned results.
    return repair_tool_use_result_pairing(
        kept,
        errored_assistant_result_policy="drop",
        missing_tool_result_text=synthetic_text,
        preserve_unframed_tool_results=preserve_unframed_tool_results,
    ).messages
