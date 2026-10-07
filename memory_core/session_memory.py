"""Session-memory hook: save the recent conversation on ``/new``, ``/reset`` and rollover.

Port of OpenClaw's bundled ``session-memory`` hook at v2026.9.6
(``src/hooks/bundled/session-memory/{HOOK.md,handler.ts,capture.ts,transcript.ts}``).

Transcript projection (``transcript.ts``):

- ``sanitize_session_memory_transcript_text``: ``sanitizeSessionMemoryTranscriptText``
  with ``sanitizeModelSpecialTokens`` (``src/security/external-content.ts``).
- ``get_recent_session_projection_from_events`` and ``count_session_memory_messages``:
  ``getRecentSessionProjectionFromEvents`` / ``countSessionMemoryMessages``. They keep
  ``type: "message"`` rows from user and assistant, take the first text block, skip user
  rows with inter-session provenance, drop delivery-mirror rows that repeat the turn's
  assistant text and texts starting with ``/``, and write each row as ``role: <JSON
  string>`` (one JSON string per record, U+0085/U+2028/U+2029 escaped). The projection
  also reports the trust class of the kept rows (``classify_session_message_origin``).
- ``capture_session_memory_events``: the visible-branch selection and budgets of
  ``captureSessionMemoryTranscript`` over host-supplied events.

Storage (decision recorded in docs/upstream_port_v2026_9_6.md, "Decisions needed" 4):
OpenClaw v2026.9.6 keeps sessions and transcripts in per-agent SQLite and the hook reads
them from there. memory-core does not couple to that schema: the host passes the ending
session's transcript events. ``get_recent_session_content`` and the ``.reset.`` file
helpers (``get_recent_session_content_with_reset_fallback``, ``find_previous_session_file``)
no longer exist upstream (the file-era runtime was removed in 4273ca9dbd9); they stay as
legacy file helpers and render through the same projection (``save_session_memory`` does not
use the ``.reset.`` recovery any more).

Optional LLM filename slug (``src/hooks/llm-slug-generator.ts``):
``generate_session_memory_slug`` sends the verbatim prompt
(``build_session_memory_slug_prompt``, excerpt cut with ``truncateUtf16Safe``) to a
host-supplied generator, rejects error replies (``is_error_slug_payload`` with
``parseApiErrorPayload`` and ``extractLeadingHttpStatus`` from
``src/shared/assistant-error-format.ts``) and normalizes the reply
(``normalize_session_memory_slug``). memory-core never calls a model itself (upstream also
admits that run for the agent and passes ``disableTools``; the host's generator owns both);
without a generator the slug is the timestamp.

The hook (``handler.ts``): ``save_session_memory`` is what the host calls on ``/new``,
``/reset`` or an automatic rollover (``is_session_memory_trigger``). It keeps the last 15
rows (``message_count``, ``hooks.internal.entries["session-memory"].messages``), stamps the
local time (``format_local_session_timestamp``: ``YYYY-MM-DD``, ``HH:MM:SS``, the zone
name itself in the heading, slug ``HHMM``) and writes a new ``memory/<date>-<slug>.md``
(``-2``, ``-3``... on a name clash) with the entry of ``build_session_memory_entry``. The
write has its own path: the file is always new (never appended to, overwritten or written
through a symlink) and ``memory/`` must stay inside the workspace. The daily-flush validator
(``MemoryWorkspace.append_daily_memory``) keeps rejecting these names.

The stored rows are the raw recent conversation, like upstream (its ``## Conversation
Summary`` is not an LLM summary); the optional ``redactor`` (deviation by choice, default
off) maps each line before it is written.

Deviations, each named at its code site: an explicit IANA zone (default UTC) instead of
``process.env.TZ``; the session key written as given (no agent re-keying); errors raised to
the caller instead of logged; a name is taken by any directory entry; no memory-write
provenance record unless the host supplies ``artifact_provenance``; no ``context.agentId``
requirement or admission (the host owns agent scoping). Not ported: the background write
queue, the agent/workspace resolution from OpenClaw config, and the 15 s model timeout (the
host's generator owns it). The files reach the next session through
``memory_core.bootstrap.build_startup_context`` (up to four slugged files per day) and, once
the host reindexes, through ``memory_search`` and ``memory_get``: discovery walks every
``memory/**/*.md`` like upstream ``listMemoryFiles``, and temporal decay treats these undated
names as evergreen (``isEvergreenMemoryPath``).
"""

from __future__ import annotations

