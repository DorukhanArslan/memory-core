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

``demo/short_term_promotion.py`` still carries its own copy of this logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Literal

from memory_core.bootstrap._js import JS_SPACE, locale_compare, utf16_len

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


@dataclass(frozen=True)
class CompactMemoryResult:
    """Upstream ``CompactMemoryResult``: trimmed existing memory and dropped section dates."""

    compacted: str
    dropped_dates: tuple[str, ...]


def parse_memory_blocks(content: str) -> list[MemoryBlock]:
    """Port of ``parseMemoryBlocks`` (memory-budget.ts:42-82)."""
    if not content:
        return []
    blocks: list[MemoryBlock] = []
    current_lines: list[str] = []
    current_kind: MemoryBlockKind = "preserved"
    current_date: str | None = None

    def flush() -> None:
        nonlocal current_lines, current_kind, current_date
        if not current_lines:
            return
        text = "\n".join(current_lines)
        if current_kind == "promotion" and current_date:
            blocks.append(MemoryBlock("promotion", text, current_date))
        else:
            blocks.append(MemoryBlock("preserved", text))
        current_lines = []
        current_kind = "preserved"
        current_date = None

    for line in _LINE_SPLIT_RE.split(content):
        if line.startswith("## "):
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
    *, existing_memory: str, new_section: str, budget_chars: int | float
) -> CompactMemoryResult:
    """Port of ``compactMemoryForBudget`` (memory-budget.ts:117-165).

    Drops the oldest promotion sections (by date) until the existing memory
    plus ``new_section`` fits ``budget_chars`` minus the 21-char writer
    reserve. Non-promotion content is never dropped; when no promotion section
    exists, or ``budget_chars <= 0``, the existing memory comes back unchanged.
    """
    if budget_chars <= 0:
        return CompactMemoryResult(existing_memory, ())
    effective_budget = max(0, budget_chars - MEMORY_WRITE_OVERHEAD_RESERVE)
    new_length = utf16_len(new_section)
    if utf16_len(existing_memory) + new_length <= effective_budget:
        return CompactMemoryResult(existing_memory, ())

    blocks = parse_memory_blocks(existing_memory)
    promotion_entries = sorted(
        (
            (index, block.date or "", utf16_len(block.text))
            for index, block in enumerate(blocks)
            if block.kind == "promotion"
        ),
        key=cmp_to_key(lambda left, right: locale_compare(left[1], right[1])),
    )
    if not promotion_entries:
        return CompactMemoryResult(existing_memory, ())

    dropped_indices: set[int] = set()
    dropped_dates: list[str] = []
    projected_size = utf16_len(existing_memory)
    block_separator_cost = 1 if len(blocks) > 1 else 0
    for index, date, length in promotion_entries:
        if projected_size + new_length <= effective_budget:
            break
        dropped_indices.add(index)
        dropped_dates.append(date)
        projected_size = max(0, projected_size - length - block_separator_cost)

    if not dropped_indices:
        return CompactMemoryResult(existing_memory, ())
    remaining = [block for index, block in enumerate(blocks) if index not in dropped_indices]
    return CompactMemoryResult(_join_blocks(remaining), tuple(dropped_dates))
