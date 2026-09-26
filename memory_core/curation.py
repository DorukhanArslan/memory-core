"""Curated memory writes: a narrow write surface for the agent (memory-core extension).

Upstream at pin 4c42815348 lets the agent edit MEMORY.md, USER.md and every
other workspace file with its generic read/write/edit tools in normal
sessions; only memory-flush runs are restricted, to an append-only write of
the daily file (``src/agents/agent-tools.ts:1040-1066``). memory-core ships no
generic file tools, so this module offers named operations instead. It is an
extension accepted as Q16 (on by default, gated by
``FeatureFlags.curated_memory_writes``) with memory-core-defined semantics:

- MEMORY.md: ``add_memory_entry(section, text)``,
  ``replace_memory_entry(old, new)`` and ``remove_memory_entry(entry)`` edit
  one line and keep every other byte of the file. Sections written by the
  promotion pipeline (``## Promoted From Short-Term Memory (DATE)`` blocks as
  parsed by ``memory_core.memory_budget.parse_memory_blocks``, the oracle-backed
  port of upstream ``parseMemoryBlocks``) and any line carrying an
  ``openclaw-memory-promotion:`` marker are read-only.
- USER.md: ``upsert_user_directive(text, observed, supersede)`` writes one
  directive as ``<!-- observed: YYYY-MM-DD | status: active -->``, a blank
  line and ``- text``. With ``supersede`` the old active directive is marked
  ``status: superseded`` and kept, and its replacement goes right after it.
  USER.md is capped at 4000 chars (``USER_FILE_MAX_CHARS``).
- PROACTIVE_PREFERENCES.md (layouts that provide it): when and how the agent
  may act or reach out unprompted. ``set_proactive_preferences(text)``
  replaces the whole file; empty text clears it.
- ``append_daily_note(text)`` delegates to
  ``MemoryWorkspace.append_daily_memory`` for today's
  ``memory/YYYY-MM-DD.md`` (host clock and timezone); empty or ``NO_REPLY``
  text writes nothing.

Safety rules shared by every operation:

- Only the files the layout provides (``curatable_files``) and the host
  policy allows (``CurationPolicy``) are written, always as a plain name
  directly under the workspace root. Symlinks, hard links, non-regular files,
  differently cased aliases (a legacy ``memory.md``) and files that are not
  valid UTF-8 are refused, never followed or repaired.
- Writes are atomic (temporary file in the root, ``fsync``, ``os.replace``)
  and refused when the file changed since it was read. Within one process,
  each file's read, check and replace run under a per-file lock, so parallel
  tool calls (a host thread pool) are serialized and no edit is lost; writers
  in other processes are not locked out, only caught by the re-read check.
- A write that grows a file is refused when the file would exceed its policy
  cap or when the workspace bootstrap budget
  (``memory_core.bootstrap.build_bootstrap_context_files`` with the policy's
  per-file and total caps) would truncate it or truncate another file that
  fits today. Shrinking writes are always allowed.
- Every result ends with a newline; entry text is a single line.
- Nothing runs during a memory flush (``memory_flush=True``): the flush keeps
  its append-only daily-file write.
- With the flag off, or an operation the policy does not allow, the tools are
  not offered and calls raise ``CurationUnavailableError``.

``after_write`` is called with the ``CurationResult`` of every write that
changed a file, typically to reindex the memory store. It runs after the write
is committed: if it raises (an embedding provider error, an unreadable file
during the reindex), the write stands and the result carries
``after_write_error`` (``afterWriteError`` in the tool payload, next to
``"status": "ok"``), so the model is never told that a committed write failed
and never retries it.

For model tool calls, ``MemoryCurator.tool_definitions()`` returns
provider-neutral specs (``name``, ``description``, JSON-schema
``parameters``; wrap them in the host's tool format) for the operations on
offer, and ``MemoryCurator.dispatch(name, arguments)`` runs one call. Errors
follow the ``memory_search`` tool contract (``memory_core.tools.common``): bad
arguments, refused writes and failed writes raise ``MemoryToolInputError``
tagged with the tool name, and a host tool loop sends the model
``error.to_tool_error()``, the ``{"status": "error", "tool", "error"}`` payload
upstream's tool adapter builds for a thrown tool error
(``src/agents/agent-tool-definition-adapter.ts:250-259``). A call to a tool
that is not on offer raises ``CurationUnavailableError``, which is not a
``MemoryToolInputError``, so the host sees its own mistake.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import stat
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_core.bootstrap import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    DEFAULT_WORKSPACE_LAYOUT,
    MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
    WorkspaceBootstrapFile,
    WorkspaceLayout,
    build_bootstrap_context_files,
    build_bootstrap_injection_stats,
    filter_completed_bootstrap_file,
    is_workspace_setup_completed,
    load_workspace_bootstrap_files,
)
from memory_core.bootstrap._js import js_trim_end, utf16_len
from memory_core.bootstrap.layout import PROACTIVE_PREFERENCES_FILENAME, USER_FILENAME
from memory_core.flags import FeatureFlags
from memory_core.memory_budget import PROMOTION_SECTION_HEADING_RE, parse_memory_blocks
from memory_core.memory_flush import SILENT_REPLY_TOKEN
from memory_core.memory_paths import UnsafeMemoryPathError
from memory_core.tools.common import MemoryToolInputError, format_error_message
from memory_core.workspace import MemoryWorkspace

ADD_MEMORY_ENTRY = "add_memory_entry"
REPLACE_MEMORY_ENTRY = "replace_memory_entry"
REMOVE_MEMORY_ENTRY = "remove_memory_entry"
UPSERT_USER_DIRECTIVE = "upsert_user_directive"
SET_PROACTIVE_PREFERENCES = "set_proactive_preferences"
APPEND_DAILY_NOTE = "append_daily_note"
MEMORY_ENTRY_OPERATIONS = (ADD_MEMORY_ENTRY, REPLACE_MEMORY_ENTRY, REMOVE_MEMORY_ENTRY)
CURATION_OPERATIONS = (
    *MEMORY_ENTRY_OPERATIONS,
    UPSERT_USER_DIRECTIVE,
    SET_PROACTIVE_PREFERENCES,
    APPEND_DAILY_NOTE,
)
# Policy entry for append_daily_note: today's canonical daily file.
DAILY_NOTE_TARGET = "memory/YYYY-MM-DD.md"
# Project rule for USER.md (memory-core extension; upstream has no USER.md cap).
USER_FILE_MAX_CHARS = 4_000

# short-term-promotion.ts:2389 marker scan (/<!--\s*openclaw-memory-promotion:/i).
_PROMOTION_MARKER_RE = re.compile(r"<!--\s*openclaw-memory-promotion:", re.IGNORECASE)
_LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d+[.)])(?:\s+|$)")
_LINE_PREFIX_RE = re.compile(r"^(\s*)((?:[-*+]|\d+[.)])\s+)?")
_DIRECTIVE_MARKER_RE = re.compile(
    r"^<!--\s*observed:\s*(\d{4}-\d{2}-\d{2})\s*\|\s*status:\s*(active|superseded)\s*-->$"
)
_DIRECTIVE_STATUS_RE = re.compile(r"(status:\s*)active")
_TRAILING_COMMENT_RE = re.compile(r"\s*<!--(?:(?!-->).)*-->\s*$")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# One lock per (workspace root, file) for this process: read, check and
# os.replace happen under it (see _edit and append_daily_note).
_TARGET_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_TARGET_LOCKS_GUARD = threading.Lock()


def _target_lock(root: Path, name: str) -> threading.Lock:
    with _TARGET_LOCKS_GUARD:
        return _TARGET_LOCKS.setdefault((str(root), name), threading.Lock())


class CurationError(ValueError):
    """A refused curated write; the message is written for the model.

    ``MemoryCurator.dispatch`` re-raises it as ``MemoryToolInputError``.
    """


class CurationUnavailableError(CurationError):
    """The operation is not offered: flag off, memory flush, or host policy."""


class CurationConflictError(CurationError):
    """The target file changed between read and write."""


@dataclass(frozen=True)
class CurationResult:
    """Outcome of one curated operation.

    ``action`` is one of added, replaced, removed, superseded, set, cleared,
    appended, skipped or unchanged. ``chars`` is the file's UTF-16 length
    (trailing whitespace trimmed, as the bootstrap budget counts it) after the
    operation; daily notes leave it unset.
    """

    operation: str
    path: str
    action: str
    changed: bool
    chars: int | None = None
    # Set when the ``after_write`` hook raised after this write was committed.
    after_write_error: str | None = None

    def to_tool_result(self) -> dict:
        payload: dict = {
            "status": "ok",
            "tool": self.operation,
            "path": self.path,
            "action": self.action,
        }
        if self.chars is not None:
            payload["chars"] = self.chars
        if self.after_write_error is not None:
            payload["afterWriteError"] = self.after_write_error
        return payload


_ONE_LINE = "One line, without the leading '- '."
_SECTION_FILTER = "Section heading, only needed when the entry appears in several sections."


def _tool_specs(user_cap: int | None) -> dict[str, tuple[str, dict, tuple[str, ...]]]:
    user_limit = f" USER.md is limited to {user_cap} characters." if user_cap else ""
    return {
        ADD_MEMORY_ENTRY: (
            "Add one entry to a MEMORY.md section. MEMORY.md keeps durable facts, decisions "
            "and current state. A missing section is created at the end of the file; "
            "sections written by memory promotion are read-only.",
            {
                "section": {
                    "type": "string",
                    "description": "Section heading text, without the leading '## '.",
                },
                "text": {"type": "string", "description": f"The entry. {_ONE_LINE}"},
            },
            ("section", "text"),
        ),
        REPLACE_MEMORY_ENTRY: (
            "Rewrite one MEMORY.md entry whose fact changed, instead of adding an entry "
            "that contradicts it.",
            {
                "old": {
                    "type": "string",
                    "description": "Current entry text exactly as in MEMORY.md, without '- '.",
                },
                "new": {"type": "string", "description": f"Updated entry. {_ONE_LINE}"},
                "section": {"type": "string", "description": _SECTION_FILTER},
            },
            ("old", "new"),
        ),
        REMOVE_MEMORY_ENTRY: (
            "Delete one MEMORY.md entry that is wrong or no longer true.",
            {
                "entry": {
                    "type": "string",
                    "description": "Entry text exactly as in MEMORY.md, without '- '.",
                },
                "section": {"type": "string", "description": _SECTION_FILTER},
            },
            ("entry",),
        ),
        UPSERT_USER_DIRECTIVE: (
            "Record in USER.md a preference or standing instruction the user stated or "
            "confirmed. When it replaces an earlier directive, pass that directive as "
            f"supersede: the old entry stays, marked superseded.{user_limit}",
            {
                "text": {"type": "string", "description": f"The directive. {_ONE_LINE}"},
                "supersede": {
                    "type": "string",
                    "description": "Text of the active directive this one replaces.",
                },
                "observed": {
                    "type": "string",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                    "description": "Date the user said it, YYYY-MM-DD. Defaults to today.",
                },
            },
            ("text",),
        ),
        SET_PROACTIVE_PREFERENCES: (
            "Replace PROACTIVE_PREFERENCES.md: when and how you may act or reach out "
            "without being asked. Send the whole file; empty text clears it. Record only "
            "what the user stated or confirmed.",
            {"text": {"type": "string", "description": "Full new file content (Markdown)."}},
            ("text",),
        ),
        APPEND_DAILY_NOTE: (
            "Append a note to today's daily log (memory/YYYY-MM-DD.md): what happened "
            "today and the context worth keeping.",
            {"text": {"type": "string", "description": "Note to append (Markdown)."}},
            ("text",),
        ),
    }


def curatable_files(layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT) -> dict[str, frozenset[str]]:
    """The widest file set each operation may write under ``layout``."""

    def provided(name: str) -> frozenset[str]:
        return frozenset({name}) if name in layout.load_order else frozenset()

    files = {operation: provided(layout.memory_file) for operation in MEMORY_ENTRY_OPERATIONS}
    files[UPSERT_USER_DIRECTIVE] = provided(USER_FILENAME)
    files[SET_PROACTIVE_PREFERENCES] = provided(PROACTIVE_PREFERENCES_FILENAME)
    files[APPEND_DAILY_NOTE] = frozenset({DAILY_NOTE_TARGET})
    return files


@dataclass(frozen=True)
class CurationPolicy:
    """Host policy: which files each operation may write, and the size caps.

    ``allowed_files`` maps operation names to file names; an operation with no
    files is not offered. The curator refuses a policy that allows a file the
    layout does not provide. ``max_file_chars`` and ``total_max_chars`` are the
    bootstrap budget the host injects with; ``file_caps`` adds stricter
    per-file caps (default: USER.md at ``USER_FILE_MAX_CHARS``).
    """

    allowed_files: Mapping[str, Iterable[str]]
    max_file_chars: int = DEFAULT_BOOTSTRAP_MAX_CHARS
    total_max_chars: int = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS
    file_caps: Mapping[str, int] = field(
        default_factory=lambda: {USER_FILENAME: USER_FILE_MAX_CHARS}
    )

    def __post_init__(self) -> None:
        unknown = sorted(set(self.allowed_files) - set(CURATION_OPERATIONS))
        if unknown:
            raise ValueError(f"unknown curation operations: {', '.join(unknown)}")
        if any(isinstance(files, str) for files in self.allowed_files.values()):
            raise ValueError("allowed_files values must be collections of file names")
        normalized = {
            operation: frozenset(self.allowed_files.get(operation, ()))
            for operation in CURATION_OPERATIONS
        }
        object.__setattr__(self, "allowed_files", MappingProxyType(normalized))
        object.__setattr__(self, "file_caps", MappingProxyType(dict(self.file_caps)))
        for name, cap in (
            ("max_file_chars", self.max_file_chars),
            ("total_max_chars", self.total_max_chars),
            *self.file_caps.items(),
        ):
            if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
                raise ValueError(f"cap for {name} must be a positive integer")

    @classmethod
    def for_layout(
        cls, layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT, **overrides
    ) -> CurationPolicy:
        """Allow every operation the layout supports; ``file_caps`` extend the defaults."""
        if "file_caps" in overrides:
            overrides["file_caps"] = {USER_FILENAME: USER_FILE_MAX_CHARS, **overrides["file_caps"]}
        return cls(allowed_files=curatable_files(layout), **overrides)

    def files_for(self, operation: str) -> frozenset[str]:
        return self.allowed_files.get(operation, frozenset())

    def without(self, *operations: str) -> CurationPolicy:
        """A copy with ``operations`` disabled."""
        allowed = {
            operation: files
            for operation, files in self.allowed_files.items()
            if operation not in operations
        }
        return CurationPolicy(
            allowed_files=allowed,
            max_file_chars=self.max_file_chars,
            total_max_chars=self.total_max_chars,
            file_caps=self.file_caps,
        )


# --- line model -------------------------------------------------------------


@dataclass(frozen=True)
class _Line:
    body: str
    ending: str  # "\n", "\r\n", or "" for a last line without newline


def _split_lines(content: str) -> list[_Line]:
    # Split like upstream's /\r?\n/ while keeping each line's own ending.
    lines: list[_Line] = []
    start = 0
    while start < len(content):
        index = content.find("\n", start)
        if index == -1:
            lines.append(_Line(content[start:], ""))
            break
        if index > start and content[index - 1] == "\r":
            lines.append(_Line(content[start : index - 1], "\r\n"))
        else:
            lines.append(_Line(content[start:index], "\n"))
        start = index + 1
    return lines


def _join_lines(lines: list[_Line]) -> str:
    return "".join(line.body + line.ending for line in lines)


def _file_newline(lines: list[_Line]) -> str:
    for line in lines:
        if line.ending:
            return line.ending
    return "\n"


def _terminate(lines: list[_Line], index: int, newline: str) -> None:
    if not lines[index].ending:
        lines[index] = _Line(lines[index].body, newline)


def _ensure_trailing_newline(content: str, newline: str = "\n") -> str:
    if content and not content.endswith("\n"):
        return content + newline
    return content


# --- input validation --------------------------------------------------------


def _check_text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise CurationError(f"{name} required")
    if "\x00" in value:
        raise CurationError(f"{name} must not contain NUL characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CurationError(f"{name} must be valid Unicode text") from exc
    return value


def _clean_line(value: object, name: str) -> str:
    text = _check_text(value, name).strip()
    if len(text.splitlines()) > 1:
        raise CurationError(f"{name} must be a single line")
    text = _LIST_MARKER_RE.sub("", text, count=1).strip()
    if not text:
        raise CurationError(f"{name} required")
    if _PROMOTION_MARKER_RE.search(text):
        raise CurationError(f"{name} must not contain a memory promotion marker")
    return text


def _clean_section(value: object, name: str = "section") -> str:
    title = _check_text(value, name).strip()
    if len(title.splitlines()) > 1:
        raise CurationError(f"{name} must be a single line")
    if title.startswith("## "):
        title = title[3:].strip()
    if not title:
        raise CurationError(f"{name} required")
    if title.startswith("#"):
        raise CurationError(f"{name} must be a heading title without '#' marks")
    if PROMOTION_SECTION_HEADING_RE.match(f"## {title}") or _PROMOTION_MARKER_RE.search(title):
        raise CurationError(f"{name} is managed by memory promotion and is read-only")
    return title


# --- MEMORY.md ---------------------------------------------------------------


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    title: str | None
    promotion: bool


def _memory_blocks(content: str, lines: list[_Line]) -> list[_Block]:
    """Map ``parse_memory_blocks`` onto line ranges of ``lines``."""
    blocks: list[_Block] = []
    cursor = 0
    for block in parse_memory_blocks(content):
        count = block.text.count("\n") + 1
        start, end = cursor, min(cursor + count, len(lines))
        cursor += count
        if start >= end:
            continue
        heading = lines[start].body
        title = heading[3:].strip() if heading.startswith("## ") else None
        blocks.append(_Block(start, end, title, block.kind == "promotion"))
    return blocks


def _entry_text(body: str) -> str | None:
    stripped = body.strip()
    if not stripped or stripped.startswith("#"):
        return None
    return _LIST_MARKER_RE.sub("", stripped, count=1).strip() or None


def _is_protected(block: _Block, body: str) -> bool:
    return block.promotion or _PROMOTION_MARKER_RE.search(body) is not None


def _find_memory_entry(
    content: str, lines: list[_Line], entry: str, section: str | None
) -> int:
    candidates: list[tuple[int, str | None]] = []
    protected_hits = 0
    for block in _memory_blocks(content, lines):
        if section is not None and (block.promotion or block.title != section):
            continue
        for index in range(block.start, block.end):
            body = lines[index].body
            if _entry_text(body) != entry:
                continue
            if _is_protected(block, body):
                protected_hits += 1
                continue
            candidates.append((index, block.title))
    if not candidates:
        if protected_hits:
            raise CurationError(
                "entry belongs to a memory promotion section, which only the promotion "
                "pipeline may change"
            )
        where = f" section {section!r}" if section is not None else ""
        raise CurationError(f"entry not found in MEMORY.md{where}")
    sections = sorted({title or "(top of file)" for _, title in candidates})
    if len(sections) > 1:
        raise CurationError(
            f"entry appears in {len(sections)} sections ({', '.join(sections)}); "
            "pass section to choose one"
        )
    return candidates[0][0]


def add_memory_entry_text(content: str, section: str, text: str) -> str:
    """Add ``- text`` at the end of section ``section``, creating the section if needed.

    A new section is appended at the end of the file as ``## section``, a blank
    line and the entry. Every other byte of ``content`` is kept.
    """
    title = _clean_section(section)
    entry = _clean_line(text, "text")
    lines = _split_lines(content)
    newline = _file_newline(lines)
    matches = [
        block
        for block in _memory_blocks(content, lines)
        if block.title == title and not block.promotion
    ]
    if len(matches) > 1:
        raise CurationError(f"section {title!r} appears {len(matches)} times in MEMORY.md")
    if matches:
        block = matches[0]
        last = max(index for index in range(block.start, block.end) if lines[index].body.strip())
        line_newline = lines[last].ending or newline
        _terminate(lines, last, line_newline)
        insert = [_Line(f"- {entry}", line_newline)]
        if last == block.start:
            insert.insert(0, _Line("", line_newline))
        lines[last + 1 : last + 1] = insert
    else:
        if lines:
            _terminate(lines, len(lines) - 1, newline)
            if lines[-1].body.strip():
                lines.append(_Line("", newline))
        lines.extend(
            [_Line(f"## {title}", newline), _Line("", newline), _Line(f"- {entry}", newline)]
        )
    return _ensure_trailing_newline(_join_lines(lines), newline)


def replace_memory_entry_text(
    content: str, old: str, new: str, *, section: str | None = None
) -> str:
    """Replace the text of the one line whose entry text equals ``old``.

    The line's indentation and list marker are kept. ``section`` narrows the
    search when the same entry exists in several sections; duplicates inside
    one section resolve to the first.
    """
    target = _clean_line(old, "old")
    replacement = _clean_line(new, "new")
    title = _clean_section(section) if section is not None else None
    lines = _split_lines(content)
    index = _find_memory_entry(content, lines, target, title)
    if replacement != target:
        prefix = _LINE_PREFIX_RE.match(lines[index].body).group(0)
        lines[index] = _Line(prefix + replacement, lines[index].ending)
    return _ensure_trailing_newline(_join_lines(lines), _file_newline(lines))


def remove_memory_entry_text(content: str, entry: str, *, section: str | None = None) -> str:
    """Remove the one line whose entry text equals ``entry`` (see replace)."""
    target = _clean_line(entry, "entry")
    title = _clean_section(section) if section is not None else None
    lines = _split_lines(content)
    index = _find_memory_entry(content, lines, target, title)
    newline = _file_newline(lines)
    del lines[index]
    return _ensure_trailing_newline(_join_lines(lines), newline)


# --- USER.md -------------------------------------------------------------------


@dataclass(frozen=True)
class UserDirective:
    """One USER.md directive: marker comment, blank line(s), ``- text``.

    ``marker_line`` and ``directive_line`` are 0-based line indexes.
    """

    observed: str
    status: str
    text: str
    marker_line: int
    directive_line: int


def _parse_directives(lines: list[_Line]) -> list[UserDirective]:
    directives: list[UserDirective] = []
    index = 0
    while index < len(lines):
        match = _DIRECTIVE_MARKER_RE.match(lines[index].body.strip())
        if match:
            bullet = index + 1
            while bullet < len(lines) and not lines[bullet].body.strip():
                bullet += 1
            body = lines[bullet].body.strip() if bullet < len(lines) else ""
            if body.startswith("- "):
                directives.append(
                    UserDirective(match.group(1), match.group(2), body[2:].strip(), index, bullet)
                )
                index = bullet + 1
                continue
        index += 1
    return directives


def parse_user_directives(content: str) -> list[UserDirective]:
    """Directives of a USER.md text, in file order; malformed entries are skipped."""
    return _parse_directives(_split_lines(content))


def _same_directive(existing: str, query: str) -> bool:
    # A trailing HTML comment is an annotation, not part of the directive.
    return query == existing or query == _TRAILING_COMMENT_RE.sub("", existing).strip()


def _clean_date(value: object, name: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    try:
        if not _DATE_RE.fullmatch(text):
            raise ValueError(text)
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise CurationError(f"{name} must be a YYYY-MM-DD date") from exc
    return text


def _insert_directive(
    lines: list[_Line], after: int | None, observed: str, text: str, newline: str
) -> None:
    if after is None:
        if lines:
            _terminate(lines, len(lines) - 1, newline)
            if lines[-1].body.strip():
                lines.append(_Line("", newline))
        index, line_newline = len(lines), newline
    else:
        line_newline = lines[after].ending or newline
        _terminate(lines, after, line_newline)
        index = after + 1
        lines.insert(index, _Line("", line_newline))
        index += 1
    lines[index:index] = [
        _Line(f"<!-- observed: {observed} | status: active -->", line_newline),
        _Line("", line_newline),
        _Line(f"- {text}", line_newline),
    ]


def upsert_user_directive_text(
    content: str, text: str, *, observed: str, supersede: str | None = None
) -> tuple[str, str]:
    """Add or supersede a USER.md directive; returns ``(content, action)``.

    Without ``supersede`` the directive goes after the last existing directive
    (or at the end of the file) unless an identical active one exists
    (``unchanged``). With ``supersede`` the matching active directive is marked
    superseded in place and the new one is inserted right after it.
    """
    directive = _clean_line(text, "text")
    day = _clean_date(observed, "observed")
    old = _clean_line(supersede, "supersede") if supersede is not None else None
    lines = _split_lines(content)
    newline = _file_newline(lines)
    directives = _parse_directives(lines)
    active_same = [
        item for item in directives if item.status == "active" and _same_directive(item.text, directive)
    ]
    if old is None:
        if active_same:
            return content, "unchanged"
        _insert_directive(
            lines, directives[-1].directive_line if directives else None, day, directive, newline
        )
        return _ensure_trailing_newline(_join_lines(lines), newline), "added"

    if old == directive:
        raise CurationError("supersede must name a different directive than text")
    matches = [item for item in directives if _same_directive(item.text, old)]
    targets = [item for item in matches if item.status == "active"]
    if not targets:
        if matches:
            raise CurationError("that directive is already superseded")
        raise CurationError("no active directive in USER.md matches supersede")
    if len(targets) > 1:
        raise CurationError(f"supersede matches {len(targets)} active directives in USER.md")
    if active_same:
        raise CurationError("an active directive with this text already exists in USER.md")
    target = targets[0]
    marker = lines[target.marker_line]
    lines[target.marker_line] = _Line(
        _DIRECTIVE_STATUS_RE.sub(r"\1superseded", marker.body, count=1), marker.ending
    )
    _insert_directive(lines, target.directive_line, day, directive, newline)
    return _ensure_trailing_newline(_join_lines(lines), newline), "superseded"


# --- PROACTIVE_PREFERENCES.md ---------------------------------------------------------


def proactive_preferences_text(text: str) -> str:
    """Normalise a full PROACTIVE_PREFERENCES.md body: LF endings, one trailing newline."""
    body = js_trim_end(_check_text(text, "text").replace("\r\n", "\n"))
    return f"{body}\n" if body else ""


# --- curator -------------------------------------------------------------------


def _parse_arguments(arguments: Mapping[str, object] | str | None, *, tool: str) -> dict:
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            raise MemoryToolInputError("arguments must be a JSON object", tool=tool) from exc
    if not isinstance(arguments, Mapping):
        raise MemoryToolInputError("arguments must be a JSON object", tool=tool)
    return dict(arguments)


def _required_arg(args: dict, key: str, *, tool: str, allow_blank: bool = False) -> str:
    value = args.get(key)
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise MemoryToolInputError(f"{key} required", tool=tool)
    return value


def _optional_arg(args: dict, key: str, *, tool: str) -> str | None:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise MemoryToolInputError(f"{key} must be a string", tool=tool)
    return value


def _is_plain_file_name(name: str) -> bool:
    return (
        bool(name)
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
    )


class MemoryCurator:
    """Curated writes for one workspace root.

    ``flags`` defaults to ``FeatureFlags()`` (curation on). ``policy`` defaults
    to ``CurationPolicy.for_layout(layout)``. ``after_write`` runs after each
    write that changed a file; its errors are reported on the result, never
    raised (the write is already committed). ``timezone`` (IANA name, default UTC like the
    rest of the package) and ``now_ms`` (epoch-milliseconds clock) decide
    "today" for daily notes and default ``observed`` dates.
    """

    def __init__(
        self,
        workspace_dir: str | os.PathLike[str],
        *,
        layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
        policy: CurationPolicy | None = None,
        flags: FeatureFlags | None = None,
        after_write: Callable[[CurationResult], None] | None = None,
        timezone: str = "UTC",
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.root = Path(workspace_dir).resolve()
        self.layout = layout
        self.policy = policy if policy is not None else CurationPolicy.for_layout(layout)
        self.flags = flags if flags is not None else FeatureFlags()
        self.after_write = after_write
        try:
            self._zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {timezone!r}") from exc
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        widest = curatable_files(layout)
        for operation in CURATION_OPERATIONS:
            for name in self.policy.files_for(operation):
                if name != DAILY_NOTE_TARGET and not _is_plain_file_name(name):
                    raise ValueError(f"curated files must be plain names in the root: {name!r}")
            extra = sorted(self.policy.files_for(operation) - widest[operation])
            if extra:
                raise ValueError(
                    f"policy allows {', '.join(extra)} for {operation}, "
                    "which the workspace layout does not provide"
                )

    # availability

    def available_operations(self, *, memory_flush: bool = False) -> tuple[str, ...]:
        """Operations offered now; empty with the flag off or during a memory flush."""
        if not self.flags.curated_memory_writes or memory_flush:
            return ()
        return tuple(op for op in CURATION_OPERATIONS if self.policy.files_for(op))

    def tool_definitions(self, *, memory_flush: bool = False) -> list[dict]:
        """``{"name", "description", "parameters"}`` specs for the offered operations."""
        specs = _tool_specs(self.policy.file_caps.get(USER_FILENAME))
        definitions = []
        for operation in self.available_operations(memory_flush=memory_flush):
            description, properties, required = specs[operation]
            definitions.append(
                {
                    "name": operation,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": list(required),
                        "additionalProperties": False,
                    },
                }
            )
        return definitions

    def dispatch(
        self,
        name: str,
        arguments: Mapping[str, object] | str | None = None,
        *,
        memory_flush: bool = False,
    ) -> dict:
        """Run one tool call; ``arguments`` is a mapping or its JSON text.

        Returns the result payload (``CurationResult.to_tool_result``). Bad
        arguments, refused writes (``CurationError``) and failed writes
        (``OSError``, as ``write failed: ...``) raise ``MemoryToolInputError``
        with ``tool == name``, like ``execute_memory_search_tool``; the host
        sends the model ``error.to_tool_error()``. A failing ``after_write``
        hook does not raise: the committed write returns its ok payload with
        ``afterWriteError``. Raises
        ``CurationUnavailableError`` for a tool that is not on offer (unknown
        name, flag off, memory flush, policy). Blank optional arguments count
        as absent.
        """
        if name not in CURATION_OPERATIONS:
            raise CurationUnavailableError(f"unknown curation tool: {name}")
        self._require(name, self._target_for(name), memory_flush=memory_flush)
        args = _parse_arguments(arguments, tool=name)
        try:
            result = self._dispatch_call(name, args, memory_flush=memory_flush)
        except CurationUnavailableError:
            raise
        except CurationError as exc:
            raise MemoryToolInputError(str(exc), tool=name) from exc
        except OSError as exc:
            raise MemoryToolInputError(
                f"write failed: {exc.strerror or exc}", tool=name
            ) from exc
        return result.to_tool_result()

    def _dispatch_call(self, name: str, args: dict, *, memory_flush: bool) -> CurationResult:
        if name == ADD_MEMORY_ENTRY:
            return self.add_memory_entry(
                _required_arg(args, "section", tool=name),
                _required_arg(args, "text", tool=name),
                memory_flush=memory_flush,
            )
        if name == REPLACE_MEMORY_ENTRY:
            return self.replace_memory_entry(
                _required_arg(args, "old", tool=name),
                _required_arg(args, "new", tool=name),
                section=_optional_arg(args, "section", tool=name),
                memory_flush=memory_flush,
            )
        if name == REMOVE_MEMORY_ENTRY:
            return self.remove_memory_entry(
                _required_arg(args, "entry", tool=name),
                section=_optional_arg(args, "section", tool=name),
                memory_flush=memory_flush,
            )
        if name == UPSERT_USER_DIRECTIVE:
            return self.upsert_user_directive(
                _required_arg(args, "text", tool=name),
                observed=_optional_arg(args, "observed", tool=name),
                supersede=_optional_arg(args, "supersede", tool=name),
                memory_flush=memory_flush,
            )
        if name == SET_PROACTIVE_PREFERENCES:
            return self.set_proactive_preferences(
                _required_arg(args, "text", tool=name, allow_blank=True),
                memory_flush=memory_flush,
            )
        return self.append_daily_note(
            _required_arg(args, "text", tool=name), memory_flush=memory_flush
        )

    def _target_for(self, operation: str) -> str:
        if operation in MEMORY_ENTRY_OPERATIONS:
            return self.layout.memory_file
        return {
            UPSERT_USER_DIRECTIVE: USER_FILENAME,
            SET_PROACTIVE_PREFERENCES: PROACTIVE_PREFERENCES_FILENAME,
            APPEND_DAILY_NOTE: DAILY_NOTE_TARGET,
        }[operation]

    def _require(self, operation: str, target: str, *, memory_flush: bool) -> None:
        if not self.flags.curated_memory_writes:
            raise CurationUnavailableError(
                "curated memory writes are disabled (FeatureFlags.curated_memory_writes)"
            )
        if memory_flush:
            raise CurationUnavailableError(
                "curated memory writes are unavailable during a memory flush; "
                "the flush only appends to its daily file"
            )
        if target not in self.policy.files_for(operation):
            raise CurationUnavailableError(f"{operation} may not write {target} under this policy")

    # MEMORY.md operations

    def add_memory_entry(
        self, section: str, text: str, *, memory_flush: bool = False
    ) -> CurationResult:
        return self._edit(
            ADD_MEMORY_ENTRY,
            self.layout.memory_file,
            lambda content: (add_memory_entry_text(content, section, text), "added"),
            memory_flush=memory_flush,
        )

    def replace_memory_entry(
        self, old: str, new: str, *, section: str | None = None, memory_flush: bool = False
    ) -> CurationResult:
        def edit(content: str) -> tuple[str, str]:
            updated = replace_memory_entry_text(content, old, new, section=section)
            return updated, "replaced" if updated != content else "unchanged"

        return self._edit(
            REPLACE_MEMORY_ENTRY,
            self.layout.memory_file,
            edit,
            memory_flush=memory_flush,
            require_existing=True,
        )

    def remove_memory_entry(
        self, entry: str, *, section: str | None = None, memory_flush: bool = False
    ) -> CurationResult:
        return self._edit(
            REMOVE_MEMORY_ENTRY,
            self.layout.memory_file,
            lambda content: (remove_memory_entry_text(content, entry, section=section), "removed"),
            memory_flush=memory_flush,
            require_existing=True,
        )

    # USER.md, PROACTIVE_PREFERENCES.md and daily notes

    def upsert_user_directive(
        self,
        text: str,
        *,
        observed: str | None = None,
        supersede: str | None = None,
        memory_flush: bool = False,
    ) -> CurationResult:
        """Record a directive in USER.md; ``observed`` defaults to today."""

        def edit(content: str) -> tuple[str, str]:
            day = observed if observed is not None else self.today()
            return upsert_user_directive_text(content, text, observed=day, supersede=supersede)

        return self._edit(UPSERT_USER_DIRECTIVE, USER_FILENAME, edit, memory_flush=memory_flush)

    def set_proactive_preferences(self, text: str, *, memory_flush: bool = False) -> CurationResult:
        """Replace PROACTIVE_PREFERENCES.md; empty text clears it."""

        def edit(content: str) -> tuple[str, str]:
            body = proactive_preferences_text(text)
            return body, "set" if body else "cleared"

        return self._edit(
            SET_PROACTIVE_PREFERENCES,
            PROACTIVE_PREFERENCES_FILENAME,
            edit,
            memory_flush=memory_flush,
        )

    def append_daily_note(
        self, text: str, *, date: str | None = None, memory_flush: bool = False
    ) -> CurationResult:
        """Append to ``memory/<date>.md`` (default today) via ``append_daily_memory``."""
        self._require(APPEND_DAILY_NOTE, DAILY_NOTE_TARGET, memory_flush=memory_flush)
        raw = _check_text(text, "text")
        day = _clean_date(date, "date") if date is not None else self.today()
        rel_path = f"memory/{day}.md"
        stripped = raw.strip()
        if not stripped or stripped.startswith(SILENT_REPLY_TOKEN):
            return CurationResult(APPEND_DAILY_NOTE, rel_path, "skipped", False)
        memory_dir = self.root / "memory"
        with _target_lock(self.root, rel_path):
            if memory_dir.is_symlink():
                raise CurationError("memory/ is a symlink; curated writes never follow symlinks")
            if os.path.lexists(memory_dir) and not memory_dir.is_dir():
                raise CurationError("memory is not a directory")
            daily = memory_dir / f"{day}.md"
            if os.path.lexists(daily) and not daily.is_symlink():
                info = os.lstat(daily)
                if not stat.S_ISREG(info.st_mode):
                    raise CurationError(f"{rel_path} is not a regular file")
                if info.st_nlink > 1:
                    raise CurationError(f"{rel_path} has more than one hard link")
            try:
                MemoryWorkspace(self.root).append_daily_memory(rel_path, raw)
            except UnsafeMemoryPathError as exc:
                raise CurationError(str(exc)) from exc
        return self._run_after_write(CurationResult(APPEND_DAILY_NOTE, rel_path, "appended", True))

    def today(self) -> str:
        """Today's ``YYYY-MM-DD`` in the curator's timezone."""
        instant = datetime.fromtimestamp(self._now_ms() / 1000, tz=UTC)
        return instant.astimezone(self._zone).strftime("%Y-%m-%d")

    # shared write path

    def _edit(
        self,
        operation: str,
        name: str,
        edit: Callable[[str], tuple[str, str]],
        *,
        memory_flush: bool,
        require_existing: bool = False,
    ) -> CurationResult:
        self._require(operation, name, memory_flush=memory_flush)
        with _target_lock(self.root, name):
            before = self._read_target(name)
            if before is None and require_existing:
                raise CurationError(f"{name} does not exist")
            updated, action = edit(before or "")
            chars = utf16_len(js_trim_end(updated))
            if updated == (before or ""):
                return CurationResult(operation, name, "unchanged", False, chars)
            self._check_caps(name, before, updated)
            self._write_target(name, before, updated)
        return self._run_after_write(CurationResult(operation, name, action, True, chars))

    def _run_after_write(self, result: CurationResult) -> CurationResult:
        # The write is committed: a failing hook is reported, never raised, so
        # neither a caller nor the model mistakes a stored write for a failed one.
        if self.after_write is None:
            return result
        try:
            self.after_write(result)
        except Exception as exc:
            return replace(result, after_write_error=format_error_message(exc))
        return result

    def _read_target(self, name: str) -> str | None:
        if not self.root.is_dir():
            raise CurationError("workspace root does not exist")
        try:
            entries = os.listdir(self.root)
        except OSError as exc:
            raise CurationError(f"workspace root is not readable: {exc.strerror}") from exc
        path = self.root / name
        if name not in entries:
            alias = next((entry for entry in entries if entry.lower() == name.lower()), None)
            if alias is not None:
                raise CurationError(f"workspace has {alias} instead of {name}; rename it first")
            if os.path.lexists(path):
                raise CurationError(f"{name} resolves to another file in the workspace")
            return None
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise CurationError(f"{name} is a symlink; curated writes never follow symlinks")
        if not stat.S_ISREG(info.st_mode):
            raise CurationError(f"{name} is not a regular file")
        if info.st_nlink > 1:
            raise CurationError(f"{name} has more than one hard link")
        if info.st_size > MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES:
            raise CurationError(f"{name} is larger than {MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES} bytes")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise CurationConflictError(f"{name} changed while it was read; retry")
            chunks: list[bytes] = []
            while chunk := os.read(fd, 1 << 16):
                chunks.append(chunk)
        finally:
            os.close(fd)
        try:
            return b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CurationError(f"{name} is not valid UTF-8; fix it by hand first") from exc

    def _check_caps(self, name: str, before: str | None, after: str) -> None:
        before_chars = utf16_len(js_trim_end(before or ""))
        after_chars = utf16_len(js_trim_end(after))
        if after_chars <= before_chars:
            return
        cap = self.policy.file_caps.get(name)
        if cap is not None and after_chars > cap:
            raise CurationError(
                f"{name} would be {after_chars} chars, over its {cap}-char cap; "
                "shorten or remove entries first"
            )
        truncated_before = self._truncated_files(None, None)
        truncated_after = self._truncated_files(name, after)
        if name in truncated_after and after_chars > self.policy.max_file_chars:
            raise CurationError(
                f"{name} would be {after_chars} chars, over the "
                f"{self.policy.max_file_chars}-char context limit per file; "
                "shorten or remove entries first"
            )
        newly = [
            file
            for file in truncated_after
            if file == name or file not in truncated_before
        ]
        if newly:
            raise CurationError(
                f"the write would push {', '.join(newly)} past the "
                f"{self.policy.total_max_chars}-char workspace context budget; "
                "shorten or remove entries first"
            )

    def _truncated_files(self, name: str | None, content: str | None) -> list[str]:
        loaded = {file.name: file for file in load_workspace_bootstrap_files(self.root, self.layout)}
        files: list[WorkspaceBootstrapFile] = []
        for file_name in self.layout.load_order:
            if file_name == name:
                files.append(
                    WorkspaceBootstrapFile(
                        name=file_name, path=os.path.join(str(self.root), file_name), content=content
                    )
                )
            elif file_name in loaded:
                files.append(loaded[file_name])
        # A completed setup drops BOOTSTRAP.md before injection (bootstrap-files.ts:256-281).
        files = filter_completed_bootstrap_file(
            files,
            setup_completed=is_workspace_setup_completed(self.root),
            root=self.root,
            layout=self.layout,
        )
        injected = build_bootstrap_context_files(
            files,
            max_chars=self.policy.max_file_chars,
            total_max_chars=self.policy.total_max_chars,
        )
        stats = build_bootstrap_injection_stats(files, injected.files)
        return [stat_.name for stat_ in stats if stat_.truncated]

    def _write_target(self, name: str, before: str | None, content: str) -> None:
        path = self.root / name
        temporary = self.root / f".{name}.{secrets.token_hex(6)}.tmp"
        mode = stat.S_IMODE(os.lstat(path).st_mode) if before is not None else None
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600 if mode is not None else 0o666)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                os.chmod(temporary, mode)
            if self._read_target(name) != before:
                raise CurationConflictError(f"{name} changed during the write; read it again")
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
            raise
        with contextlib.suppress(OSError):
            dir_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