import contextlib
import errno
import json
import math
import os
import posixpath
import re
import secrets
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_core.bootstrap._js import (
    JS_SPACE_CLASS,
    js_trim,
    js_utf8_encode,
    reject_json_constant,
    truncate_utf16_safe,
)
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver
from memory_core.transcript_tree import select_visible_transcript_events
from memory_core.workspace import UnsafeMemoryPathError

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
    tool-call blocks, role directive blocks and tags and a
    trailing ``NO_REPLY`` line; returns ``None`` when nothing visible is left.
    """
    if _is_no_reply_marker(text):
        return None
    without_artifacts = sanitize_model_special_tokens(text)
    without_artifacts = _DROP_BLOCK_RE.sub("", without_artifacts)
    without_artifacts = _ROLE_DIRECTIVE_BLOCK_RE.sub("", without_artifacts)
    without_artifacts = _ROLE_DIRECTIVE_TAG_RE.sub("", without_artifacts)
    without_artifacts = _TRAILING_NO_REPLY_RE.sub("", without_artifacts, count=1)
    return js_trim(without_artifacts) or None


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


def _parse_jsonl_row(line: str) -> object:
    # JSON.parse: NaN and Infinity are not JSON.
    return json.loads(line, parse_constant=reject_json_constant)


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


_JSON_LINE_SEPARATOR_RE = re.compile("[\u0085\u2028\u2029]")
_LONE_SURROGATE_ESCAPE_RE = re.compile("[\ud800-\udfff]")


def _quote_session_memory_text(text: str) -> str:
    """``quoteSessionMemoryText`` (transcript.ts:20-26): one JSON string per record.

    ``JSON.stringify`` is well-formed (lone surrogates are escaped) and the
    separators U+0085, U+2028 and U+2029 are escaped on top of it.
    """
    quoted = json.dumps(text, ensure_ascii=False)
    quoted = _LONE_SURROGATE_ESCAPE_RE.sub(lambda m: f"\\u{ord(m.group()):04x}", quoted)
    return _JSON_LINE_SEPARATOR_RE.sub(lambda m: f"\\u{ord(m.group()):04x}", quoted)


def _as_record(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def classify_session_message_origin(message: Mapping[str, Any], turn_origin: str) -> str:
    """``classifySessionMessageOrigin`` (memory-host-sdk host/session-provenance.ts).

    ``owner``, ``agent``, ``untrusted`` or ``system`` from the message's role,
    ``provenance.kind`` and ``__openclaw`` metadata (``turnTainted``,
    ``senderIsOwner``).
    """
    if message.get("role") == "assistant":
        metadata = _as_record(message.get("__openclaw"))
        if metadata is not None and metadata.get("turnTainted") is True:
            return "untrusted"
        return "agent" if turn_origin == "owner" else turn_origin
    provenance = _as_record(message.get("provenance"))
    if provenance is not None and provenance.get("kind") == "internal_system":
        return "system"
    metadata = _as_record(message.get("__openclaw"))
    return "owner" if metadata is not None and metadata.get("senderIsOwner") is True else "untrusted"


def _render_session_memory_message(
    entry: object, turn_origin: str
) -> tuple[tuple[bool, str, str, str | None] | None, str]:
    """``renderSessionMemoryMessage`` (transcript.ts:97-150).

    Returns ``((is_delivery_mirror, origin_class, role, text) | None, turn_origin)``.
    A user row whose text is a slash command stays as a row without text (it
    ends the turn but is not written).
    """
    record = _as_record(entry)
    if record is None or record.get("type") != "message":
        return None, turn_origin
    message = _as_record(record.get("message"))
    if message is None:
        return None, turn_origin
    role = message.get("role")
    if role not in ("user", "assistant") or "content" not in message:
        return None, turn_origin
    next_turn_origin = (
        classify_session_message_origin(message, turn_origin) if role == "user" else turn_origin
    )
    origin_class = classify_session_message_origin(message, next_turn_origin)
    if role == "user" and _has_inter_session_user_provenance(message):
        return None, next_turn_origin
    text = _extract_text_message_content(message["content"])
    sanitized = sanitize_session_memory_transcript_text(text) if text else None
    if not sanitized:
        return None, next_turn_origin
    if sanitized.startswith("/"):
        return ((False, origin_class, role, None) if role == "user" else None), next_turn_origin
    return (
        (_is_delivery_mirror_assistant_message(message), origin_class, role, sanitized),
        next_turn_origin,
    )


def _render_session_memory_records(events: Iterable[object]) -> list[tuple[str, str]]:
    """``renderSessionMemoryRecords`` (transcript.ts:157-190): ``(line, origin_class)`` pairs."""
    records: list[tuple[str, str]] = []
    last_assistant_text: str | None = None
    turn_origin = "untrusted"
    for event in events:
        rendered, turn_origin = _render_session_memory_message(event, turn_origin)
        if rendered is None:
            continue
        is_mirror, origin_class, role, text = rendered
        if role == "user":
            # New turn: reset even when slash commands are omitted from memory, so
            # later standalone delivery mirrors are preserved.
            last_assistant_text = None
        if not text:
            continue
        # Delivery-mirror rows are skipped only when they repeat the preceding
        # assistant text; mirrors with unique visible content are preserved.
        if is_mirror and text == last_assistant_text:
            continue
        records.append((f"{role}: {_quote_session_memory_text(text)}", origin_class))
        if role == "assistant":
            last_assistant_text = text
    return records


def count_session_memory_messages(events: Iterable[object]) -> int:
    """``countSessionMemoryMessages`` (transcript.ts:193-195)."""
    return len(_render_session_memory_records(events))


@dataclass(frozen=True)
class SessionMemoryProjection:
    """``SessionMemoryProjection``: the quoted lines and their trust class."""

    content: str
    origin_class: str  # "agent" | "untrusted"


def _message_limit(message_count: object) -> int:
    # Number.isFinite(messageCount) ? Math.max(0, Math.floor(messageCount)) : 0
    if isinstance(message_count, bool) or not isinstance(message_count, int | float):
        return 0
    if isinstance(message_count, float) and not math.isfinite(message_count):
        return 0
    return max(0, math.floor(message_count))


def get_recent_session_projection_from_events(
    events: Iterable[object], message_count: int | float = DEFAULT_SESSION_MEMORY_MESSAGE_COUNT
) -> SessionMemoryProjection | None:
    """Port of ``getRecentSessionProjectionFromEvents`` (transcript.ts:201-221).

    ``events`` are host-supplied transcript events (dicts with ``type:
    "message"`` and a ``message``). Each kept row is ``role: <JSON string>``;
    the last ``message_count`` rows are joined with newlines. ``None`` when the
    count is 0 or no row survives; ``origin_class`` is ``untrusted`` as soon as
    one kept row is untrusted or system.
    """
    limit = _message_limit(message_count)
    if limit == 0:
        return None
    records = _render_session_memory_records(events)[-limit:]
    if not records:
        return None
    untrusted = any(origin in ("untrusted", "system") for _, origin in records)
    return SessionMemoryProjection(
        content="\n".join(line for line, _ in records),
        origin_class="untrusted" if untrusted else "agent",
    )


# Capture budget of upstream's authoritative reader (capture.ts SESSION_MEMORY_CAPTURE_*).
SESSION_MEMORY_CAPTURE_MAX_SCANNED_MESSAGES = 4_096
SESSION_MEMORY_CAPTURE_MAX_BYTES = 8 * 1024 * 1024


def capture_session_memory_events(events: Iterable[object]) -> list[object]:
    """What ``captureSessionMemoryTranscript`` keeps of a host transcript.

    Port of the visible-branch selection and the authoritative-read budgets of
    ``captureAuthoritativeMemoryEvents`` (capture.ts:78-110, without the reset
    window, which only applies to its repair read): events on the active
    branch (``selectVisibleTranscriptEvents``), ``type: "message"`` rows only,
    the last 4096 of them, newest first until 8 MiB of JSON is reached.
    Deviation: upstream first reads bounded pages of the host's SQLite store;
    the host supplies the events here, so only the budgets of the fallback read
    apply.
    """
    messages = [
        event
        for event in select_visible_transcript_events(list(events))
        if isinstance(event, Mapping) and event.get("type") == "message"
    ][-SESSION_MEMORY_CAPTURE_MAX_SCANNED_MESSAGES:]
    captured: list[object] = []
    total = 0
    for event in reversed(messages):
        try:
            size = len(js_utf8_encode(json.dumps(event, ensure_ascii=False))) + 1
        except (TypeError, ValueError):
            size = 1
        if total + size <= SESSION_MEMORY_CAPTURE_MAX_BYTES:
            captured.insert(0, event)
            total += size
    return captured


def _recent_message_lines(entries: Iterable[object]) -> list[str]:
    return [line for line, _ in _render_session_memory_records(entries)]


def _recent_session_lines(
    source: str | os.PathLike[str] | Iterable[object], message_count: int | float
) -> list[str] | None:
    if isinstance(source, str | os.PathLike):
        entries = _read_session_file_entries(os.fspath(source))
        if entries is None:
            return None
    else:
        entries = _entries_from_messages(source)
    limit = _message_limit(message_count)
    return _recent_message_lines(entries)[-limit:] if limit else []


def get_recent_session_content(
    source: str | os.PathLike[str] | Iterable[object],
    message_count: int | float = DEFAULT_SESSION_MEMORY_MESSAGE_COUNT,
) -> str | None:
    """Port of ``getRecentSessionContent`` (transcript.ts:59-115).

    ``source`` is a session JSONL path or a list of entries/messages. Returns
    the last ``message_count`` rows as ``role: <JSON string>`` lines (the
    projection of ``getRecentSessionProjectionFromEvents``; a count of 0 or
    infinity gives no rows), ``""`` when no row survives and ``None`` when the
    file cannot be read. Legacy file input: v2026.9.6 no longer has this
    function (its transcripts live in SQLite); use
    ``get_recent_session_projection_from_events`` with host-supplied events.
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


