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
``openclaw-memory-promotion:`` byte for byte. Default readers accept both prefixes, so
files written by OpenClaw or in either mode reconcile without duplicates, and a
snippet carrying either marker is pipeline scaffolding (upstream only knows its
own prefix). Markers written under an earlier project name are not read, so
reconciliation can append their entries a second time (README › Rename the
Project).

An explicit compatibility/custom promotion flow selects its own reader identity for
reconciliation, budget compaction, preimages and builtin origin pruning. Ordinary
core promotion keeps the default dual reader. Custom non-ASCII prefix characters
are literal; this does not promise a general Unicode case-folding engine.
"""

from __future__ import annotations

import re

from memory_core.bootstrap._js import JS_SPACE, js_i_pattern, js_iu_keyword_pattern, js_trim
from memory_core.runtime_identity import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    MEMORY_CORE_RUNTIME_IDENTITY,
    RuntimeIdentity,
)

MEMORY_CORE_PROMOTION_MARKER_PREFIX = MEMORY_CORE_RUNTIME_IDENTITY.promotion_marker_prefix
OPENCLAW_PROMOTION_MARKER_PREFIX = OPENCLAW_COMPAT_RUNTIME_IDENTITY.promotion_marker_prefix
PROMOTION_MARKER_PREFIXES = (MEMORY_CORE_PROMOTION_MARKER_PREFIX, OPENCLAW_PROMOTION_MARKER_PREFIX)

# Upstream reads markers with /giu (simple case folding: U+017F and U+212A fold onto ASCII) and the
# dreaming fences with /i (ASCII-only folding), so neither can use Python's re.IGNORECASE.
_PREFIX_ALTERNATION = "|".join(js_iu_keyword_pattern(prefix) for prefix in PROMOTION_MARKER_PREFIXES)
_PROMOTION_MARKER_RE = re.compile(rf"<!--{JS_SPACE}*(?:{_PREFIX_ALTERNATION})([^\n]*?){JS_SPACE}*-->")
_PROMOTION_MARKER_START_RE = re.compile(rf"<!--{JS_SPACE}*(?:{_PREFIX_ALTERNATION})")
_DREAMING_FENCE_START_RE = re.compile(
    js_i_pattern(r"<!--\s*openclaw:dreaming:")
    + "[a-zA-Z][a-zA-Z0-9-]*"
    + js_i_pattern(r":start\s*-->")
)
_DREAMING_FENCE_END_RE = re.compile(
    js_i_pattern(r"<!--\s*openclaw:dreaming:")
    + "[a-zA-Z][a-zA-Z0-9-]*"
    + js_i_pattern(r":end\s*-->")
)


def format_promotion_marker(
    key: str, identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY
) -> str:
    """Return the marker comment line written above a promoted MEMORY.md entry."""
    return f"<!-- {identity.promotion_marker_prefix}{key} -->"


def promotion_marker_reader_identity(identity: RuntimeIdentity) -> RuntimeIdentity | None:
    """Keep ordinary core's Q22 dual reader; explicit compatibility/custom owns one prefix."""
    return None if identity == MEMORY_CORE_RUNTIME_IDENTITY else identity


def extract_promotion_markers(memory_text: str, *, identity: RuntimeIdentity | None = None) -> list[str]:
    """Return the recall keys of every promotion marker in ``memory_text``, in order.

    Matches upstream ``extractPromotionMarkers`` for each prefix in
    :data:`PROMOTION_MARKER_PREFIXES`: whitespace after ``<!--`` and before
    ``-->`` is optional and the prefix is case-insensitive. ``identity=None`` retains
    the Q22 dual-prefix reader; an explicit identity selects only its own prefix.
    Non-ASCII custom prefix characters match literally; generic Unicode case parity
    for custom runtime identities is not claimed.
    """
    markers = []
    pattern = (_PROMOTION_MARKER_RE if identity is None else re.compile(
        rf"<!--{JS_SPACE}*{js_iu_keyword_pattern(identity.promotion_marker_prefix)}([^\n]*?){JS_SPACE}*-->"))
    for match in pattern.finditer(memory_text):
        key = js_trim(match.group(1))
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
