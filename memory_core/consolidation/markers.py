"""Markers the promotion pipeline writes into, or looks for in, memory files.

Ports from ``extensions/memory-core/src/short-term-promotion.ts`` at OpenClaw
pin 4c42815348:

- the promotion marker comment ``<!-- <prefix><recall key> -->`` written above
  each promoted line (``PROMOTION_MARKER_PREFIX``, ``buildPromotionSection``)
  and parsed back for reconciliation (``extractPromotionMarkers``: spaced and
  case-insensitive variants count);
- the managed dreaming fences ``<!-- openclaw:dreaming:<name>:start/end -->``
  in daily notes, which rehydration refuses to promote from
  (``lineRangeOverlapsDreamingFence``).

Neutral marker (decision Q22, 2026-09-26): the prefix comes from
:class:`~memory_core.runtime_identity.RuntimeIdentity`. The default
``MEMORY_CORE_RUNTIME_IDENTITY`` writes ``memory-core-memory-promotion:``;
``OPENCLAW_COMPAT_RUNTIME_IDENTITY`` writes upstream's
``openclaw-memory-promotion:`` byte for byte. Readers accept both prefixes, so
files written by OpenClaw or in either mode reconcile without duplicates, and a
snippet carrying either marker is pipeline scaffolding (upstream only knows its
own prefix). Markers written under an earlier project name are not read, so
reconciliation can append their entries a second time (README › Rename the
Project).
"""

from __future__ import annotations

import re

from memory_core.runtime_identity import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    MEMORY_CORE_RUNTIME_IDENTITY,
    RuntimeIdentity,
)

MEMORY_CORE_PROMOTION_MARKER_PREFIX = MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix
OPENCLAW_PROMOTION_MARKER_PREFIX = OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix
PROMOTION_MARKER_PREFIXES = (MEMORY_CORE_PROMOTION_MARKER_PREFIX, OPENCLAW_PROMOTION_MARKER_PREFIX)

_PREFIX_ALTERNATION = "|".join(re.escape(prefix) for prefix in PROMOTION_MARKER_PREFIXES)
_PROMOTION_MARKER_RE = re.compile(
    rf"<!--\s*(?:{_PREFIX_ALTERNATION})([^\n]+?)\s*-->",
    re.IGNORECASE,
)
_PROMOTION_MARKER_START_RE = re.compile(rf"<!--\s*(?:{_PREFIX_ALTERNATION})", re.IGNORECASE)
_DREAMING_FENCE_START_RE = re.compile(
    r"<!--\s*openclaw:dreaming:[a-z][a-z0-9-]*:start\s*-->", re.IGNORECASE
)
_DREAMING_FENCE_END_RE = re.compile(
    r"<!--\s*openclaw:dreaming:[a-z][a-z0-9-]*:end\s*-->", re.IGNORECASE
)


def format_promotion_marker(
    key: str, identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY
) -> str:
    """Return the marker comment line written above a promoted MEMORY.md entry."""
    return f"<!-- {identity.promotion_marker_prefix}{key} -->"


def extract_promotion_markers(memory_text: str) -> list[str]:
    """Return the recall keys of every promotion marker in ``memory_text``, in order.

    Matches upstream ``extractPromotionMarkers`` for each prefix in
    :data:`PROMOTION_MARKER_PREFIXES`: whitespace after ``<!--`` and before
    ``-->`` is optional and the prefix is case-insensitive.
    """
    markers = []
    for match in _PROMOTION_MARKER_RE.finditer(memory_text):
        key = match.group(1).strip()
        if key:
            markers.append(key)
    return markers


def contains_promotion_marker(text: str) -> bool:
    """True when ``text`` contains the start of a promotion marker comment (any prefix)."""
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
