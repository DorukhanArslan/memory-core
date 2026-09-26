"""Session-memory hook: save the recent conversation on ``/new`` and ``/reset``.

Port of OpenClaw's bundled ``session-memory`` hook at pin 4c42815348
(``src/hooks/bundled/session-memory/{HOOK.md,handler.ts,transcript.ts}``).

Transcript extraction (``transcript.ts``):

- ``sanitize_session_memory_transcript_text``: ``sanitizeSessionMemoryTranscriptText``
  (``transcript.ts:8-38``) with ``sanitizeModelSpecialTokens``
  (``src/security/external-content.ts:116-153,298-307``).
- ``get_recent_session_content``: ``getRecentSessionContent``
  (``transcript.ts:40-115``). It keeps ``type: "message"`` rows from user and
  assistant, takes the first text block, skips user rows with inter-session
  provenance (``src/sessions/input-provenance.ts:38-112``), drops delivery-mirror
  rows that repeat the turn's assistant text
  (``src/shared/transcript-only-openclaw-assistant.ts:33-43``) and texts starting
  with ``/``, and returns the last N ``role: text`` lines joined by newlines.
- ``get_recent_session_content_with_reset_fallback`` and
  ``find_previous_session_file``: ``transcript.ts:117-231``.

Input is an OpenClaw session JSONL path or, as a memory-core addition, a list of
dicts: session entries (they have a ``type`` key) are read like parsed JSONL
rows, and plain message dicts (``role``, ``content``, optional ``provenance``,
``provider``, ``model``) count as ``type: "message"`` rows.

The stored lines are the raw recent conversation, like upstream (its
``## Conversation Summary`` is not an LLM summary).
"""

from __future__ import annotations

import json
import math
import os
import posixpath
import re
from collections.abc import Iterable, Mapping
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim

DEFAULT_SESSION_MEMORY_MESSAGE_COUNT = 15

# external-content.ts:116-153.
SPECIAL_TOKEN_REPLACEMENT = "[REMOVED_SPECIAL_TOKEN]"
LLM_SPECIAL_TOKEN_LITERALS = (
    # ChatML / Qwen
    "<|im_start|>",
    "<|im_end|>",
    "<|endoftext|>",
    # Llama 3.x / 4.x
    "<|begin_of_text|>",
    "<|end_of_text|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<|eot_id|>",
    "<|python_tag|>",
    "<|eom_id|>",
    # Mistral / Mixtral
    "[INST]",
    "[/INST]",
    "<<SYS>>",
    "<</SYS>>",
    # Phi and other sentencepiece-style templates
    "<s>",
    "</s>",
    # GPT-OSS / harmony
    "<|channel|>",
    "<|message|>",
    "<|return|>",
    "<|call|>",
    # Gemma
    "<start_of_turn>",
    "<end_of_turn>",
)
_LLM_SPECIAL_TOKEN_PATTERNS = (re.compile(r"<\|reserved_special_token_[0-9]+\|>"),)

# transcript.ts:8-18. The upstream regexes have no ``u`` flag: ``\b`` and case
# folding are ASCII-only (re.ASCII), ``\s`` is the JavaScript set and ``$``
# (no ``m`` flag) is the end of input (``\Z``).
_S = f"[{JS_SPACE_CLASS}]"
_TOOL_DIRECTIVE_PREFIX = "(?:(?:\\|DSML\\|)|(?:\\uFF5CDSML\\uFF5C))?"
_TOOL_DIRECTIVE_KIND = "(?:tool_calls?|function_calls?|tool_use_error)"
_DROP_BLOCK_RE = re.compile(
    f"<{_TOOL_DIRECTIVE_PREFIX}{_TOOL_DIRECTIVE_KIND}\\b[^>]*>"
    f"[\\s\\S]*?(?:</{_TOOL_DIRECTIVE_PREFIX}{_TOOL_DIRECTIVE_KIND}>|\\Z)",
    re.ASCII | re.IGNORECASE,
)
_ROLE_DIRECTIVE_BLOCK_RE = re.compile(
    r"<(system|assistant|user)\b[^>]*>[\s\S]*?</\1>", re.ASCII | re.IGNORECASE
)
_ROLE_DIRECTIVE_TAG_RE = re.compile(
    r"</?(?:system|assistant|user)\b[^>]*>", re.ASCII | re.IGNORECASE
)
_MEDIA_PLACEHOLDER_RE = re.compile(
    f"(^|\\n){_S}*<media:[^>]+>(?:{_S}*\\([^)]*\\))?{_S}*", re.ASCII | re.IGNORECASE
)
_TRAILING_NO_REPLY_RE = re.compile(
    f"(?:^|\\n){_S}*NO_REPLY{_S}*\\Z", re.ASCII | re.IGNORECASE
)
_NO_REPLY_RE = re.compile(r"^NO_REPLY\Z", re.ASCII | re.IGNORECASE)
_NO_REPLY_JSON_RE = re.compile(
    f'^\\{{{_S}*"action"{_S}*:{_S}*"NO_REPLY"{_S}*\\}}\\Z', re.ASCII | re.IGNORECASE
)

