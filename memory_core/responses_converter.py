"""The OpenAI Responses message converter (``openai-responses-replay-messages-internal.ts``).

Rebuilds the wire ``input`` array of a Responses request from transcript messages:
``convertResponsesMessages`` (the transport projection) and ``convertProviderResponsesMessages``
(the provider projection). The measured-usage check of
:func:`memory_core.compaction_replay.resolve_responses_context_usage_boundary` replays it to bind a
measured token total to the exact wire prefix that produced it, so the byte shape matters.

Ported with the converter: the replay plan hand-off (``buildOpenAIResponsesCompactionReplayPlan``),
reasoning-item replay and ciphertext fencing, text/tool-call item ids, async tool-result ordering
(``orderResponsesAsyncToolResults``), the delivery-order reconstruction of
``openai-responses-input-replay.ts``, user/tool-result media, and the system prompt message. The
transcript transforms live in :mod:`memory_core.transcript_transform` and the tool-result text
extraction in :mod:`memory_core.tool_result_text`.

An item field that upstream leaves ``undefined`` (``phase``, ``arguments``) is carried as
:data:`memory_core.compaction_replay.UNDEFINED` while the reconstruction runs (``stableStringify``
prints it) and dropped from the returned items, as ``JSON.stringify`` would.

Deviations: see :mod:`memory_core.tool_result_text` (secret redaction of structured tool-result
blocks) and docs/gap4-compaction-notes.md.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from memory_core.bootstrap._js import js_trim, js_truthy, js_utf8_encode, utf16_len
from memory_core.compaction_replay import (
    UNDEFINED,
    ReplayIdentity,
    ReplayModel,
    _js_number_to_string,
    _stable_stringify,
    build_openai_responses_compaction_replay_plan,
    build_openai_responses_replay_context,
    is_openai_responses_replay_context,
    is_safe_responses_replay_item_id,
    provider_replay_context_matches,
    short_hash,
)
from memory_core.tool_result_text import (
    Redactor,
    default_redact_model_visible_secrets,
    describe_tool_result_media_placeholder,
    extract_tool_result_text,
    is_image_with_media_payload,
    sanitize_non_empty_transport_payload_text,
    js_stringify,
    sanitize_transport_payload_text,
)
from memory_core.transcript_transform import (
    transform_provider_messages,
    transform_transport_messages,
)

TOOL_CALL_PROVIDERS = frozenset({"openai", "opencode", "azure-openai-responses", "github-copilot"})
REASONING_REPLAY_META_KEY = "__openclaw_replay"
REASONING_REPLAY_BLOCK_META_KEY = "openclawReasoningReplay"
REPLAY_ITEM_ID_MAX_LENGTH = 64

_CACHE_BOUNDARY = "\n<!-- OPENCLAW_CACHE_BOUNDARY -->\n"
_RELOCATABLE = "\n<!-- OPENCLAW-RELOCATABLE-BOUNDARY -->\n"
_RELOCATABLE_END = "\n<!-- /OPENCLAW-RELOCATABLE-BOUNDARY -->"
_UNSET: Any = object()


def strip_system_prompt_cache_boundary(text: str) -> str:
    """``stripSystemPromptCacheBoundary`` (utils/system-prompt-cache-boundary.ts)."""

    text = text.replace(_CACHE_BOUNDARY, "\n").replace(_CACHE_BOUNDARY.strip(), "")
    return (
        text.replace(_RELOCATABLE, "\n")
        .replace(_RELOCATABLE_END, "")
        .replace(_RELOCATABLE.strip(), "")
        .replace(_RELOCATABLE_END.strip(), "")
    )


def _js_string(record: Mapping[str, Any], key: str) -> str:
    """Template-literal interpolation of ``record[key]``."""

    if key not in record:
        return "undefined"
    value = record[key]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _js_number_to_string(value)
    if isinstance(value, str):
        return value
    return "[object Object]" if isinstance(value, dict) else js_stringify(value)[1:-1]


def _sanitize_id_part(part: str, provider_style: bool) -> str:
    # ``part.replace(/[^a-zA-Z0-9_-]/g, "_")`` runs over UTF-16 code units.
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "_-") else "_" * utf16_len(ch) for ch in part
    )
    return sanitized if provider_style else sanitized.rstrip("_")


def _normalize_id_part(part: str, provider_style: bool) -> str:
    sanitized = _sanitize_id_part(part, provider_style)
    normalized = sanitized[:64] if len(sanitized) > 64 else sanitized
    return normalized.rstrip("_")


def _normalize_replay_item_id(item_id: str | None, prefix: str) -> str | None:
    if not item_id:
        return None
    if utf16_len(item_id) <= REPLAY_ITEM_ID_MAX_LENGTH:
        return item_id
    return f"{prefix}_{short_hash(item_id)}"


def encode_text_signature_v1(item_id: str, phase: str | None = None) -> str:
    """``encodeTextSignatureV1``."""

    payload: dict[str, Any] = {"v": 1, "id": item_id}
    if phase:
        payload["phase"] = phase
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _parse_text_signature(signature: Any) -> dict[str, Any] | None:
    """``parseOpenAIResponsesTextSignature``: ``{"id"?, "phase"?}`` or ``None``."""

    if not js_truthy(signature):
        return None
    if not isinstance(signature, str):
        raise TypeError("signature.startsWith is not a function")
    if signature.startswith("{"):
        try:
            parsed = json.loads(signature, parse_constant=_reject)
            if isinstance(parsed, dict) and parsed.get("v") == 1:
                item_id = parsed.get("id") if isinstance(parsed.get("id"), str) else None
                phase = (
                    parsed.get("phase")
                    if parsed.get("phase") in ("commentary", "final_answer")
                    else None
                )
                # A reasoning-dropped replay keeps the phase but omits the paired id.
                if item_id is not None or phase is not None:
                    return {"id": item_id, "phase": phase}
                return None
            if parsed is None:
                raise TypeError("null")
        except (ValueError, RecursionError, TypeError):
            pass  # keep the legacy plain-string behaviour below
    return {"id": signature, "phase": None}


def _reject(name: str) -> Any:
    raise ValueError(name)


def resolve_replayable_responses_message_id(
    *,
    replay_responses_item_ids: bool,
    text_signature_id: str | None,
    fallback_id: str,
    fallback_ordinal: int,
    previous_replay_item_was_reasoning: bool,
) -> str | None:
    """``resolveReplayableResponsesMessageId`` (openai-responses-replay.ts)."""

    if not replay_responses_item_ids:
        return None
    if not text_signature_id:
        # Id-less text signatures get a deterministic synthetic id per fallback ordinal; signed
        # text can only replay when paired with preceding reasoning.
        return fallback_id if fallback_ordinal == 0 else f"{fallback_id}_{fallback_ordinal}"
    return text_signature_id if previous_replay_item_was_reasoning else None


# --- reasoning items ------------------------------------------------------------------------


def strip_encrypted_reasoning_content_fields(value: Any) -> tuple[Any, bool]:
    """``stripEncryptedReasoningContentFields``: ``(value, changed)``."""

    if not isinstance(value, dict | list):
        return value, False
    if isinstance(value, list):
        changed = False
        out = []
        for item in value:
            stripped, item_changed = strip_encrypted_reasoning_content_fields(item)
            changed = changed or item_changed
            out.append(stripped)
        return (out, True) if changed else (value, False)
    if value.get("type") == "compaction":
        return value, False
    changed = False
    nxt: dict[str, Any] = {}
    for key, child in value.items():
        if key == "encrypted_content":
            changed = True
            continue
        stripped, child_changed = strip_encrypted_reasoning_content_fields(child)
        changed = changed or child_changed
        nxt[key] = stripped
    return (nxt, True) if changed else (value, False)


def _is_reasoning_replay_metadata(value: Any) -> bool:
    return (
        is_openai_responses_replay_context(value)
        and value.get("v") == 1
        and value.get("source") == "openai-responses"
    )


def _read_block_metadata(block: Mapping[str, Any]) -> Any:
    """``readOpenAIResponsesReasoningReplayBlockMetadata``: ``_UNSET``, ``None`` or the record."""

    if REASONING_REPLAY_BLOCK_META_KEY not in block:
        return _UNSET
    value = block[REASONING_REPLAY_BLOCK_META_KEY]
    return value if _is_reasoning_replay_metadata(value) else None


def _normalize_reasoning_item(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") != "reasoning" or isinstance(item.get("summary"), list):
        return item
    return {**item, "summary": []}


def _prepare_reasoning_item(
    item: dict[str, Any],
    context: Mapping[str, Any],
    block_metadata: Any,
    *,
    preserve_unattributed_encrypted_content: bool,
) -> dict[str, Any]:
    has_raw_metadata = REASONING_REPLAY_META_KEY in item
    raw_metadata = item.get(REASONING_REPLAY_META_KEY)
    rest = {k: v for k, v in item.items() if k != REASONING_REPLAY_META_KEY}
    if "encrypted_content" not in rest:
        return _normalize_reasoning_item(rest)
    if block_metadata is not _UNSET:
        metadata = block_metadata
    else:
        metadata = raw_metadata if _is_reasoning_replay_metadata(raw_metadata) else None
    preserve_unattributed = (
        block_metadata is _UNSET
        and not has_raw_metadata
        and preserve_unattributed_encrypted_content
    )
    if preserve_unattributed or (metadata and provider_replay_context_matches(metadata, context)):
        return _normalize_reasoning_item(rest)
    stripped, _ = strip_encrypted_reasoning_content_fields(rest)
    return _normalize_reasoning_item(stripped)


# --- delivery order -------------------------------------------------------------------------


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(js_utf8_encode(text)).hexdigest()


def responses_input_fingerprint(item: Any) -> str:
    """``responsesInputFingerprint``: a call's output is keyed by its call id alone."""

    if (
        isinstance(item, dict)
        and item.get("type") in ("function_call_output", "custom_tool_call_output")
        and isinstance(item.get("call_id"), str)
    ):
        return _sha256_hex(_stable_stringify({"type": item["type"], "call_id": item["call_id"]}))
    return _sha256_hex(_stable_stringify(item))


