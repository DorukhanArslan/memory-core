"""Markers the promotion pipeline writes into, or looks for in, memory files.

Ports from ``extensions/memory-core/src/short-term-promotion.ts`` at OpenClaw
pin 4c42815348:

- the promotion marker comment ``<!-- openclaw-memory-promotion:<key> -->``
  written above each promoted line (``PROMOTION_MARKER_PREFIX``,
  ``buildPromotionSection``) and parsed back for reconciliation
  (``extractPromotionMarkers``: spaced and case-insensitive variants count);
- the managed dreaming fences ``<!-- openclaw:dreaming:<name>:start/end -->``
  in daily notes, which rehydration refuses to promote from
  (``lineRangeOverlapsDreamingFence``).
"""

from __future__ import annotations

import re

PROMOTION_MARKER_PREFIX = "openclaw-memory-promotion:"

_PROMOTION_MARKER_RE = re.compile(
    r"<!--\s*openclaw-memory-promotion:([^\n]+?)\s*-->",
    re.IGNORECASE,
)
_PROMOTION_MARKER_START_RE = re.compile(r"<!--\s*openclaw-memory-promotion:", re.IGNORECASE)
_DREAMING_FENCE_START_RE = re.compile(
    r"<!--\s*openclaw:dreaming:[a-z][a-z0-9-]*:start\s*-->", re.IGNORECASE
)
_DREAMING_FENCE_END_RE = re.compile(
    r"<!--\s*openclaw:dreaming:[a-z][a-z0-9-]*:end\s*-->", re.IGNORECASE
)


def format_promotion_marker(key: str) -> str:
    """Return the marker comment line written above a promoted MEMORY.md entry."""
    return f"<!-- {PROMOTION_MARKER_PREFIX}{key} -->"


def extract_promotion_markers(memory_text: str) -> list[str]:
    """Return the recall keys of every promotion marker in ``memory_text``, in order.

    Matches upstream ``extractPromotionMarkers``: whitespace after ``<!--`` and
    before ``-->`` is optional and the prefix is case-insensitive.
    """
    markers = []
    for match in _PROMOTION_MARKER_RE.finditer(memory_text):
        key = match.group(1).strip()
        if key:
            markers.append(key)
    return markers


def contains_promotion_marker(text: str) -> bool:
    """True when ``text`` contains the start of a promotion marker comment."""
    return _PROMOTION_MARKER_START_RE.search(text) is not None


def line_range_overlaps_dreaming_fence(lines: list[str], start_line: int, end_line: int) -> bool:
    """True when 1-based ``start_line..end_line`` touches a managed dreaming block.

    Port of ``lineRangeOverlapsDreamingFence``: a fence marker line itself
    counts as inside the block, so a relocated range that includes it would
    leak the marker text into MEMORY.md.
    """
    if not lines:
        return False
    safe_start = max(1, min(start_line, len(lines)))
    safe_end = max(safe_start, min(end_line, len(lines)))
    inside_fence = False
    for index, line in enumerate(lines[:safe_end], start=1):
        is_start = bool(_DREAMING_FENCE_START_RE.search(line))
        is_end = bool(_DREAMING_FENCE_END_RE.search(line))
        if is_start or is_end:
            if safe_start <= index <= safe_end:
                return True
            inside_fence = is_start
            continue
        if inside_fence and safe_start <= index <= safe_end:
            return True
    return False
