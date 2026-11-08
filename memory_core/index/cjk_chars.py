"""CJK-aware character counting for token budgets (OpenClaw ``@openclaw/normalization-core``
``cjk-chars.ts`` at v2026.9.6).

A provider-independent budget heuristic, not a tokenizer: lengths are UTF-16 code units, as in
JavaScript, and common CJK, rare BMP, width-compatibility and supplementary characters weigh more
than Latin text. :func:`utf16_length` and :func:`truncate_utf16_safe` give the matching length and
slice for a Python string.
"""

from __future__ import annotations

import re

from memory_core.bootstrap._js import truncate_utf16_safe as _truncate_utf16_safe

CHARS_PER_TOKEN_ESTIMATE = 4
_SURROGATE_RE = re.compile("[\ud800-\udfff]")

# cjk-chars.ts WEIGHTED_CJK_RANGES, one list per weight bucket (bucket 1 first).
_WEIGHTED_CJK_RANGES: tuple[tuple[tuple[int, int], ...], ...] = (
    ((0x00B7, 0x00B7), (0x3000, 0x319F), (0x4E00, 0x9FA5), (0xAC00, 0xD7AF), (0xFF01, 0xFF60)),
    (
        (0x1100, 0x11FF),
        (0x2E80, 0x2FFF),
        (0x31A0, 0x4DFF),
        (0x9FA6, 0x9FFF),
        (0xA000, 0xA4FF),
        (0xA700, 0xA707),
        (0xA960, 0xA97F),
        (0xD7B0, 0xD7FF),
        (0xF900, 0xFAFF),
    ),
    (
        (0x02C7, 0x02C7),
        (0x02C9, 0x02CB),
        (0x02D9, 0x02D9),
        (0x02EA, 0x02EB),
        (0x0305, 0x0305),
        (0x0323, 0x0323),
        (0xFE10, 0xFE4F),
        (0xFF61, 0xFFDC),
        (0xFFE0, 0xFFE6),
    ),
    ((0x1D360, 0x1D371),),
    (
        (0x16FE0, 0x16FFF),
        (0x1AFF0, 0x1AFFF),
        (0x1B000, 0x1B16F),
        (0x1F200, 0x1F2FF),
        (0x20000, 0x2FA1F),
        (0x30000, 0x3347F),
    ),
)
_CATEGORY_RANGES = tuple(
    (start, end, bucket + 1)
    for bucket, ranges in enumerate(_WEIGHTED_CJK_RANGES)
    for start, end in ranges
)


def _category(code_point: int) -> int:
    for start, end, bucket in _CATEGORY_RANGES:
        if start <= code_point <= end:
            return bucket
    return 0


def utf16_length(text: str) -> int:
    """``text.length`` in JavaScript."""
    return len(text) + sum(1 for char in text if ord(char) > 0xFFFF)


def estimate_string_chars(text: str) -> int:
    """``estimateStringChars``: UTF-16 length with the CJK weights applied."""
    # A literal high/low pair denotes the same JS code point as its astral
    # spelling. Join valid pairs for weighting, preserving malformed units.
    if _SURROGATE_RE.search(text):
        text = text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
    total = utf16_length(text)
    if text.isascii():
        return total
    common = rare_bmp = two_token = three_token_supplementary = supplementary = 0
    for char in text:
        bucket = _category(ord(char)) if ord(char) >= 0x80 else 0
        if bucket == 1:
            common += 1
        elif bucket == 2:
            rare_bmp += 1
        elif bucket == 3:
            two_token += 1
        elif bucket == 4:
            three_token_supplementary += 1
        elif bucket == 5:
            supplementary += 1
    per = CHARS_PER_TOKEN_ESTIMATE
    return (
        total
        + common * (per - 1)
        + rare_bmp * (per * 3 - 1)
        + two_token * (per * 2 - 1)
        + three_token_supplementary * (per * 3 - 2)
        + supplementary * (per * 4 - 2)
    )


def truncate_utf16_safe(text: str, max_units: int) -> str:
    """``truncateUtf16Safe``: the longest prefix within ``max_units`` units, never splitting a pair."""
    return _truncate_utf16_safe(text, max_units)
