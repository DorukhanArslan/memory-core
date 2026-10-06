from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from memory_core.bootstrap._js import js_trim


_THREAD_SUFFIX_RE = re.compile(
    r"^([^\n\r\u2028\u2029]*):(?:thread|topic):\d+\Z", re.IGNORECASE | re.ASCII
)
_ACCOUNT_ID_VALID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z", re.IGNORECASE | re.ASCII)
_ACCOUNT_ID_INVALID_CHARS_RE = re.compile(r"[^a-z0-9_-]+", re.IGNORECASE | re.ASCII)
_BLOCKED_OBJECT_KEYS = frozenset({"__proto__", "prototype", "constructor"})
_MISSING: Any = object()


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
    user_turns_to_keep = target_user_turns + (
        (user_count - target_user_turns) % eviction_batch_size
    )

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
    route: Mapping[str, Any] | None = None,
) -> Any:
    """``getHistoryLimitFromSessionKey`` (embedded-agent-runner/history.ts, v2026.9.6).

    Resolves the DM/channel history limit of a session key. ``route`` carries the observed
    route facts (``accountId``, ``peerId``, ``chatType``) that disambiguate keys where an
    account name or a linked peer contains a kind token; account-scoped values
    (``channels.<provider>.accounts.<id>``) win over the channel root. Like upstream, the
    configured value is returned as is (no number validation); ``None`` is undefined/null.
    """

    if not session_key or not config:
        return None

    parts = session_key.split(":")
    provider_parts = parts[2:] if len(parts) >= 3 and parts[0] == "agent" else parts

    provider = _normalize_provider_id(provider_parts[0] if provider_parts else "")
    if not provider:
        return None

    route = route if isinstance(route, Mapping) else {}
    route_chat_type = route.get("chatType")
    candidates: list[dict[str, Any]] = []
    for account_segments in (0, 1):
        index = 1 + account_segments
        kind = _normalize_chat_type(provider_parts[index] if index < len(provider_parts) else None)
        if (
            not kind
            or (route_chat_type and kind != route_chat_type)
            or (account_segments and kind != "direct")
        ):
            continue
        account_id = provider_parts[1] if account_segments else None
        candidates.append(
            {
                "kind": kind,
                "accountId": account_id,
                "userId": ":".join(provider_parts[2 + account_segments :]),
            }
        )

    raw_peer_id = route.get("peerId")
    raw_peer_id = js_trim(raw_peer_id) if isinstance(raw_peer_id, str) else None
    session_config = config.get("session")
    identity_links = (
        session_config.get("identityLinks") if isinstance(session_config, Mapping) else None
    )
    logical_peer_id = (
        _normalize_optional_lowercase(
            _resolve_linked_direct_peer_id(identity_links, provider, raw_peer_id) or raw_peer_id
        )
        if raw_peer_id
        else None
    )
    if logical_peer_id:
        matching = [
            candidate
            for candidate in candidates
            if candidate["kind"] != "direct"
            or candidate["userId"] == logical_peer_id
            or _strip_thread_suffix(candidate["userId"]) == logical_peer_id
        ]
    else:
        matching = candidates
    resolved = matching[0] if len(matching) == 1 else None
    if resolved is not None:
        kind = resolved["kind"]
    elif all(candidate["kind"] == candidates[0]["kind"] for candidate in candidates):
        kind = candidates[0]["kind"] if candidates else None
    else:
        kind = None
    # A linked peer may itself end in :thread:<number>; observed identity wins over the
    # legacy suffix heuristic.
    user_id = (
        (logical_peer_id or _strip_thread_suffix(resolved["userId"]))
        if resolved is not None
        else None
    )
    routed_account_id = route.get("accountId")
    if routed_account_id is None:
        if len(candidates) == 1:
            routed_account_id = candidates[0]["accountId"]
        else:
            routed_account_id = resolved["accountId"] if resolved is not None else None

    provider_config = _resolve_provider_config(config, provider)
    if provider_config is None:
        return None

    trimmed_account_id = js_trim(routed_account_id) if isinstance(routed_account_id, str) else None
    account_config = (
        _resolve_account_entry(
            provider_config.get("accounts"), _normalize_account_id(trimmed_account_id)
        )
        if trimmed_account_id
        else None
    )
    account_config = account_config if isinstance(account_config, Mapping) else {}

    if kind == "direct":
        if user_id:
            dms = account_config.get("dms")
            if dms is None:
                dms = provider_config.get("dms")
            dm_config = dms.get(user_id) if isinstance(dms, Mapping) else None
            if isinstance(dm_config, Mapping):
                per_dm_limit = dm_config.get("historyLimit", _MISSING)
                if per_dm_limit is not _MISSING:
                    return per_dm_limit
        return _first_defined(
            account_config.get("dmHistoryLimit"), provider_config.get("dmHistoryLimit")
        )

    if kind in {"channel", "group"}:
        return _first_defined(
            account_config.get("historyLimit"), provider_config.get("historyLimit")
        )

    return None


