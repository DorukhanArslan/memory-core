"""Session corpus entry builder: ``buildSessionEntry`` over host-supplied transcript events.

Port of ``packages/memory-host-sdk/src/host/session-files.ts`` at v2026.9.6
(``buildSessionEntryInProcess``, ``sanitizeSessionText``, ``splitLongSessionLine``,
``hashSessionEntrySnapshot``) with ``stripInboundMetadata``
(``src/auto-reply/reply/strip-inbound-meta.ts``), ``isExecCompletionEvent``
(``src/infra/heartbeat-events-filter.ts``) and ``resolveSessionResetRecallCutoff``.

Storage (plan decision 4): upstream reads SQLite snapshots; memory-core does not couple to
that schema, so the host passes the transcript events (or a JSONL text, whose line ordinals
become ``line_map`` like upstream's archive branch). Deviations, by design:

- ``redact_text`` is a host hook (default: no redaction). Upstream redacts every exported text
  with ``redactSensitiveText(text, {mode: "tools"})`` (``src/logging/redact.ts``, a 1600-line
  pattern set plus a secret registry); that is not ported (gap R13).
- ``stripInternalRuntimeContext`` is the memory-core helper of ``replay_history`` (the
  memory-core and OpenClaw runtime identities), not upstream's full legacy-format stripper.
- The session key classification (dreaming narrative, cron run) needs the key from the host's
  store; ``normalizeSessionKeyPreservingOpaquePeerIds`` is approximated by trim + lower-case.
- ``Date.parse`` of string timestamps accepts ISO-8601 forms only (and ``YYYY-MM-DD HH:MM``
  with a space); other legacy formats count as unknown (0).
- Not ported: the worker offload, archive/incognito path handling, store classification from
  files, transcript stats and the cold-storage restore.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any

from memory_core.bootstrap._js import (
    JS_SPACE_CLASS,
    _from_units,
    _units,
    js_json_stringify,
    js_trim,
    js_utf8_encode,
    reject_json_constant,
    utf16_len,
)
from memory_core.heartbeat import (
    HEARTBEAT_PROMPT,
    HEARTBEAT_TOKEN,
    MESSAGE_TOOL_DELIVERY_HINTS,
    is_heartbeat_user_message,
    is_silent_reply_payload_text,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_memory import (
    _has_inter_session_user_provenance,
    classify_session_message_origin,
)

SESSION_EXPORT_CONTENT_WRAP_CHARS = 800
MAX_DATE_TIMESTAMP_MS = 8_640_000_000_000_000
DREAMING_NARRATIVE_RUN_PREFIX = "dreaming-narrative-"
INBOUND_CONTEXT_MARKER = "⟦openclaw:ctx⟧"

_S = f"[{JS_SPACE_CLASS}]"
_DIRECT_CRON_PROMPT_RE = re.compile(f"^\\[cron:[^\\]]+\\]{_S}*")
_GENERATED_SYSTEM_MESSAGE_RE = re.compile(f"^System(?: \\(untrusted\\))?: \\[[^\\]]+\\]{_S}*")
_NEWLINE_RUN_RE = re.compile(f"{_S}*\n+{_S}*")
_WHITESPACE_RUN_RE = re.compile(f"{_S}+")
_STRUCTURED_EXEC_RE = re.compile(
    r"^exec (completed|failed) \(([a-z0-9_-]{1,64}), (code -?[0-9]+|signal [^)]+)\)(?: :: ([\s\S]*))?\Z",
    re.IGNORECASE | re.ASCII,
)
_CRON_REST_RE = re.compile(r"^cron:[^:]+:run:[^:]+(?::|$)")


# --- stripInboundMetadata ------------------------------------------------------------------

_LEADING_TIMESTAMP_RE = re.compile(
    r"^\[[A-Za-z]{3} [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}[^\]]*\] *"
)
_CHANNEL_CONTEXT_HEADER = f"Context: {INBOUND_CONTEXT_MARKER}"
_ACTIVE_MEMORY_CONTEXT_HEADER = "Context:"
_ACTIVE_MEMORY_OPEN = "<active_memory_plugin>"
_ACTIVE_MEMORY_CLOSE = "</active_memory_plugin>"
_METADATA_TOKENS_RE = re.compile(
    "|".join(re.escape(token) for token in (INBOUND_CONTEXT_MARKER, *MESSAGE_TOOL_DELIVERY_HINTS))
)
# JS /^[ \t]*Context:[ \t]*$/m: ^ and $ also break at \r, U+2028 and U+2029, not only \n.
_BARE_CONTEXT_LINE_RE = re.compile(
    r"(?<![^\n\r\u2028\u2029])[ \t]*Context:[ \t]*(?![^\n\r\u2028\u2029])"
)


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    next: int
    trimmed: str


def _read_line(text: str, start: int) -> _Line | None:
    if start > len(text):
        return None
    newline = text.find("\n", start)
    end = len(text) if newline < 0 else newline
    return _Line(start, end, end + 1, js_trim(text[start:end]))


def _find_line(text: str, value: str, frm: int = 0) -> _Line | None:
    index = text.find(value, frm)
    while index >= 0:
        start = text.rfind("\n", 0, index) + 1
        line = _read_line(text, start)
        assert line is not None
        if line.trimmed == value:
            return line
        index = text.find(value, line.next)
    return None


def _skip_empty_lines(text: str, start: int, trimmed: bool = True) -> int:
    nxt = start
    line = _read_line(text, nxt)
    while line is not None and (line.trimmed == "" if trimmed else line.start == line.end):
        nxt = line.next
        line = _read_line(text, nxt)
    return nxt


def _has_sentinel(text: str) -> bool:
    return (
        INBOUND_CONTEXT_MARKER in text
        or any(hint in text for hint in MESSAGE_TOOL_DELIVERY_HINTS)
        or (_ACTIVE_MEMORY_CONTEXT_HEADER in text and _BARE_CONTEXT_LINE_RE.search(text) is not None)
    )


def _metadata_block_end(text: str, header: _Line) -> int:
    line = _read_line(text, header.next)
    if line is not None and line.trimmed == "```json":
        closing = _find_line(text, "```", line.next)
        return closing.next if closing is not None else len(text) + 1
    while line is not None and line.trimmed != "":
        line = _read_line(text, line.next)
    return _skip_empty_lines(text, line.start if line is not None else len(text) + 1)


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for span_start, span_next in spans:
        start = span_start - 1 if span_next > len(text) and span_start > 0 else span_start
        parts.append(text[cursor : max(cursor, start)])
        cursor = span_next
    parts.append(text[cursor:])
    return "".join(parts)


def _strip_active_memory_blocks(text: str) -> str:
    if _ACTIVE_MEMORY_OPEN not in text:
        return text
    spans: list[tuple[int, int]] = []
    header = _find_line(text, _ACTIVE_MEMORY_CONTEXT_HEADER)
    while header is not None:
        opening = _read_line(text, header.next)
        closing = (
            _find_line(text, _ACTIVE_MEMORY_CLOSE, opening.next)
            if opening is not None and opening.trimmed == _ACTIVE_MEMORY_OPEN
            else None
        )
        nxt = _skip_empty_lines(text, closing.next) if closing is not None else header.next
        if closing is not None:
            spans.append((header.start, nxt))
        header = _find_line(text, _ACTIVE_MEMORY_CONTEXT_HEADER, nxt)
    return _remove_spans(text, spans)


def strip_inbound_metadata(text: str) -> str:
    """Port of ``stripInboundMetadata``: removes injected inbound context blocks."""
    without_timestamp = _LEADING_TIMESTAMP_RE.sub("", text, count=1)
    if not _has_sentinel(without_timestamp):
        return without_timestamp
    source = _strip_active_memory_blocks(without_timestamp)
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        match = _METADATA_TOKENS_RE.search(source, pos)
        if match is None:
            break
        start = source.rfind("\n", 0, match.start()) + 1
        line = _read_line(source, start)
        assert line is not None
        pos = line.next
        if line.trimmed == _CHANNEL_CONTEXT_HEADER:
            spans.append((start, len(source) + 1))
            break
        if len(line.trimmed) > len(INBOUND_CONTEXT_MARKER) and line.trimmed.endswith(
            INBOUND_CONTEXT_MARKER
        ):
            pos = _metadata_block_end(source, line)
            spans.append((start, pos))
        elif line.trimmed in MESSAGE_TOOL_DELIVERY_HINTS:
            spans.append((start, line.next))
    result = _remove_spans(source, spans)
    result = re.sub(r"^\n+", "", result)
    result = re.sub(r"\n+\Z", "", result)
    return _LEADING_TIMESTAMP_RE.sub("", result, count=1)


def is_exec_completion_event(evt: str) -> bool:
    """Port of ``isExecCompletionEvent`` (heartbeat-events-filter.ts)."""
    trimmed = re.sub(f"^{_S}+", "", evt)
    normalized = trimmed.lower()
    return (
        re.match(f"^exec finished(?::|{_S}*\\()", normalized, re.ASCII) is not None
        or _STRUCTURED_EXEC_RE.match(trimmed) is not None
    )


# --- text sanitising and wrapping ------------------------------------------------------------


def normalize_session_text(value: str) -> str:
    return js_trim(_WHITESPACE_RUN_RE.sub(" ", _NEWLINE_RUN_RE.sub(" ", value)))


def _collect_raw_session_text(content: object) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list | tuple):
        return None
    parts = [
        block["text"]
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    return "\n".join(parts) if parts else None


def split_long_session_line(
    text: str, max_chars: int = SESSION_EXPORT_CONTENT_WRAP_CHARS
) -> list[str]:
    """Port of ``splitLongSessionLine``; lengths and cuts are in UTF-16 units."""
    normalized = js_trim(text)
    if not normalized:
        return []
    if utf16_len(normalized) <= max_chars:
        return [normalized]
    # One str character per UTF-16 unit (astral characters become surrogate pairs).
    units = "".join(chr(u) for u in _unit_values(normalized))
    n = len(units)
    segments: list[str] = []
    cursor = 0
    while cursor < n:
        if n - cursor <= max_chars:
            segments.append(js_trim(units[cursor:]))
            break
        limit = cursor + max_chars
        split_at = limit
        for index in range(limit, cursor, -1):
            if index < n and units[index] == " ":
                split_at = index
                break
        if (
            cursor < split_at < n
            and "\ud800" <= units[split_at - 1] <= "\udbff"
            and "\udc00" <= units[split_at] <= "\udfff"
        ):
            split_at -= 1
        segments.append(js_trim(units[cursor:split_at]))
        cursor = split_at
        while cursor < n and units[cursor] == " ":
            cursor += 1
    return [_from_units(_units(segment)) for segment in segments if segment]


def _unit_values(value: str) -> list[int]:
    data = _units(value)
    return [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]


def sanitize_session_text(
    text: str,
    role: str,
    *,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
    strip_runtime_context: Callable[[str], str] | None = None,
) -> str | None:
    """Port of ``sanitizeSessionText`` (session-files.ts)."""
    stripped = strip_inbound_metadata(text) if role == "user" else text
    stripper = strip_runtime_context or _default_strip_runtime_context
    normalized = normalize_session_text(stripper(stripped))
    if not normalized:
        return None
    if role == "user" and (
        _GENERATED_SYSTEM_MESSAGE_RE.match(normalized)
        or _DIRECT_CRON_PROMPT_RE.match(normalized)
        or is_heartbeat_user_message(
            {"role": role, "content": normalized}, HEARTBEAT_PROMPT, runtime_identity=runtime_identity
        )
    ):
        return None
    if is_silent_reply_payload_text(normalized):
        return None
    if role == "assistant" and normalized == HEARTBEAT_TOKEN:
        return None
    without_envelope = js_trim(_GENERATED_SYSTEM_MESSAGE_RE.sub("", normalized, count=1))
    if is_exec_completion_event(without_envelope):
        return None
    return normalized


def _default_strip_runtime_context(text: str) -> str:
    from memory_core.replay_history import _strip_runtime_context_and_preface

    return _strip_runtime_context_and_preface(text)


# --- classification helpers ------------------------------------------------------------------


def is_dreaming_narrative_session_store_key(session_key: str) -> bool:
    trimmed = js_trim(session_key)
    if not trimmed:
        return False
    first = trimmed.find(":")
    if first < 0:
        return trimmed.startswith(DREAMING_NARRATIVE_RUN_PREFIX)
    second = trimmed.find(":", first + 1)
    segment = trimmed if second < 0 else trimmed[second + 1 :]
    return segment.startswith(DREAMING_NARRATIVE_RUN_PREFIX)


def is_cron_run_session_key(session_key: str | None) -> bool:
    """``isCronRunSessionKey`` (key normalised by trim + lower-case, see module doc)."""
    if not isinstance(session_key, str):
        return False
    key = js_trim(session_key).lower()
    if not key.startswith("agent:"):
        return False
    end = key.find(":", 6)
    if end == -1:
        return False
    agent_id, rest = js_trim(key[6:end]), key[end + 1 :]
    if not agent_id or not rest or rest.startswith(":"):
        return False
    return _CRON_REST_RE.match(rest) is not None


def _record(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _has_dreaming_identity(value: object) -> bool:
    return isinstance(value, str) and is_dreaming_narrative_session_store_key(value)


def _is_dreaming_generated_record(record: object) -> bool:
    candidate = _record(record)
    if candidate is None:
        return False
    data = _record(candidate.get("data"))
    if (
        candidate.get("type") == "custom"
        and candidate.get("customType") == "openclaw:bootstrap-context:full"
        and data is not None
        and isinstance(data.get("runId"), str)
        and data["runId"].startswith(DREAMING_NARRATIVE_RUN_PREFIX)
    ):
        return True
    message = _record(candidate.get("message")) if candidate.get("type") == "message" else None
    metadata = _record(message.get("__openclaw")) if message is not None else None
    return (
        _has_dreaming_identity(candidate.get("runId"))
        or _has_dreaming_identity(candidate.get("sessionKey"))
        or (data is not None and _has_dreaming_identity(data.get("runId")))
        or (data is not None and _has_dreaming_identity(data.get("sessionKey")))
        or (
            message is not None
            and message.get("role") in ("assistant", "toolResult")
            and metadata is not None
            and _has_dreaming_identity(metadata.get("runId"))
        )
    )


def _is_cron_generated_record(record: object) -> bool:
    candidate = _record(record)
    if candidate is None:
        return False
    data = _record(candidate.get("data"))
    return is_cron_run_session_key(candidate.get("sessionKey")) or (
        data is not None and is_cron_run_session_key(data.get("sessionKey"))
    )


def _is_recalled_memory_message(message: Mapping[str, Any]) -> bool:
    provenance = _record(message.get("provenance"))
    return (
        provenance is not None
        and provenance.get("kind") == "internal_system"
        and provenance.get("sourceTool") in ("memory_search", "memory_get")
    )


_ISO_RE = re.compile(
    r"^([+-][0-9]{6}|[0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?"
    r"(?:[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:[.,]([0-9]+))?)?)?"
    r"(Z|[+-][0-9]{2}:?[0-9]{2})?\Z",
    re.ASCII,
)


def js_date_parse(value: str) -> float:
    """``Date.parse`` for ISO-8601 strings; ``nan`` otherwise (see module doc)."""
    match = _ISO_RE.match(js_trim(value))
    if match is None:
        return math.nan
    year, month, day, hour, minute, second, frac, zone = match.groups()
    try:
        naive = datetime(
            int(year), int(month or 1), int(day or 1), int(hour or 0), int(minute or 0), int(second or 0)
        )
    except ValueError:
        return math.nan
    millis = int((frac or "0")[:3].ljust(3, "0"))
    if zone is not None:
        if zone == "Z":
            offset = timedelta(0)
        else:
            sign = -1 if zone[0] == "-" else 1
            digits = zone[1:].replace(":", "")
            offset = sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        stamp = naive.replace(tzinfo=dt_timezone(offset))
    elif hour is None:
        stamp = naive.replace(tzinfo=dt_timezone.utc)  # date-only forms are UTC
    else:
        stamp = naive.astimezone()  # date-time without offset: host local time
        stamp = naive.replace(tzinfo=stamp.tzinfo)
    return math.floor(
        (stamp - datetime(1970, 1, 1, tzinfo=dt_timezone.utc)).total_seconds() * 1000
    ) + millis


def parse_session_timestamp_ms(record: Mapping[str, Any], message: Mapping[str, Any]) -> int:
    """``parseSessionTimestampMs``: message timestamp, then record timestamp; 0 if unknown."""
    for value in (message.get("timestamp"), record.get("timestamp")):
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value):
            ms = value * 1000 if 0 < value < 1e11 else value
            if math.isfinite(ms) and 0 < ms <= MAX_DATE_TIMESTAMP_MS:
                return math.floor(ms)
        if isinstance(value, str):
            parsed = js_date_parse(value)
            if math.isfinite(parsed) and parsed > 0:
                return int(parsed)
    return 0


def resolve_session_reset_recall_cutoff(events: list[Any]) -> dict[str, Any]:
    """Port of ``resolveSessionResetRecallCutoff`` (session-reset-recall.ts)."""
    reset_index = -1
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if isinstance(event, Mapping) and event.get("type") == "reset":
            reset_index = index
            break
    if reset_index < 0:
        return {"state": "absent"}
    reset = events[reset_index]
    if "firstKeptEntryId" not in reset:
        return {"state": "valid", "cutoffLine": reset_index + 1}
    kept_id = reset["firstKeptEntryId"]
    if not isinstance(kept_id, str) or not js_trim(kept_id):
        return {"state": "invalid"}
    for index in range(reset_index):
        event = events[index]
        event_id = event.get("id") if isinstance(event, Mapping) else None
        if isinstance(event_id, str) and js_trim(event_id) and event_id == kept_id:
            return {"state": "valid", "cutoffLine": index + 1}
    return {"state": "invalid"}


# --- the entry -------------------------------------------------------------------------------


@dataclass
class SessionEntry:
    """``SessionFileEntry`` without the path fields (the host owns them)."""

    content: str
    line_map: list[int]
    message_timestamps_ms: list[int]
    line_provenance: list[dict[str, Any]]
    hash: str
    session_kind: str
    reset_recall_cutoff: dict[str, Any]
    generated_by_dreaming_narrative: bool = False
    generated_by_cron_run: bool = False
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)


def hash_session_entry_snapshot(
    content: str,
    line_map: list[int],
    message_timestamps_ms: list[int],
    line_provenance: list[dict[str, Any]],
    reset_recall_cutoff: Mapping[str, Any],
) -> str:
    """``hashSessionEntrySnapshot``: sha256 over content, line map, timestamps, provenance, cutoff."""
    digest = hashlib.sha256()
    digest.update(js_utf8_encode(content))
    digest.update(b"\n")
    digest.update(",".join(str(n) for n in line_map).encode())
    digest.update(b"\n")
    digest.update(",".join(str(n) for n in message_timestamps_ms).encode())
    digest.update(b"\n")
    digest.update(js_utf8_encode(js_json_stringify(line_provenance)))
    digest.update(b"\n")
    digest.update(js_json_stringify(dict(reset_recall_cutoff)).encode())
    return digest.hexdigest()


def parse_jsonl_records(text: str) -> list[tuple[int, Any]]:
    """Raw-line records of a JSONL transcript: ``(1-based line ordinal, value)``; blank and
    malformed lines are skipped but keep their ordinals (upstream's archive branch)."""
    import json

    records: list[tuple[int, Any]] = []
    for ordinal, line in enumerate(text.split("\n"), start=1):
        if not js_trim(line):
            continue
        try:
            records.append((ordinal, json.loads(line, parse_constant=reject_json_constant)))
        except (ValueError, RecursionError):
            continue
    return records


def build_session_entry(
    events: Iterable[object] | None = None,
    *,
    records: Iterable[tuple[int, Any]] | None = None,
    mtime_ms: float = 0,
    session_kind: str = "unknown",
    generated_by_dreaming_narrative: bool | None = None,
    generated_by_cron_run: bool | None = None,
    session_key: str | None = None,
    allow_record_cron_classification: bool = False,
    reset_recall_cutoff: Mapping[str, Any] | None = None,
    redact_text: Callable[[str], str] | None = None,
    on_transcript_message: Callable[[object, int], None] | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
    strip_runtime_context: Callable[[str], str] | None = None,
) -> SessionEntry:
    """Port of ``buildSessionEntryInProcess`` over transcript events supplied by the host.

    ``events`` are the transcript rows in order (``line_map`` is the 1-based event index, like
    upstream's SQLite branch); ``records`` gives explicit ``(line, value)`` pairs instead (see
    :func:`parse_jsonl_records`). ``session_key`` is the key of the host's store row (it
    classifies dreaming-narrative and cron-run sessions unless the flags are given);
    ``mtime_ms`` is the activity time used when a message has no timestamp.
    """
    if (events is None) == (records is None):
        raise ValueError("pass events or records")
    event_list = list(events) if events is not None else None
    pairs = (
        list(records)
        if records is not None
        else [(index + 1, event) for index, event in enumerate(event_list or [])]
    )
    if reset_recall_cutoff is None:
        reset_recall_cutoff = resolve_session_reset_recall_cutoff(
            event_list if event_list is not None else [value for _, value in pairs]
        )
    dreaming = (
        generated_by_dreaming_narrative
        if generated_by_dreaming_narrative is not None
        else bool(session_key and is_dreaming_narrative_session_store_key(session_key))
    )
    cron = (
        generated_by_cron_run
        if generated_by_cron_run is not None
        else bool(session_key and is_cron_run_session_key(session_key))
    )
    redact = redact_text or (lambda text: text)
    collected: list[str] = []
    line_map: list[int] = []
    timestamps: list[int] = []
    provenance: list[dict[str, Any]] = []
    inside_heartbeat = False
    inside_recalled = False
    turn_origin = "untrusted"
    for line_no, record in pairs:
        identifies_dreaming = not dreaming and _is_dreaming_generated_record(record)
        identifies_cron = (
            not cron and allow_record_cron_classification and _is_cron_generated_record(record)
        )
        if identifies_dreaming or identifies_cron:
            dreaming = dreaming or identifies_dreaming
            cron = cron or identifies_cron
            collected.clear()
            line_map.clear()
            timestamps.clear()
            provenance.clear()
        if not isinstance(record, Mapping) or record.get("type") != "message":
            continue
        message = record.get("message")
        if not isinstance(message, Mapping) or not isinstance(message.get("role"), str):
            continue
        role = message["role"]
        if role not in ("user", "assistant"):
            continue
        timestamp_ms = parse_session_timestamp_ms(record, message)
        observed_at = max(0, math.floor(timestamp_ms or mtime_ms))
        if on_transcript_message is not None:
            on_transcript_message(message, observed_at)
        input_provenance = _record(message.get("provenance"))
        if role == "user":
            inside_heartbeat = (
                input_provenance is not None
                and input_provenance.get("kind") == "internal_system"
                and input_provenance.get("sourceTool") == "heartbeat"
            )
            inside_recalled = _is_recalled_memory_message(message)
            turn_origin = classify_session_message_origin(message, turn_origin)
        if role == "user" and _has_inter_session_user_provenance(message):
            continue
        if inside_heartbeat or inside_recalled or dreaming or cron:
            continue
        raw_text = _collect_raw_session_text(message.get("content"))
        if raw_text is None:
            continue
        text = sanitize_session_text(
            raw_text, role, runtime_identity=runtime_identity, strip_runtime_context=strip_runtime_context
        )
        if not text:
            continue
        safe = redact(text)
        label = "User" if role == "user" else "Assistant"
        rendered = [f"{label}: {segment}" for segment in split_long_session_line(safe)]
        entry_provenance = {
            "originClass": classify_session_message_origin(message, turn_origin),
            "sessionKind": session_kind,
            "observedAt": observed_at,
        }
        collected.extend(rendered)
        line_map.extend(line_no for _ in rendered)
        timestamps.extend(timestamp_ms for _ in rendered)
        provenance.extend(dict(entry_provenance) for _ in rendered)
    content = "\n".join(collected)
    return SessionEntry(
        content=content,
        line_map=line_map,
        message_timestamps_ms=timestamps,
        line_provenance=provenance,
        hash=hash_session_entry_snapshot(content, line_map, timestamps, provenance, reset_recall_cutoff),
        session_kind=session_kind,
        reset_recall_cutoff=dict(reset_recall_cutoff),
        generated_by_dreaming_narrative=dreaming,
        generated_by_cron_run=cron,
    )


def matches_session_entry_prefix_hash(entry: SessionEntry, line_count: int, expected_hash: str) -> bool:
    """Port of ``matchesSessionEntryPrefixHash``."""
    lines = entry.content.split("\n") if entry.content else []
    if not isinstance(line_count, int) or line_count < 0 or line_count > len(lines):
        return False
    return (
        hash_session_entry_snapshot(
            "\n".join(lines[:line_count]),
            entry.line_map[:line_count],
            entry.message_timestamps_ms[:line_count],
            entry.line_provenance[:line_count],
            entry.reset_recall_cutoff,
        )
        == expected_hash
    )


