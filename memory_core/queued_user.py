"""Recover an unanswered external user message on the active session branch."""
from collections.abc import Mapping
import re

from memory_core.bootstrap._js import js_json_stringify, js_trim, truncate_utf16_safe, utf16_len

METADATA = frozenset({"thinking_level_change", "model_change", "custom", "label", "session_info"})
MARKER = ("[Queued user message from a previous active turn; preserved as context only. "
          "Continue with the active prompt below.]")
_STATE_UPDATES = frozenset({"agent_harness_task", "agent_harness_completion", "image_generate", "music_generate",
    "video_generate", "exec_approval_followup", "subagent_announce", "subagent_settle", "subagent_interrupted_resume"})


def trailing_user(events, completed_turn_id=None):
    """Return the unanswered user and transparent metadata following it on this branch."""
    end = len(events)
    while end and events[end - 1].get("type") in METADATA:
        end -= 1
    if not end:
        return None
    entry = events[end - 1]
    message = entry.get("message") or {}
    if entry.get("type") != "message" or message.get("role") != "user":
        return None
    if completed_turn_id and message.get("idempotencyKey") == completed_turn_id:
        return None
    return entry, events[end:]


def _media(label, value):
    if not isinstance(value, str) or not (text := js_trim(value)):
        return None
    if match := re.match(r"^data:([^;,]+)?(?:;[^,]*)?,", text, re.I):
        return f"[{label}] inline data URI ({match.group(1) or 'unknown'}, {utf16_len(text)} chars)"
    if utf16_len(text) > 300:
        text = f"{truncate_utf16_safe(text, 300)}... ({utf16_len(text)} chars)"
    return f"[{label}] {text}"


def _bounded(value, depth=0):
    if isinstance(value, str):
        summary = _media("value", value)
        if summary and "inline data URI" in summary:
            return summary
        return (f"{truncate_utf16_safe(value, 300)}... ({utf16_len(value)} chars)" if utf16_len(value) > 300 else value)
    if not isinstance(value, (list, Mapping)):
        return value
    if depth >= 4:
        return "[max depth]"
    if isinstance(value, list):
        return [_bounded(v, depth + 1) for v in value[:16]] + ([f"[{len(value)-16} more items]"] if len(value) > 16 else [])
    out = {k: _bounded(v, depth + 1) for k, v in list(value.items())[:32]}
    if len(value) > 32:
        out["__truncated"] = f"{len(value)-32} more keys"
    return out


def _part(block):
    if not isinstance(block, Mapping):
        return None
    kind = block.get("type")
    if kind == "text":
        return js_trim(block["text"]) if isinstance(block.get("text"), str) else None
    if kind == "image_url":
        value = block.get("image_url")
        return _media(kind, value.get("url") if isinstance(value, Mapping) else value)
    if isinstance(kind, str):
        keys = ("url", "source") if kind in {"image", "input_image"} else ("audio_url", "media_url", "url", "source")
        ref = next((ref for k in keys if (ref := _media(kind, block.get(k)))), None)
        if ref or kind in {"image", "input_image"}:
            return ref
    fallback = js_json_stringify(_bounded(block))
    if fallback == "{}":
        return None
    clean = re.sub(r"""data:[^"'\\\s]+""",
                   lambda match: f"[inline data URI: {utf16_len(match[0])} chars]", fallback, flags=re.I)
    return f"{truncate_utf16_safe(clean, 1000)}... ({utf16_len(clean)} chars)" if utf16_len(clean) > 1000 else clean


def merge_text(prompt, user):
    content = user.get("content")
    if isinstance(content, str):
        text = js_trim(content)
    elif isinstance(content, list):
        text = js_trim("\n".join(part for block in content if (part := _part(block))))
    else:
        text = ""
    origin = user.get("provenance")
    if js_trim(prompt) and isinstance(origin, Mapping):
        source = origin.get("sourceTool")
        if ((origin.get("kind") == "internal_system" and source == "progress_card_refresh")
                or (origin.get("kind") == "inter_session" and isinstance(source, str) and source.lower() in _STATE_UPDATES)):
            return prompt
    normalized = prompt.replace("\r\n", "\n")
    line = text.replace("\r\n", "\n").strip()
    if not line or "\n" + line + "\n" in "\n" + normalized + "\n":
        return prompt
    return f"{MARKER}\n{text}\n\n{prompt}"
