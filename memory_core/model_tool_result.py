"""Model/tool-result sanitization and non-persisted admitted text provenance.

Ports the ordinary JSON owners in ``embedded-agent-tool-results.ts``,
``redact-internal-state.ts`` and ``sessions/session-tool-result-redaction.ts``.
Prepared carriers keep policy state outside JSON keys. Plain Python dicts and
lists cannot be weakly referenced; their raw inputs are deliberately not cached.
Only prepared output can reuse itself under an unchanged structural snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from memory_core.bootstrap._js import truncate_utf16_safe, utf16_len
from memory_core.redact import (
    LoggingConfig,
    get_logging_redaction_config,
    is_full_context_tool_payload_redaction,
    redact_model_visible_field_value,
    redact_model_visible_secrets,
    redact_model_visible_tool_payload_text,
    redact_sensitive_field_value,
    redact_tool_payload_text,
)
from memory_core.secret_registry import get_secret_redaction_registry_revision


TOOL_RESULT_MAX_CHARS = 8000


@dataclass(frozen=True)
class ModelVisibleRedactionPolicy:
    patterns: tuple[str, ...]
    full_context: bool
    registry_revision: int


def capture_model_visible_redaction_policy(
    logging_config: LoggingConfig | None = None,
) -> ModelVisibleRedactionPolicy:
    config = logging_config if logging_config is not None else get_logging_redaction_config()
    return ModelVisibleRedactionPolicy(
        tuple(config.redact_patterns or ()) if config else (),
        is_full_context_tool_payload_redaction(config),
        get_secret_redaction_registry_revision(),
    )


class PreparedToolTextBlock(dict[str, Any]):
    """A real admitted block; its policy marker disappears in JSON persistence."""

    __slots__ = ("_admitted_text", "_admitted_policy")


def is_prepared_model_visible_tool_text(
    block: object, text: str, logging_config: LoggingConfig | None = None,
) -> bool:
    return (
        isinstance(block, PreparedToolTextBlock)
        and getattr(block, "_admitted_text", None) == text
        and getattr(block, "_admitted_policy", None) == capture_model_visible_redaction_policy(logging_config)
    )


def prepare_model_visible_tool_text_block(
    block: dict[str, Any], logging_config: LoggingConfig | None = None,
) -> PreparedToolTextBlock:
    if is_prepared_model_visible_tool_text(block, block["text"], logging_config):
        return block
    prepared = PreparedToolTextBlock(block)
    prepared["text"] = redact_model_visible_field_value("text", block["text"], logging_config=logging_config)
    prepared._admitted_text = prepared["text"]
    prepared._admitted_policy = capture_model_visible_redaction_policy(logging_config)
    return prepared


def copy_prepared_model_visible_tool_text(
    source: object, target: dict[str, Any],
) -> dict[str, Any]:
    """Copy genuine provenance only with unchanged admitted text; use the returned carrier."""
    if (not isinstance(source, PreparedToolTextBlock)
            or not isinstance(source.get("text"), str) or source["text"] != target.get("text")
            or getattr(source, "_admitted_text", None) != source["text"]):
        return target
    copied = PreparedToolTextBlock(target)
    copied._admitted_text = source._admitted_text
    copied._admitted_policy = source._admitted_policy
    return copied


def prepare_session_tool_result(
    event: dict[str, Any], *, logging_config: LoggingConfig | None = None,
) -> bool:
    """Prepare actual message-end text before both live consumers and storage.

    Like the native session event owner, this replaces the event's content array
    and returns whether any admitted text changed; non-text blocks keep identity.
    """
    message = event.get("message")
    if event.get("type") != "message_end" or not isinstance(message, dict) or message.get("role") != "toolResult":
        return False
    changed = False
    content = []
    for block in message["content"]:
        if block.get("type") != "text":
            content.append(block)
            continue
        prepared = prepare_model_visible_tool_text_block(block, logging_config)
        changed |= prepared["text"] != block["text"]
        content.append(prepared)
    message["content"] = content
    return changed


class SanitizedToolResult(dict[str, Any]):
    __slots__ = ("_sanitized_policy", "_sanitized_snapshot")


class SanitizedToolResultList(list[Any]):
    __slots__ = ("_sanitized_policy", "_sanitized_snapshot")


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if math.isnan(left) and math.isnan(right):
            return True
        if left == right == 0:
            return math.copysign(1, left) == math.copysign(1, right)
        return left == right
    return type(left) is type(right) and left == right


def _capture_snapshot(root: dict | list) -> list[tuple[object, type, tuple]] | None:
    snapshot = []
    seen: set[int] = set()

    def visit(value: Any) -> bool:
        if not isinstance(value, (dict, list)):
            return value is None or isinstance(value, (str, bool, int, float))
        if type(value) not in (dict, list, SanitizedToolResult, SanitizedToolResultList):
            return False
        if id(value) in seen:
            return True
        seen.add(id(value))
        properties = tuple(value.items()) if isinstance(value, dict) else tuple(enumerate(value))
        if not all(visit(item) for _, item in properties):
            return False
        snapshot.append((value, type(value), properties))
        return True

    return snapshot if visit(root) else None


def _matches_snapshot(snapshot: list[tuple[object, type, tuple]]) -> bool:
    for value, kind, properties in snapshot:
        if type(value) is not kind:
            return False
        current = tuple(value.items()) if isinstance(value, dict) else tuple(enumerate(value))
        if len(current) != len(properties) or any(
            key != old_key or not _same_value(item, old_item)
            for (key, item), (old_key, old_item) in zip(current, properties, strict=True)
        ):
            return False
    return True


def _estimate_base64_decoded_bytes(value: str) -> int:
    # Match the original estimator, including malformed data: do not decode it.
    effective = 0
    previous = last = None
    for char in value:
        code = ord(char)
        if code > 0x20:
            effective += 2 if code > 0xFFFF else 1
            previous, last = last, code
    padding = (1 if last == 61 else 0) + (1 if last == previous == 61 else 0)
    return max(0, effective * 3 // 4 - padding)


def _sanitize_structured_result(result: dict | list, logging_config: LoggingConfig | None) -> dict | list:
    if isinstance(result, list):
        return redact_model_visible_secrets(result, logging_config=logging_config)
    cleaned = dict(result)
    original_content = result.get("content")
    if isinstance(original_content, list):
        content = []
        for block in original_content:
            if isinstance(block, dict) and block.get("type") == "image":
                item = dict(block)
                data = item.pop("data", None)
                if isinstance(data, str):
                    item["bytes"] = _estimate_base64_decoded_bytes(data)
                elif not isinstance(item.get("bytes"), (int, float)) or isinstance(item.get("bytes"), bool):
                    item.pop("bytes", None)
                item["omitted"] = True
                content.append(item)
            else:
                content.append(block)
        cleaned["content"] = content
    sanitized = redact_model_visible_secrets(cleaned, logging_config=logging_config)
    content = sanitized.get("content")
    if isinstance(content, list):
        sanitized["content"] = [
            {**block, "text": truncate_utf16_safe(block["text"], TOOL_RESULT_MAX_CHARS) + "\n…(truncated)…"}
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str) and utf16_len(block["text"]) > TOOL_RESULT_MAX_CHARS
            else block for block in content
        ]
    return sanitized


def sanitize_tool_result(result: Any, *, logging_config: LoggingConfig | None = None) -> Any:
    """Sanitize the whole result, stripping image data before redaction/truncation."""
    if isinstance(result, str):
        return redact_model_visible_tool_payload_text(result, logging_config=logging_config)
    if not isinstance(result, (dict, list)):
        return result
    policy = capture_model_visible_redaction_policy(logging_config)
    if isinstance(result, (SanitizedToolResult, SanitizedToolResultList)):
        snapshot = getattr(result, "_sanitized_snapshot", None)
        if getattr(result, "_sanitized_policy", None) == policy and snapshot is not None and _matches_snapshot(snapshot):
            return result
    sanitized = _sanitize_structured_result(result, logging_config)
    prepared = SanitizedToolResult(sanitized) if isinstance(sanitized, dict) else SanitizedToolResultList(sanitized)
    prepared._sanitized_policy = policy
    prepared._sanitized_snapshot = _capture_snapshot(prepared)
    return prepared


def sanitize_tool_args(args: Any, *, logging_config: LoggingConfig | None = None) -> Any:
    """Diagnostic argument walker; aliases, like cycles, use the native seen marker."""
    seen: set[int] = set()

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return redact_tool_payload_text(value, logging_config=logging_config)
        if not isinstance(value, (dict, list)):
            return value
        if id(value) in seen:
            return "[Circular]"
        seen.add(id(value))
        if isinstance(value, list):
            return [walk(item) for item in value]
        return {key: redact_sensitive_field_value(key, item, logging_config=logging_config)
                if isinstance(item, str) else walk(item) for key, item in value.items()}

    return walk(args)


__all__ = [
    "PreparedToolTextBlock", "SanitizedToolResult", "SanitizedToolResultList",
    "ModelVisibleRedactionPolicy", "capture_model_visible_redaction_policy",
    "prepare_model_visible_tool_text_block", "is_prepared_model_visible_tool_text",
    "copy_prepared_model_visible_tool_text", "prepare_session_tool_result",
    "sanitize_tool_result", "sanitize_tool_args",
]