def _read_input_replay(message: Mapping[str, Any]) -> dict[str, Any] | None:
    replay = message.get("openclawResponsesInputReplay")
    if (
        isinstance(replay, dict)
        and isinstance(replay.get("afterResponseId"), str)
        and isinstance(replay.get("before"), list)
        and all(isinstance(item, str) for item in replay["before"])
        and isinstance(replay.get("after"), list)
        and all(isinstance(item, str) for item in replay["after"])
    ):
        return replay
    return None


def _index_of(items: list[Any], target: Any) -> int:
    for position, item in enumerate(items):
        if item is target:
            return position
    return -1


class _InputReplay:
    """``createResponsesInputReplay``: reconstruct delivery order of deferred inputs."""

    def __init__(self, model: ReplayModel) -> None:
        self.model = model
        self.starts: dict[str, Any] = {}
        self.ends: dict[str, Any] = {}
        self.fingerprints: dict[int, str] = {}

    def _fingerprint(self, item: Any) -> str:
        value = self.fingerprints.get(id(item))
        if value is None:
            value = responses_input_fingerprint(item)
            self.fingerprints[id(item)] = value
        return value

    def __call__(self, inputs: list[Any], output: list[Any], message: Mapping[str, Any]) -> None:
        turn_id = message.get("turnId")
        key = turn_id if js_truthy(turn_id) else message.get("responseId")
        key = key if js_truthy(key) else None
        start = self.starts.get(key) if key is not None else None
        if start is None:
            start = output[0] if output else None
        if key is not None and start is not None:
            self.starts[key] = start
        inputs.extend(output)
        end = inputs[-1] if inputs else None
        replay = _read_input_replay(message)
        parent = self.ends.get(replay["afterResponseId"]) if replay else None
        if (
            replay
            and parent is not None
            and message.get("provider") == self.model.provider
            and message.get("api") == self.model.api
            and message.get("model") == self.model.id
        ):

            def take(keys: list[str]) -> list[Any]:
                moved: list[Any] = []
                # Match the most recent occurrence within this parent's suffix. Identical older
                # user inputs must not be moved when history was edited or compacted.
                for input_key in reversed(keys):
                    boundary = _index_of(inputs, parent)
                    index = -1
                    for position in range(len(inputs) - 1, -1, -1):
                        if position > boundary and self._fingerprint(inputs[position]) == input_key:
                            index = position
                            break
                    if index > boundary:
                        moved.insert(0, inputs.pop(index))
                return moved

            before = take(replay["before"])
            after = take(replay["after"])
            at = _index_of(inputs, start) if start is not None else len(inputs)
            if at < 0:
                at = max(len(inputs) + at, 0)
            inputs[at:at] = before
            end = inputs[-1] if inputs else None
            inputs.extend(after)
        response_id = message.get("responseId")
        if js_truthy(response_id) and end is not None:
            # Deferred inputs are not part of this response's prefix.
            self.ends[response_id] = end


