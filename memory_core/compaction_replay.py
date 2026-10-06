"""Compaction replay checkpoint owners (packages/ai/src/transports/provider-compaction-replay.ts).

A server-side compaction checkpoint (``providerReplay`` of type ``anthropic-compaction``,
``openai-responses-compaction`` or ``openai-responses-retained-compaction``) is bound to the
exact assistant content that produced it. Every local history rewrite of such an owner message
goes through :func:`replace_compaction_replay_owner_content`, which re-indexes the checkpoint
(``replayIndex``) over the surviving blocks, or strips it when the rewrite makes the binding
ambiguous.

Ported: ``isCompactionReplayCheckpoint``, ``stripCompactionReplayCheckpoint``,
``stripCompactionReplayCheckpointInPlace`` and ``replaceCompactionReplayOwnerContent``. Not
ported (they need the provider payload policies and the Responses/Anthropic checkpoint
resolvers): ``resolveCompactionSource``, ``preserveCompactionReplayWindow``,
``requiresCompactionReplayRefresh`` and ``resolveCompactionReplayPressure``.

``replaceCompactionReplayOwnerContent`` matches surviving blocks with ``Array.prototype.indexOf``,
that is by object identity for objects and arrays; the port uses ``is`` for the same reason, so a
caller must pass the *same* block objects it read from ``message["content"]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
