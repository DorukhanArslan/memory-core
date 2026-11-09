"""Exact six-alias Letter primitive for the existing Unicode regex translator.

A negated property is materialized BEFORE case folding. In particular,
``\\P{L}/iu`` differs from ``[^\\p{L}]/iu``. The caller retains its original
Unicode/token/range/safety/flag handling and its regex backend. Other properties
and broader capture/case-fold/v-set behavior are outside this helper.
"""
from __future__ import annotations

from functools import lru_cache

from ._unicode_letter_ranges import UNICODE_LETTER_RANGES


LETTER_PROPERTY_ALIASES = frozenset({
    "L", "Letter", "gc=L", "gc=Letter", "General_Category=L", "General_Category=Letter",
})


def _escape(point: int) -> str:
    if point <= 0xFF:
        return f"\\x{point:02x}"
    if point <= 0xFFFF:
        return f"\\u{point:04x}"
    return f"\\U{point:08x}"


def _range(first: int, last: int) -> str:
    return _escape(first) if first == last else f"{_escape(first)}-{_escape(last)}"


@lru_cache(maxsize=2)
def _class_body(negate: bool) -> str:
    if not negate:
        return "".join(_range(first, last) for first, last in UNICODE_LETTER_RANGES)
    parts = []
    cursor = 0
    for first, last in UNICODE_LETTER_RANGES:
        if cursor < first:
            parts.append(_range(cursor, first - 1))
        cursor = last + 1
    if cursor <= 0x10FFFF:
        parts.append(_range(cursor, 0x10FFFF))
    return "".join(parts)


def letter_property_class_body(name: str, *, unicode_mode: bool, negate: bool = False) -> str | None:
    """Return explicit class contents, or absence for a non-u/unsupported name.

    Wrap this body in ``[...]`` for an atom. Inside a class, keep it as a set
    member so the existing parser can reject invalid range endpoints. Do not
    turn ``negate=True`` into an outer ``[^...]`` operation.
    """
    if not unicode_mode or not isinstance(name, str) or name not in LETTER_PROPERTY_ALIASES:
        return None
    return _class_body(bool(negate))


__all__ = ["LETTER_PROPERTY_ALIASES", "letter_property_class_body"]