def order_responses_async_tool_results(source: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """``orderResponsesAsyncToolResults``: async results follow their response's last fragment."""

    def turn_key(message: Mapping[str, Any]) -> str | None:
        turn_id = message.get("turnId")
        ident = turn_id if js_truthy(turn_id) else message.get("responseId")
        if not js_truthy(ident):
            return None
        return (
            f"{_js_string(message, 'provider')}:{_js_string(message, 'api')}:"
            f"{_js_string(message, 'model')}:{ident}"
        )

    last_assistant: dict[str, int] = {}
    for index, message in enumerate(source):
        if message.get("role") == "assistant":
            key = turn_key(message)
            if key:
                last_assistant[key] = index
    owners: dict[Any, str] = {}
    pending: dict[int, list[dict[str, Any]]] = {}
    ordered: list[dict[str, Any]] = []
    for index, message in enumerate(source):
        if message.get("role") == "assistant":
            key = turn_key(message)
            if key:
                for block in message["content"]:
                    if block.get("type") == "toolCall" and js_truthy(block.get("async")):
                        owners[block.get("id")] = key
        owner = (
            owners.get(message.get("toolCallId")) if message.get("role") == "toolResult" else None
        )
        last_index = last_assistant.get(owner) if owner else None
        if last_index is not None and last_index > index:
            pending.setdefault(last_index, []).append(message)
        else:
            ordered.append(message)
        results = pending.pop(index, None)
        if results:
            ordered.extend(results)
    return ordered


# --- the converter --------------------------------------------------------------------------


def _responses_message(role: str, content: list[Any]) -> dict[str, Any]:
    return {"type": "message", "role": role, "content": content}


def _data_url(item: Mapping[str, Any]) -> str:
    return f"data:{_js_string(item, 'mimeType')};base64,{_js_string(item, 'data')}"


def _convert(
    model: ReplayModel,
    messages_in: Sequence[dict[str, Any]],
    system_prompt: str | None,
    allowed_tool_call_providers: frozenset[str] | set[str],
    *,
    include_system_prompt: bool | None,
    replay_reasoning_items: bool | None,
    replay_responses_item_ids: bool | None,
    session_id: str | None,
    auth_profile_id: str | None,
    replay_mode: str | None,
    redact: Redactor,
    provider_style: bool,
) -> list[Any]:
    messages: list[Any] = []
    should_replay_reasoning = True if replay_reasoning_items is None else replay_reasoning_items
    should_replay_item_ids = (
        True if replay_responses_item_ids is None else replay_responses_item_ids
    )
    identity = ReplayIdentity(session_id=session_id, auth_profile_id=auth_profile_id)
    replay_context = build_openai_responses_replay_context(model, identity)
    should_normalize_same_model_ids = model.provider == "github-copilot"

    def normalize_id(part: str) -> str:
        return _normalize_id_part(part, provider_style)

    def foreign_item_id(item_id: str) -> str:
        normalized = f"fc_{short_hash(item_id)}"
        return normalized[:64] if len(normalized) > 64 else normalized

    def copilot_item_id(item_id: str) -> str:
        sanitized = _sanitize_id_part(item_id, provider_style)
        candidate = sanitized if sanitized.startswith("fc_") else f"fc_{sanitized}"
        return foreign_item_id(item_id) if len(candidate) > 64 else candidate

    def normalize_tool_call_id(
        tool_id: str, _target: ReplayModel, source: Mapping[str, Any]
    ) -> str:
        if model.provider not in allowed_tool_call_providers:
            return normalize_id(tool_id)
        if "|" not in tool_id:
            return normalize_id(tool_id)
        separator = tool_id.index("|")
        call_id = tool_id[:separator]
        item_id = tool_id[separator + 1 :]
        normalized_call_id = normalize_id(call_id)
        is_foreign = source.get("provider") != model.provider or source.get("api") != model.api
        if is_foreign:
            normalized_item_id = foreign_item_id(item_id)
        elif model.provider == "github-copilot":
            normalized_item_id = (
                normalize_id(item_id) if provider_style else copilot_item_id(item_id)
            )
        else:
            normalized_item_id = normalize_id(item_id)
        if not normalized_item_id.startswith("fc_"):
            normalized_item_id = normalize_id(f"fc_{normalized_item_id}")
        return f"{normalized_call_id}|{normalized_item_id}"

    plan = build_openai_responses_compaction_replay_plan(
        messages_in, model, identity, full_history=replay_mode == "full-history"
    )
    if provider_style:
        transformed = transform_provider_messages(plan["messages"], model, normalize_tool_call_id)
    else:
        transformed = transform_transport_messages(
            plan["messages"],
            model,
            normalize_tool_call_id,
            normalize_same_model_tool_call_ids=should_normalize_same_model_ids,
            preserve_unframed_tool_results=plan["preserveUnframedToolResults"],
        )
    # Results are durable when jobs finish, but Responses continuation must replay every output
    # fragment before adding results to that response's input suffix.
    transformed_messages = order_responses_async_tool_results(transformed)
    include_system = True if include_system_prompt is None else include_system_prompt
    if include_system and system_prompt:
        supports_developer_role = (
            model.compat.get("supportsDeveloperRole") if isinstance(model.compat, Mapping) else None
        )
        role = "developer" if model.reasoning and supports_developer_role is not False else "system"
        messages.append(
            _responses_message(
                role,
                [
                    {
                        "type": "input_text",
                        "text": sanitize_transport_payload_text(
                            strip_system_prompt_cache_boundary(system_prompt)
                        ),
                    }
                ],
            )
        )
    # The compact endpoint's output is already canonical provider input, not internal user
    # content to normalize or reinterpret as text/image blocks.
    if plan.get("compactedWindow"):
        messages.extend(plan["compactedWindow"])
    replay_messages: list[Any] = (
        [plan["compaction"], *transformed_messages]
        if plan.get("compaction")
        else transformed_messages
    )

    # Responses continuation requires the complete prior input before tool output. Each carrier
    # stays with its preceding user/checkpoint; moving it past an appended steering user would
    # rewrite the already admitted request prefix.
    def is_carrier(message: Mapping[str, Any]) -> bool:
        return (
            "role" in message
            and message["role"] == "user"
            and message.get("runtimeContextCarrier") is True
        )

    if any(is_carrier(message) for message in replay_messages):
        anchored: list[Any] = []
        # A canonical window is already emitted above; its checkpoint anchors an otherwise
        # userless tail.
        insertion_index: int | None = 0 if plan.get("compactedWindow") else None
        for message in replay_messages:
            if is_carrier(message) and insertion_index is not None:
                anchored.insert(insertion_index, message)
                insertion_index += 1
                continue
            anchored.append(message)
            if not is_carrier(message) and (
                message["role"] == "user"
                if "role" in message
                else message.get("type") == "compaction"
            ):
                insertion_index = len(anchored)
        replay_messages = anchored

    msg_index = 0
    append_assistant = _InputReplay(model)
    for msg in replay_messages:
        if "role" not in msg:
            messages.append(msg)
            continue
        role = msg["role"]
        if role == "user":
            content = msg.get("content")
            if isinstance(content, str):
                messages.append(
                    _responses_message(
                        "user",
                        [{"type": "input_text", "text": sanitize_transport_payload_text(content)}],
                    )
                )
            else:
                if not isinstance(content, list):
                    raise TypeError("msg.content.map is not a function")
                parts: list[Any] = []
                for item in content:
                    if not isinstance(item, dict):
                        raise TypeError("Cannot read properties of a non-object content block")
                    if item.get("type") == "text":
                        part = {
                            "type": "input_text",
                            "text": sanitize_transport_payload_text(item.get("text")),
                        }
                    else:
                        part = {
                            "type": "input_image",
                            "detail": "auto",
                            "image_url": _data_url(item),
                        }
                    if provider_style or "image" in model.input or part["type"] != "input_image":
                        parts.append(part)
                if parts:
                    messages.append(_responses_message("user", parts))
                elif provider_style:
                    continue
        elif role == "assistant":
            output: list[Any] = []
            text_fallback_ordinal = 0
            previous_was_reasoning = False
            is_different_model = (
                msg.get("model") != model.id
                and msg.get("provider") == model.provider
                and msg.get("api") == model.api
            )
            for block in msg["content"]:
                kind = block.get("type")
                if kind == "thinking":
                    signature = block.get("thinkingSignature")
                    if not (should_replay_reasoning and js_truthy(signature)):
                        continue
                    if isinstance(signature, str):
                        if not (provider_style or signature.startswith("{")):
                            continue
                    elif not provider_style:
                        raise TypeError("block.thinkingSignature.startsWith is not a function")
                    # Persisted signatures are provider-owned data. Skip malformed or unrelated
                    # shapes so one corrupt history item cannot prevent the next request.
                    try:
                        reasoning_item = json.loads(
                            signature if isinstance(signature, str) else json.dumps(signature),
                            parse_constant=_reject,
                        )
                    except (ValueError, RecursionError):
                        continue
                    if (
                        not isinstance(reasoning_item, dict)
                        or reasoning_item.get("type") != "reasoning"
                    ):
                        continue
                    item = _prepare_reasoning_item(
                        reasoning_item,
                        replay_context,
                        _read_block_metadata(block),
                        preserve_unattributed_encrypted_content=provider_style,
                    )
                    if not should_replay_item_ids:
                        item.pop("id", None)
                    if (
                        should_replay_item_ids
                        and not provider_style
                        and model.provider == "github-copilot"
                        and not is_safe_responses_replay_item_id(item.get("id"))
                    ):
                        continue
                    output.append(item)
                    previous_was_reasoning = True
                elif kind == "text":
                    text_signature = _parse_text_signature(block.get("textSignature"))
                    signature_id = text_signature["id"] if text_signature else None
                    message_id = resolve_replayable_responses_message_id(
                        replay_responses_item_ids=should_replay_item_ids,
                        text_signature_id=signature_id,
                        fallback_id=f"msg_{msg_index}",
                        fallback_ordinal=text_fallback_ordinal,
                        previous_replay_item_was_reasoning=previous_was_reasoning,
                    )
                    if not signature_id:
                        text_fallback_ordinal += 1
                    message_id = _normalize_replay_item_id(message_id, "msg")
                    message_item: dict[str, Any] = {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": sanitize_transport_payload_text(block.get("text")),
                                "annotations": [],
                            }
                        ],
                        "status": "completed",
                    }
                    if message_id:
                        message_item["id"] = message_id
                    phase = text_signature["phase"] if text_signature else None
                    message_item["phase"] = phase if phase is not None else UNDEFINED
                    output.append(message_item)
                    previous_was_reasoning = False
                elif kind == "toolCall":
                    block_id = block.get("id")
                    if not isinstance(block_id, str):
                        raise TypeError("block.id.indexOf is not a function")
                    separator = block_id.find("|")
                    call_id = block_id if separator == -1 else block_id[:separator]
                    item_id_raw = None if separator == -1 else block_id[separator + 1 :]
                    item_id = (
                        item_id_raw
                        if should_replay_item_ids
                        and not (
                            is_different_model and item_id_raw and item_id_raw.startswith("fc_")
                        )
                        else None
                    )
                    call: dict[str, Any] = {"type": "function_call"}
                    if item_id:
                        call["id"] = item_id
                    call["call_id"] = call_id
                    call["name"] = block.get("name", UNDEFINED)
                    if js_truthy(block.get("async")):
                        call["async"] = True
                    arguments = block.get("arguments", UNDEFINED)
                    if provider_style:
                        call["arguments"] = (
                            UNDEFINED if arguments is UNDEFINED else js_stringify(arguments)
                        )
                    elif isinstance(arguments, str):
                        call["arguments"] = arguments
                    else:
                        call["arguments"] = js_stringify(
                            {} if arguments is None or arguments is UNDEFINED else arguments
                        )
                    output.append(call)
                    previous_was_reasoning = False
            # Completed encrypted reasoning is self-contained, including steered async fragments.
            # After route checks strip ciphertext, bare ids still need a following item.
            while output:
                last = output[-1]
                encrypted = last.get("encrypted_content")
                if (
                    last.get("type") != "reasoning"
                    or not (isinstance(last.get("id"), str) and last["id"].startswith("rs_"))
                    or (isinstance(encrypted, str) and len(encrypted) > 0)
                ):
                    break
                output.pop()
            append_assistant(messages, output, msg)
            if not output and provider_style:
                continue
        elif role == "toolResult":
            content = msg.get("content")
            text_result = extract_tool_result_text(content, redact=redact)
            sanitized_text = sanitize_transport_payload_text(text_result)
            has_text = bool(js_trim(sanitized_text))
            placeholder = describe_tool_result_media_placeholder(content)
            has_images = any(is_image_with_media_payload(item) for item in content)
            tool_call_id = msg.get("toolCallId")
            if not isinstance(tool_call_id, str):
                raise TypeError("msg.toolCallId.indexOf is not a function")
            separator = tool_call_id.find("|")
            call_id = tool_call_id if separator == -1 else tool_call_id[:separator]
            if has_images and "image" in model.input:
                parts = []
                if has_text:
                    parts.append({"type": "input_text", "text": sanitized_text})
                elif placeholder == "(see attached media)":
                    parts.append({"type": "input_text", "text": placeholder})
                parts.extend(
                    {"type": "input_image", "detail": "auto", "image_url": _data_url(item)}
                    for item in content
                    if is_image_with_media_payload(item)
                )
                tool_output: Any = parts
            else:
                tool_output = sanitize_non_empty_transport_payload_text(
                    text_result, placeholder or "(no output)"
                )
            messages.append(
                {"type": "function_call_output", "call_id": call_id, "output": tool_output}
            )
        msg_index += 1
    return [_drop_undefined(item) for item in messages]


