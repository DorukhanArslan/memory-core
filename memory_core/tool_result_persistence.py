"""Guarded tool-result persistence, including bounded diagnostic details.

Ports ``session-tool-result-guard.payload.ts`` and the ordinary tool-result
stages of ``AgentSessionBase`` / ``guardSessionManager``. Direct catalog append
keeps its own direct native append contract. This settlement owner represents
the guarded caller's preparation, cap, before-write policy, cap and append.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import re
from typing import Any

from memory_core.bootstrap._js import js_trim, js_truthy, js_utf8_encode, slice_utf16_safe, truncate_utf16_safe, utf16_len
from memory_core.compaction_replay import _js_number_to_string
from memory_core.model_tool_result import prepare_session_tool_result
from memory_core.preemptive_compaction import DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS, truncate_tool_result_message
from memory_core.redact import (
    LoggingConfig, _js_object_key_order, is_sensitive_field_key,
    redact_sensitive_field_value, redact_tool_payload_text, translate_js_regex,
)
from memory_core.session_transcript_append import redact_message_for_storage
from memory_core.tool_result_context_guard import format_context_limit_truncation_notice
from memory_core.tool_result_text import js_stringify


MAX_DETAILS_BYTES = 8192
MAX_DETAIL_STRING_CHARS = 2000
_BOUNDARY = "\x00OPENCLAW_PERSISTED_DETAIL_BOUNDARY\x00"
_PARTIAL_SECRET = re.compile(translate_js_regex(
    r'''(?:["']?(?:api[-_]?key|apikey|token|secret|password|passwd|access[-_]?token|accesstoken|refresh[-_]?token|refreshtoken|auth[-_]?token|authtoken|client[-_]?secret|clientsecret|app[-_]?secret|appsecret|card[-_]?number|cardnumber|cvc|cvv)["']?\s*[:=]\s*["']?)(?!\*{3})(?=[^\s"',}\]]{8,})''',
)[0], re.I | re.ASCII,
)
_PARTIAL_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|OPENSSH PRIVATE KEY|RSA PRIVATE KEY|EC PRIVATE KEY|DSA PRIVATE KEY)-----", re.I | re.ASCII)
_SUMMARY_KEYS = ("status", "sessionId", "pid", "startedAt", "endedAt", "cwd", "name", "exitCode",
                 "exitSignal", "retryInMs", "total", "totalLines", "totalChars", "truncated", "spill",
                 "fullOutputPath", "spilledChars", "spillTruncated", "truncation")
_FALLBACK_KEYS = ("status", "sessionId", "pid", "exitCode", "exitSignal", "truncated", "spill",
                  "fullOutputPath", "spilledChars", "spillTruncated")
_SESSION_KEYS = ("sessionId", "status", "pid", "startedAt", "endedAt", "runtimeMs", "cwd", "name",
                 "truncated", "exitCode", "exitSignal")


@dataclass(frozen=True)
class BoundedJsonBytes:
    bytes: int | float
    complete: bool


def json_utf8_bytes_or_infinity(value: Any) -> int | float:
    try:
        return len(js_utf8_encode(js_stringify(value)))
    except (TypeError, ValueError, RecursionError, OverflowError):
        return math.inf


def bounded_json_utf8_bytes(value: Any, maximum: int) -> BoundedJsonBytes:
    """Original early-exit walker, including its retained lower-bound count."""
    count: int | float = 0
    seen: set[int] = set()

    def add(amount):
        nonlocal count
        count += amount
        if count > maximum:
            raise ValueError("json_byte_limit_exceeded")

    def string_bytes(text):
        remaining = maximum - count
        length = utf16_len(text)
        if length + 2 > remaining or (length * 3 + 2 > remaining and len(js_utf8_encode(text)) + 2 > remaining):
            return remaining + 1
        return json_utf8_bytes_or_infinity(text)

    def visit(entry):
        if entry is None:
            add(4)
        elif isinstance(entry, str):
            add(string_bytes(entry))
        elif isinstance(entry, bool):
            add(4 if entry else 5)
        elif isinstance(entry, (int, float)):
            add(json_utf8_bytes_or_infinity(entry))
        elif isinstance(entry, (dict, list)):
            if id(entry) in seen:
                raise ValueError("json_byte_length_circular")
            seen.add(id(entry))
            try:
                add(1)
                if isinstance(entry, list):
                    for index, item in enumerate(entry):
                        if index:
                            add(1)
                        visit(item)
                else:
                    for index, key in enumerate(_js_object_key_order(list(entry))):
                        if index:
                            add(1)
                        add(string_bytes(key))
                        add(1)
                        visit(entry[key])
                add(1)
            finally:
                seen.remove(id(entry))
        else:
            raise TypeError("json_byte_length_unsupported")

    try:
        visit(value)
        return BoundedJsonBytes(count, True)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return BoundedJsonBytes(max(count, maximum + 1), False)


def _size_fields(size: BoundedJsonBytes) -> dict:
    return {"originalDetailsBytes" if size.complete else "originalDetailsBytesAtLeast": size.bytes}


def _string(value: int | float | bool) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else _js_number_to_string(value)


def redact_persisted_detail_string(
    value: str, max_chars: int = MAX_DETAIL_STRING_CHARS, logging_config: LoggingConfig | None = None,
) -> str:
    if utf16_len(value) <= max_chars:
        return redact_tool_payload_text(value, logging_config=logging_config)
    scan = slice_utf16_safe(value, 0, max_chars) + _BOUNDARY + slice_utf16_safe(value, max_chars, max_chars + 1024)
    redacted = redact_tool_payload_text(scan, logging_config=logging_config)
    index = redacted.find(_BOUNDARY)
    prefix = redacted[:index] if index >= 0 else "[OpenClaw persisted detail redacted: boundary marker removed]"
    prefix = truncate_utf16_safe(prefix, max(0, max_chars - min(max_chars, 512)))
    if _PARTIAL_SECRET.search(prefix) or _PARTIAL_PRIVATE_KEY.search(prefix):
        prefix = "[OpenClaw persisted detail redacted: partial secret span omitted]"
    return (prefix + ("\n" if prefix else "") + "[OpenClaw persisted detail redacted: boundary overlap omitted]\n\n"
            + f"[OpenClaw persisted detail truncated: {max(0, utf16_len(value) - max_chars)} original chars omitted]")


def _detail(value, depth=0, inherited_key=None, config=None):
    if isinstance(value, str):
        return (redact_sensitive_field_value(inherited_key, value, logging_config=config) if inherited_key
                else redact_tool_payload_text(value, logging_config=config))
    if inherited_key and isinstance(value, (bool, int, float)):
        return redact_sensitive_field_value(inherited_key, _string(value), logging_config=config)
    if not isinstance(value, (dict, list)):
        return value
    if depth >= 8:
        return "[OpenClaw persisted detail redacted: max depth exceeded]"
    if isinstance(value, list):
        output = [_detail(item, depth + 1, inherited_key, config) for item in value]
        return value if all(item is previous or item == previous for item, previous in zip(output, value, strict=True)) else output
    output, changed = {}, False
    for key in _js_object_key_order(list(value)):
        next_key = redact_tool_payload_text(key, logging_config=config)
        next_value = _detail(value[key], depth + 1, key if is_sensitive_field_key(key) else inherited_key, config)
        # The original details owner builds an ordinary JS object through
        # assignment. Its __proto__ setter does not produce an enumerable own
        # field. Reproduce its serialized result without Python prototype state;
        # an entirely unchanged record still returns the original below.
        if next_key != "__proto__":
            output[next_key] = next_value
        changed |= next_key != key or next_value is not value[key] and next_value != value[key]
    return output if changed else value


def _get(source, key, default=None):
    return source.get(key, default) if isinstance(source, dict) else default


def _copy_summary(target, source, keys, max_chars, config):
    for key in keys:
        if isinstance(source, dict) and key in source:
            value = source[key]
            target[key] = (redact_persisted_detail_string(value, max_chars, config) if isinstance(value, str)
                           else _detail(value, 0, key if is_sensitive_field_key(key) else None, config))


def _copy_state(target, source, max_chars, config):
    for key in ("disabled", "unavailable", "success"):
        if isinstance(_get(source, key), bool):
            target[key] = source[key]
    error = _get(source, "error")
    if isinstance(error, str) and error:
        target["error"] = redact_persisted_detail_string(error, max_chars, config)
    elif js_truthy(error):
        target["error"] = True


def _redacted_keys(source, config):
    keys = _js_object_key_order(list(source))[:40] if isinstance(source, dict) else [str(index) for index in range(min(len(source), 40))]
    return [redact_tool_payload_text(key, logging_config=config) for key in keys]


def _fallback(source, original_size, sanitized_bytes, config):
    output = {"persistedDetailsTruncated": True, "finalDetailsTruncated": True, **_size_fields(original_size)}
    if sanitized_bytes is not None:
        output["sanitizedDetailsBytes"] = sanitized_bytes
    if source is not None:
        output["originalDetailKeys"] = _redacted_keys(source, config)
        _copy_summary(output, source, _FALLBACK_KEYS, 200, config)
        _copy_state(output, source, 200, config)
    return output


def _enforce(value, original, original_size, config):
    size = json_utf8_bytes_or_infinity(value)
    if size <= MAX_DETAILS_BYTES:
        return value
    fallback = _fallback(original if isinstance(original, dict) else None, original_size, size, config)
    return fallback if json_utf8_bytes_or_infinity(fallback) <= MAX_DETAILS_BYTES else _fallback(None, original_size, size, config)


def sanitize_tool_result_details_for_persistence(details: Any, logging_config: LoggingConfig | None = None) -> Any:
    if details is None:
        return details
    original_size = bounded_json_utf8_bytes(details, MAX_DETAILS_BYTES)
    if original_size.complete and original_size.bytes <= MAX_DETAILS_BYTES:
        return _enforce(_detail(details, config=logging_config), details, original_size, logging_config)
    if not isinstance(details, (dict, list)):
        kind = "string" if isinstance(details, str) else "boolean" if isinstance(details, bool) else "number" if isinstance(details, (int, float)) else "object"
        return _enforce({"persistedDetailsTruncated": True, **_size_fields(original_size), "valueType": kind},
                        None, original_size, logging_config)
    output = {"persistedDetailsTruncated": True, **_size_fields(original_size),
              "originalDetailKeys": _redacted_keys(details, logging_config)}
    _copy_summary(output, details, _SUMMARY_KEYS, MAX_DETAIL_STRING_CHARS, logging_config)
    _copy_state(output, details, MAX_DETAIL_STRING_CHARS, logging_config)
    if isinstance(_get(details, "tail"), str):
        output["tail"] = redact_persisted_detail_string(details["tail"], MAX_DETAIL_STRING_CHARS, logging_config)
    sessions = _get(details, "sessions")
    if isinstance(sessions, list):
        saved = []
        for session in sessions[:10]:
            if not isinstance(session, (dict, list)):
                saved.append(session)
                continue
            item = {}
            _copy_summary(item, session, _SESSION_KEYS, 500, logging_config)
            if isinstance(_get(session, "command"), str):
                item["command"] = redact_persisted_detail_string(session["command"], 500, logging_config)
            saved.append(item)
        output["sessions"] = saved
        if len(sessions) > 10:
            output["sessionsTruncated"] = len(sessions) - 10
    return _enforce(output, details, original_size, logging_config)


def cap_tool_result_for_persistence(
    message: dict[str, Any], max_chars: int | float = DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS,
    logging_config: LoggingConfig | None = None,
) -> dict[str, Any]:
    if message.get("role") != "toolResult":
        return message
    capped = truncate_tool_result_message(message, max_chars, suffix=format_context_limit_truncation_notice, min_keep_chars=2000)
    if "details" not in capped:
        return capped
    details = sanitize_tool_result_details_for_persistence(capped["details"], logging_config)
    return capped if details is capped["details"] else {**capped, "details": details}


@dataclass(frozen=True)
class ToolResultSettlement:
    live_message: dict[str, Any]
    append_result: dict[str, Any]


def normalize_persisted_tool_result_name(
    message: dict[str, Any], fallback_name: str | None = None, fallback_id: str | None = None,
) -> dict[str, Any]:
    """The guarded caller's ordinary tool identity normalization before capping."""
    if message.get("role") != "toolResult":
        return message
    raw_name = message.get("toolName")
    name = ((js_trim(raw_name) or None) if isinstance(raw_name, str) else None)
    name = name or ((js_trim(fallback_name) or None) if isinstance(fallback_name, str) else None) or "unknown"
    raw_id = message.get("toolCallId") if isinstance(message.get("toolCallId"), str) else None
    tool_id = raw_id if raw_id is not None else ((js_trim(fallback_id) or None) if isinstance(fallback_id, str) else None)
    is_error = message.get("isError") if isinstance(message.get("isError"), bool) else False
    if raw_name == name and raw_id == tool_id and message.get("isError") is is_error:
        return message
    return {**message, **({"toolCallId": tool_id} if tool_id else {}), "toolName": name, "isError": is_error}


