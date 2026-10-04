"""CJK-aware character budgets (normalization-core ``cjk-chars.ts``) and the budgeted slices of
``tool-result-text-budget.ts`` at v2026.9.6.

Lengths are UTF-16 code units, like ``String.length``. The weighting is a provider-independent
budget heuristic: common CJK counts as one token (4 chars), rarer ranges as 2 or 3 tokens.
"""

from __future__ import annotations

import math
import re

from memory_core.bootstrap._js import slice_utf16_safe, utf16_len

CHARS_PER_TOKEN_ESTIMATE = 4

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


def _build_category_table() -> bytes:
    top = max(end for ranges in _WEIGHTED_CJK_RANGES for _, end in ranges)
    table = bytearray(top + 1)
    for bucket, ranges in enumerate(_WEIGHTED_CJK_RANGES):
        for start, end in ranges:
            table[start : end + 1] = bytes([bucket + 1]) * (end - start + 1)
    return bytes(table)


_CJK_CATEGORY = _build_category_table()
_ASCII_RUN_OR_NON_ASCII = re.compile(r"[\x00-\x7f]+|[^\x00-\x7f]")


def estimate_string_chars(text: str) -> int:
    return estimate_string_chars_with_minimum_raw_weight(text)


def estimate_string_chars_with_minimum_raw_weight(
    text: str, minimum_raw_weight: int | float | None = None
) -> int | float:
    """``estimateStringCharsWithMinimumRawWeight``: a raw-text safety floor per UTF-16 unit."""

    weight = max(1, 1 if minimum_raw_weight is None else minimum_raw_weight)
    if weight not in (1, 2):
        chars = 0
        for match in _ASCII_RUN_OR_NON_ASCII.finditer(text):
            segment = match.group(0)
            minimum_chars = math.ceil(utf16_len(segment) * weight)
            if ord(segment[0]) <= 0x7F:
                chars += minimum_chars
            else:
                chars += max(estimate_string_chars(segment), minimum_chars)
        return chars
    if text.isascii():
        return len(text) * weight
    common = rare_bmp = two_token = three_supplementary = supplementary = 0
    table = _CJK_CATEGORY
    limit = len(table)
    for char in text:
        code = ord(char)
        if code < 0x80 or code >= limit:
            continue
        category = table[code]
        if category == 1:
            common += 1
        elif category == 2:
            rare_bmp += 1
        elif category == 3:
            two_token += 1
        elif category == 4:
            three_supplementary += 1
        elif category == 5:
            supplementary += 1
    return (
        utf16_len(text) * weight
        + common * (CHARS_PER_TOKEN_ESTIMATE - weight)
        + rare_bmp * (CHARS_PER_TOKEN_ESTIMATE * 3 - weight)
        + two_token * (CHARS_PER_TOKEN_ESTIMATE * 2 - weight)
        + three_supplementary * (CHARS_PER_TOKEN_ESTIMATE * 3 - 2 * weight)
        + supplementary * (CHARS_PER_TOKEN_ESTIMATE * 4 - 2 * weight)
    )


def _slice(text: str, start: int, end: int | None = None) -> str:
    if text.isascii():
        length = len(text)
        from_index = max(length + start, 0) if start < 0 else min(start, length)
        if end is None:
            to_index = length
        else:
            to_index = max(length + end, 0) if end < 0 else min(end, length)
        return text[from_index:to_index] if to_index > from_index else ""
    return slice_utf16_safe(text, start, end)


def _slice_to_budget(
    text: str, max_chars: int | float, minimum_raw_weight: int | float | None, from_end: bool
) -> str:
    budget = max(0, math.floor(max_chars))
    length = utf16_len(text)
    if length <= budget and estimate_string_chars_with_minimum_raw_weight(
        text, minimum_raw_weight
    ) <= budget:
        return text
    best = ""
    low = 0
    # Every UTF-16 unit costs at least one budget unit, so longer candidates cannot fit.
    high = min(length, budget)
    while low <= high:
        midpoint = (low + high) // 2
        candidate = _slice(text, length - midpoint) if from_end else _slice(text, 0, midpoint)
        if estimate_string_chars_with_minimum_raw_weight(candidate, minimum_raw_weight) <= budget:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def slice_tool_result_text_to_budget(
    text: str, max_chars: int | float, minimum_raw_weight: int | float | None = None
) -> str:
    return _slice_to_budget(text, max_chars, minimum_raw_weight, False)


def slice_tool_result_text_tail_to_budget(
    text: str, max_chars: int | float, minimum_raw_weight: int | float | None = None
) -> str:
    return _slice_to_budget(text, max_chars, minimum_raw_weight, True)
