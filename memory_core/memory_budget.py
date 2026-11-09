"""Bounded MEMORY.md compaction for promotion writes.

Port of ``extensions/memory-core/src/memory-budget.ts`` at OpenClaw pin
4c42815348: ``parseMemoryBlocks`` (module-private upstream, observable through
``compactMemoryForBudget``), ``compactMemoryForBudget`` and
``DEFAULT_MEMORY_FILE_MAX_CHARS``.

A MEMORY.md file splits into blocks at every line that starts with ``## ``.
A block whose heading matches ``## Promoted From Short-Term Memory (DATE)``
belongs to the promotion pipeline; every other block (the file header, user
or agent sections) is preserved unconditionally. ``memory_core.curation`` uses the
same block parser to keep promotion sections read-only.

JavaScript semantics kept: lengths are UTF-16 code units (``String.length``),
lines split on ``/\\r?\\n/`` and blocks rejoin with ``\\n``, heading whitespace
is ECMAScript ``\\s``, and dates sort with ``localeCompare`` via
``memory_core.bootstrap._js.locale_compare`` (exact for printable ASCII, which
covers ``YYYY-MM-DD`` dates; other characters are approximated).

``memory_core.consolidation.promotion`` delegates its promotion-write compaction here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Literal

from memory_core.bootstrap._js import JS_SPACE, js_trim, locale_compare, utf16_len
from memory_core.runtime_identity import (
    MEMORY_CORE_RUNTIME_IDENTITY,
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    RuntimeIdentity,
)

# Legacy calls without an explicit identity recognize both historical marker prefixes.
_PREFIX_ALTERNATION = "|".join(
    re.escape(identity.promotion_marker_prefix)
    for identity in (MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY)
)

PROMOTION_SECTION_HEADING_RE = re.compile(
    rf"^## Promoted From Short-Term Memory \(([^)]+)\){JS_SPACE}*\Z"
)
# memory-budget.ts:25. Default MEMORY.md budget for promotion writes, in chars.
DEFAULT_MEMORY_FILE_MAX_CHARS = 10_000
# memory-budget.ts:35. Header re-emitted on an emptied file (20) + trailing "\n" (1).
MEMORY_WRITE_OVERHEAD_RESERVE = 21

_LINE_SPLIT_RE = re.compile(r"\r?\n")

MemoryBlockKind = Literal["preserved", "promotion"]


@dataclass(frozen=True)
class MemoryBlock:
    """One MEMORY.md block (upstream ``MemoryBlock``); ``date`` only for promotion blocks."""

    kind: MemoryBlockKind
    text: str
    date: str | None = None
    entry_count: int = 0


@dataclass(frozen=True)
class CompactMemoryResult:
    """Upstream ``CompactMemoryResult``: trimmed existing memory and dropped section dates."""

    compacted: str
    dropped_dates: tuple[str, ...]


_SUBSECTION_HEADING_RE = re.compile(rf"^### (?:Global|Project: .+?){JS_SPACE}*\Z")
_ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|\Z)")
_SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*\Z")
_ENTRY_MARKER_RE = re.compile(
    rf"^<!--{JS_SPACE}*(?:{_PREFIX_ALTERNATION}).*-->{JS_SPACE}*\Z", re.IGNORECASE
)


def _entry_marker_re(identity: RuntimeIdentity | None) -> re.Pattern[str]:
    if identity is None:
        return _ENTRY_MARKER_RE
    return re.compile(
        rf"^<!--{JS_SPACE}*{re.escape(identity.promotion_marker_prefix)}.*-->{JS_SPACE}*\Z", re.IGNORECASE
    )


def _is_blank(line: str) -> bool:
    return js_trim(line) == ""


def _is_generated_promotion_block(lines: list[str], entry_marker_re: re.Pattern[str]) -> bool:
    """``isGeneratedPromotionBlock``: only marker + bullet pairs (and subsection headings)."""
    saw_entry = False
    index = 1
    while index < len(lines):
        line = lines[index]
        if _is_blank(line):
            index += 1
            continue
        if _SUBSECTION_HEADING_RE.match(line):
            index += 1
            while index < len(lines) and _is_blank(lines[index]):
                index += 1
        if not entry_marker_re.match(lines[index] if index < len(lines) else ""):
            return False
        # A marker owns only the single bullet emitted with it; any other body shape is mixed
        # user content that compaction must not delete.
        if not (lines[index + 1] if index + 1 < len(lines) else "").startswith("- "):
            return False
        saw_entry = True
        index += 2
    return saw_entry


def _starts_generated_promotion_subsection(lines: list[str], index: int, entry_marker_re: re.Pattern[str]) -> bool:
    if not _SUBSECTION_HEADING_RE.match(lines[index]):
        return False
    for line in lines[index + 1 :]:
        if _is_blank(line):
            continue
        return entry_marker_re.match(line) is not None
    return False


def _take_setext_heading_lines(lines: list[str], entry_marker_re: re.Pattern[str]) -> list[str] | None:
    start = len(lines)
    while start > 1 and not _is_blank(lines[start - 1]):
        start -= 1
    if start == len(lines):
        return None
    heading_lines = lines[start:]
    if any(entry_marker_re.match(line) for line in heading_lines):
        return None
    del lines[start:]
    return heading_lines


def parse_memory_blocks(content: str, *, identity: RuntimeIdentity | None = None) -> list[MemoryBlock]:
    """Port of ``parseMemoryBlocks`` (memory-budget.ts at v2026.9.6).

    A block starts at any ATX heading; a ``## Promoted From Short-Term Memory (DATE)`` block counts
    as generated only when its whole body is marker + bullet entries (with ``### Global`` /
    ``### Project:`` subsections), a setext heading line ends it, anything else is preserved.
    An explicit identity owns only its literal promotion-marker prefix; omitting it retains
    the legacy recognition of both built-in runtime prefixes.
    """
    if not content:
        return []
    entry_marker_re = _entry_marker_re(identity)
    lines = _LINE_SPLIT_RE.split(content)
    blocks: list[MemoryBlock] = []
    current_lines: list[str] = []
    current_kind: MemoryBlockKind = "preserved"
    current_date: str | None = None

    def flush() -> None:
        nonlocal current_lines, current_kind, current_date
        if not current_lines:
            return
        text = "\n".join(current_lines)
        if current_kind == "promotion" and current_date and _is_generated_promotion_block(current_lines, entry_marker_re):
            entry_count = sum(1 for line in current_lines if entry_marker_re.match(line))
            blocks.append(MemoryBlock("promotion", text, current_date, entry_count))
        else:
            blocks.append(MemoryBlock("preserved", text))
        current_lines = []
        current_kind = "preserved"
        current_date = None

    for index, line in enumerate(lines):
        if current_kind == "promotion" and _SETEXT_UNDERLINE_RE.match(line):
            heading_lines = _take_setext_heading_lines(current_lines, entry_marker_re)
            if heading_lines is not None:
                flush()
                current_lines = [*heading_lines, line]
                continue
        continues_promotion_body = current_kind == "promotion" and _starts_generated_promotion_subsection(
            lines, index, entry_marker_re
        )
        if _ATX_HEADING_RE.match(line) and not continues_promotion_body:
            flush()
            match = PROMOTION_SECTION_HEADING_RE.match(line)
            if match:
                current_kind = "promotion"
                current_date = match.group(1)
            else:
                current_kind = "preserved"
            current_lines = [line]
        else:
            current_lines.append(line)
    flush()
    return blocks


def _join_blocks(blocks: list[MemoryBlock]) -> str:
    return "\n".join(block.text for block in blocks)


def compact_memory_for_budget(
    *,
    existing_memory: str,
    new_section: str,
    budget_chars: int | float,
    max_prior_entry_loss_fraction: float | None = None,
    identity: RuntimeIdentity | None = None,
) -> CompactMemoryResult:
    """Port of ``compactMemoryForBudget``.

    Drops the oldest generated promotion sections (by date) until the existing memory plus
    ``new_section`` fits ``budget_chars`` minus the 21-char writer reserve, never removing more
    than ``max_prior_entry_loss_fraction`` of the generated entries (default 1). Non-promotion
    content is never dropped; when the budget cannot be met within the loss bound the caller owns
    the final fit check. ``identity`` selects owned markers as in :func:`parse_memory_blocks`.
    ``budget_chars <= 0`` returns the memory unchanged.
    """
    if budget_chars <= 0:
        return CompactMemoryResult(existing_memory, ())
    effective_budget = max(0, budget_chars - MEMORY_WRITE_OVERHEAD_RESERVE)
    new_length = utf16_len(new_section)
    if utf16_len(existing_memory) + new_length <= effective_budget:
        return CompactMemoryResult(existing_memory, ())

    blocks = parse_memory_blocks(existing_memory, identity=identity)
    promotion_entries = sorted(
        (
            (index, block.date or "", utf16_len(block.text), block.entry_count)
            for index, block in enumerate(blocks)
            if block.kind == "promotion"
        ),
        key=cmp_to_key(lambda left, right: locale_compare(left[1], right[1])),
    )
    if not promotion_entries:
        return CompactMemoryResult(existing_memory, ())

    dropped_indices: set[int] = set()
    dropped_dates: list[str] = []
    total_entry_count = sum(entry[3] for entry in promotion_entries)
    max_loss = max(0.0, min(1.0, 1.0 if max_prior_entry_loss_fraction is None else max_prior_entry_loss_fraction))
    dropped_entry_count = 0
    projected_size = utf16_len(existing_memory)
    block_separator_cost = 1 if len(blocks) > 1 else 0
    for index, date, length, entry_count in promotion_entries:
        if projected_size + new_length <= effective_budget:
            break
        if total_entry_count > 0 and (dropped_entry_count + entry_count) / total_entry_count > max_loss:
            break
        dropped_indices.add(index)
        dropped_dates.append(date)
        dropped_entry_count += entry_count
        projected_size = max(0, projected_size - length - block_separator_cost)

    if not dropped_indices:
        return CompactMemoryResult(existing_memory, ())
    remaining = [block for index, block in enumerate(blocks) if index not in dropped_indices]
    return CompactMemoryResult(_join_blocks(remaining), tuple(dropped_dates))


def build_budgeted_memory_append(
    *,
    existing_memory: str,
    new_section: str,
    budget_chars: int | float,
    max_prior_entry_loss_fraction: float | None = None,
    identity: RuntimeIdentity | None = None,
) -> tuple[str, tuple[str, ...]]:
    """``buildBudgetedMemoryAppend``: the complete post-promotion file and the dropped dates."""
    compaction = compact_memory_for_budget(
        existing_memory=existing_memory,
        new_section=new_section,
        budget_chars=budget_chars,
        max_prior_entry_loss_fraction=max_prior_entry_loss_fraction,
        identity=identity,
    )
    header = "" if js_trim(compaction.compacted) else "# Long-Term Memory\n\n"
    base = (
        compaction.compacted
        if not compaction.compacted or compaction.compacted.endswith("\n")
        else f"{compaction.compacted}\n"
    )
    return f"{header}{base}{new_section}", compaction.dropped_dates
