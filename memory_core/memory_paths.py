"""Daily memory path shape and its single validator.

The canonical daily memory file is ``memory/YYYY-MM-DD.md`` relative to the
workspace root: the only durable write target (``append_daily_memory``) and the
memory flush target (OpenClaw ``buildMemoryFlushPlan`` relativePath,
``extensions/memory-core/src/flush-plan.ts:121``). Every check of that shape
goes through this module so the write surface, the flush plan and temporal
decay cannot drift apart.
"""

from __future__ import annotations

import re

_DAILY_DATE_PATTERN = r"(\d{4})-(\d{2})-(\d{2})"

# Whole relative path; always applied with ``fullmatch`` (``re.match`` plus a
# ``$`` anchor would also accept a trailing newline).
DAILY_MEMORY_PATH_RE = re.compile(rf"memory/{_DAILY_DATE_PATTERN}\.md")
# Session-corpus basename under memory/.dreams/session-corpus/; ``fullmatch``.
SESSION_CORPUS_FILE_RE = re.compile(rf"{_DAILY_DATE_PATTERN}\.(?:md|txt)")
# OpenClaw temporal-decay.ts DATED_MEMORY_PATH_RE
# (`/(?:^|\/)memory\/(\d{4})-(\d{2})-(\d{2})\.md$/`), used with ``search``. JS
# `$` without the m flag only matches at the end of input, hence ``\Z``.
DATED_MEMORY_PATH_SEARCH_RE = re.compile(rf"(?:^|/)memory/{_DAILY_DATE_PATTERN}\.md\Z")


class UnsafeMemoryPathError(ValueError):
    """Raised when a path is not allowed for the requested memory read or write."""


class MemoryPathNotAllowedError(UnsafeMemoryPathError):
    """``memoryPathNotAllowed()`` of read-file.ts: its error code is ``MEMORY_PATH_NOT_ALLOWED``."""

    code = "MEMORY_PATH_NOT_ALLOWED"


def is_daily_memory_path(rel_path: str) -> bool:
    return DAILY_MEMORY_PATH_RE.fullmatch(rel_path) is not None


def validate_daily_memory_path(rel_path: str) -> str:
    """Return ``rel_path`` unchanged if it is exactly ``memory/YYYY-MM-DD.md``."""
    if not is_daily_memory_path(rel_path):
        raise UnsafeMemoryPathError(
            f"path is not a canonical daily memory file (memory/YYYY-MM-DD.md): {rel_path!r}"
        )
    return rel_path


def parse_dated_memory_path(file_path: str) -> tuple[int, int, int] | None:
    """Year, month and day of a dated memory path, as temporal decay reads it."""
    match = DATED_MEMORY_PATH_SEARCH_RE.search(file_path)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    return year, month, day
