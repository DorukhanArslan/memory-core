from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_THREAD_SUFFIX_RE = re.compile(r"^(.*):(?:thread|topic):\d+$", re.IGNORECASE)
_SUPPORTED_PROVIDER_IDS = {
    "telegram",
    "whatsapp",
    "discord",
    "slack",
    "signal",
    "imessage",
    "msteams",
    "nextcloud-talk",
}


def limit_history_turns(messages: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """Keep recent user turns and following messages, matching OpenClaw history.ts.

    Eviction is lazy: nothing is cut until there are more than ceil(1.5 * limit) user
    turns, then a full batch goes at once.

    Leading non-conversation messages (e.g. compactionSummary, branchSummary)
    are always preserved, since they carry summarized pre-compaction context
    that history limiting must not drop.
    """

    if not limit or limit <= 0 or not messages:
        return messages

    conversation_start = 0
    while conversation_start < len(messages):
        if messages[conversation_start].get("role") in {"user", "assistant"}:
            break
        conversation_start += 1

    tail = messages[conversation_start:]
    if not tail:
        return messages

    user_count = sum(1 for message in tail if message.get("role") == "user")

    # Allow a 50% cushion, then evict a full batch so the prompt-cache prefix stays
    # stable between cuts (history.ts, d5dee714c4f): up to 1.5x turns before cutting.
    target_user_turns = int(limit)
    max_user_turns = -(-target_user_turns * 3 // 2)
    if user_count <= max_user_turns:
        return messages
    eviction_batch_size = max_user_turns - target_user_turns + 1
    user_turns_to_keep = target_user_turns + ((user_count - target_user_turns) % eviction_batch_size)

    user_count = 0
    last_user_index = len(tail)
    for index in range(len(tail) - 1, -1, -1):
        if tail[index].get("role") != "user":
            continue
        user_count += 1
        if user_count > user_turns_to_keep:
            return messages[:conversation_start] + tail[last_user_index:]
        last_user_index = index
    return messages


def get_history_limit_from_session_key(
    session_key: str | None,
    config: Mapping[str, Any] | None,
) -> int | None:
    """Resolve OpenClaw channel/DM history limits from a session key."""

    if not session_key or not config:
        return None

    parts = [part for part in session_key.split(":") if part]
    provider_parts = parts[2:] if len(parts) >= 3 and parts[0] == "agent" else parts

    provider = _normalize_provider_id(provider_parts[0] if provider_parts else "")
    if not provider:
        return None

    kind = _normalize_optional_lowercase(provider_parts[1] if len(provider_parts) > 1 else None)
    user_id = _strip_thread_suffix(":".join(provider_parts[2:]))
    provider_config = _resolve_provider_config(config, provider)
    if provider_config is None:
        return None

    if kind in {"dm", "direct"}:
        dms = provider_config.get("dms")
        if isinstance(dms, Mapping) and user_id:
            dm_config = dms.get(user_id)
            if isinstance(dm_config, Mapping) and "historyLimit" in dm_config:
                return _history_limit_value(dm_config.get("historyLimit"))
        return _history_limit_value(provider_config.get("dmHistoryLimit"))

    if kind in {"channel", "group"}:
        return _history_limit_value(provider_config.get("historyLimit"))

    return None


def _strip_thread_suffix(value: str) -> str:
    match = _THREAD_SUFFIX_RE.match(value)
    return match.group(1) if match else value


def _normalize_optional_lowercase(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_provider_id(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized == "z.ai":
        normalized = "z-ai"
    return normalized if normalized in _SUPPORTED_PROVIDER_IDS else None


def _resolve_provider_config(
    config: Mapping[str, Any],
    provider_id: str,
) -> Mapping[str, Any] | None:
    channels = config.get("channels")
    if not isinstance(channels, Mapping):
        return None
    for configured_provider_id, value in channels.items():
        if not isinstance(configured_provider_id, str):
            continue
        if _normalize_provider_id(configured_provider_id) != provider_id:
            continue
        if isinstance(value, Mapping):
            return value
        return None
    return None


def _history_limit_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