# --- LLM filename slug (src/hooks/llm-slug-generator.ts) ---------------------------------

# llm-slug-generator.ts:25. memory-core does not run the model: the host's generator
# enforces the timeout (upstream: this default, or agents.defaults.timeoutSeconds).
DEFAULT_SLUG_GENERATOR_TIMEOUT_MS = 15_000
SLUG_PROMPT_SESSION_CONTENT_MAX_CHARS = 2_000
SLUG_MAX_CHARS = 30

SlugReply = str | Mapping[str, Any] | None
"""A slug generator's reply: the model text, or a payload with ``text`` and ``isError``."""
SlugGenerator = Callable[[str], SlugReply]

# src/shared/assistant-error-format.ts:3-13 and llm-slug-generator.ts:26-29, without
# the u flag (ASCII \w, \d, \b and case folding; the JavaScript \s set; $ is \Z).
_ERROR_PAYLOAD_PREFIX_RE = re.compile(
    f"^(?:error|(?:[a-z][\\w-]*{_S}+)?api{_S}*error|apierror|openai{_S}*error"
    f"|anthropic{_S}*error|gateway{_S}*error|codex{_S}*error)(?:{_S}+\\d{{3}})?"
    f"[:{JS_SPACE_CLASS}-]+",
    re.ASCII | re.IGNORECASE,
)
_HTTP_STATUS_CODE_PREFIX_RE = re.compile(
    f"^(?:http{_S}*)?(\\d{{3}})(?:(?:{_S}*:{_S}*|{_S}+)([\\s\\S]+))?\\Z",
    re.ASCII | re.IGNORECASE,
)
_PROVIDER_ERROR_PREFIX_RE = re.compile(
    f"^(?:provider{_S}+)?(?:api|llm|model|openai|anthropic|codex|gateway){_S}+"
    f"(?:request{_S}+)?(?:error|failed|failure)\\b",
    re.ASCII | re.IGNORECASE,
)
_PROVIDER_ERROR_DETAIL_RE = re.compile(
    r"\b(?:insufficient[_ -]?quota|quota (?:exceeded|exhausted)|exceeded your current quota"
    r"|payment required|insufficient credits|credit balance|insufficient[_ -]?(?:balance|funds)"
    r"|rate[_ -]?limit(?:ed)?|too many requests|invalid[_ -]?api[_ -]?key|incorrect api key"
    r"|authentication failed|oauth token refresh failed|missing (?:token|projectid|credentials)"
    r"|google cloud credentials|re-?authenticate|unauthorized|forbidden|permission_error"
    r"|billing hard limit|spend(?:ing)? limit)\b",
    re.ASCII | re.IGNORECASE,
)
_SLUG_DISALLOWED_RE = re.compile(r"[^a-z0-9-]")
_SLUG_DASH_RUN_RE = re.compile(r"-+")
_SLUG_EDGE_DASHES_RE = re.compile(r"^-+|-+\Z")


