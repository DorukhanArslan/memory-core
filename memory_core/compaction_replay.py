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
Not ported: ``resolveCompactionReplayPressure`` (needs the Responses context-usage boundary)
and the compact-endpoint egress projection: ``readOpenAIResponsesCompactionWindow`` re-runs the
Responses image sanitiser and payload policy and requires the window to survive them
unchanged; here that is the optional host hook ``egress_projection`` (identity when absent).

``replaceCompactionReplayOwnerContent`` matches surviving blocks with ``Array.prototype.indexOf``,
that is by object identity for objects and arrays; the port uses ``is`` for the same reason, so a
caller must pass the *same* block objects it read from ``message["content"]``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory_core.bootstrap._js import (
    _units,
    js_json_stringify,
    js_trim,
    js_utf8_encode,
    reject_json_constant,
    utf16_len,
)

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
OPENAI_RESPONSES_APIS = frozenset(
    {
        "openai-responses",
        "azure-openai-responses",
        "openai-chatgpt-responses",
        "openclaw-openai-responses-transport",
        "openclaw-openai-chatgpt-responses-transport",
        "openclaw-azure-openai-responses-transport",
    }
)
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
    value: Any, egress_projection: EgressProjection | None = None
) -> bool:
    """``isOpenAIResponsesCompactionOutput``: schema validation of a saved compacted window."""

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
    if egress_projection is not None:
        return js_json_stringify(egress_projection(value)) == js_json_stringify(value)
    return True


def read_openai_responses_compaction_window(
    replay: Mapping[str, Any], egress_projection: EgressProjection | None = None
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
        if not is_openai_responses_compaction_output(output, egress_projection):
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
            output = read_openai_responses_compaction_window(replay, egress_projection)
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
