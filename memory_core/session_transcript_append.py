"""Transcript-message storage rules owned by the session catalog.

Ports the ordinary JSON-message path of OpenClaw's
``session-accessor.sqlite-transcript-message-append.ts``, ``transcript-parent.ts``
and ``agents/transcript-redact.ts``. Provider replay, media migration and pending
input custody are separate host facilities, not supplied by this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from memory_core.bootstrap._js import js_trim
from memory_core.redact import (
    LoggingConfig,
    redact_secrets,
    redact_transcript_structured_field_value,
    redact_transcript_text,
)
from memory_core.transcript_tree import (
    UNSET, is_canonical_session_transcript_entry, is_session_transcript_leaf_control,
    is_session_transcript_side_append_entry, parse_session_transcript_tree_entry,
    scan_session_transcript_tree,
)


class TranscriptTurnAdmissionConflictError(ValueError):
    """A durable event or admission key already owns different message bytes."""

    name = "TranscriptTurnAdmissionConflictError"

    def __init__(self, key: str) -> None:
        super().__init__(f'Transcript idempotency key "{key}" conflicts with the admitted message.')


class SqliteTranscriptMutationConflictError(ValueError):
    name = "SqliteTranscriptMutationConflictError"

    def __init__(self, session_id: str) -> None:
        super().__init__(f"SQLite transcript changed while preparing rewrite for {session_id}")


def timestamp_ms_to_iso(value: float) -> str:
    """JavaScript Date's millisecond-resolution UTC representation."""
    return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat(
        timespec="milliseconds",
    ).replace("+00:00", "Z")


def message_idempotency_key(message: object) -> str | None:
    value = message.get("idempotencyKey") if isinstance(message, Mapping) else None
    return (js_trim(value) or None) if isinstance(value, str) else None


def redact_message_for_storage(
    message: Any, logging_config: LoggingConfig | None = None,
) -> Any:
    """Redact role-aware ordinary JSON while retaining correlation identities.

    Tool result content uses the model-visible payload policy; diagnostic
    metadata keeps the diagnostic policy. A caller's object is never mutated.
    """
    if not isinstance(message, Mapping) or not isinstance(message.get("role"), str):
        return redact_secrets(message, logging_config=logging_config)
    seen: set[int] = set()

    def walk(value: Any, field: str | None = None, location: str = "nested",
             model_visible: bool = False) -> tuple[Any, bool]:
        if isinstance(value, str):
            result = (
                redact_transcript_structured_field_value(
                    field, value, logging_config=logging_config,
                    model_visible_tool_result=model_visible,
                ) if field else redact_transcript_text(
                    value, logging_config=logging_config,
                    model_visible_tool_result=model_visible,
                )
            )
            return result, result != value
        if not isinstance(value, (Mapping, list, tuple)):
            return value, False
        if id(value) in seen:
            return "[Circular]", True
        seen.add(id(value))
        changed = False
        if isinstance(value, (list, tuple)):
            result = []
            for item in value:
                replacement, changed_item = walk(
                    item, field,
                    "assistant-content-block" if location == "assistant-content-array" else "nested",
                    model_visible,
                )
                result.append(replacement)
                changed |= changed_item
        else:
            result = {}
            changes: set[str] = set()
            for key, item in value.items():
                identity = location == "root" and key == "idempotencyKey"
                identity |= isinstance(item, str) and (
                    (location == "root" and value.get("role") == "toolResult" and key == "toolCallId")
                    or (location == "assistant-content-block" and value.get("type") == "toolCall" and key == "id")
                )
                if identity:
                    result[key] = item
                    continue
                child_location = (
                    "assistant-content-array"
                    if location == "root" and value.get("role") == "assistant"
                    and key == "content" and isinstance(item, (list, tuple)) else "nested"
                )
                replacement, changed_item = walk(
                    item, key, child_location,
                    model_visible or (location == "root" and value.get("role") == "toolResult" and key == "content"),
                )
                result[key] = replacement
                if changed_item:
                    changes.add(key)
                    changed = True
            if field == "__openclaw":
                if changes & {"senderIdentity", "senderId"}:
                    result.pop("senderIdentity", None)
                if "humanMentions" in changes:
                    result.pop("humanMentions", None)
            if location == "root" and value.get("role") == "user" and "content" in changes:
                metadata = result.get("__openclaw")
                if isinstance(metadata, dict):
                    metadata.pop("humanMentions", None)
        seen.remove(id(value))
        return result, changed

    return walk(message, location="root")[0]