def _drop_undefined(item: Any) -> Any:
    if isinstance(item, dict) and any(value is UNDEFINED for value in item.values()):
        return {key: value for key, value in item.items() if value is not UNDEFINED}
    return item


def convert_responses_messages(
    model: ReplayModel,
    messages: Sequence[dict[str, Any]],
    system_prompt: str | None = None,
    allowed_tool_call_providers: frozenset[str] | set[str] = TOOL_CALL_PROVIDERS,
    *,
    include_system_prompt: bool | None = None,
    replay_reasoning_items: bool | None = None,
    replay_responses_item_ids: bool | None = None,
    session_id: str | None = None,
    auth_profile_id: str | None = None,
    replay_mode: str | None = None,
    redact: Redactor = default_redact_model_visible_secrets,
) -> list[Any]:
    """``convertResponsesMessages``: the transport projection of the Responses ``input``."""

    return _convert(
        model,
        messages,
        system_prompt,
        allowed_tool_call_providers,
        include_system_prompt=include_system_prompt,
        replay_reasoning_items=replay_reasoning_items,
        replay_responses_item_ids=replay_responses_item_ids,
        session_id=session_id,
        auth_profile_id=auth_profile_id,
        replay_mode=replay_mode,
        redact=redact,
        provider_style=False,
    )