# transcript-only-openclaw-assistant.ts:5-6.
_TRANSCRIPT_ARTIFACT_PROVIDER = "openclaw"
_DELIVERY_MIRROR_MODEL = "delivery-mirror"


def sanitize_model_special_tokens(content: str) -> str:
    """Port of ``sanitizeModelSpecialTokens`` (external-content.ts:298-307)."""
    output = content
    for literal in LLM_SPECIAL_TOKEN_LITERALS:
        output = output.replace(literal, SPECIAL_TOKEN_REPLACEMENT)
    for pattern in _LLM_SPECIAL_TOKEN_PATTERNS:
        output = pattern.sub(SPECIAL_TOKEN_REPLACEMENT, output)
    return output


def _is_no_reply_marker(text: str) -> bool:
    trimmed = js_trim(text)
    return bool(_NO_REPLY_RE.match(trimmed) or _NO_REPLY_JSON_RE.match(trimmed))


def sanitize_session_memory_transcript_text(text: str) -> str | None:
    """Port of ``sanitizeSessionMemoryTranscriptText`` (transcript.ts:25-38).

    Drops a bare ``NO_REPLY`` marker, replaces model special tokens, removes
    tool-call blocks, role directive blocks and tags, media placeholders and a
    trailing ``NO_REPLY`` line; returns ``None`` when nothing visible is left.
    """
    if _is_no_reply_marker(text):
        return None
    without_artifacts = sanitize_model_special_tokens(text)
    without_artifacts = _DROP_BLOCK_RE.sub("", without_artifacts)
    without_artifacts = _ROLE_DIRECTIVE_BLOCK_RE.sub("", without_artifacts)
    without_artifacts = _ROLE_DIRECTIVE_TAG_RE.sub("", without_artifacts)
    without_artifacts = _MEDIA_PLACEHOLDER_RE.sub(r"\1", without_artifacts)
    without_artifacts = _TRAILING_NO_REPLY_RE.sub("", without_artifacts, count=1)
    return js_trim(without_artifacts) or None


