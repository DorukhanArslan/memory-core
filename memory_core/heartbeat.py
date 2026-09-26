"""Heartbeat turn inputs and output handling.

Port of the OpenClaw heartbeat surface at pin 4c42815348:

- constants and prompt resolution: ``src/auto-reply/heartbeat.ts:14-134`` and
  ``src/auto-reply/tokens.ts:5``; the brand-bearing transcript row
  (``HEARTBEAT_TRANSCRIPT_PROMPT``) goes through
  :class:`~memory_core.runtime_identity.RuntimeIdentity`;
- ``HEARTBEAT.md`` scanning: ``isHeartbeatContentEffectivelyEmpty``
  (``heartbeat.ts:27-109``), the ``tasks:`` block parser ``parseHeartbeatTasks``
  (``:250-344``) and the due check ``isTaskDue`` (``:346-360``) with
  ``parseDurationMs`` (``src/cli/parse-duration.ts``);
- the cadence helper ``resolveHeartbeatIntervalMs``
  (``src/infra/heartbeat-summary.ts:53-80``).

Scope: the host owns scheduling (intervals, active hours, busy-lane deferral,
wake sources, delivery targets). memory-core supplies the inputs of one heartbeat
turn and the handling of its reply; it never starts a timer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim, js_trim_end, js_trim_start
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY

# src/auto-reply/tokens.ts:5
HEARTBEAT_TOKEN = "HEARTBEAT_OK"

# src/auto-reply/heartbeat.ts:16-25
_HEARTBEAT_CONTEXT_PROMPT = (
    "Read HEARTBEAT.md if it exists (workspace context). Follow it strictly. "
    "Do not infer or repeat old tasks from prior chats."
)
HEARTBEAT_PROMPT = f"{_HEARTBEAT_CONTEXT_PROMPT} If nothing needs attention, reply HEARTBEAT_OK."
HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS = (
    "Use heartbeat_respond to report the wake outcome. Set notify=false when nothing needs the "
    "user's attention. Set notify=true with notificationText only when the user should be "
    "interrupted."
)
HEARTBEAT_RESPONSE_TOOL_PROMPT = f"{_HEARTBEAT_CONTEXT_PROMPT} {HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS}"
# memory-core default; OPENCLAW_COMPAT_RUNTIME_IDENTITY carries the upstream string.
HEARTBEAT_TRANSCRIPT_PROMPT = MEMORY_CORE_RUNTIME_IDENTITY.heartbeat_transcript_prompt
DEFAULT_HEARTBEAT_EVERY = "30m"
DEFAULT_HEARTBEAT_ACK_MAX_CHARS = 300

DurationUnit = Literal["ms", "s", "m", "h", "d"]

_DURATION_MULTIPLIERS: dict[str, int] = {
    "ms": 1,
    "s": 1000,
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
}
_MAX_SAFE_INTEGER = 2**53 - 1
# JavaScript \d without the u flag is ASCII only.
_SINGLE_DURATION_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(ms|s|m|h|d)?\Z")
_COMPOSITE_DURATION_TOKEN_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h|d)")

_S = JS_SPACE_CLASS
# `$` without the m flag is end of input (\Z); `.` excludes JS line terminators.
_SINGLE_LINE_HTML_COMMENT_RE = re.compile("^<!--[^\n\r  ]*-->\\Z")
_ATX_HEADING_RE = re.compile(f"^#+(?:[{_S}]|\\Z)")
_EMPTY_LIST_ITEM_RE = re.compile(f"^[-*+][{_S}]*(?:\\[[{_S}Xx]?\\][{_S}]*)?\\Z")
_FENCE_MARKER_RE = re.compile("^```[A-Za-z0-9_-]*\\Z")
_EDGE_QUOTES_RE = re.compile("^[\"']|[\"']\\Z")


@dataclass(frozen=True)
class HeartbeatTask:
    """One ``tasks:`` entry of HEARTBEAT.md (upstream ``HeartbeatTask``)."""

    name: str
    interval: str
    prompt: str


def _js_round(value: float) -> float:
    """``Math.round``: halves round toward +Infinity."""
    if not math.isfinite(value):
        return value
    floor = math.floor(value)
    return float(floor + 1) if value - floor >= 0.5 else float(floor)


def _invalid_duration(raw: str, reason: str | None = None) -> ValueError:
    value = f'"{raw}"' if js_trim(raw) else "empty value"
    prefix = f"Invalid duration ({reason}): {value}." if reason else f"Invalid duration: {value}."
    return ValueError(f"{prefix} Use values like 500ms, 30s, 5m, 2h, or 1h30m.")


def _round_safe_duration_ms(raw: str, value: float) -> int:
    ms = _js_round(value)
    if not math.isfinite(ms) or abs(ms) > _MAX_SAFE_INTEGER:
        raise _invalid_duration(raw)
    return int(ms)


def parse_duration_ms(raw: str, *, default_unit: DurationUnit | None = None) -> int:
    """Port of ``parseDurationMs`` (``src/cli/parse-duration.ts:34-82``).

    Accepts ``500ms``, ``30s``, ``5m``, ``2h``, ``1d``, decimals and composite
    forms such as ``1h30m``; a bare number uses ``default_unit`` (``ms`` when
    unset). Raises ``ValueError`` with the upstream message on invalid input.
    """
    trimmed = js_trim(raw).lower() if isinstance(raw, str) else ""
    if not trimmed:
        raise _invalid_duration(raw if isinstance(raw, str) else "", "empty")

    single = _SINGLE_DURATION_RE.match(trimmed)
    if single:
        value = float(single.group(1))
        if not math.isfinite(value) or value < 0:
            raise _invalid_duration(raw)
        unit = single.group(2) or default_unit or "ms"
        return _round_safe_duration_ms(raw, value * _DURATION_MULTIPLIERS[unit])

    total_ms = 0.0
    consumed = 0
    for match in _COMPOSITE_DURATION_TOKEN_RE.finditer(trimmed):
        if match.start() != consumed:
            raise _invalid_duration(raw, "each composite segment needs a unit")
        value = float(match.group(1))
        if not math.isfinite(value) or value < 0:
            raise _invalid_duration(raw)
        total_ms += value * _DURATION_MULTIPLIERS[match.group(2)]
        consumed += len(match.group(0))
    if consumed != len(trimmed) or consumed == 0:
        raise _invalid_duration(raw)
    return _round_safe_duration_ms(raw, total_ms)


def resolve_heartbeat_interval_ms(every: str | None = None) -> int | None:
    """Heartbeat cadence in ms, or ``None`` when disabled or invalid.

    Port of ``resolveHeartbeatIntervalMs`` (``src/infra/heartbeat-summary.ts:53-80``)
    for one agent: ``every`` stands in for the resolved ``heartbeat.every``
    (``None`` means unset and falls back to ``DEFAULT_HEARTBEAT_EVERY``; an empty
    string disables). Bare numbers are minutes. The host scheduler uses it.
    """
    raw = DEFAULT_HEARTBEAT_EVERY if every is None else every
    if not raw or not isinstance(raw, str):
        return None
    trimmed = js_trim(raw)
    if not trimmed:
        return None
    try:
        ms = parse_duration_ms(trimmed, default_unit="m")
    except ValueError:
        return None
    if ms <= 0:
        return None
    return ms


def _normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = js_trim(value)
    return trimmed or None


def resolve_heartbeat_prompt(raw: str | None = None) -> str:
    """Configured heartbeat prompt, trimmed, or ``HEARTBEAT_PROMPT`` (``heartbeat.ts:112-115``)."""
    return _normalize_optional_string(raw) or HEARTBEAT_PROMPT


def resolve_heartbeat_prompt_for_response_tool(raw: str | None = None) -> str:
    """Heartbeat prompt for ``heartbeat_respond`` runs (``heartbeat.ts:117-134``).

    A custom prompt keeps its text and gains ``HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS``
    after a blank line unless it already contains them.
    """
    trimmed = _normalize_optional_string(raw)
    if not trimmed:
        return HEARTBEAT_RESPONSE_TOOL_PROMPT
    if HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS in trimmed:
        return trimmed
    return f"{trimmed}\n\n{HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS}"


def _strip_leading_html_comment_scaffolding(line: str, state: list[bool]) -> str:
    # heartbeat.ts:27-49; state[0] tracks an open multi-line comment.
    remaining = line
    while state[0] or js_trim_start(remaining).startswith("<!--"):
        search_text = remaining if state[0] else js_trim_start(remaining)
        comment_end = search_text.find("-->")
        if comment_end == -1:
            state[0] = True
            return ""
        state[0] = False
        if search_text == remaining:
            remaining = remaining[comment_end + 3 :]
        else:
            leading_width = len(remaining) - len(search_text)
            remaining = remaining[:leading_width] + search_text[comment_end + 3 :]
    return remaining


def _strip_heartbeat_html_comments(content: str) -> list[str]:
    state = [False]
    return [_strip_leading_html_comment_scaffolding(line, state) for line in content.split("\n")]


def is_heartbeat_content_effectively_empty(content: str | None) -> bool:
    """True when HEARTBEAT.md holds no actionable content (``heartbeat.ts:56-109``).

    Blank lines, HTML comments (multi-line aware, leading only), ATX headings,
    empty list stubs (``-``, ``- [ ]``) and code-fence markers are ignored.
    ``None`` (missing file) is ``False`` so the heartbeat still runs.
    """
    if not isinstance(content, str):
        return False
    for line in _strip_heartbeat_html_comments(content):
        trimmed = js_trim(line)
        if not trimmed:
            continue
        if _SINGLE_LINE_HTML_COMMENT_RE.match(trimmed):
            continue
        if _ATX_HEADING_RE.match(trimmed):
            continue
        if _EMPTY_LIST_ITEM_RE.match(trimmed):
            continue
        if _FENCE_MARKER_RE.match(trimmed):
            continue
        return False
    return True


def _strip_edge_quotes(value: str) -> str:
    return _EDGE_QUOTES_RE.sub("", value)


def _field_value(trimmed: str, field: str) -> str:
    # `.replace(field, "")` replaces the first occurrence only.
    return _strip_edge_quotes(js_trim(trimmed.replace(field, "", 1)))


def parse_heartbeat_tasks(content: str) -> list[HeartbeatTask]:
    """Parse the YAML-like ``tasks:`` block of HEARTBEAT.md (``heartbeat.ts:250-344``).

    Recognises::

        tasks:
          - name: inbox
            interval: 30m
            prompt: Check urgent inbox items

    Entries missing a name, interval or prompt are dropped; tasks inside HTML
    comments are ignored.
    """
    tasks: list[HeartbeatTask] = []
    lines = _strip_heartbeat_html_comments(content)
    in_tasks_block = False
    for index, line in enumerate(lines):
        trimmed = js_trim(line)
        if trimmed == "tasks:":
            in_tasks_block = True
            continue
        if not in_tasks_block:
            continue
        is_task_field = (
            trimmed.startswith("interval:")
            or trimmed.startswith("prompt:")
            or trimmed.startswith("- name:")
        )
        if (
            not is_task_field
            and not trimmed.startswith(" ")
            and not trimmed.startswith("\t")
            and trimmed
            and not trimmed.startswith("-")
        ):
            in_tasks_block = False
            continue
        if not trimmed.startswith("- name:"):
            continue
        name = _field_value(trimmed, "- name:")
        interval = ""
        prompt = ""
        for next_line in lines[index + 1 :]:
            next_trimmed = js_trim(next_line)
            if next_trimmed.startswith("- name:"):
                break
            indented = next_line.startswith(" ") or next_line.startswith("\t")
            if next_trimmed.startswith("interval:") and indented:
                interval = _field_value(next_trimmed, "interval:")
            elif next_trimmed.startswith("prompt:") and indented:
                prompt = _field_value(next_trimmed, "prompt:")
            elif (
                not next_trimmed.startswith(" ")
                and not next_trimmed.startswith("\t")
                and next_trimmed
            ):
                in_tasks_block = False
                break
        if name and interval and prompt:
            tasks.append(HeartbeatTask(name=name, interval=interval, prompt=prompt))
    return tasks


def is_task_due(last_run_ms: float | None, interval: str, now_ms: float) -> bool:
    """``isTaskDue`` (``heartbeat.ts:346-360``): never run is due; bad intervals are not."""
    if last_run_ms is None:
        return True
    try:
        interval_ms = parse_duration_ms(interval, default_unit="m")
    except ValueError:
        return False
    return now_ms - last_run_ms >= interval_ms


# --- reply handling -------------------------------------------------------------------------

StripHeartbeatMode = Literal["heartbeat", "message"]


@dataclass(frozen=True)
class HeartbeatStripResult:
    """Result of :func:`strip_heartbeat_token`.

    ``should_skip`` means the reply carries nothing to deliver (empty, a bare
    acknowledgement, or in heartbeat mode a remainder of at most the ack limit).
    """

    should_skip: bool
    text: str
    did_strip: bool


# JavaScript regexes without the u flag work on UTF-16 code units, so the text
# is processed with astral characters split into surrogate pairs.
_TOKEN_AT_END_RE = re.compile(re.escape(HEARTBEAT_TOKEN) + "[^A-Za-z0-9_]{0,4}\\Z")
_HTML_TAG_RE = re.compile("<[^>]*>")
_NBSP_ENTITY_RE = re.compile("&[nN][bB][sS][pP];")
_LEADING_MARKUP_RE = re.compile("^[*`~_]+")
_TRAILING_MARKUP_RE = re.compile("[*`~_]+\\Z")
_JS_WHITESPACE_RUN_RE = re.compile(f"[{_S}]+")
_DECIMAL_NUMBER_RE = re.compile(
    "^[+-]?(?:Infinity|[0-9]+\\.?[0-9]*(?:[eE][+-]?[0-9]+)?|\\.[0-9]+(?:[eE][+-]?[0-9]+)?)\\Z"
)
_NON_DECIMAL_NUMBER_RE = re.compile("^0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)\\Z")


def _to_utf16_units(value: str) -> str:
    if value.isascii():
        return value
    out: list[str] = []
    for char in value:
        code = ord(char)
        if code > 0xFFFF:
            code -= 0x10000
            out.append(chr(0xD800 + (code >> 10)))
            out.append(chr(0xDC00 + (code & 0x3FF)))
        else:
            out.append(char)
    return "".join(out)


def _from_utf16_units(value: str) -> str:
    if value.isascii():
        return value
    return value.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _js_string_to_number(value: str) -> float:
    """``Number(string)`` (ECMAScript StringToNumber)."""
    trimmed = js_trim(value)
    if not trimmed:
        return 0.0
    if _DECIMAL_NUMBER_RE.match(trimmed):
        return float(trimmed)
    if _NON_DECIMAL_NUMBER_RE.match(trimmed):
        base = {"x": 16, "o": 8, "b": 2}[trimmed[1].lower()]
        return float(int(trimmed[2:], base))
    return math.nan


def _resolve_max_ack_chars(value: object) -> float:
    # heartbeat.ts:200-208: strings go through Number(); anything that is not a
    # finite number falls back to the default; negatives clamp to 0.
    parsed = _js_string_to_number(value) if isinstance(value, str) else value
    if (
        isinstance(parsed, (int, float))
        and not isinstance(parsed, bool)
        and math.isfinite(parsed)
    ):
        return max(0, parsed)
    return DEFAULT_HEARTBEAT_ACK_MAX_CHARS


def _strip_token_at_edges(raw: str) -> tuple[str, bool]:
    # heartbeat.ts:138-184, on UTF-16 units.
    text = js_trim(raw)
    if not text:
        return "", False
    if HEARTBEAT_TOKEN not in text:
        return text, False
    did_strip = False
    changed = True
    while changed:
        changed = False
        current = js_trim(text)
        if current.startswith(HEARTBEAT_TOKEN):
            text = js_trim_start(current[len(HEARTBEAT_TOKEN) :])
            did_strip = True
            changed = True
            continue
        if _TOKEN_AT_END_RE.search(current):
            index = current.rfind(HEARTBEAT_TOKEN)
            before = js_trim_end(current[:index])
            if not before:
                text = ""
            else:
                after = js_trim_start(current[index + len(HEARTBEAT_TOKEN) :])
                text = js_trim_end(f"{before}{after}")
            did_strip = True
            changed = True
    return js_trim(_JS_WHITESPACE_RUN_RE.sub(" ", text)), did_strip


def _strip_markup(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    text = _NBSP_ENTITY_RE.sub(" ", text)
    text = _LEADING_MARKUP_RE.sub("", text, count=1)
    return _TRAILING_MARKUP_RE.sub("", text, count=1)


def strip_heartbeat_token(
    raw: str | None,
    *,
    mode: StripHeartbeatMode = "message",
    max_ack_chars: int | float | str | None = None,
) -> HeartbeatStripResult:
    """Strip ``HEARTBEAT_OK`` acknowledgements (port of ``stripHeartbeatToken``,
    ``src/auto-reply/heartbeat.ts:186-248``).

    The token is removed at the start or end of the reply (with up to four
    trailing non-word characters), also inside ``<b>``/``**``-style wrappers;
    a token in the middle is left alone. In ``heartbeat`` mode a remainder of
    at most ``max_ack_chars`` UTF-16 units (default 300) is still skipped, so a
    heartbeat reply is delivered only when it carries a real alert. Heartbeat
    replies use ``mode="heartbeat"`` with the configured ``ackMaxChars``
    (``src/infra/heartbeat-runner.ts:862-874``).
    """
    if not raw:
        return HeartbeatStripResult(True, "", False)
    trimmed = js_trim(_to_utf16_units(raw))
    if not trimmed:
        return HeartbeatStripResult(True, "", False)
    ack_limit = _resolve_max_ack_chars(max_ack_chars)

    trimmed_normalized = _strip_markup(trimmed)
    if HEARTBEAT_TOKEN not in trimmed and HEARTBEAT_TOKEN not in trimmed_normalized:
        return HeartbeatStripResult(False, _from_utf16_units(trimmed), False)

    original_text, original_stripped = _strip_token_at_edges(trimmed)
    normalized_text, normalized_stripped = _strip_token_at_edges(trimmed_normalized)
    if original_stripped and original_text:
        picked_text, picked_stripped = original_text, original_stripped
    else:
        picked_text, picked_stripped = normalized_text, normalized_stripped
    if not picked_stripped:
        return HeartbeatStripResult(False, _from_utf16_units(trimmed), False)
    if not picked_text:
        return HeartbeatStripResult(True, "", True)

    rest = js_trim(picked_text)
    if mode == "heartbeat" and len(rest) <= ack_limit:
        return HeartbeatStripResult(True, "", True)
    return HeartbeatStripResult(False, _from_utf16_units(rest), True)
