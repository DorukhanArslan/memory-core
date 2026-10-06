"""Compaction replay checkpoint owners (packages/ai/src/transports/provider-compaction-replay.ts).

A server-side compaction checkpoint (``providerReplay`` of type ``anthropic-compaction``,
``openai-responses-compaction`` or ``openai-responses-retained-compaction``) is bound to the
exact assistant content that produced it. Every local history rewrite of such an owner message
goes through :func:`replace_compaction_replay_owner_content`, which re-indexes the checkpoint
(``replayIndex``) over the surviving blocks, or strips it when the rewrite makes the binding
ambiguous.

Ported: ``isCompactionReplayCheckpoint``, ``stripCompactionReplayCheckpoint``,
``stripCompactionReplayCheckpointInPlace``, ``replaceCompactionReplayOwnerContent``,
``resolveCompactionSource`` (with ``resolveNewestAnthropicCompaction`` and
``resolveNewestOpenAIResponsesCompactionReplay``), ``preserveCompactionReplayWindow``,
``requiresCompactionReplayRefresh``, the two replay-plan builders and the provider replay
context fence (``buildProviderReplayContext``, ``shortHash``). The model identity and the
session/auth identity are plain parameters (:class:`ReplayModel`, :class:`ReplayIdentity`).
Also ported: the capture and suppression writers (``createCompactionCapture``,
``suppressAnthropicCompaction``, ``captureOpenAIResponsesCompaction``,
``suppressOpenAIResponsesCompaction``, ``createCompactionTracker``),
``resolveCompactionReplayEligibility`` (with the Anthropic server-compaction gate),
``resolveCompactionReplayPressure`` with ``resolveResponsesContextUsageBoundary``, and the
compact-endpoint egress projection (:mod:`memory_core.responses_egress`: inline image sanitiser
plus the Responses payload policy), which ``readOpenAIResponsesCompactionWindow`` uses to require
the saved window to survive egress unchanged. ``egress_projection`` stays an optional override of
that built-in projection.

Host hooks: the Responses message converter that rebuilds the wire input for the measured-usage
check (``projector``), the plugin-manifest endpoint classes and the secret-sentinel swap of the
Anthropic eligibility gate.

``replaceCompactionReplayOwnerContent`` matches surviving blocks with ``Array.prototype.indexOf``,
that is by object identity for objects and arrays; the port uses ``is`` for the same reason, so a
caller must pass the *same* block objects it read from ``message["content"]``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory_core.bootstrap._js import (
    _units,
    js_json_stringify,
    js_trim,
    js_truthy,
    js_utf8_encode,
    reject_json_constant,
    utf16_len,
    utf16_slice,
)
from memory_core.js_url import url_hostname
from memory_core.responses_egress import OPENAI_RESPONSES_APIS, project_responses_input

COMPACTION_REPLAY_CHECKPOINT_TYPES = frozenset(
    {
        "anthropic-compaction",
        "openai-responses-compaction",
        "openai-responses-retained-compaction",
    }
)


def is_compaction_replay_checkpoint(replay: Any) -> bool:
    """Whether provider replay state is a prefix-bound server compaction checkpoint."""

    replay_type = replay.get("type") if isinstance(replay, Mapping) else None
    return isinstance(replay_type, str) and replay_type in COMPACTION_REPLAY_CHECKPOINT_TYPES


def strip_compaction_replay_checkpoint(message: Mapping[str, Any]) -> Mapping[str, Any]:
    """Drop a prefix-bound checkpoint after a local history rewrite (the input when none)."""

    if not is_compaction_replay_checkpoint(message.get("providerReplay")):
        return message
    return {key: value for key, value in message.items() if key != "providerReplay"}


def strip_compaction_replay_checkpoint_in_place(message: dict[str, Any]) -> None:
    """Drop a prefix-bound checkpoint from an in-place message rewrite."""

    if is_compaction_replay_checkpoint(message.get("providerReplay")):
        del message["providerReplay"]


def replace_compaction_replay_owner_content(
    message: Mapping[str, Any], content: list[Any]
) -> dict[str, Any] | Mapping[str, Any]:
    """Replace an assistant message's content and re-index its compaction checkpoint.

    The checkpoint stays (re-indexed when blocks before ``replayIndex`` were removed) only when
    every new block is one of the original blocks, in order; otherwise it is stripped. A
    retained-user checkpoint has no content index and is kept as is. Raises ``TypeError`` where
    upstream throws (a ``null`` original content, or a non-array, non-string original content
    with new blocks to look up).
    """

    following: dict[str, Any] = {**message, "content": content}
    replay = message.get("providerReplay")
    if not is_compaction_replay_checkpoint(replay):
        return following
    if replay["type"] == "openai-responses-retained-compaction":
        # Anchored to retained user turns, not assistant content indexes.
        return following
    replay_index = replay.get("replayIndex")
    if replay_index is None:
        replay_index = 0
    original = message.get("content")
    original_length = _js_length(original)
    if (len(content) == 0 and original_length is not None and original_length > 0) or (
        original_length is not None and replay_index > original_length
    ):
        return strip_compaction_replay_checkpoint(following)
    source_index = 0
    next_replay_index = 0
    for block in content:
        index = _js_index_of(original, block, source_index)
        source_index = index + 1
        if index >= 0 and index < replay_index:
            next_replay_index += 1
        if index < 0:
            return strip_compaction_replay_checkpoint(following)
    if next_replay_index == replay_index:
        return following
    return {**following, "providerReplay": {**replay, "replayIndex": next_replay_index}}


def _js_length(value: Any) -> int | None:
    """``value.length``: ``None`` for ``undefined``; ``TypeError`` for ``null``."""

    if isinstance(value, list | str):
        return len(value)
    if value is None:
        raise TypeError("Cannot read properties of null (reading 'length')")
    return None


def _js_index_of(items: Any, target: Any, from_index: int) -> int:
    """``items.indexOf(target, from_index)`` with strict equality (identity for objects)."""

    if isinstance(items, str):
        needle = target if isinstance(target, str) else "[object Object]"
        return items.find(needle, from_index) if isinstance(target, str | dict) else -1
    if not isinstance(items, list):
        raise TypeError("message.content.indexOf is not a function")
    for index in range(from_index, len(items)):
        if _strict_equals(items[index], target):
            return index
    return -1


def _strict_equals(left: Any, right: Any) -> bool:
    if isinstance(left, dict | list) or isinstance(right, dict | list):
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return left == right
    return type(left) is type(right) and left == right


# --- provider replay context fence ---------------------------------------------------------

_MISSING: Any = object()
_ANTHROPIC_TYPE = "anthropic-compaction"
_ANTHROPIC_SUPPRESSION_TYPE = "anthropic-compaction-suppression"
_RESPONSES_TYPE = "openai-responses-compaction"
_RESPONSES_RETAINED_TYPE = "openai-responses-retained-compaction"
_RESPONSES_SUPPRESSION_TYPE = "openai-responses-compaction-suppression"
_SUPPRESSION_DATA = "rejected"
_REPLAY_ITEM_ID_MAX_LENGTH = 64
_COMPACTION_WINDOW_MAX_BYTES = 16 * 1024 * 1024
_MAX_SAFE_INTEGER = 2**53 - 1

EgressProjection = Callable[[list[Any]], Any]


@dataclass(frozen=True)
class ReplayModel:
    """The model identity the checkpoint is fenced to (``Model.provider/api/id/baseUrl``)."""

    provider: str
    api: str
    id: str
    base_url: str | None = None


@dataclass(frozen=True)
class ReplayIdentity:
    """``ReplayIdentity``: session, auth profile and the Anthropic server-compaction switch."""

    session_id: str | None = None
    auth_profile_id: str | None = None
    enabled: bool | None = None


def _base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while value:
        value, rem = divmod(value, 36)
        out = digits[rem] + out
    return out or "0"


def short_hash(text: str) -> str:
    """``shortHash`` (packages/ai/src/utils/hash.ts), over UTF-16 code units."""

    mask = 0xFFFFFFFF
    h1, h2 = 0xDEADBEEF, 0x41C6CE57
    units = _units(text)
    for i in range(0, len(units), 2):
        ch = units[i] | (units[i + 1] << 8)
        h1 = ((h1 ^ ch) * 2654435761) & mask
        h2 = ((h2 ^ ch) * 1597334677) & mask
    h1 = (((h1 ^ (h1 >> 16)) * 2246822507) & mask) ^ (((h2 ^ (h2 >> 13)) * 3266489909) & mask)
    h2 = (((h2 ^ (h2 >> 16)) * 2246822507) & mask) ^ (((h1 ^ (h1 >> 13)) * 3266489909) & mask)
    return _base36(h2) + _base36(h1)


def _hash_context_value(value: str | None) -> str | None:
    normalized = js_trim(value) if value is not None else None
    return short_hash(normalized) if normalized else None


def build_provider_replay_context(
    model: ReplayModel, identity: ReplayIdentity | None = None
) -> dict[str, Any]:
    """``buildProviderReplayContext``; absent hashes are ``None`` (``undefined`` upstream)."""

    identity = identity or ReplayIdentity()
    return {
        "provider": model.provider,
        "api": model.api,
        "model": model.id,
        "baseUrlHash": _hash_context_value(model.base_url),
        "sessionHash": _hash_context_value(identity.session_id),
        "authProfileHash": _hash_context_value(identity.auth_profile_id),
    }


def provider_replay_context_matches(state: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    """``providerReplayContextMatches``: the replay state is fenced to the exact identity."""

    return all(
        _strict_equals(state.get(key), context.get(key))
        for key in ("provider", "api", "model", "baseUrlHash", "sessionHash", "authProfileHash")
    )


# --- state readers -------------------------------------------------------------------------


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_opt_str(value: Any) -> bool:
    """``undefined`` (absent) or a string: ``null`` is rejected."""

    return value is _MISSING or isinstance(value, str)


def _is_safe_index(value: Any) -> bool:
    """``Number.isSafeInteger(value) && value >= 0``."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    if isinstance(value, float) and not (math.isfinite(value) and value == math.floor(value)):
        return False
    return 0 <= value <= _MAX_SAFE_INTEGER