def _js_truthy(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return bool(value)
    if isinstance(value, int | float):
        return value != 0 and not math.isnan(value)
    if isinstance(value, str):
        return value != ""
    return True  # objects and arrays, even empty ones


def _extract_text_message_content(content: object) -> str | None:
    """Port of ``extractTextMessageContent`` (transcript.ts:40-57)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list | tuple):
        return None
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            return block["text"]
    return None


def _has_inter_session_user_provenance(message: Mapping[str, Any]) -> bool:
    """``hasInterSessionUserProvenance`` (input-provenance.ts:38-53,77-79,105-112)."""
    if message.get("role") != "user":
        return False
    provenance = message.get("provenance")
    return isinstance(provenance, Mapping) and provenance.get("kind") == "inter_session"


def _is_delivery_mirror_assistant_message(message: Mapping[str, Any]) -> bool:
    """``isOpenClawDeliveryMirrorAssistantMessage`` (transcript-only-openclaw-assistant.ts:33-43)."""
    return (
        message.get("role") == "assistant"
        and message.get("provider") == _TRANSCRIPT_ARTIFACT_PROVIDER
        and message.get("model") == _DELIVERY_MIRROR_MODEL
    )


def _reject_json_constant(name: str) -> object:
    raise ValueError(f"not JSON: {name}")


def _parse_jsonl_row(line: str) -> object:
    # JSON.parse: NaN and Infinity are not JSON.
    return json.loads(line, parse_constant=_reject_json_constant)


def _read_session_file_entries(session_file_path: str) -> list[object] | None:
    try:
        with open(session_file_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    # fs.readFile(..., "utf-8") replaces invalid sequences; trim, then split on "\n".
    lines = js_trim(raw.decode("utf-8", errors="replace")).split("\n")
    entries: list[object] = []
    for line in lines:
        try:
            entries.append(_parse_jsonl_row(line))
        except (ValueError, RecursionError):
            continue  # Skip invalid JSON lines.
    return entries


def _entries_from_messages(messages: Iterable[object]) -> list[object]:
    entries: list[object] = []
    for item in messages:
        if isinstance(item, Mapping) and "type" not in item:
            entries.append({"type": "message", "message": item})
        else:
            entries.append(item)
    return entries


def _to_integer_or_infinity(value: float) -> float:
    if math.isnan(value):
        return 0
    if math.isinf(value):
        return value
    return math.trunc(value)


def _slice_last(items: list[str], message_count: int | float) -> list[str]:
    """``items.slice(-message_count)`` with JavaScript index semantics."""
    start = _to_integer_or_infinity(-message_count)
    length = len(items)
    index = max(length + start, 0) if start < 0 else min(start, length)
    return items[int(index) :]


def _recent_message_lines(entries: Iterable[object]) -> list[str]:
    """Message loop of ``getRecentSessionContent`` (transcript.ts:67-109)."""
    all_messages: list[str] = []
    last_assistant_text: str | None = None
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("type") != "message" or not _js_truthy(entry.get("message")):
            continue
        message = entry["message"]
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        if role not in ("user", "assistant") or not isinstance(role, str):
            continue
        if "content" not in message or not _js_truthy(message["content"]):
            continue
        if role == "user" and _has_inter_session_user_provenance(message):
            continue
        if role == "user":
            # New turn: reset even when slash commands are omitted from memory,
            # so later standalone delivery mirrors are preserved.
            last_assistant_text = None
        text = _extract_text_message_content(message["content"])
        sanitized = sanitize_session_memory_transcript_text(text) if text else None
        # Delivery-mirror rows are skipped only when they repeat the preceding
        # assistant text of the same turn.
        if _is_delivery_mirror_assistant_message(message):
            if sanitized and sanitized == last_assistant_text:
                continue
        if sanitized and not sanitized.startswith("/"):
            all_messages.append(f"{role}: {sanitized}")
            if role == "assistant":
                last_assistant_text = sanitized
    return all_messages


def _recent_session_lines(
    source: str | os.PathLike[str] | Iterable[object], message_count: int | float
) -> list[str] | None:
    if isinstance(source, str | os.PathLike):
        entries = _read_session_file_entries(os.fspath(source))
        if entries is None:
            return None
    else:
        entries = _entries_from_messages(source)
    return _slice_last(_recent_message_lines(entries), message_count)


def get_recent_session_content(
    source: str | os.PathLike[str] | Iterable[object],
    message_count: int | float = DEFAULT_SESSION_MEMORY_MESSAGE_COUNT,
) -> str | None:
    """Port of ``getRecentSessionContent`` (transcript.ts:59-115).

    ``source`` is a session JSONL path or a list of entries/messages. Returns
    the last ``message_count`` lines (``slice(-message_count)``: 0 keeps every
    line), ``""`` when no line survives and ``None`` when the file cannot be
    read.
    """
    lines = _recent_session_lines(source, message_count)
    return None if lines is None else "\n".join(lines)


def _node_basename(value: str) -> str:
    """``path.basename`` (posix): trailing separators are ignored."""
    stripped = value.rstrip("/")
    return posixpath.basename(stripped) if stripped else ""


def _node_dirname(value: str) -> str:
    """``path.dirname`` (posix): ``"."`` for a bare name, trailing separators ignored."""
    if not value:
        return "."
    stripped = value.rstrip("/")
    if not stripped:
        return "/"
    head = posixpath.dirname(stripped)
    if not head:
        return "."
    return head.rstrip("/") or "/"


def _node_join(*parts: str) -> str:
    """``path.join`` (posix): join the non-empty parts, then normalize."""
    joined = "/".join(part for part in parts if part)
    return posixpath.normpath(joined) if joined else "."


def _utf16_sort_key(value: str) -> bytes:
    # Array.prototype.toSorted() without a comparator compares UTF-16 code units.
    return value.encode("utf-16-be", "surrogatepass")


def _sorted_names(names: Iterable[str], *, reverse: bool = False) -> list[str]:
    return sorted(names, key=_utf16_sort_key, reverse=reverse)


def _list_dir(directory: str) -> list[str] | None:
    try:
        return os.listdir(directory)
    except OSError:
        return None


def get_recent_session_content_with_reset_fallback(
    session_file_path: str | os.PathLike[str],
    message_count: int | float = DEFAULT_SESSION_MEMORY_MESSAGE_COUNT,
) -> str | None:
    """Port of ``getRecentSessionContentWithResetFallback`` (transcript.ts:117-142).

    When the file yields no lines, reads the newest sibling
    ``<name>.reset.*`` rotation instead.
    """
    lines = _recent_session_lines_with_reset_fallback(
        os.fspath(session_file_path), message_count
    )
    return None if lines is None else "\n".join(lines)


def _recent_session_lines_with_reset_fallback(
    session_file_path: str, message_count: int | float
) -> list[str] | None:
    primary = _recent_session_lines(session_file_path, message_count)
    if primary:
        return primary
    directory = _node_dirname(session_file_path)
    reset_prefix = f"{_node_basename(session_file_path)}.reset."
    files = _list_dir(directory)
    if files is None:
        return primary
    candidates = _sorted_names(name for name in files if name.startswith(reset_prefix))
    if not candidates:
        return primary
    latest = _recent_session_lines(_node_join(directory, candidates[-1]), message_count)
    return latest or primary


def _strip_reset_suffix(file_name: str) -> str:
    reset_index = file_name.find(".reset.")
    return file_name if reset_index == -1 else file_name[:reset_index]


def find_previous_session_file(
    sessions_dir: str | os.PathLike[str],
    *,
    current_session_file: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> str | None:
    """Port of ``findPreviousSessionFile`` (transcript.ts:149-231).

    Looks in ``sessions_dir`` for the transcript behind a missing or rotated
    (``.reset.``) session file pointer: the pointer's base file, the pointer
    itself, then ``<session_id>.jsonl`` and its reset/topic variants, then
    (only with a pointer) the newest ``.jsonl`` or ``.jsonl.reset.*`` file.
    """
    directory = os.fspath(sessions_dir)
    files = _list_dir(directory)
    if files is None:
        return None
    file_set = set(files)
    current = os.fspath(current_session_file) if current_session_file else None

    current_base_name = _node_basename(current) if current else None
    base_from_reset = _strip_reset_suffix(current_base_name) if current_base_name else None
    if base_from_reset and base_from_reset in file_set:
        return _node_join(directory, base_from_reset)
    if current_base_name and ".reset." in current_base_name and current_base_name in file_set:
        return _node_join(directory, current_base_name)

    trimmed_session_id = js_trim(session_id) if session_id else None
    if trimmed_session_id:
        canonical_file = f"{trimmed_session_id}.jsonl"
        if canonical_file in file_set:
            return _node_join(directory, canonical_file)
        canonical_reset_variants = _sorted_names(
            (name for name in files if name.startswith(f"{canonical_file}.reset.")), reverse=True
        )
        if canonical_reset_variants:
            return _node_join(directory, canonical_reset_variants[0])
        topic_prefix = f"{trimmed_session_id}-topic-"
        topic_variants = _sorted_names(
            (
                name
                for name in files
                if name.startswith(topic_prefix)
                and name.endswith(".jsonl")
                and ".reset." not in name
            ),
            reverse=True,
        )
        if topic_variants:
            return _node_join(directory, topic_variants[0])
        topic_reset_variants = _sorted_names(
            (name for name in files if name.startswith(topic_prefix) and ".jsonl.reset." in name),
            reverse=True,
        )
        if topic_reset_variants:
            return _node_join(directory, topic_reset_variants[0])

    if not current:
        return None
    non_reset_jsonl = _sorted_names(
        (name for name in files if name.endswith(".jsonl") and ".reset." not in name),
        reverse=True,
    )
    if non_reset_jsonl:
        return _node_join(directory, non_reset_jsonl[0])
    reset_jsonl = _sorted_names((name for name in files if ".jsonl.reset." in name), reverse=True)
    if reset_jsonl:
        return _node_join(directory, reset_jsonl[0])
    return None
