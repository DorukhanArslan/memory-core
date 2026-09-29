"""JavaScript string semantics needed for byte-identical bootstrap ports.

OpenClaw measures and slices strings in UTF-16 code units (``String.length``,
``String.prototype.slice``) and trims with the ECMAScript WhiteSpace and
LineTerminator sets. Python counts code points and trims with ``str.isspace``,
so every cap, slice and trim in ``memory_core.bootstrap`` goes through these
helpers instead of ``len()``/``str.strip()``.

Lone surrogates are representable in Python ``str`` values; a UTF-16 slice that
splits a surrogate pair returns a string with a lone surrogate, exactly like
JavaScript's plain ``slice``. Such strings cannot be UTF-8 encoded in Python
(``str.encode``, ``json.dumps(ensure_ascii=False)``), so host-facing text passes
through :func:`js_to_well_formed` at the transport boundary.
"""

from __future__ import annotations

import errno
import json
import math
import re
import unicodedata
from collections.abc import Callable
from functools import cmp_to_key

# ECMAScript WhiteSpace (TAB, VT, FF, ZWNBSP, USP = Zs) plus LineTerminator
# (LF, CR, LS, PS): the set used by String.prototype.trim/trimEnd and by \s.
JS_WHITESPACE = (
    "\t\n\u000b\u000c\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
# Regex character class body equivalent to JavaScript's \s.
JS_SPACE_CLASS = (
    "\\t\\n\\u000b\\u000c\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f"
    "\\u205f\\u3000\\ufeff"
)
JS_SPACE = f"[{JS_SPACE_CLASS}]"
JS_NON_SPACE = f"[^{JS_SPACE_CLASS}]"
# JavaScript \w under the /iu flags also matches U+017F and U+212A because they
# case-fold into [a-z]; \b is defined over this set.
JS_IU_WORD_CLASS = "A-Za-z0-9_\\u017f\\u212a"


def js_trim(value: str) -> str:
    return value.strip(JS_WHITESPACE)


def js_truthy(value: object) -> bool:
    """JavaScript truthiness of a JSON value: ``null``, ``false``, ``0``, ``NaN`` and ``""`` are
    falsy; objects and arrays are truthy even when empty."""
    if value is None or isinstance(value, bool):
        return bool(value)
    if isinstance(value, int | float):
        return value != 0 and value == value
    if isinstance(value, str):
        return value != ""
    return True


# ECMAScript StringToNumber after the trim: a StrDecimalLiteral (optional sign, Infinity or a
# decimal with an optional exponent) or an unsigned 0x/0o/0b integer literal.
_JS_DECIMAL_LITERAL_RE = re.compile(
    r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
)
_JS_NON_DECIMAL_LITERAL_RE = re.compile(r"0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)")
_JS_RADIX = {"x": 16, "o": 8, "b": 2}


def js_to_number(value: object) -> float:
    """ECMAScript ``ToNumber`` of a JSON value, as a relational comparison with a number applies
    it: ``null`` is 0, booleans 0/1, strings go through ``StringToNumber`` (trimmed, blank is 0,
    ``0x``/``0o``/``0b`` literals, ``Infinity``, anything else ``NaN``), an array through its
    ``join(",")`` string and an object is ``NaN``."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = js_trim(value)
        if not text:
            return 0.0
        if _JS_NON_DECIMAL_LITERAL_RE.fullmatch(text):
            return float(int(text[2:], _JS_RADIX[text[1].lower()]))
        if _JS_DECIMAL_LITERAL_RE.fullmatch(text):
            return float(text.replace("Infinity", "inf"))
        return math.nan
    if isinstance(value, list):
        return js_to_number(",".join(_js_array_item_string(item) for item in value))
    return math.nan


def _js_array_item_string(item: object) -> str:
    # Array.prototype.join: null and undefined are "", everything else its String().
    if item is None:
        return ""
    if isinstance(item, bool):
        return "true" if item else "false"
    if isinstance(item, int):
        return str(item)
    if isinstance(item, float):
        if math.isnan(item):
            return "NaN"
        if math.isinf(item):
            return "Infinity" if item > 0 else "-Infinity"
        return str(int(item)) if item.is_integer() and abs(item) < 1e21 else repr(item)
    if isinstance(item, str):
        return item
    if isinstance(item, list):
        return ",".join(_js_array_item_string(inner) for inner in item)
    return "[object Object]"


def reject_json_constant(name: str) -> object:
    """``json.loads(..., parse_constant=reject_json_constant)``: ``JSON.parse`` refuses ``NaN``
    and ``Infinity``, which ``json.loads`` would accept; ``ValueError`` like a parse error."""
    raise ValueError(f"not JSON: {name}")


def js_trim_end(value: str) -> str:
    return value.rstrip(JS_WHITESPACE)


def js_trim_start(value: str) -> str:
    return value.lstrip(JS_WHITESPACE)


def utf16_len(value: str) -> int:
    if value.isascii():
        return len(value)
    return len(value.encode("utf-16-le", "surrogatepass")) // 2


def _units(value: str) -> bytes:
    return value.encode("utf-16-le", "surrogatepass")


def _from_units(data: bytes) -> str:
    return data.decode("utf-16-le", "surrogatepass")


def _resolve_slice_bounds(length: int, start: int, end: int | None) -> tuple[int, int]:
    start_index = max(length + start, 0) if start < 0 else min(start, length)
    if end is None:
        end_index = length
    else:
        end_index = max(length + end, 0) if end < 0 else min(end, length)
    return start_index, end_index


def utf16_slice(value: str, start: int, end: int | None = None) -> str:
    """``String.prototype.slice`` in UTF-16 units (may split surrogate pairs)."""
    if value.isascii():
        start_index, end_index = _resolve_slice_bounds(len(value), start, end)
        return value[start_index:end_index] if start_index < end_index else ""
    data = _units(value)
    length = len(data) // 2
    start_index, end_index = _resolve_slice_bounds(length, start, end)
    if start_index >= end_index:
        return ""
    return _from_units(data[start_index * 2 : end_index * 2])


_LONE_SURROGATE_RE = re.compile("[\\ud800-\\udfff]")


def js_to_well_formed(value: str) -> str:
    """``String.prototype.toWellFormed``: every lone surrogate becomes U+FFFD.

    Adjacent surrogate code points join into one character first. The UTF-16
    length is unchanged, and the UTF-8 bytes equal what Node writes for the
    original string (``Buffer.from(text, "utf-8")``).
    """
    if value.isascii():
        return value
    joined = _from_units(_units(value))
    return _LONE_SURROGATE_RE.sub("\ufffd", joined)


def js_utf8_encode(value: str) -> bytes:
    """UTF-8 bytes as Node writes a string (``fs.writeFile(path, text, "utf-8")``).

    Adjacent surrogate code points join into one character first; any lone
    surrogate left becomes U+FFFD, like ``Buffer.from(text, "utf-8")``.
    """
    if value.isascii():
        return value.encode("ascii")
    return js_to_well_formed(value).encode("utf-8")


def js_json_stringify(value: object, *, indent: int | None = None) -> str:
    """``JSON.stringify(value, null, indent)`` for JSON-compatible Python values.

    Non-ASCII stays literal and lone surrogates are escaped as ``\\udXXX``
    (well-formed JSON.stringify); adjacent surrogate code points form a pair.
    """
    separators = (",", ": ") if indent else (",", ":")
    text = json.dumps(value, ensure_ascii=False, indent=indent or None, separators=separators)
    if text.isascii():
        return text
    joined = _from_units(_units(text))
    return _LONE_SURROGATE_RE.sub(lambda match: f"\\u{ord(match.group()):04x}", joined)


def _is_high_surrogate(unit: int) -> bool:
    return 0xD800 <= unit <= 0xDBFF


def _is_low_surrogate(unit: int) -> bool:
    return 0xDC00 <= unit <= 0xDFFF


def slice_utf16_safe(value: str, start: int, end: int | None = None) -> str:
    """Port of normalization-core ``sliceUtf16Safe`` (utf16-slice.ts at v2026.9.6).

    Reversed bounds give ``""`` (the pin swapped them); a bound that would split a surrogate
    pair moves inward.
    """
    data = _units(value)
    length = len(data) // 2
    start_index, end_index = _resolve_slice_bounds(length, start, end)
    if end_index <= start_index:
        return ""

    def unit_at(index: int) -> int:
        return int.from_bytes(data[index * 2 : index * 2 + 2], "little")

    if 0 < start_index < length:
        if _is_low_surrogate(unit_at(start_index)) and _is_high_surrogate(unit_at(start_index - 1)):
            start_index += 1
    if 0 < end_index < length:
        if _is_high_surrogate(unit_at(end_index - 1)) and _is_low_surrogate(unit_at(end_index)):
            end_index -= 1
    if start_index >= end_index:
        return ""
    return _from_units(data[start_index * 2 : end_index * 2])


def truncate_utf16_safe(value: str, max_len: int | float) -> str:
    """Port of normalization-core ``truncateUtf16Safe`` (utf16-slice.ts)."""
    limit = max(0, int(max_len // 1))
    if utf16_len(value) <= limit:
        return value
    return slice_utf16_safe(value, 0, limit)


def js_iu_keyword_pattern(keyword: str) -> str:
    """Regex source matching ``keyword`` like a JavaScript /iu literal.

    Python's re.IGNORECASE folds more characters than ECMAScript's simple case
    folding (for example U+0130 matches ``i`` in Python but not in JavaScript),
    so ASCII letters expand into explicit classes of the characters that
    JavaScript folds onto them.
    """
    parts: list[str] = []
    for char in keyword:
        if char.isascii() and char.isalpha():
            lower = char.lower()
            members = {lower, lower.upper()}
            if lower == "s":
                members.add("\u017f")
            if lower == "k":
                members.add("\u212a")
            parts.append("[" + "".join(sorted(members)) + "]")
        else:
            parts.append(re.escape(char))
    return "".join(parts)


# ICU root collation order of printable ASCII as produced by V8's
# String.prototype.localeCompare (measured with node v25.2.1, locale en-US).
# Letters share a primary weight with their other case.
_ICU_ASCII_ORDER = (
    " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$0123456789"
    "aAbBcCdDeEfFgGhHiIjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ"
)
_ICU_ASCII_PRIMARY: dict[str, int] = {}
_weight = 0
for _char in _ICU_ASCII_ORDER:
    if _char.isalpha() and _char.isupper():
        _ICU_ASCII_PRIMARY[_char] = _ICU_ASCII_PRIMARY[_char.lower()]
        continue
    _weight += 1
    _ICU_ASCII_PRIMARY[_char] = _weight
_NON_ASCII_PRIMARY_BASE = 1_000


def _collation_key(value: str) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    primaries: list[int] = []
    secondaries: list[int] = []
    tertiaries: list[int] = []
    for char in unicodedata.normalize("NFD", value):
        if unicodedata.combining(char):
            secondaries.append(ord(char))
            continue
        weight = _ICU_ASCII_PRIMARY.get(char)
        if weight is None:
            folded = char.lower()
            weight = _ICU_ASCII_PRIMARY.get(folded)
            if weight is None:
                weight = _NON_ASCII_PRIMARY_BASE + ord(folded[0])
        primaries.append(weight)
        secondaries.append(0)
        tertiaries.append(1 if char != char.lower() else 0)
    return tuple(primaries), tuple(secondaries), tuple(tertiaries)


def locale_compare(left: str, right: str) -> int:
    """Approximation of V8 ``localeCompare`` (ICU root collation).

    Exact for printable ASCII (primary order measured from V8, lowercase before
    uppercase, accents as secondary differences after NFD). Other characters
    sort after ASCII letters by lowercase code point, which is an approximation
    of the ICU root tables; callers only use it for tie-breaking file paths.
    """
    left_key = _collation_key(left)
    right_key = _collation_key(right)
    if left_key < right_key:
        return -1
    if left_key > right_key:
        return 1
    return 0


locale_sort_key = cmp_to_key(locale_compare)


def js_error_code(error: BaseException) -> str | None:
    """The ``code`` a JavaScript error of this failure carries (``readProperty(err, "code")`` in
    normalization-core error-coercion.ts): a string ``code`` attribute, a number one as its text,
    else an ``OSError``'s errno name (Node's ``code`` for a system error)."""
    code = getattr(error, "code", None)
    if isinstance(code, str):
        return code
    if isinstance(code, int | float) and not isinstance(code, bool):
        return str(int(code)) if float(code).is_integer() else str(code)
    if isinstance(error, OSError) and error.errno is not None:
        return errno.errorcode.get(error.errno)
    return None


def format_js_error_message(exc: BaseException, *, redact: Callable[[str], str] | None = None) -> str:
    """``formatErrorMessage`` (``packages/normalization-core/src/error-coercion.ts:140-190``) for
    the ``__cause__`` chain: the message (the type name when blank), then each cause's message
    (skipped when the text already contains it) and its code (:func:`js_error_code`), joined by
    `` | ``; repeats are skipped.

    Upstream then applies ``redactSensitiveText`` (``src/infra/errors.ts``); memory-core does not
    port it, so ``redact`` is the host's redactor (none: the text is returned as is).
    """
    formatted = str(exc) or type(exc).__name__
    seen = {formatted}

    def append(message: str | None) -> None:
        nonlocal formatted
        if message and message not in seen:
            formatted += f" | {message}"
            seen.add(message)

    visited = {id(exc)}
    cause = exc.__cause__
    while cause is not None and id(cause) not in visited:
        visited.add(id(cause))
        message = str(cause)
        if message and message in formatted:
            seen.add(message)
        else:
            append(message)
        append(js_error_code(cause))
        cause = cause.__cause__
    return redact(formatted) if redact is not None else formatted