def build_session_memory_slug_prompt(session_content: str) -> str:
    """The slug prompt of ``generateSlugViaLLM`` (llm-slug-generator.ts:88-93), verbatim.

    At most the first 2000 UTF-16 units are included (``truncateUtf16Safe``: a cut never splits a surrogate pair).
    """
    excerpt = truncate_utf16_safe(session_content, SLUG_PROMPT_SESSION_CONTENT_MAX_CHARS)
    return (
        "Based on this conversation, generate a short 1-2 word filename slug (lowercase, "
        "hyphen-separated, no file extension).\n"
        "\n"
        "Conversation summary:\n"
        f"{excerpt}\n"
        "\n"
        'Reply with ONLY the slug, nothing else. Examples: "vendor-pitch", "api-design", '
        '"bug-fix"'
    )


def normalize_session_memory_slug(text: str) -> str | None:
    """Slug cleanup of ``generateSlugViaLLM`` (llm-slug-generator.ts:128-136).

    Lower-cases the trimmed reply, maps every character outside ``[a-z0-9-]``
    to ``-``, collapses and trims dashes, and keeps at most 30 characters.
    """
    slug = js_trim(text).lower()
    slug = _SLUG_DISALLOWED_RE.sub("-", slug)
    slug = _SLUG_DASH_RUN_RE.sub("-", slug)
    slug = _SLUG_EDGE_DASHES_RE.sub("", slug)
    slug = _SLUG_EDGE_DASHES_RE.sub("", slug[:SLUG_MAX_CHARS])
    return slug or None