def convert_provider_responses_messages(
    model: ReplayModel,
    messages: Sequence[dict[str, Any]],
    system_prompt: str | None = None,
    allowed_tool_call_providers: frozenset[str] | set[str] = TOOL_CALL_PROVIDERS,
    *,
    include_system_prompt: bool | None = None,
    replay_responses_item_ids: bool | None = None,
    session_id: str | None = None,
    auth_profile_id: str | None = None,
    replay_mode: str | None = None,
    redact: Redactor = default_redact_model_visible_secrets,
) -> list[Any]:
    """``convertProviderResponsesMessages``: the provider projection (no reasoning toggle)."""

    return _convert(
        model,
        messages,
        system_prompt,
        allowed_tool_call_providers,
        include_system_prompt=include_system_prompt,
        replay_reasoning_items=None,
        replay_responses_item_ids=replay_responses_item_ids,
        session_id=session_id,
        auth_profile_id=auth_profile_id,
        replay_mode=replay_mode,
        redact=redact,
        provider_style=True,
    )


def default_responses_input_projector(
    model: ReplayModel,
    identity: ReplayIdentity | None = None,
    *,
    redact: Redactor = default_redact_model_visible_secrets,
):
    """The built-in ``projector`` of the measured-usage check, bound to a model and identity.

    ``(projection, provider messages, system prompt, include_system_prompt) -> wire input``,
    exactly what ``resolveResponsesContextUsageBoundary`` calls ``convert*ResponsesMessages``
    with (``TOOL_CALL_PROVIDERS``, the identity's session and auth profile).
    """

    identity = identity or ReplayIdentity()

    def project(
        projection: str, messages: list[Any], system_prompt: str | None, include: bool
    ) -> list[Any]:
        convert = (
            convert_responses_messages
            if projection == "transport"
            else convert_provider_responses_messages
        )
        return convert(
            model,
            messages,
            system_prompt,
            session_id=identity.session_id,
            auth_profile_id=identity.auth_profile_id,
            include_system_prompt=include,
            redact=redact,
        )

    return project