def _first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_chat_type(raw: str | None) -> str | None:
    value = _normalize_optional_lowercase(raw)
    if value in {"direct", "dm"}:
        return "direct"
    if value in {"group", "channel"}:
        return value
    return None


def _normalize_token(value: Any) -> str:
    return _normalize_optional_lowercase(value) or ""


def _resolve_linked_direct_peer_id(identity_links: Any, channel: str, peer_id: str) -> str | None:
    if not isinstance(identity_links, Mapping):
        return None
    peer_id = js_trim(peer_id)
    if not peer_id:
        return None
    candidates = set()
    raw_candidate = _normalize_token(peer_id)
    if raw_candidate:
        candidates.add(raw_candidate)
    channel_token = _normalize_token(channel)
    if channel_token:
        scoped = _normalize_token(f"{channel_token}:{peer_id}")
        if scoped:
            candidates.add(scoped)
    if not candidates:
        return None
    for canonical, ids in identity_links.items():
        canonical_name = js_trim(canonical) if isinstance(canonical, str) else ""
        if not canonical_name or not isinstance(ids, list):
            continue
        for item in ids:
            normalized = _normalize_token(item)
            if normalized and normalized in candidates:
                return canonical_name
    return None


def _normalize_account_id(value: str | None) -> str:
    """routing/account-id.ts ``normalizeAccountId`` (without the cache)."""

    trimmed = js_trim(value or "")
    if not trimmed:
        return "default"
    return _canonical_account_id(trimmed) or "default"


def _normalize_optional_account_id(value: str | None) -> str | None:
    trimmed = js_trim(value or "")
    return _canonical_account_id(trimmed) if trimmed else None


def _canonical_account_id(value: str) -> str | None:
    normalized = _normalize_optional_lowercase(value) or ""
    if not _ACCOUNT_ID_VALID_RE.match(value):
        normalized = _ACCOUNT_ID_INVALID_CHARS_RE.sub("-", normalized)
        normalized = normalized.lstrip("-").rstrip("-")[:64]
    if not normalized or normalized in _BLOCKED_OBJECT_KEYS:
        return None
    return normalized


def _resolve_account_entry(accounts: Any, account_id: str) -> Any:
    """resolveChannelAccountEntry without a channel key policy: exact key, then normalized."""

    if not isinstance(accounts, Mapping):
        return None
    if account_id in accounts and account_id not in _BLOCKED_OBJECT_KEYS:
        return accounts[account_id]
    normalized = _normalize_account_id(account_id)
    for key in accounts:
        if not isinstance(key, str) or key in _BLOCKED_OBJECT_KEYS:
            continue
        candidate = _normalize_account_id(key)
        if (
            _normalize_optional_account_id(key)
            and candidate not in _BLOCKED_OBJECT_KEYS
            and candidate == normalized
        ):
            return accounts[key]
    return None


def _strip_thread_suffix(value: str) -> str:
    match = _THREAD_SUFFIX_RE.match(value)
    return match.group(1) if match else value


def _normalize_optional_lowercase(value: Any) -> str | None:
    """``normalizeOptionalLowercaseString``: JS-trimmed, lowercased, ``None`` when blank."""

    if not isinstance(value, str):
        return None
    normalized = js_trim(value).lower()
    return normalized or None


def _normalize_provider_id(value: str) -> str | None:
    return _normalize_optional_lowercase(value)


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