def _type_of(value: Any) -> Any:
    return value.get("type") if isinstance(value, dict) else None


def _field(value: dict[str, Any], key: str) -> Any:
    return value.get(key, _MISSING)


def _read_anthropic_state(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if not (
        _strict_equals(_field(value, "v"), 1)
        and _is_str(_field(value, "data"))
        and _is_str(_field(value, "provider"))
        and _is_str(_field(value, "api"))
        and _is_str(_field(value, "model"))
        and _is_str(_field(value, "baseUrlHash"))
        and _is_opt_str(_field(value, "sessionHash"))
        and _is_opt_str(_field(value, "authProfileHash"))
    ):
        return None
    if value.get("type") == _ANTHROPIC_SUPPRESSION_TYPE:
        return value if value["data"] == _SUPPRESSION_DATA else None
    encrypted = _field(value, "encryptedContent")
    replay_index = _field(value, "replayIndex")
    ok = (
        value.get("type") == _ANTHROPIC_TYPE
        and len(value["data"]) > 0
        and (encrypted is _MISSING or encrypted is None or isinstance(encrypted, str))
        and (replay_index is _MISSING or _is_safe_index(replay_index))
    )
    return value if ok else None


def _read_responses_state(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if not (
        _is_str(_field(value, "provider"))
        and _is_str(_field(value, "api"))
        and _is_str(_field(value, "model"))
        and _is_opt_str(_field(value, "baseUrlHash"))
        and _is_opt_str(_field(value, "sessionHash"))
        and _is_opt_str(_field(value, "authProfileHash"))
    ):
        return None
    if not _is_str(_field(value, "baseUrlHash")) or not _strict_equals(_field(value, "v"), 1):
        return None
    state_type = value.get("type")
    data = _field(value, "data")
    if state_type == _RESPONSES_SUPPRESSION_TYPE:
        return value if data == _SUPPRESSION_DATA else None
    replay_index = _field(value, "replayIndex")
    if state_type == _RESPONSES_RETAINED_TYPE:
        ok = (
            _is_str(data)
            and len(data) > 0
            and _is_opt_str(_field(value, "id"))
            and replay_index is _MISSING
        )
        return value if ok else None
    ok = (
        state_type == _RESPONSES_TYPE
        and _is_str(data)
        and len(data) > 0
        and _is_opt_str(_field(value, "id"))
        and (replay_index is _MISSING or _is_safe_index(replay_index))
    )
    return value if ok else None


def _is_bounded_json(value: Any, depth: int = 0) -> bool:
    if depth > 64:
        return False
    if value is None or isinstance(value, str | bool):
        return True
    if isinstance(value, int | float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_bounded_json(child, depth + 1) for child in value)
    if isinstance(value, dict):
        return all(_is_bounded_json(child, depth + 1) for child in value.values())
    return False


def _is_input_content(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    breakpoint_ = _field(value, "prompt_cache_breakpoint")
    if breakpoint_ is not _MISSING and (
        not isinstance(breakpoint_, dict) or breakpoint_.get("mode") != "explicit"
    ):
        return False
    kind = value.get("type")
    if kind == "input_text":
        return _is_str(_field(value, "text"))
    if kind == "input_image":
        image_url, file_id = _field(value, "image_url"), _field(value, "file_id")
        return (
            _is_str(_field(value, "detail"))
            and value["detail"] in ("auto", "low", "high", "original")
            and (_is_str(image_url) or _is_str(file_id))
            and (image_url is None or _is_opt_str(image_url))
            and (file_id is None or _is_opt_str(file_id))
        )
    if kind == "input_file":
        detail = _field(value, "detail")
        file_id = _field(value, "file_id")
        return (
            (detail is _MISSING or (_is_str(detail) and detail in ("auto", "low", "high")))
            and any(_is_str(_field(value, key)) for key in ("file_data", "file_id", "file_url"))
            and _is_opt_str(_field(value, "file_data"))
            and (file_id is None or _is_opt_str(file_id))
            and _is_opt_str(_field(value, "file_url"))
            and _is_opt_str(_field(value, "filename"))
        )
    return False


def is_openai_responses_compaction_output(
    value: Any,
    model: ReplayModel | None = None,
    egress_projection: EgressProjection | None = None,
) -> bool:
    """``isOpenAIResponsesCompactionOutput``: schema validation of a saved compacted window.

    The window must also survive provider egress unchanged: the inline image sanitiser and, with
    a ``model``, the Responses payload policy (:mod:`memory_core.responses_egress`).
    ``egress_projection`` overrides that built-in projection.
    """

    if not isinstance(value, list) or len(value) == 0 or not _is_bounded_json(value):
        return False
    item = value[-1]
    if not (
        isinstance(item, dict)
        and item.get("type") == "compaction"
        and _is_str(item.get("encrypted_content"))
        and len(item["encrypted_content"]) > 0
        and _is_opt_str(_field(item, "id"))
        and _is_opt_str(_field(item, "created_by"))
    ):
        return False
    for message in value[:-1]:
        if not (
            isinstance(message, dict)
            and message.get("type") == "message"
            and _is_str(message.get("role"))
            and message["role"] in ("user", "developer", "system")
            and _is_opt_str(_field(message, "id"))
            and (
                _field(message, "status") is _MISSING
                or (
                    _is_str(message.get("status"))
                    and message["status"] in ("in_progress", "completed", "incomplete")
                )
            )
            and isinstance(message.get("content"), list)
            and all(_is_input_content(part) for part in message["content"])
        ):
            return False
    projected = (
        egress_projection(value)
        if egress_projection is not None
        else project_responses_input(value, model)
    )
    return js_json_stringify(projected) == js_json_stringify(value)


def read_openai_responses_compaction_window(
    replay: Mapping[str, Any],
    model: ReplayModel | None = None,
    egress_projection: EgressProjection | None = None,
) -> list[Any] | None:
    """``readOpenAIResponsesCompactionWindow``: the saved window when it matches its checkpoint."""

    window = replay.get("compactedWindow")
    if (
        not isinstance(window, dict)
        or window.get("state") != "ready"
        or not isinstance(window.get("output"), str)
    ):
        return None
    if (
        len(js_utf8_encode(window["output"])) + len(js_utf8_encode(replay["data"]))
        > _COMPACTION_WINDOW_MAX_BYTES
    ):
        return None
    try:
        if len(js_utf8_encode(js_json_stringify(replay))) > _COMPACTION_WINDOW_MAX_BYTES:
            return None
        output = json.loads(window["output"], parse_constant=reject_json_constant)
        if not is_openai_responses_compaction_output(output, model, egress_projection):
            return None
        item = output[-1]
        if (
            item.get("type") == "compaction"
            and item.get("encrypted_content") == replay["data"]
            and item.get("id") == replay.get("id")
        ):
            return output
        return None
    except (ValueError, RecursionError):
        return None


def is_safe_responses_replay_item_id(item_id: Any) -> bool:
    return isinstance(item_id, str) and 0 < utf16_len(item_id) <= _REPLAY_ITEM_ID_MAX_LENGTH


# --- checkpoint resolvers ------------------------------------------------------------------


def resolve_newest_anthropic_compaction(
    messages: Sequence[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity | None = None,
) -> dict[str, Any] | None:
    """``resolveNewestAnthropicCompaction``: the newest matching checkpoint, or ``None``."""

    context = build_provider_replay_context(model, identity)
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        state = _read_anthropic_state(message.get("providerReplay"))
        if state is not None and state.get("type") == _ANTHROPIC_SUPPRESSION_TYPE:
            if provider_replay_context_matches(state, context):
                return None
            continue
        if _type_of(message.get("providerReplay")) != _ANTHROPIC_TYPE:
            continue
        if state is None or not provider_replay_context_matches(state, context):
            return None
        selected: dict[str, Any] = {
            "owner": message,
            "replayIndex": int(state.get("replayIndex", 0)),
            "summary": state["data"],
        }
        if "encryptedContent" in state:
            selected["encryptedContent"] = state["encryptedContent"]
        return selected
    return None


def resolve_newest_openai_responses_compaction_replay(
    messages: Sequence[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity | None = None,
    egress_projection: EgressProjection | None = None,
) -> dict[str, Any] | None:
    """``resolveNewestOpenAIResponsesCompactionReplay``.

    Modes: ``compacted-prefix``, ``complete-window`` and ``refresh-required``.
    """

    context = build_provider_replay_context(model, identity)
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        raw = message.get("providerReplay")
        replay = _read_responses_state(raw)
        if replay is not None and replay.get("type") == _RESPONSES_SUPPRESSION_TYPE:
            if provider_replay_context_matches(replay, context):
                return None
            continue
        if replay is None or replay.get("type") not in (_RESPONSES_TYPE, _RESPONSES_RETAINED_TYPE):
            if _type_of(raw) in (_RESPONSES_TYPE, _RESPONSES_RETAINED_TYPE):
                return None
            continue
        if not provider_replay_context_matches(replay, context):
            return None
        retained = replay["type"] == _RESPONSES_RETAINED_TYPE
        if "compactedWindow" in replay or retained:
            output = read_openai_responses_compaction_window(replay, model, egress_projection)
            item = output[-1] if output else None
            if not output or not isinstance(item, dict) or item.get("type") != "compaction":
                return {"owner": message, "mode": "refresh-required"}
            return {
                "owner": message,
                "mode": "complete-window",
                "output": output,
                "item": item,
                "replayIndex": (
                    _content_length(message) if retained else int(replay.get("replayIndex", 0))
                ),
            }
        prefix_item: dict[str, Any] = {"type": "compaction"}
        if is_safe_responses_replay_item_id(replay.get("id")):
            prefix_item["id"] = replay["id"]
        prefix_item["encrypted_content"] = replay["data"]
        return {
            "owner": message,
            "item": prefix_item,
            "mode": "compacted-prefix",
            "replayIndex": int(replay.get("replayIndex", 0)),
        }
    return None


def _content_length(message: Mapping[str, Any]) -> int:
    length = _js_length(message.get("content"))
    if length is None:
        raise TypeError("message.content.length is undefined")
    return length


def resolve_compaction_source(
    messages: Sequence[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity,
    egress_projection: EgressProjection | None = None,
) -> dict[str, Any] | None:
    """``resolveCompactionSource``: the newest usable checkpoint with its ``family``.

    ``owner`` is the very message object from ``messages`` (identity, like upstream).
    """

    if identity.enabled is False:
        return None
    assistants = [m for m in messages if m.get("role") == "assistant"]
    selected: dict[str, Any] | None
    if model.api in OPENAI_RESPONSES_APIS:
        responses = resolve_newest_openai_responses_compaction_replay(
            assistants, model, identity, egress_projection
        )
        selected = {"family": "responses", **responses} if responses else None
    elif identity.enabled is not True:
        selected = None
    else:
        anthropic = resolve_newest_anthropic_compaction(assistants, model, identity)
        selected = {"family": "anthropic", **anthropic} if anthropic else None
    if selected is None:
        return None
    owner = next((m for m in assistants if m is selected["owner"]), None)
    return {**selected, "owner": owner} if owner is not None else None


def requires_compaction_replay_refresh(
    messages: Sequence[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity,
    egress_projection: EgressProjection | None = None,
) -> bool:
    """``requiresCompactionReplayRefresh``: a Responses checkpoint that needs ``/compact``."""

    checkpoint = resolve_compaction_source(messages, model, identity, egress_projection)
    return (
        checkpoint is not None
        and checkpoint["family"] == "responses"
        and checkpoint["mode"] == "refresh-required"
    )


def preserve_compaction_replay_window(
    source: Sequence[Mapping[str, Any]],
    windowed: list[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity,
    egress_projection: EgressProjection | None = None,
) -> list[Mapping[str, Any]]:
    """``preserveCompactionReplayWindow``: carry the checkpoint through history limiting.

    When the window dropped the checkpoint owner, the owner returns as an empty projected
    message (``replayIndex`` 0) followed by the windowed messages that originally came after it.
    """

    checkpoint = resolve_compaction_source(source, model, identity, egress_projection)
    if checkpoint is None or any(message is checkpoint["owner"] for message in windowed):
        return windowed
    owner = checkpoint["owner"]
    replay = owner.get("providerReplay")
    if isinstance(replay, dict) and replay.get("type") == _RESPONSES_RETAINED_TYPE:
        provider_replay = replay
    else:
        provider_replay = {**(replay if isinstance(replay, dict) else {}), "replayIndex": 0}
    owner_index = next(i for i, message in enumerate(source) if message is owner)
    suffix = {id(message) for message in source[owner_index + 1 :]}
    return [
        {**owner, "content": [], "providerReplay": provider_replay},
        *(message for message in windowed if id(message) in suffix),
    ]


def build_anthropic_replay_plan(
    messages: Sequence[Mapping[str, Any]], model: ReplayModel, identity: ReplayIdentity
) -> dict[str, Any]:
    """``buildAnthropicReplayPlan``: ``{"messages", "compaction"?}``."""

    if identity.enabled is not True:
        return {"messages": list(messages)}
    checkpoint = resolve_newest_anthropic_compaction(messages, model, identity)
    if checkpoint is None:
        return {"messages": list(messages)}
    owner_index = next(i for i, m in enumerate(messages) if m is checkpoint["owner"])
    owner = {
        **checkpoint["owner"],
        "content": checkpoint["owner"]["content"][checkpoint["replayIndex"] :],
    }
    compaction: dict[str, Any] = {"type": "compaction", "content": checkpoint["summary"]}
    if "encryptedContent" in checkpoint:
        compaction["encrypted_content"] = checkpoint["encryptedContent"]
    return {"messages": [owner, *messages[owner_index + 1 :]], "compaction": compaction}


class CompactionReplayRefreshRequiredError(Exception):
    """``CompactionReplayRefreshRequiredError``: the checkpoint must be rebuilt with /compact."""

    def __init__(self) -> None:
        super().__init__(
            "Provider compaction checkpoint needs rebuilding. "
            "Run /compact to rebuild from saved conversation history."
        )


def build_openai_responses_compaction_replay_plan(
    messages: Sequence[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity | None = None,
    *,
    full_history: bool = False,
    egress_projection: EgressProjection | None = None,
) -> dict[str, Any]:
    """``buildOpenAIResponsesCompactionReplayPlan``.

    Raises :class:`CompactionReplayRefreshRequiredError` for a checkpoint that needs a rebuild.
    """

    if full_history:
        return {"messages": list(messages), "preserveUnframedToolResults": False}
    compaction = resolve_newest_openai_responses_compaction_replay(
        messages, model, identity, egress_projection
    )
    if compaction is None:
        return {"messages": list(messages), "preserveUnframedToolResults": False}
    if compaction["mode"] == "refresh-required":
        raise CompactionReplayRefreshRequiredError
    owner_index = next(i for i, m in enumerate(messages) if m is compaction["owner"])
    owner = {
        **compaction["owner"],
        "content": compaction["owner"]["content"][compaction["replayIndex"] :],
    }
    plan: dict[str, Any] = {"messages": [owner, *messages[owner_index + 1 :]]}
    if compaction["mode"] == "complete-window":
        plan["compactedWindow"] = compaction["output"]
    else:
        plan["compaction"] = compaction["item"]
    plan["preserveUnframedToolResults"] = True
    return plan


# --- replay context readers and the capture/suppression writers ------------------------------


class ResponsesCompactionCaptureError(Exception):
    """The ``Error`` ``captureOpenAIResponsesCompaction`` throws for a window it cannot keep."""


def _defined(context: Mapping[str, Any]) -> dict[str, Any]:
    """The replay context without its absent (``undefined``) hashes."""

    return {key: value for key, value in context.items() if value is not None}


def is_openai_responses_replay_context(value: Any) -> bool:
    """``isOpenAIResponsesReplayContext``: provider, api and model plus optional string hashes."""

    if not isinstance(value, dict):
        return False
    return (
        _is_str(value.get("provider"))
        and _is_str(value.get("api"))
        and _is_str(value.get("model"))
        and _is_opt_str(_field(value, "baseUrlHash"))
        and _is_opt_str(_field(value, "sessionHash"))
        and _is_opt_str(_field(value, "authProfileHash"))
    )


def build_openai_responses_replay_context(
    model: ReplayModel, identity: ReplayIdentity | None = None
) -> dict[str, Any]:
    """``buildOpenAIResponsesReplayContext`` (the provider replay context)."""

    return build_provider_replay_context(model, identity)


def build_openai_responses_reasoning_replay_metadata(
    model: ReplayModel, identity: ReplayIdentity | None = None
) -> dict[str, Any]:
    """``buildOpenAIResponsesReasoningReplayMetadata``: ``{v, source, ...context}`` sans ``None``."""

    return {
        "v": 1,
        "source": "openai-responses",
        **_defined(build_provider_replay_context(model, identity)),
    }


class CompactionCapture:
    """``createCompactionCapture`` (anthropic-compaction-replay.ts): stream compaction capture.

    ``begin``/``delta``/``complete`` follow the Anthropic stream events of a ``compaction``
    content block; ``complete`` writes ``output["providerReplay"]`` when the block carries a
    summary, the model has a base URL and ``replayIndex`` is a non-negative safe integer.
    """

    def __init__(
        self,
        output: dict[str, Any],
        model: ReplayModel,
        identity: ReplayIdentity | None = None,
    ) -> None:
        self._output = output
        self._model = model
        self._identity = identity
        self._pending: dict[Any, dict[str, Any]] = {}

    def begin(self, index: Any, block: Any, replay_index: Any) -> bool:
        if not isinstance(block, dict) or block.get("type") != "compaction":
            return False
        content = block.get("content")
        pending: dict[str, Any] = {
            "content": content if isinstance(content, str) else "",
            "replayIndex": replay_index,
        }
        if "encrypted_content" in block and (
            block["encrypted_content"] is None or isinstance(block["encrypted_content"], str)
        ):
            pending["encryptedContent"] = block["encrypted_content"]
        self._pending[index] = pending
        return True

    def delta(self, index: Any, delta: Any) -> bool:
        capture = self._pending.get(index)
        if (
            capture is None
            or not isinstance(delta, dict)
            or delta.get("type") != "compaction_delta"
        ):
            return False
        if isinstance(delta.get("content"), str):
            capture["content"] += delta["content"]
        if "encrypted_content" in delta and (
            delta["encrypted_content"] is None or isinstance(delta["encrypted_content"], str)
        ):
            capture["encryptedContent"] = delta["encrypted_content"]
        return True

    def complete(self, index: Any) -> bool:
        capture = self._pending.pop(index, None)
        if capture is None:
            return False
        _capture_anthropic_compaction(self._output, capture, self._model, self._identity)
        return True


def _capture_anthropic_compaction(
    output: dict[str, Any],
    capture: Mapping[str, Any],
    model: ReplayModel,
    identity: ReplayIdentity | None,
) -> None:
    summary, replay_index = capture["content"], capture["replayIndex"]
    context = build_provider_replay_context(model, identity)
    if not summary or not context["baseUrlHash"] or not _is_safe_index(replay_index):
        return
    replay: dict[str, Any] = {"v": 1, "type": _ANTHROPIC_TYPE, "data": summary}
    if "encryptedContent" in capture:
        replay["encryptedContent"] = capture["encryptedContent"]
    replay["replayIndex"] = replay_index
    replay.update(_defined(context))
    output["providerReplay"] = replay


def suppress_anthropic_compaction(
    output: dict[str, Any], model: ReplayModel, identity: ReplayIdentity | None = None
) -> None:
    """``suppressAnthropicCompaction``: a rejected-checkpoint tombstone fenced to the identity."""

    context = build_provider_replay_context(model, identity)
    if not context["baseUrlHash"]:
        return
    output["providerReplay"] = {
        "v": 1,
        "type": _ANTHROPIC_SUPPRESSION_TYPE,
        "data": _SUPPRESSION_DATA,
        **_defined(context),
    }


def capture_openai_responses_compaction(
    output: dict[str, Any],
    item: Mapping[str, Any],
    boundary: int | float | str,
    model: ReplayModel,
    capture_metadata: Mapping[str, Any] | None = None,
    compacted_output: list[Any] | None = None,
    egress_projection: EgressProjection | None = None,
) -> None:
    """``captureOpenAIResponsesCompaction``: write the checkpoint onto ``output["providerReplay"]``.

    ``boundary`` is the content index the checkpoint covers, or ``"retained-users"``. Without
    ``capture_metadata`` the fence is built from the model alone (no session or auth hash), as
    upstream does. Raises :class:`ResponsesCompactionCaptureError` for a ``compacted_output``
    that is invalid, does not survive egress, or exceeds the 16 MiB window ceiling.
    """

    metadata = (
        capture_metadata
        if capture_metadata is not None
        else build_openai_responses_reasoning_replay_metadata(model)
    )
    if not js_truthy(item.get("encrypted_content")):
        return
    if not js_truthy(metadata.get("baseUrlHash")):
        return
    current = _read_responses_state(output.get("providerReplay"))
    if (
        isinstance(boundary, int | float)
        and not isinstance(boundary, bool)
        and current is not None
        and current.get("type") == _RESPONSES_TYPE
        and (-1 if current.get("replayIndex") is None else current["replayIndex"]) > boundary
    ):
        return
    if compacted_output is not None and not is_openai_responses_compaction_output(
        compacted_output, model, egress_projection
    ):
        raise ResponsesCompactionCaptureError("Responses compact endpoint checkpoint is invalid")
    replay: dict[str, Any] = {"v": 1}
    if boundary == "retained-users":
        replay["type"] = _RESPONSES_RETAINED_TYPE
    else:
        replay["type"] = _RESPONSES_TYPE
        replay["replayIndex"] = boundary
    if js_truthy(item.get("id")):
        replay["id"] = item["id"]
    replay["data"] = item["encrypted_content"]
    for key in ("provider", "api", "model", "baseUrlHash"):
        if key in metadata:
            replay[key] = metadata[key]
    for key in ("sessionHash", "authProfileHash"):
        if js_truthy(metadata.get(key)):
            replay[key] = metadata[key]
    if compacted_output is not None:
        replay["compactedWindow"] = {
            "state": "ready",
            "output": js_json_stringify(compacted_output),
        }
        if read_openai_responses_compaction_window(replay, model, egress_projection) is None:
            raise ResponsesCompactionCaptureError(
                "Responses compact endpoint checkpoint is invalid or exceeds 16 MiB"
            )
    output["providerReplay"] = replay


def suppress_openai_responses_compaction(
    output: dict[str, Any],
    model: ReplayModel,
    identity: ReplayIdentity | None = None,
    rejected_checkpoint: Any = None,
    on_compaction_rejected: Callable[[Any], Any] | None = None,
) -> None:
    """``suppressOpenAIResponsesCompaction``: the tombstone, then the rejection callback."""

    context = build_openai_responses_replay_context(model, identity)
    if not context["baseUrlHash"]:
        return
    output["providerReplay"] = {
        "v": 1,
        "type": _RESPONSES_SUPPRESSION_TYPE,
        "data": _SUPPRESSION_DATA,
        **_defined(context),
    }
    if js_truthy(rejected_checkpoint) and on_compaction_rejected is not None:
        on_compaction_rejected(rejected_checkpoint)


class CompactionTracker:
    """``createCompactionTracker``: map a streamed compaction item id to its content index."""

    def __init__(
        self,
        output: dict[str, Any],
        model: ReplayModel,
        reasoning_replay_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._output = output
        self._model = model
        self._metadata = reasoning_replay_metadata
        self._indexes: dict[Any, Any] = {}

    def added(self, item: Mapping[str, Any], replay_index: Any) -> None:
        if item.get("type") == "compaction" and js_truthy(item.get("id")):
            self._indexes[item["id"]] = replay_index

    def completed(self, item: Mapping[str, Any], fallback_replay_index: Any) -> None:
        if item.get("type") != "compaction" or not js_truthy(item.get("encrypted_content")):
            return
        has_id = js_truthy(item.get("id"))
        captured: dict[str, Any] = {"type": "compaction"}
        if has_id:
            captured["id"] = item["id"]
        captured["encrypted_content"] = item["encrypted_content"]
        boundary = self._indexes.get(item["id"]) if has_id else None
        capture_openai_responses_compaction(
            self._output,
            captured,
            fallback_replay_index if boundary is None else boundary,
            self._model,
            self._metadata,
        )
        if has_id:
            self._indexes.pop(item["id"], None)


# --- eligibility -----------------------------------------------------------------------------

_ANTHROPIC_PUBLIC_HOST = "api.anthropic.com"
_HOSTNAME_SHAPE_RE = re.compile(r"[A-Za-z0-9.\[\]\-]+(?::\d+)?(?:[/?#][^\n\r  ]*)?")
_ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"

AnthropicEndpointClass = Callable[[str | None], str]


def _normalized_lower(value: Any) -> str | None:
    """``normalizeOptionalLowercaseString``: trimmed, lower-cased, ``None`` when blank."""

    if not isinstance(value, str):
        return None
    trimmed = js_trim(value)
    return trimmed.lower() if trimmed else None


def _attribution_hostname(value: str) -> str | None:
    """``resolveUrlHostname`` of provider-attribution.ts: a bare host gets ``https://``."""

    trimmed = js_trim(value)
    if not trimmed:
        return None
    candidate = f"https://{trimmed}" if _HOSTNAME_SHAPE_RE.fullmatch(trimmed) else trimmed
    host = url_hostname(candidate)
    return host.lower() if host else None


def resolve_anthropic_endpoint_class(base_url: str | None) -> str:
    """The endpoint class the OpenClaw host reports for a base URL, as far as Anthropic needs it.

    ``default`` for a blank URL, ``anthropic-public`` for the ``api.anthropic.com`` manifest host,
    ``invalid`` for an unparsable URL and ``custom`` otherwise (the host also knows ``local`` and
    the other plugins' endpoints; none of them is direct Anthropic).
    """

    if not isinstance(base_url, str) or not js_trim(base_url):
        return "default"
    host = _attribution_hostname(base_url)
    if host is None:
        return "invalid"
    return "anthropic-public" if host == _ANTHROPIC_PUBLIC_HOST else "custom"


def _optional_trim(value: Any, what: str) -> str | None:
    """``value?.trim()``: ``TypeError`` for a non-string, like ``.trim is not a function``."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{what}.trim is not a function")
    return js_trim(value)


def is_direct_anthropic_model(
    model: ReplayModel,
    *,
    env: Mapping[str, str] | None = None,
    endpoint_class: AnthropicEndpointClass | None = None,
) -> bool:
    """``isDirectAnthropicModel``: provider ``anthropic`` on the public endpoint."""

    environment = os.environ if env is None else env
    base_url = _optional_trim(model.base_url, "model.baseUrl") or _optional_trim(
        environment.get(_ENV_ANTHROPIC_BASE_URL), "env.ANTHROPIC_BASE_URL"
    )
    kind = (endpoint_class or resolve_anthropic_endpoint_class)(base_url or None)
    if _normalized_lower(model.provider) != "anthropic":
        return False
    if kind == "anthropic-public":
        return True
    return kind == "default" and (not base_url or url_hostname(base_url) == _ANTHROPIC_PUBLIC_HOST)


def resolve_anthropic_server_compaction_enabled(
    model: ReplayModel,
    extra_params: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    endpoint_class: AnthropicEndpointClass | None = None,
    resolve_secret_sentinel: Callable[[str], str] | None = None,
) -> bool:
    """``resolveAnthropicServerCompactionPlan(...).enabled`` (the threshold is not ported)."""

    if extra_params is None or extra_params.get("anthropicServerCompaction") is not True:
        return False
    if isinstance(api_key, str):
        resolved = resolve_secret_sentinel(api_key) if resolve_secret_sentinel else api_key
        if "sk-ant-oat" in resolved:
            return False
    return _normalized_lower(model.api) == "anthropic-messages" and is_direct_anthropic_model(
        model, env=env, endpoint_class=endpoint_class
    )


def resolve_compaction_replay_eligibility(
    model: ReplayModel,
    *,
    extra_params: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    env: Mapping[str, str] | None = None,
    endpoint_class: AnthropicEndpointClass | None = None,
    resolve_secret_sentinel: Callable[[str], str] | None = None,
) -> bool:
    """``resolveCompactionReplayEligibility``: may this prepared route use a checkpoint?

    Every OpenAI Responses API is eligible. Anthropic needs a non-blank API key (never an OAuth
    token), ``extraParams.anthropicServerCompaction === true`` and the direct public endpoint.
    ``endpoint_class`` overrides the host's endpoint classification (plugin manifests) and
    ``resolve_secret_sentinel`` the host's process-local secret sentinel swap (identity default).
    """

    if model.api in OPENAI_RESPONSES_APIS:
        return True
    if not _optional_trim(api_key, "options.apiKey"):
        return False
    return resolve_anthropic_server_compaction_enabled(
        model,
        extra_params,
        api_key,
        env=env,
        endpoint_class=endpoint_class,
        resolve_secret_sentinel=resolve_secret_sentinel,
    )


# --- replay pressure -------------------------------------------------------------------------


class _Undefined:
    """JavaScript ``undefined`` where a missing field reaches an estimator."""

    def __repr__(self) -> str:
        return "UNDEFINED"


UNDEFINED: Any = _Undefined()


@dataclass(frozen=True)
class ReplayPressureEstimator:
    """``ReplayPressureEstimator``: token estimators supplied by the host.

    ``json`` may receive :data:`UNDEFINED` (a message without ``content``).
    """

    text: Callable[[str], int | float]
    image: Callable[[], int | float]
    json: Callable[[Any], int | float]
    tool_result: Callable[[str], int | float] | None = None


def default_replay_pressure_estimator() -> ReplayPressureEstimator:
    """The estimator the embedded runner passes (``preemptive-compaction.ts``)."""

    from memory_core import preemptive_compaction as pc  # noqa: PLC0415 - avoids an import cycle

    def json_tokens(value: Any) -> int | float:
        return 1 if value is UNDEFINED else pc.estimate_json_payload_token_pressure(value)

    def tool_result(value: str) -> int | float:
        return max(
            math.ceil(utf16_len(value) / 2),
            pc.estimate_string_token_pressure(value),
        )

    return ReplayPressureEstimator(
        text=pc.estimate_string_token_pressure,
        image=lambda: pc.IMAGE_BLOCK_TOKENS,
        json=json_tokens,
        tool_result=tool_result,
    )


def _without(record: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in keys}


def _estimate_responses_content(
    content: Any, estimate: ReplayPressureEstimator, text: Callable[[str], int | float]
) -> int | float:
    if isinstance(content, str):
        return text(content)
    if not isinstance(content, list):
        return estimate.json(content)
    tokens: int | float = 0
    for block in content:
        if not isinstance(block, dict):
            tokens += estimate.json(block)
        elif block.get("type") in ("input_text", "output_text") and isinstance(
            block.get("text"), str
        ):
            tokens += text(block["text"]) + estimate.json(_without(block, "text"))
        elif block.get("type") == "input_image":
            url = block.get("image_url")
            metadata = _without(block, "image_url")
            tokens += estimate.image() + estimate.json(
                metadata if isinstance(url, str) and url.startswith("data:") else block
            )
        else:
            tokens += estimate.json(block)
    return tokens


def estimate_responses_input(
    items: Sequence[Any], estimate: ReplayPressureEstimator
) -> int | float:
    """``estimateResponsesInput``: tokens of a Responses ``input`` array."""

    tokens: int | float = 0
    for entry in items:
        if not isinstance(entry, dict):
            tokens += estimate.json(entry)
        elif entry.get("type") == "compaction" and isinstance(entry.get("encrypted_content"), str):
            tokens += estimate.text(entry["encrypted_content"]) + estimate.json(
                _without(entry, "encrypted_content")
            )
        elif entry.get("type") == "message":
            tokens += estimate.json(_without(entry, "content")) + _estimate_responses_content(
                entry["content"] if "content" in entry else UNDEFINED,
                estimate,
                estimate.text,
            )
        elif entry.get("type") in ("function_call_output", "custom_tool_call_output"):
            tool_text = estimate.tool_result if estimate.tool_result else estimate.text
            tokens += estimate.json(_without(entry, "output")) + _estimate_responses_content(
                entry["output"] if "output" in entry else UNDEFINED, estimate, tool_text
            )
        else:
            tokens += estimate.json(entry)
    return tokens


def _js_number_to_string(value: Any) -> str:
    """``String(number)`` (ECMAScript ``Number::toString``) for a JSON number."""

    if isinstance(value, int):
        return str(value)
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exp = repr(abs(value)).partition("e")
    int_part, _, frac_part = mantissa.partition(".")
    digits = int_part + frac_part
    point = len(int_part) + int(exp or 0)
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0") or "0"
    count = len(digits)
    if count <= point <= 21:
        return sign + digits + "0" * (point - count)
    if 0 < point <= 21:
        return sign + digits[:point] + "." + digits[point:]
    if -6 < point <= 0:
        return sign + "0." + "0" * -point + digits
    exponent = point - 1
    head = digits[0] + ("." + digits[1:] if count > 1 else "")
    return f"{sign}{head}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"


def _stable_stringify(value: Any) -> str:
    """``stableStringify`` for JSON values: object keys in UTF-16 code unit order."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return js_json_stringify(value)
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            return js_json_stringify(str(value))
        return _js_number_to_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_stable_stringify(entry) for entry in value) + "]"
    keys = sorted(value, key=lambda key: key.encode("utf-16-be", "surrogatepass"))
    return (
        "{"
        + ",".join(f"{js_json_stringify(key)}:{_stable_stringify(value[key])}" for key in keys)
        + "}"
    )


def _normalize_assistant_replay_input(items: Sequence[Any]) -> list[Any]:
    """``normalizeAssistantReplayInput(input)`` (the request side, ``fromResponse`` false)."""

    out: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
        elif item.get("type") == "reasoning":
            out.append({"type": "reasoning"})
        elif item.get("type") != "function_call" and not (
            item.get("type") == "message" and item.get("role") == "assistant"
        ):
            out.append(item)
        else:
            stable = _without(item, "id", "status")
            if item.get("type") == "message" and isinstance(stable.get("content"), list):
                stable["content"] = [
                    _without(part, "annotations", "logprobs")
                    if isinstance(part, dict) and part.get("type") == "output_text"
                    else part
                    for part in stable["content"]
                ]
            out.append(stable)
    return out


def responses_context_fingerprint(items: Sequence[Any]) -> str:
    """``contextFingerprint(input)``: the sha256 binding measured usage to its replay prefix."""

    reasoning = [_without(item, "id", "status") for item in items if _is_reasoning(item)]
    prefix = hashlib.sha256(
        js_utf8_encode(_stable_stringify(_normalize_assistant_replay_input(items)))
    ).hexdigest()
    return hashlib.sha256(
        js_utf8_encode(_stable_stringify({"prefix": prefix, "reasoning": reasoning}))
    ).hexdigest()


def _is_reasoning(item: Any) -> bool:
    return isinstance(item, dict) and item.get("type") == "reasoning"


class ResponsesProjectionUnavailableError(RuntimeError):
    """A measured-usage check needs the Responses message converter, which is a host hook."""


# ``(projection, provider messages, system prompt, include_system_prompt) -> wire input items``:
# ``convertResponsesMessages`` / ``convertProviderResponsesMessages`` of
# openai-responses-replay-messages-internal.ts, with the model and identity bound by the host.
ResponsesInputProjector = Callable[[str, list[Any], "str | None", bool], list[Any]]

_PROVIDER_MESSAGE_ROLES = frozenset({"user", "assistant", "toolResult"})


def _is_safe_integer(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and (isinstance(value, int) or (math.isfinite(value) and value == math.floor(value)))
        and abs(value) <= _MAX_SAFE_INTEGER
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _message_usage(message: Mapping[str, Any]) -> Mapping[str, Any]:
    """``message.usage`` where upstream reads a property off it (``TypeError`` when absent)."""

    usage = message.get("usage")
    if usage is None:
        raise TypeError("Cannot read properties of undefined (reading 'contextUsage')")
    return usage if isinstance(usage, dict) else {}


def resolve_responses_context_usage_boundary(
    messages: Sequence[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity | None = None,
    system_prompt: str | None = None,
    *,
    projector: ResponsesInputProjector | None = None,
) -> dict[str, Any] | None:
    """``resolveResponsesContextUsageBoundary``: measured usage that still binds this replay.

    Walks back to the newest assistant message with an available ``contextUsage`` and a saved
    ``openclawResponsesInputReplay.contextUsage`` state; the state must match the identity, the
    message's route, its token counts and the sha256 of the wire-input prefix, which is rebuilt
    through ``projector``. Returns ``{index, totalTokens, suffix}``, the suffix being the wire
    items after the measured prefix. Without a ``projector`` a candidate that passes every other
    check raises :class:`ResponsesProjectionUnavailableError`.
    """

    context = build_provider_replay_context(model, identity)
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not message or message.get("role") != "assistant":
            continue
        replay = message.get("openclawResponsesInputReplay")
        state = replay.get("contextUsage") if isinstance(replay, dict) else None
        usage = _message_usage(message).get("contextUsage")
        if not isinstance(state, dict) or not (
            isinstance(usage, dict) and usage.get("state") == "available"
        ):
            continue
        projection = state.get("projection")
        prefix_hash = state.get("prefixHash")
        prefix_length = state.get("prefixLength")
        total_tokens = usage.get("totalTokens")
        if (
            not is_openai_responses_replay_context(state)
            or not provider_replay_context_matches(state, context)
            or not _strict_equals(message.get("provider"), model.provider)
            or not _strict_equals(message.get("api"), model.api)
            or not _strict_equals(message.get("model"), model.id)
            or projection not in ("transport", "provider")
            or not isinstance(prefix_hash, str)
            or not _is_number(prefix_length)
            or not _is_safe_integer(prefix_length)
            or prefix_length <= 0
            or not _strict_equals(state.get("promptTokens"), usage.get("promptTokens"))
            or not _strict_equals(state.get("totalTokens"), total_tokens)
            or not _is_safe_integer(total_tokens)
            or total_tokens <= 0
        ):
            return None
        if projector is None:
            raise ResponsesProjectionUnavailableError(
                "the Responses message converter is a host hook (projector)"
            )
        wire = projector(
            projection,
            [m for m in messages if m and m.get("role") in _PROVIDER_MESSAGE_ROLES],
            system_prompt,
            state.get("includeSystemPrompt") is True,
        )
        if len(wire) < prefix_length or responses_context_fingerprint(wire[:prefix_length]) != (
            prefix_hash
        ):
            return None
        return {"index": index, "totalTokens": total_tokens, "suffix": wire[prefix_length:]}
    return None


def _object_rest(value: Any, omit: str) -> dict[str, Any]:
    """``const { [omit]: _, ...rest } = value``: ``TypeError`` for ``undefined``/``null``."""

    if value is None:
        raise TypeError(f"Cannot destructure property '{omit}' of undefined")
    if isinstance(value, dict):
        return _without(value, omit)
    if isinstance(value, str):
        return {str(i): char for i, char in enumerate(value)}
    if isinstance(value, list):
        return {str(i): item for i, item in enumerate(value)}
    return {}


def resolve_compaction_replay_pressure(
    messages: Sequence[Mapping[str, Any]],
    model: ReplayModel,
    identity: ReplayIdentity,
    estimate: ReplayPressureEstimator,
    system_prompt: str | None = None,
    *,
    projector: ResponsesInputProjector | None = None,
    egress_projection: EgressProjection | None = None,
) -> dict[str, Any] | None:
    """``resolveCompactionReplayPressure``: estimate the canonical prefix and its tail once.

    ``None`` without a usable checkpoint. Otherwise ``{"messages", "prefixTokens"}`` (plus
    ``measuredTokens`` when measured Responses usage binds the replay): the projected owner
    (content from ``replayIndex``, stale ``usage.contextUsage`` dropped) followed by the later
    messages with unbound ``contextUsage`` removed from assistant usage, or ``[]`` when the
    measured boundary replaces the local estimate. Raises
    :class:`CompactionReplayRefreshRequiredError` for a Responses checkpoint that needs
    ``/compact``, and ``TypeError`` where upstream's property reads throw.
    """

    checkpoint = resolve_compaction_source(messages, model, identity, egress_projection)
    if checkpoint is None:
        return None
    if checkpoint["family"] == "responses" and checkpoint["mode"] == "refresh-required":
        raise CompactionReplayRefreshRequiredError
    owner = checkpoint["owner"]
    owner_index = next((i for i, m in enumerate(messages) if m is owner), -1)
    if owner_index < 0:
        return None
    if checkpoint["family"] == "anthropic":
        prefix_tokens = estimate.text(checkpoint["summary"])
    elif checkpoint["mode"] == "complete-window":
        prefix_tokens = estimate_responses_input(checkpoint["output"], estimate)
    else:
        prefix_tokens = estimate.text(checkpoint["item"]["encrypted_content"])
    measured = (
        resolve_responses_context_usage_boundary(
            messages, model, identity, system_prompt, projector=projector
        )
        if checkpoint["family"] == "responses"
        else None
    )
    if measured is not None:
        return {
            "messages": [],
            "prefixTokens": measured["totalTokens"]
            + estimate_responses_input(measured["suffix"], estimate),
            "measuredTokens": measured["totalTokens"],
        }
    usage = _object_rest(owner.get("usage"), "contextUsage")
    tail: list[Mapping[str, Any]] = []
    for message in messages[owner_index + 1 :]:
        if message.get("role") != "assistant" or "contextUsage" not in _message_usage(message):
            tail.append(message)
            continue
        tail.append({**message, "usage": _object_rest(message["usage"], "contextUsage")})
    return {
        "messages": [
            {**owner, "content": _content_from(owner, checkpoint["replayIndex"]), "usage": usage},
            *tail,
        ],
        "prefixTokens": prefix_tokens,
    }


def _content_from(message: Mapping[str, Any], start: int) -> Any:
    """``message.content.slice(start)``."""

    content = message.get("content")
    if isinstance(content, list):
        return content[start:]
    if isinstance(content, str):
        return utf16_slice(content, start)
    raise TypeError("message.content.slice is not a function")