def _json_equal(left: object, right: object) -> bool:
    # JS strict deep equality distinguishes boolean and number, but not int/float.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def messages_match_for_replay(stored: object, candidate: object) -> bool:
    """Ignore only the root message timestamp, including old delivery mirrors."""
    stored_delivery = stored.get("openclawDelivery", UNSET) if isinstance(stored, dict) else UNSET
    legacy = isinstance(stored, dict) and (
        stored.get("role") == "assistant" and stored.get("provider") == "openclaw"
        and stored.get("model") == "delivery-mirror" and stored.get("api") == "openclaw-transcript"
        and (stored_delivery is UNSET or isinstance(stored_delivery, dict)
             and "mediaUrls" not in stored_delivery)
    )

    def shape(value: object, project: bool = False) -> object:
        if not isinstance(value, dict):
            return value
        result = {key: item for key, item in value.items() if key != "timestamp"}
        delivery = result.get("openclawDelivery")
        if project and isinstance(delivery, dict) and isinstance(delivery.get("mediaUrls"), list) and all(
            isinstance(url, str) for url in delivery["mediaUrls"]
        ):
            delivery = {key: item for key, item in delivery.items() if key != "mediaUrls"}
            if stored_delivery is UNSET and not delivery:
                result.pop("openclawDelivery")
            else:
                result["openclawDelivery"] = delivery
        return result

    return _json_equal(shape(stored), shape(candidate, legacy))


def resolve_message_append_parent(
    events: Sequence[object], parent_id: Any = UNSET, append_intent: str | None = None,
) -> str | None:
    tree = scan_session_transcript_tree(list(events))
    tail = tree.append_parent_id
    if parent_id is UNSET:
        return tail
    if append_intent != "active-branch" or tail == parent_id or tail is None:
        return parent_id
    current = tail
    # Match the native owner's bounded ancestry traversal, including dangling/null parents.
    for _ in range(4096):
        node = tree.by_id.get(current)
        if node is None:
            break
        if node.parent_id == parent_id:
            return tail
        if node.parent_id is None:
            break
        current = node.parent_id
    return parent_id


def can_forward_project_event(events: Sequence[object], event: object) -> bool:
    """Whether the native forward projection can certify this next event.

    Branch controls and changes retain durable dirty state until the host
    rebuilds the active projection; raw bytes alone never certify a stale row.
    """
    if not events:
        return True
    tree = scan_session_transcript_tree(list(events))
    canonical = is_canonical_session_transcript_entry(event)
    tree_entry = parse_session_transcript_tree_entry(event)

    def projects(record: object) -> bool:
        return isinstance(record, dict) and record.get("type") != "session" and (
            is_canonical_session_transcript_entry(record)
            or parse_session_transcript_tree_entry(record) is not None or "message" in record
        )

    return not (
        is_session_transcript_leaf_control(event) or is_session_transcript_side_append_entry(event)
        or (canonical and tree.leaf_id is None and any(projects(record) for record in events))
        or (not canonical and tree.leaf_id is not None and projects(event))
        or (tree_entry is not None and tree_entry.parent_id != tree.leaf_id)
    )


__all__ = [
    "SqliteTranscriptMutationConflictError", "TranscriptTurnAdmissionConflictError",
    "can_forward_project_event", "message_idempotency_key", "messages_match_for_replay", "redact_message_for_storage",
    "resolve_message_append_parent", "timestamp_ms_to_iso",
]