def settle_session_tool_result(
    catalog, session_id: str, message: dict[str, Any], *, session_key: str,
    event_id: str | None = None, now_ms: float | None = None, cwd: str | None = None,
    max_chars: int | float = DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS, logging_config: LoggingConfig | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    on_stage: Callable[[str, dict[str, Any]], None] | None = None,
) -> ToolResultSettlement:
    """Run real guarded tool-result stages and append through the durable owner.

    ``on_event`` represents the actual live listener boundary; a listener may
    change the current result or register another secret. ``on_stage`` observes
    complete actual intermediate messages and never replaces their values.
    """
    if message.get("role") != "toolResult":
        raise ValueError("Guarded tool-result settlement requires an actual toolResult message")
    event = {"type": "message_end", "message": message}

    def observed(label, current):
        if on_stage is not None:
            on_stage(label, current)
        return current

    prepare_session_tool_result(event, logging_config=logging_config)
    observed("before-live-listeners", event["message"])
    if on_event is not None:
        on_event(event)
    prepare_session_tool_result(event, logging_config=logging_config)
    observed("after-live-listeners", event["message"])
    normalized = normalize_persisted_tool_result_name(event["message"])
    capped = observed("first-persistence-cap", cap_tool_result_for_persistence(normalized, max_chars, logging_config))
    before_write = observed("before-message-write-policy", redact_message_for_storage(capped, logging_config))
    persisted = observed("final-persistence-cap", cap_tool_result_for_persistence(before_write, max_chars, logging_config))
    appended = catalog.append_message(session_id, persisted, session_key=session_key, event_id=event_id,
                                      now_ms=now_ms, cwd=cwd, logging_config=logging_config)
    observed("committed-message", appended["message"])
    prepare_session_tool_result(event, logging_config=logging_config)
    observed("after-write-settlement", event["message"])
    return ToolResultSettlement(event["message"], appended)


__all__ = ["BoundedJsonBytes", "bounded_json_utf8_bytes", "json_utf8_bytes_or_infinity",
           "redact_persisted_detail_string", "sanitize_tool_result_details_for_persistence",
           "cap_tool_result_for_persistence", "normalize_persisted_tool_result_name", "ToolResultSettlement", "settle_session_tool_result"]