def _is_error_payload_object(payload: object) -> bool:
    """``isErrorPayloadObject`` (assistant-error-format.ts:37-67)."""
    if not isinstance(payload, Mapping):
        return False
    if payload.get("type") == "error":
        return True
    if isinstance(payload.get("request_id"), str) or isinstance(payload.get("requestId"), str):
        return True
    if "error" in payload:
        error = payload["error"]
        if isinstance(error, Mapping) and any(
            isinstance(error.get(key), str) for key in ("message", "type", "code")
        ):
            return True
        # Flat error payloads: {"error":"insufficient_balance","message":"..."}
        if isinstance(error, str) and isinstance(payload.get("message"), str):
            return True
    return False


def parse_api_error_payload(raw: str | None) -> dict[str, Any] | None:
    """Port of ``parseApiErrorPayload`` (assistant-error-format.ts:69-95)."""
    if not raw:
        return None
    trimmed = js_trim(raw)
    if not trimmed:
        return None
    candidates = [trimmed]
    if _ERROR_PAYLOAD_PREFIX_RE.match(trimmed):
        candidates.append(js_trim(_ERROR_PAYLOAD_PREFIX_RE.sub("", trimmed, count=1)))
    for candidate in candidates:
        if not candidate.startswith("{") or not candidate.endswith("}"):
            continue
        try:
            parsed = _parse_jsonl_row(candidate)
        except (ValueError, RecursionError):
            continue
        if _is_error_payload_object(parsed):
            return parsed
    return None


def extract_leading_http_status(raw: str) -> tuple[int, str] | None:
    """Port of ``extractLeadingHttpStatus`` (assistant-error-format.ts:97-107): (code, rest)."""
    match = _HTTP_STATUS_CODE_PREFIX_RE.match(raw)
    if match is None:
        return None
    return int(match.group(1)), js_trim(match.group(2) or "")


def is_error_slug_payload(payload: Mapping[str, Any] | None) -> bool:
    """Port of ``isErrorSlugPayload`` (llm-slug-generator.ts:39-68).

    A reply flagged ``isError``, an API error payload, a leading 401/402/403/429
    status (or 400 with an error detail) or provider error wording is not a slug.
    """
    if not payload:
        return False
    if payload.get("isError") is True:
        return True
    text = payload.get("text")
    text = js_trim(text) if isinstance(text, str) else None
    if not text:
        return False
    if parse_api_error_payload(text):
        return True
    status = extract_leading_http_status(text)
    if status is not None:
        code, rest = status
        if code in (401, 402, 403, 429):
            return True
        if code == 400 and (
            parse_api_error_payload(rest)
            or _PROVIDER_ERROR_PREFIX_RE.match(rest)
            or _PROVIDER_ERROR_DETAIL_RE.search(rest)
        ):
            return True
    return bool(_PROVIDER_ERROR_PREFIX_RE.match(text) or _PROVIDER_ERROR_DETAIL_RE.search(text))


def generate_session_memory_slug(session_content: str, generator: SlugGenerator) -> str | None:
    """Port of ``generateSlugViaLLM`` (llm-slug-generator.ts:73-155) around a host model call.

    ``generator`` receives the verbatim prompt and returns the model's reply
    (text, or a ``{"text", "isError"}`` payload like upstream's first run
    payload). Errors raised by the generator, error replies and replies that
    normalize to nothing give ``None``, so the caller falls back to the
    timestamp slug.
    """
    try:
        reply = generator(build_session_memory_slug_prompt(session_content))
    except Exception:  # upstream logs "Failed to generate slug" and returns null
        return None
    payload = {"text": reply} if isinstance(reply, str) else reply
    if not isinstance(payload, Mapping):
        return None
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        return None
    if is_error_slug_payload(payload):
        return None
    return normalize_session_memory_slug(text)


# --- the hook (handler.ts) -----------------------------------------------------------------

SESSION_MEMORY_EVENT_TYPE = "command"
SESSION_MEMORY_ACTIONS = ("new", "reset")
# Automatic rollover (``session`` / ``auto-reset`` with reason daily or idle,
# session-auto-reset.ts isSessionAutoResetReason).
SESSION_MEMORY_AUTO_RESET_EVENT_TYPE = "session"
SESSION_MEMORY_AUTO_RESET_ACTION = "auto-reset"
SESSION_MEMORY_AUTO_RESET_REASONS = ("daily", "idle")
# Names this module writes: memory/YYYY-MM-DD-<slug>.md with a timestamp (HHMM) or
# normalized LLM slug and an optional -N suffix. The daily-flush validator
# (memory_core.workspace.DAILY_MEMORY_PATH_RE) keeps rejecting these names.
SESSION_MEMORY_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md\Z", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
# Filesystems without hard links: create the file in place instead.
_NO_HARD_LINK_ERRNOS = frozenset(
    code
    for code in (
        getattr(errno, name, None)
        for name in ("EPERM", "ENOTSUP", "EOPNOTSUPP", "ENOSYS", "EMLINK", "EXDEV")
    )
    if code is not None
)


