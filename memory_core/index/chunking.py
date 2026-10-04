"""Markdown chunking (OpenClaw ``packages/memory-host-sdk/src/host/markdown-chunks.ts``).

``chunk_markdown`` is the tag's ``chunkMarkdown`` at ``MEMORY_CHUNKING_VERSION`` 5: lines fill a
chunk up to ``tokens * 4`` weighted characters (CJK-aware, see :mod:`cjk_chars`), a trailing window
of ``overlap * 4`` carries into the next chunk, and a line longer than the budget is split. With
``per_entry`` (the curated ``MEMORY.md`` and ``USER.md``) every ``- `` entry and every heading
starts a chunk of its own. A chunk's text is its lines joined by newlines, unstripped; chunks with
only whitespace are dropped by the caller (``manager-index-preparation.ts``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from memory_core.index.cjk_chars import (
    CHARS_PER_TOKEN_ESTIMATE,
    estimate_string_chars,
    truncate_utf16_safe,
    utf16_length,
)

_HEADING_RE = re.compile(r"#{1,6}(?:\s|$)")


@dataclass(frozen=True)
class MemoryChunk:
    id: str
    path: str
    start_line: int
    end_line: int
    text: str
    source: str = "memory"
    # The curated entry a fragment belongs to (every fragment of an oversized entry
    # inherits its full span); None outside per-entry chunking.
    entry_start_line: int | None = None
    entry_end_line: int | None = None


def curated_markdown_entry_kind(line: str) -> str | None:
    """``curatedMarkdownEntryKind``: ``entry`` for a ``- `` line, ``section`` for a heading."""
    if line.startswith("- "):
        return "entry"
    return "section" if _HEADING_RE.match(line) else None


def _tail_by_estimated_chars(text: str, budget: int) -> str:
    # takeTailByEstimatedChars: the trailing slice within the weighted budget.
    acc = 0
    start = len(text)
    while start > 0:
        previous = start - 1
        acc += estimate_string_chars(text[previous:start])
        if not acc <= budget:
            break
        start = previous
    return text[start:]


def chunk_markdown(
    path: str,
    text: str,
    *,
    source: str = "memory",
    target_tokens: int = 400,
    overlap_tokens: int = 80,
    per_entry: bool = False,
) -> list[MemoryChunk]:
    lines = text.split("\n")
    max_chars = max(32, target_tokens * CHARS_PER_TOKEN_ESTIMATE)
    overlap_chars = max(0, overlap_tokens * CHARS_PER_TOKEN_ESTIMATE)
    raw: list[list] = []  # [start, end, text, entry_start, entry_end]
    current: list[tuple[str, int]] = []
    current_chars = 0
    entry_start: int | None = None
    entry_first_chunk = 0

    def flush() -> None:
        if not current:
            return
        raw.append([current[0][1], current[-1][1], "\n".join(line for line, _ in current), None, None])

    def carry_overlap(window: int) -> None:
        nonlocal current, current_chars
        if window <= 0 or not current:
            current = []
            current_chars = 0
            return
        acc = 0
        kept: list[tuple[str, int]] = []
        for line, line_no in reversed(current):
            entry_size = estimate_string_chars(line) + 1
            remaining = window - acc
            if entry_size > remaining:
                # A segment wider than the remaining window keeps only its trailing slice.
                tail = _tail_by_estimated_chars(line, remaining - 1) if not kept else ""
                if tail:
                    kept.insert(0, (tail, line_no))
                    acc += estimate_string_chars(tail) + 1
                break
            acc += entry_size
            kept.insert(0, (line, line_no))
            if acc >= window:
                break
        current = kept
        current_chars = acc

    def append_segment(segment: str, line_no: int, chars: int) -> None:
        nonlocal current_chars
        line_size = chars + 1
        if current_chars + line_size > max_chars and current:
            flush()
            # Carry and the incoming segment share one budget, line separators included.
            carry_overlap(min(overlap_chars, max(0, max_chars - line_size)))
        current.append((segment, line_no))
        current_chars += line_size

    def finish_entry(entry_end: int) -> None:
        if entry_start is None:
            return
        for chunk in raw[entry_first_chunk:]:
            chunk[3] = entry_start
            chunk[4] = entry_end

    for index, line in enumerate(lines):
        line_no = index + 1
        entry_kind = (
            (curated_markdown_entry_kind(line) or ("section" if index == 0 else None))
            if per_entry
            else None
        )
        if entry_kind:
            if current:
                flush()
            finish_entry(line_no - 1)
            current = []
            current_chars = 0
            entry_start = line_no if entry_kind == "entry" else None
            entry_first_chunk = len(raw)
        if len(line) == 0:
            append_segment("", line_no, 0)
            continue
        start = 0
        while start < len(line):
            coarse = truncate_utf16_safe(line[start:], max_chars)
            coarse_chars = estimate_string_chars(coarse)
            if coarse_chars > max_chars:
                # Rare and supplementary ideographs can cost several tokens each: split by the
                # estimator's units, every code point intact.
                part_start = 0
                part_end = 0
                part_chars = 0
                for character in coarse:
                    chars = estimate_string_chars(character)
                    if part_chars + chars > max_chars:
                        append_segment(coarse[part_start:part_end], line_no, part_chars)
                        part_start = part_end
                        part_chars = 0
                    part_end += 1
                    part_chars += chars
                append_segment(coarse[part_start:], line_no, part_chars)
            else:
                append_segment(coarse, line_no, coarse_chars)
            # `start += coarse.length` in UTF-16 units; `coarse` is a prefix of `line[start:]`.
            start += len(coarse)
    flush()
    finish_entry(len(lines))

    chunks: list[MemoryChunk] = []
    for start_line, end_line, chunk_text, entry_start_line, entry_end_line in raw:
        if not chunk_text.strip():
            continue
        digest = hashlib.sha256(
            f"{path}:{start_line}:{end_line}:{chunk_text}".encode("utf-8", "surrogatepass")
        ).hexdigest()
        chunks.append(
            MemoryChunk(
                id=digest,
                path=path,
                start_line=start_line,
                end_line=end_line,
                text=chunk_text,
                source=source,
                entry_start_line=entry_start_line,
                entry_end_line=entry_end_line,
            )
        )
    return chunks


__all__ = ["MemoryChunk", "chunk_markdown", "curated_markdown_entry_kind", "utf16_length"]