def is_session_memory_trigger(event_type: str, action: str, reason: object = None) -> bool:
    """The hook's gate (handler.ts ``saveSessionToMemory``).

    ``command`` events for ``/new`` and ``/reset``, and ``session`` /
    ``auto-reset`` events whose ``reason`` is ``daily`` or ``idle`` (additive
    argument, default ``None``: the old two-argument call keeps its meaning).
    """
    if event_type == SESSION_MEMORY_EVENT_TYPE and action in SESSION_MEMORY_ACTIONS:
        return True
    return (
        event_type == SESSION_MEMORY_AUTO_RESET_EVENT_TYPE
        and action == SESSION_MEMORY_AUTO_RESET_ACTION
        and reason in SESSION_MEMORY_AUTO_RESET_REASONS
    )


def resolve_session_memory_message_count(value: object) -> int | float:
    """``hooks.internal.entries["session-memory"].messages`` rule (handler.ts:207-212).

    A positive number is used as given (fractions are floored; infinity is not
    finite and projects nothing, like upstream's ``Number.isFinite`` guard);
    anything else is 15.
    """
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_SESSION_MEMORY_MESSAGE_COUNT


@dataclass(frozen=True)
class SessionTimestamp:
    """``formatLocalSessionTimestamp`` result: ``YYYY-MM-DD``, ``HH:MM:SS``, ``HHMM``."""

    date: str
    time: str
    time_slug: str
    time_zone_name: str | None  # the resolved zone as written in the heading (v2026.9.6)


def _resolve_timezone(timezone: str) -> tuple[str, ZoneInfo]:
    name = js_trim(timezone) if isinstance(timezone, str) else ""
    try:
        return name, ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {timezone!r}") from exc


def format_local_session_timestamp(
    now_ms: int | float, timezone: str = "UTC"
) -> SessionTimestamp:
    """Port of ``formatLocalSessionTimestamp`` (handler.ts:31-86).

    Upstream formats with ``Intl.DateTimeFormat("en-US")`` in the user timezone
    (``resolveUserTimezone``: h23). Deviation: the zone is an explicit IANA name
    (default UTC) and an unknown zone raises, where upstream falls back to the
    host zone. At v2026.9.6 the heading carries that zone name itself
    (``time_zone_name``), no longer ICU's short name (``EST``, ``GMT+3``).
    """
    zone_name, zone = _resolve_timezone(timezone)
    if isinstance(now_ms, bool) or not isinstance(now_ms, int | float) or not math.isfinite(now_ms):
        raise ValueError(f"invalid timestamp: {now_ms!r}")
    try:
        local = (_EPOCH + timedelta(milliseconds=math.trunc(now_ms))).astimezone(zone)
    except OverflowError as exc:
        raise ValueError(f"invalid timestamp: {now_ms!r}") from exc
    hour, minute = f"{local.hour:02d}", f"{local.minute:02d}"
    return SessionTimestamp(
        date=f"{local.year}-{local.month:02d}-{local.day:02d}",
        time=f"{hour}:{minute}:{local.second:02d}",
        time_slug=f"{hour}{minute}",
        time_zone_name=zone_name or None,
    )


def resolve_available_memory_filename(
    memory_dir: str | os.PathLike[str], date_str: str, slug: str
) -> str:
    """Port of ``resolveAvailableMemoryFilename`` (handler.ts:88-108).

    ``<date>-<slug>.md``, then ``-2``, ``-3``... while the name is taken.
    Deviation (stricter): any directory entry takes the name, a dangling
    symlink included; upstream's ``fs.access`` follows symlinks, so it treats a
    dangling one as free and its write then replaces the link.
    """
    basename = f"{date_str}-{slug}"
    suffix = 1
    while True:
        filename = f"{basename}.md" if suffix == 1 else f"{basename}-{suffix}.md"
        if not os.path.lexists(os.path.join(os.fspath(memory_dir), filename)):
            return filename
        suffix += 1


def build_session_memory_entry(
    *,
    timestamp: SessionTimestamp,
    session_key: str,
    session_id: str | None,
    source: str | None = None,
    session_content: str | None,
    reason: str | None = None,
    event_type: str = SESSION_MEMORY_EVENT_TYPE,
    unavailable_reason: str | None = None,
) -> str:
    """The Markdown entry of the hook (handler.ts ``saveSessionMemoryNow``), verbatim.

    The boundary line is ``- **Reason**`` for a ``session`` event and
    ``- **Source**`` otherwise. ``## Conversation Summary`` is present with
    content, or with the quoted ``unavailable_reason`` (the host could not read
    the transcript); the entry ends with a newline.
    """
    time_zone_suffix = f" {timestamp.time_zone_name}" if timestamp.time_zone_name else ""
    boundary = (
        f"- **Reason**: {reason or 'unknown'}"
        if event_type == SESSION_MEMORY_AUTO_RESET_EVENT_TYPE
        else f"- **Source**: {source or 'unknown'}"
    )
    parts = [
        f"# Session: {timestamp.date} {timestamp.time}{time_zone_suffix}",
        "",
        f"- **Session Key**: {session_key}",
        f"- **Session ID**: {session_id or 'unknown'}",
        boundary,
        "",
    ]
    if unavailable_reason is not None:
        parts.extend(
            [
                "## Conversation Summary",
                "",
                f"> Transcript content was unavailable: {json.dumps(unavailable_reason, ensure_ascii=False)}",
                "",
            ]
        )
    elif session_content:
        parts.extend(["## Conversation Summary", "", session_content, ""])
    return "\n".join(parts)


@dataclass(frozen=True)
class SessionMemoryResult:
    """What ``save_session_memory`` wrote."""

    path: Path
    rel_path: str
    slug: str
    llm_slug: bool
    session_file: str | None
    session_content: str | None
    entry: str
    origin_class: str = "agent"


def _memory_dir(workspace_dir: str) -> Path:
    root = Path(workspace_dir)
    memory_dir = root / "memory"
    os.makedirs(memory_dir, exist_ok=True)
    resolved_root = root.resolve()
    resolved = memory_dir.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise UnsafeMemoryPathError("memory directory escapes the workspace")
    if not resolved.is_dir():
        raise UnsafeMemoryPathError("memory path is not a directory")
    return resolved


def _fsync_directory(directory: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


_EXCLUSIVE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


def _create_exclusive(path: Path, data: bytes) -> bool:
    try:
        fd = os.open(path, _EXCLUSIVE_FLAGS, 0o666)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _publish_new_file(memory_dir: Path, filename: str, data: bytes) -> bool:
    """Write ``memory_dir/filename`` only if no entry has that name; ``False`` if taken.

    The content goes to a temporary file first and is published with a hard
    link, which fails instead of replacing an existing entry, so a complete
    file appears atomically and nothing is ever overwritten or followed.
    """
    temporary = memory_dir / f".{filename}.{secrets.token_hex(6)}.tmp"
    if not _create_exclusive(temporary, data):
        raise FileExistsError(temporary)
    try:
        try:
            os.link(temporary, memory_dir / filename)
        except FileExistsError:
            return False
        except OSError as exc:
            if exc.errno not in _NO_HARD_LINK_ERRNOS:
                raise
            if not _create_exclusive(memory_dir / filename, data):
                return False
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
    _fsync_directory(memory_dir)
    return True


class _SessionMemoryNameCollision(FileExistsError):
    """Rollback a reserved trust record before retrying exclusive publication."""


def _write_session_memory_file(
    memory_dir: Path, date_str: str, slug: str, entry: str,
    provenance: MemoryWriteProvenanceObserver | None = None,
) -> str:
    data = js_utf8_encode(entry)
    while True:
        filename = resolve_available_memory_filename(memory_dir, date_str, slug)
        if SESSION_MEMORY_FILE_RE.match(filename) is None:
            raise UnsafeMemoryPathError(f"not a session memory file name: memory/{filename}")
        def commit() -> None:
            if not _publish_new_file(memory_dir, filename, data):
                raise _SessionMemoryNameCollision(filename)

        try:
            if provenance is None:
                commit()
            else:
                provenance.write(
                    absolute_path=memory_dir / filename,
                    content_before="",
                    content_after=entry,
                    commit=commit,
                )
        except _SessionMemoryNameCollision:
            continue
        return filename


def save_session_memory(
    workspace_dir: str | os.PathLike[str],
    *,
    session_key: str,
    session_id: str | None = None,
    events: Iterable[object] | None = None,
    session_file: str | os.PathLike[str] | None = None,
    messages: Iterable[object] | None = None,
    source: str | None = None,
    event_type: str = SESSION_MEMORY_EVENT_TYPE,
    reason: str | None = None,
    unavailable_reason: str | None = None,
    now_ms: int | float | None = None,
    timezone: str = "UTC",
    message_count: object = DEFAULT_SESSION_MEMORY_MESSAGE_COUNT,
    slug_generator: SlugGenerator | None = None,
    redactor: Callable[[str], str] | None = None,
    artifact_provenance: MemoryArtifactProvenanceStore | None = None,
) -> SessionMemoryResult:
    """Port of the session-memory hook's save (``saveSessionMemoryNow``, handler.ts).

    Call it when the host handles ``/new``, ``/reset`` or an automatic
    rollover (``is_session_memory_trigger``), with the session that is ending.

    With ``artifact_provenance``, reserve the projection's trust record before publishing
    the new file, like the upstream hook. A failed write or a filename collision rolls the
    reservation back; a trust-store error prevents publication. Without a store the file
    is written untracked, as before.

    The conversation comes from ``events``: the host-supplied transcript events
    of the ending session (dicts with ``type: "message"`` and a ``message``;
    leaf controls pick the active branch). Upstream v2026.9.6 reads them from
    its per-agent SQLite store (``captureSessionMemoryTranscript``), which
    memory-core does not couple to: the host owns storage. ``messages`` (plain
    message dicts) and ``session_file`` (a JSONL path; legacy input, the
    file-era runtime is gone upstream, including the ``.reset.`` recovery) are
    convenience inputs that feed the same projection; pass at most one of the
    three. ``unavailable_reason`` records that the host could not read the
    transcript (upstream's ``unavailable`` capture status).

    Writes a new ``memory/<date>-<slug>.md`` with the heading (the zone name),
    session key, id and ``Source`` (or ``Reason`` for ``event_type="session"``),
    and the last ``message_count`` rows as ``role: <JSON string>`` lines
    (``get_recent_session_projection_from_events``). The slug is the local
    ``HHMM`` unless ``slug_generator`` (off by default, upstream ``llmSlug``)
    yields one; like upstream it is only asked for a non-blank ``session_id``
    and non-empty content.

    ``session_key`` is written as given; upstream shows it re-keyed to the
    agent that owns the workspace (``resolveDisplaySessionKey``), which needs
    OpenClaw's agent config, so the host passes the key it wants shown. Not
    ported: the memory-write provenance record (``SessionMemoryResult.
    origin_class`` carries the capture's trust class for the host), and the
    ``context.agentId`` requirement (the host owns agent scoping).

    Deviation by choice: ``redactor`` (default ``None`` = upstream behaviour)
    maps each selected ``role: text`` line before it is written or sent to the
    slug generator; a line it maps to blank is dropped. Without it the file
    holds the raw recent lines, like upstream.

    Upstream runs the save in the background and logs failures; here errors
    propagate to the caller (``ValueError`` for an unknown zone or timestamp,
    ``UnsafeMemoryPathError`` for a ``memory/`` outside the workspace,
    ``OSError`` from the filesystem). Generator failures still fall back to the
    timestamp slug.
    """
    if sum(item is not None for item in (events, session_file, messages)) > 1:
        raise ValueError("pass at most one of events, session_file and messages")
    if not isinstance(session_key, str):
        raise TypeError("session_key must be a string")
    count = resolve_session_memory_message_count(message_count)
    timestamp_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    timestamp = format_local_session_timestamp(timestamp_ms, timezone)
    root = os.fspath(workspace_dir)
    memory_dir = _memory_dir(root)

    resolved_file: str | None = None
    projection: SessionMemoryProjection | None = None
    if session_file is not None:
        resolved_file = os.fspath(session_file) or None
        file_events = _read_session_file_entries(resolved_file) if resolved_file else None
        if file_events is not None:
            events = file_events
    elif messages is not None:
        events = _entries_from_messages(list(messages))
    if events is not None:
        projection = get_recent_session_projection_from_events(
            capture_session_memory_events(list(events)), count
        )
    lines = projection.content.split("\n") if projection is not None else None
    origin_class = projection.origin_class if projection is not None else "agent"
    if redactor is not None and lines:
        redacted = [redactor(line) for line in lines]
        if not all(isinstance(line, str) for line in redacted):
            raise TypeError("redactor must return a string")
        lines = [line for line in redacted if js_trim(line)]
    session_content = "\n".join(lines) if lines else None

    llm_slug = (
        generate_session_memory_slug(session_content, slug_generator)
        if session_content
        and slug_generator is not None
        and isinstance(session_id, str)
        and js_trim(session_id)
        else None
    )
    slug = llm_slug or timestamp.time_slug
    entry = build_session_memory_entry(
        timestamp=timestamp,
        session_key=session_key,
        session_id=session_id,
        source=source,
        session_content=session_content,
        reason=reason,
        event_type=event_type,
        unavailable_reason=unavailable_reason,
    )
    # handler.ts:253-271 reserves the captured projection's trust before exposing the file.
    # Our exclusive publication retries also roll back that reservation on a name collision.
    provenance = None if artifact_provenance is None else MemoryWriteProvenanceObserver(
        store=artifact_provenance,
        mutation_root=root,
        workspace_dir=root,
        resolve_origin_class=lambda: origin_class,
        session_id=session_id,
        session_key=session_key,
        now=lambda: int(timestamp_ms),
    )
    filename = _write_session_memory_file(memory_dir, timestamp.date, slug, entry, provenance)
    return SessionMemoryResult(
        path=memory_dir / filename,
        rel_path=f"memory/{filename}",
        slug=slug,
        llm_slug=llm_slug is not None,
        session_file=resolved_file,
        session_content=session_content,
        entry=entry,
        origin_class=origin_class,
    )
