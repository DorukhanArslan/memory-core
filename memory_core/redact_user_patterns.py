"""User-configured redaction patterns (``logging.redactPatterns``) for :mod:`memory_core.redact`.

Upstream: ``src/logging/redact-pattern-runtime.ts`` (``parseRedactPatternSource``),
``src/security/config-regex.ts`` (``compileConfigRegex``) and ``src/security/safe-regex.ts``
(``compileSafeRegexDetailed``: the trimmed source, the nested-repetition screen, the
``new RegExp`` try/catch).

A configured entry is a string. ``/source/flags`` (flags from ``gimsuy``) is a regex literal;
any other string is the source itself with the flags ``gi``; ``g`` is always added; a blank entry
is skipped silently; a source the nested-repetition screen rejects or ``new RegExp`` rejects is
dropped without a diagnostic in :func:`memory_core.redact.redact_sensitive_text` (the rest of
the list still applies). :func:`compile_config_regex` returns the reason for hosts that report
it.

JavaScript regex source is translated into Python ``re`` source by a small parser
(:func:`translate_user_regex`), following ECMAScript 2024 with the Annex B web-compat syntax
for the non-``u`` mode: ``\\d``, ``\\w``, ``\\s``, ``\\b``, ``.``, ``^`` and ``$`` have their
ECMAScript meaning (ASCII word set, the JS white-space set, the four line terminators, ``$`` is
the end of input without the ``m`` flag), literal ``{``/``}``/``]`` and identity escapes work
outside ``u`` mode, ``\\1`` beyond the group count is an octal escape, named groups and ``\\k<n>``
are mapped to numbered groups. Patterns without the ``u`` flag run over UTF-16 code units (the
caller converts the text), patterns with it over code points.

The six exact Letter aliases (``L``, ``Letter``, ``gc=L``, ``gc=Letter``,
``General_Category=L``, ``General_Category=Letter``) under ``u`` use pinned Unicode 17 ranges.
The ``P`` form materializes its complement before the existing case-folding stage.

Deviations (reported as ``unsupported`` instead of guessing; such an entry is dropped like an
invalid one and noted by :func:`memory_core.redact.unsupported_redact_patterns`):
other ``\\p{..}``/``\\P{..}`` property escapes, look-behind assertions Python cannot compile (variable
width), ``\\S``/``\\W``... negated shorthands inside a class that Python cannot express (``\\S``),
repeat counts beyond Python's limit. Known engine differences kept: a backreference to a group
that did not participate fails in Python and matches empty in JavaScript, captures inside a
repeated group are not reset per iteration, case-insensitive matching without ``u`` also folds
U+017F and U+212A (Python's Unicode folding).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from memory_core.bootstrap._js import JS_IU_WORD_CLASS, JS_SPACE_CLASS, js_trim
from memory_core.unicode_letter_property import letter_property_class_body

_ASTRAL_RE = re.compile("[\U00010000-\U0010ffff]")
_SURROGATE_PAIR_RE = re.compile("[\ud800-\udbff][\udc00-\udfff]")
_LITERAL_RE = re.compile("^/([^\n\r  ]+)/([gimsuy]*)\\Z")
_LINE_TERMINATORS = "\\n\\r\\u2028\\u2029"
_MAX_REPEAT = 2**31 - 2

RejectReason = Literal["unsafe-nested-repetition", "invalid-regex", "unsupported-syntax"]


class InvalidRegexError(ValueError):
    """The source is a syntax error in JavaScript (``new RegExp`` would throw)."""


class UnsupportedRegexError(ValueError):
    """JavaScript accepts the source but this port cannot translate it faithfully."""


def to_units(text: str) -> str:
    if text.isascii():
        return text
    return _ASTRAL_RE.sub(
        lambda m: chr(0xD800 + ((ord(m.group(0)) - 0x10000) >> 10))
        + chr(0xDC00 + ((ord(m.group(0)) - 0x10000) & 0x3FF)),
        text,
    )


def from_units(text: str) -> str:
    if text.isascii():
        return text
    return _SURROGATE_PAIR_RE.sub(
        lambda m: chr(0x10000 + ((ord(m.group(0)[0]) - 0xD800) << 10) + (ord(m.group(0)[1]) - 0xDC00)),
        text,
    )


# --- safe-regex.ts ---------------------------------------------------------------------------
@dataclass
class _Quantifier:
    consumed: int
    min_repeat: int
    max_repeat: int | None


@dataclass
class _TokenState:
    contains_repetition: bool
    has_ambiguous_alternation: bool
    min_length: float
    max_length: float


class _Frame:
    __slots__ = (
        "last_token",
        "contains_repetition",
        "has_alternation",
        "branch_min",
        "branch_max",
        "alt_min",
        "alt_max",
    )

    def __init__(self) -> None:
        self.last_token: _TokenState | None = None
        self.contains_repetition = False
        self.has_alternation = False
        self.branch_min: float = 0
        self.branch_max: float = 0
        self.alt_min: float | None = None
        self.alt_max: float | None = None


_INF = float("inf")


def _add_length(left: float, right: float) -> float:
    if left == _INF or right == _INF:
        return _INF
    return left + right


def _multiply_length(length: float, factor: float) -> float:
    if length == _INF:
        return 0 if factor == 0 else _INF
    return length * factor


def _ascii_digit(char: str) -> bool:
    return "0" <= char <= "9" and len(char) == 1


def _read_quantifier(source: str, index: int) -> _Quantifier | None:
    char = source[index]
    consumed = 2 if source[index + 1 : index + 2] == "?" else 1
    if char == "*":
        return _Quantifier(consumed, 0, None)
    if char == "+":
        return _Quantifier(consumed, 1, None)
    if char == "?":
        return _Quantifier(consumed, 0, 1)
    if char != "{":
        return None
    i = index + 1
    while i < len(source) and _ascii_digit(source[i]):
        i += 1
    if i == index + 1:
        return None
    min_repeat = int(source[index + 1 : i])
    max_repeat: int | None = min_repeat
    if source[i : i + 1] == ",":
        i += 1
        max_start = i
        while i < len(source) and _ascii_digit(source[i]):
            i += 1
        max_repeat = None if i == max_start else int(source[max_start:i])
    if source[i : i + 1] != "}":
        return None
    i += 1
    if source[i : i + 1] == "?":
        i += 1
    if max_repeat is not None and max_repeat < min_repeat:
        return None
    return _Quantifier(i - index, min_repeat, max_repeat)


def _tokenize(source: str) -> list[tuple[str, _Quantifier | None]]:
    tokens: list[tuple[str, _Quantifier | None]] = []
    in_class = False
    i = 0
    while i < len(source):
        char = source[i]
        if in_class:
            if char == "\\":
                i += 2
                continue
            if char == "]":
                in_class = False
            i += 1
            continue
        if char == "\\":
            i += 2
            tokens.append(("simple", None))
            continue
        if char == "[":
            in_class = True
            tokens.append(("simple", None))
        elif char == "(":
            tokens.append(("open", None))
        elif char == ")":
            tokens.append(("close", None))
        elif char == "|":
            tokens.append(("alt", None))
        else:
            quantifier = _read_quantifier(source, i)
            if quantifier is not None:
                tokens.append(("quant", quantifier))
                i += quantifier.consumed
                continue
            tokens.append(("simple", None))
        i += 1
    return tokens


def _record_alternative(frame: _Frame) -> None:
    if frame.alt_min is None or frame.alt_max is None:
        frame.alt_min = frame.branch_min
        frame.alt_max = frame.branch_max
        return
    frame.alt_min = min(frame.alt_min, frame.branch_min)
    frame.alt_max = max(frame.alt_max, frame.branch_max)


def _has_nested_repetition(source: str) -> bool:
    """``hasNestedRepetition``: a repeated token or group that is repeated again."""
    frames = [_Frame()]

    def emit(token: _TokenState) -> None:
        frame = frames[-1]
        frame.last_token = token
        if token.contains_repetition:
            frame.contains_repetition = True
        frame.branch_min = _add_length(frame.branch_min, token.min_length)
        frame.branch_max = _add_length(frame.branch_max, token.max_length)

    for kind, quantifier in _tokenize(source):
        if kind == "simple":
            emit(_TokenState(False, False, 1, 1))
        elif kind == "open":
            frames.append(_Frame())
        elif kind == "close":
            if len(frames) > 1:
                frame = frames.pop()
                if frame.has_alternation:
                    _record_alternative(frame)
                group_min = (frame.alt_min or 0) if frame.has_alternation else frame.branch_min
                group_max = (frame.alt_max or 0) if frame.has_alternation else frame.branch_max
                emit(
                    _TokenState(
                        frame.contains_repetition,
                        frame.has_alternation
                        and frame.alt_min is not None
                        and frame.alt_max is not None
                        and frame.alt_min != frame.alt_max,
                        group_min,
                        group_max,
                    )
                )
        elif kind == "alt":
            frame = frames[-1]
            frame.has_alternation = True
            _record_alternative(frame)
            frame.branch_min = 0
            frame.branch_max = 0
            frame.last_token = None
        else:
            assert quantifier is not None
            frame = frames[-1]
            previous = frame.last_token
            if previous is None:
                continue
            if previous.contains_repetition:
                return True
            if previous.has_ambiguous_alternation and quantifier.max_repeat is None:
                return True
            previous_min = previous.min_length
            previous_max = previous.max_length
            previous.min_length = _multiply_length(previous.min_length, quantifier.min_repeat)
            previous.max_length = (
                _INF
                if quantifier.max_repeat is None
                else _multiply_length(previous.max_length, quantifier.max_repeat)
            )
            previous.contains_repetition = True
            frame.contains_repetition = True
            frame.branch_min = frame.branch_min - previous_min + previous.min_length
            base = (
                frame.branch_max - previous_max
                if frame.branch_max != _INF and previous_max != _INF
                else _INF
            )
            frame.branch_max = _add_length(base, previous.max_length)
    return False


# --- JavaScript regex source -> Python ------------------------------------------------------------
_SYNTAX_CHARS = frozenset("^$\\.*+?()[]{}|/")
_HEX = frozenset("0123456789abcdefABCDEF")
_ID_START = re.compile("[A-Za-z_$ª-￿]")
_ID_PART = re.compile("[A-Za-z0-9_$ª-￿]")


def _chr(code: int) -> str:
    return chr(code)


_SPACE_INTERVALS = (
    (0x09, 0x0D), (0x20, 0x20), (0xA0, 0xA0), (0x1680, 0x1680), (0x2000, 0x200A), (0x2028, 0x2029),
    (0x202F, 0x202F), (0x205F, 0x205F), (0x3000, 0x3000), (0xFEFF, 0xFEFF),
)  # fmt: skip
_DIGIT_INTERVALS = ((0x30, 0x39),)
_WORD_INTERVALS = ((0x30, 0x39), (0x41, 0x5A), (0x5F, 0x5F), (0x61, 0x7A))
_WORD_IU_INTERVALS = ((0x30, 0x39), (0x41, 0x5A), (0x5F, 0x5F), (0x61, 0x7A), (0x17F, 0x17F), (0x212A, 0x212A))


def _complement_body(intervals: tuple[tuple[int, int], ...]) -> str:
    """A class body matching every code point outside the (sorted) intervals."""
    parts: list[str] = []
    cursor = 0
    for low, high in intervals:
        if low > cursor:
            parts.append(f"{_lit(chr(cursor))}-{_lit(chr(low - 1))}" if low - 1 > cursor else _lit(chr(cursor)))
        cursor = high + 1
    parts.append(f"{_lit(chr(cursor))}-{_lit(chr(0x10FFFF))}")
    return "".join(parts)


def _lit(char: str) -> str:
    """A literal character as Python regex source (hex escape, immune to every special case)."""
    code = ord(char)
    if code <= 0xFF:
        return f"\\x{code:02x}"
    if code <= 0xFFFF:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"


class _Translator:
    def __init__(self, source: str, flags: str) -> None:
        self.unicode = "u" in flags
        self.ignore_case = "i" in flags
        self.multiline = "m" in flags
        self.dot_all = "s" in flags
        # Non-unicode patterns run over UTF-16 units, unicode ones over code points.
        self.src = from_units(source) if self.unicode else to_units(source)
        self.pos = 0
        self.group_count = 0
        self.names: dict[str, int] = {}
        self.group_names_present = False
        self._prescan()
        self.group_index = 0
        self.closed: set[int] = set()
        self.word = JS_IU_WORD_CLASS if (self.unicode and self.ignore_case) else "A-Za-z0-9_"

    # -- group prescan: total capture count and whether named groups exist ---------------------
    def _prescan(self) -> None:
        src = self.src
        i = 0
        in_class = False
        while i < len(src):
            char = src[i]
            if char == "\\":
                i += 2
                continue
            if in_class:
                if char == "]":
                    in_class = False
            elif char == "[":
                in_class = True
            elif char == "(":
                if src[i + 1 : i + 2] != "?":
                    self.group_count += 1
                elif src[i + 2 : i + 3] == "<" and src[i + 3 : i + 4] not in ("=", "!"):
                    self.group_count += 1
                    self.group_names_present = True
            i += 1

    # -- helpers --------------------------------------------------------------------------------
    def _peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.src[index] if index < len(self.src) else ""

    def _fail(self, message: str = "invalid regular expression") -> InvalidRegexError:
        return InvalidRegexError(message)

    def translate(self) -> str:
        out = self._disjunction()
        if self.pos < len(self.src):
            raise self._fail("unmatched ')'")
        return out

    def _disjunction(self) -> str:
        return "|".join(self._alternatives())

    def _alternatives(self) -> list[str]:
        alternatives = [self._alternative()]
        while self._peek() == "|":
            self.pos += 1
            alternatives.append(self._alternative())
        return alternatives

    def _alternative(self) -> str:
        parts: list[str] = []
        while self.pos < len(self.src) and self._peek() not in ("|", ")"):
            parts.append(self._term())
        return "".join(parts)

    # -- quantifiers ----------------------------------------------------------------------------
    def _quantifier(self) -> tuple[str, bool] | None:
        """Parse a quantifier at the cursor: (python source, matched)."""
        char = self._peek()
        if char in ("*", "+", "?"):
            self.pos += 1
            base = char
        elif char == "{":
            match = re.compile("\\{([0-9]+)(?:(,)([0-9]*))?\\}").match(self.src, self.pos)
            if match is None:
                if self.unicode:
                    raise self._fail("incomplete quantifier")
                return None
            low = int(match.group(1))
            high = low if match.group(2) is None else (int(match.group(3)) if match.group(3) else None)
            if high is not None and high < low:
                raise self._fail("numbers out of order in {} quantifier")
            if low > _MAX_REPEAT or (high is not None and high > _MAX_REPEAT):
                raise UnsupportedRegexError("repeat count beyond the supported limit")
            self.pos = match.end()
            base = f"{{{low}}}" if match.group(2) is None else f"{{{low},{'' if high is None else high}}}"
        else:
            return None
        lazy = ""
        if self._peek() == "?":
            self.pos += 1
            lazy = "?"
        if self._peek() in ("*", "+", "?") or (self._peek() == "{" and self._quantifier_ahead()):
            raise self._fail("nothing to repeat")
        return base + lazy, True

    def _quantifier_ahead(self) -> bool:
        return re.compile("\\{[0-9]+(?:,[0-9]*)?\\}").match(self.src, self.pos) is not None

    # -- terms ----------------------------------------------------------------------------------
    def _term(self) -> str:
        char = self._peek()
        atom: str
        quantifiable = True
        if char == "^":
            self.pos += 1
            atom = "(?:^|(?<=[" + _LINE_TERMINATORS + "]))" if self.multiline else "^"
            quantifiable = False
        elif char == "$":
            self.pos += 1
            atom = "(?=[" + _LINE_TERMINATORS + "]|\\Z)" if self.multiline else "\\Z"
            quantifiable = False
        elif char == "(":
            atom, quantifiable = self._group()
        elif char == "[":
            atom = self._class()
        elif char == ".":
            self.pos += 1
            atom = "(?s:.)" if self.dot_all else "[^" + _LINE_TERMINATORS + "]"
        elif char == "\\":
            atom, quantifiable = self._atom_escape()
        elif char in ("*", "+", "?"):
            raise self._fail("nothing to repeat")
        elif char == "{":
            if self.unicode or self._quantifier_ahead():
                raise self._fail("nothing to repeat")
            self.pos += 1
            atom = _lit("{")
        elif char == "}":
            if self.unicode:
                raise self._fail("lone quantifier brackets")
            self.pos += 1
            atom = _lit("}")
        elif char == "]":
            if self.unicode:
                raise self._fail("lone quantifier brackets")
            self.pos += 1
            atom = _lit("]")
        else:
            self.pos += 1
            atom = _lit(char)
        quantifier = self._quantifier()
        if quantifier is None:
            return atom
        if not quantifiable:
            raise self._fail("nothing to repeat")
        return f"(?:{atom}){quantifier[0]}"

    def _group(self) -> tuple[str, bool]:
        src = self.src
        self.pos += 1  # (
        if self._peek() == "?":
            kind = src[self.pos + 1 : self.pos + 2]
            if kind == ":":
                self.pos += 2
                body = self._disjunction()
                self._close()
                return f"(?:{body})", True
            if kind in ("=", "!"):
                self.pos += 2
                body = self._disjunction()
                self._close()
                # Annex B allows quantified look-ahead outside u mode.
                return f"(?{kind}{body})", not self.unicode
            if kind == "<":
                after = src[self.pos + 2 : self.pos + 3]
                if after in ("=", "!"):
                    self.pos += 3
                    alternatives = self._alternatives()
                    self._close()
                    # Python needs a fixed width per look-behind: one look-behind per alternative.
                    try:
                        for alternative in alternatives:
                            re.compile(f"(?<{after}{alternative})")
                    except re.error as error:
                        raise UnsupportedRegexError(f"look-behind: {error}") from error
                    if after == "=":
                        joined = "|".join(f"(?<={alternative})" for alternative in alternatives)
                        return f"(?:{joined})", False
                    return "".join(f"(?<!{alternative})" for alternative in alternatives), False
                self.pos += 2
                name = self._group_name()
                if name in self.names:
                    raise UnsupportedRegexError("duplicate capture group name")
                self.group_index += 1
                number = self.group_index
                self.names[name] = number
                body = self._disjunction()
                self._close()
                self.closed.add(number)
                return f"({body})", True
            raise self._fail("invalid group")
        self.group_index += 1
        number = self.group_index
        body = self._disjunction()
        self._close()
        self.closed.add(number)
        return f"({body})", True

    def _group_name(self) -> str:
        start = self.pos
        if not _ID_START.match(self._peek() or "\x00"):
            raise self._fail("invalid capture group name")
        while self.pos < len(self.src) and _ID_PART.match(self.src[self.pos]):
            self.pos += 1
        name = self.src[start : self.pos]
        if self._peek() != ">":
            raise self._fail("invalid capture group name")
        self.pos += 1
        return name

    def _close(self) -> None:
        if self._peek() != ")":
            raise self._fail("unterminated group")
        self.pos += 1

    # -- escapes --------------------------------------------------------------------------------
    def _read_hex(self, count: int) -> int | None:
        digits = self.src[self.pos : self.pos + count]
        if len(digits) == count and all(d in _HEX for d in digits):
            self.pos += count
            return int(digits, 16)
        return None

    def _character_escape(self, in_class: bool) -> str | None:
        """Parse a character escape after the backslash; returns the character, else ``None``."""
        char = self._peek()
        if char == "":
            raise self._fail("\\ at end of pattern")
        simple = {"t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r"}
        if char in simple:
            self.pos += 1
            return simple[char]
        if char == "c":
            letter = self._peek(1)
            if letter and re.fullmatch("[A-Za-z]", letter):
                self.pos += 2
                return _chr(ord(letter) % 32)
            if in_class and not self.unicode and letter and re.fullmatch("[0-9_]", letter):
                self.pos += 2
                return _chr(ord(letter) % 32)
            if self.unicode:
                raise self._fail("invalid unicode escape")
            return "\\"  # Annex B: the backslash is literal and ``c`` is read next
        if char == "0" and not _ascii_digit(self._peek(1)):
            self.pos += 1
            return "\x00"
        if char == "x":
            self.pos += 1
            code = self._read_hex(2)
            if code is None:
                if self.unicode:
                    raise self._fail("invalid escape")
                return "x"
            return _chr(code)
        if char == "u":
            self.pos += 1
            return self._unicode_escape()
        if char in "0123456789":
            return None
        if self.unicode:
            if char in _SYNTAX_CHARS or (in_class and char == "-"):
                self.pos += 1
                return char
            raise self._fail("invalid escape")
        self.pos += 1
        return char

    def _unicode_escape(self) -> str:
        if self.unicode and self._peek() == "{":
            end = self.src.find("}", self.pos)
            digits = self.src[self.pos + 1 : end] if end > 0 else ""
            if not digits or any(d not in _HEX for d in digits) or int(digits, 16) > 0x10FFFF:
                raise self._fail("invalid unicode escape")
            self.pos = end + 1
            return _chr(int(digits, 16))
        code = self._read_hex(4)
        if code is None:
            if self.unicode:
                raise self._fail("invalid unicode escape")
            return "u"
        if self.unicode and 0xD800 <= code <= 0xDBFF and self._peek() == "\\" and self._peek(1) == "u":
            saved = self.pos
            self.pos += 2
            low = self._read_hex(4)
            if low is not None and 0xDC00 <= low <= 0xDFFF:
                return _chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00))
            self.pos = saved
        return _chr(code)

    def _property_escape(self) -> str:
        """Read a supported property token, retaining set/range syntax at the caller."""
        negate = self._peek() == "P"
        self.pos += 1
        if self._peek() != "{":
            raise self._fail("invalid unicode property escape")
        end = self.src.find("}", self.pos + 1)
        if end < 0:
            raise self._fail("unterminated unicode property escape")
        name = self.src[self.pos + 1:end]
        self.pos = end + 1
        body = letter_property_class_body(name, unicode_mode=self.unicode, negate=negate)
        if body is None:
            raise UnsupportedRegexError("unicode property escape")
        return body

    def _atom_escape(self) -> tuple[str, bool]:
        self.pos += 1  # backslash
        char = self._peek()
        word = self.word
        if char == "d":
            self.pos += 1
            return "[0-9]", True
        if char == "D":
            self.pos += 1
            return "[^0-9]", True
        if char == "w":
            self.pos += 1
            return f"[{word}]", True
        if char == "W":
            self.pos += 1
            return f"[^{word}]", True
        if char == "s":
            self.pos += 1
            return f"[{JS_SPACE_CLASS}]", True
        if char == "S":
            self.pos += 1
            return f"[^{JS_SPACE_CLASS}]", True
        if char == "b":
            self.pos += 1
            return f"(?:(?<=[{word}])(?![{word}])|(?<![{word}])(?=[{word}]))", False
        if char == "B":
            self.pos += 1
            return f"(?:(?<=[{word}])(?=[{word}])|(?<![{word}])(?![{word}]))", False
        if char in ("p", "P") and self.unicode:
            return f"[{self._property_escape()}]", True
        if char == "k" and (self.unicode or self.group_names_present):
            self.pos += 1
            if self._peek() != "<":
                raise self._fail("invalid named reference")
            self.pos += 1
            name = self._group_name()
            if name not in self._all_names():
                raise self._fail("invalid named capture referenced")
            return self._backreference(self._all_names()[name]), True
        if char == "0" and _ascii_digit(self._peek(1)):
            if self.unicode:
                raise self._fail("invalid decimal escape")
            octal = re.compile("[0-3][0-7]{0,2}|[4-7][0-7]?").match(self.src, self.pos)
            assert octal is not None
            self.pos = octal.end()
            return _lit(_chr(int(octal.group(0), 8))), True
        if char in "123456789":
            digits = re.compile("[0-9]+").match(self.src, self.pos)
            assert digits is not None
            value = int(digits.group(0))
            if value <= self.group_count:
                self.pos = digits.end()
                return self._backreference(value), True
            if self.unicode:
                raise self._fail("invalid escape")
            if char in "89":
                self.pos += 1
                return _lit(char), True
            octal = re.compile("[0-3][0-7]{0,2}|[4-7][0-7]?").match(self.src, self.pos)
            assert octal is not None
            self.pos = octal.end()
            return _lit(_chr(int(octal.group(0), 8))), True
        escaped = self._character_escape(False)
        if escaped is None:
            raise self._fail("invalid escape")
        if escaped == "\\" and char == "c":
            return _lit("\\"), True
        return _lit(escaped), True

    def _backreference(self, number: int) -> str:
        """``\\N``: the captured text when group N has participated, else the empty string (JavaScript
        semantics; a group that is not closed yet, including a forward reference, never has)."""
        if number not in self.closed:
            return "(?:)"
        return f"(?:(?({number})\\{number}|))"

    def _all_names(self) -> dict[str, int]:
        if not hasattr(self, "_names_cache"):
            names: dict[str, int] = {}
            src = self.src
            i = 0
            index = 0
            in_class = False
            while i < len(src):
                char = src[i]
                if char == "\\":
                    i += 2
                    continue
                if in_class:
                    in_class = char != "]"
                elif char == "[":
                    in_class = True
                elif char == "(":
                    if src[i + 1 : i + 2] != "?":
                        index += 1
                    elif src[i + 2 : i + 3] == "<" and src[i + 3 : i + 4] not in ("=", "!"):
                        index += 1
                        end = src.find(">", i)
                        if end > 0:
                            names.setdefault(src[i + 3 : end], index)
                i += 1
            self._names_cache = names
        return self._names_cache

    # -- character classes ----------------------------------------------------------------------
    def _class(self) -> str:
        self.pos += 1  # [
        negated = False
        if self._peek() == "^":
            negated = True
            self.pos += 1
        items: list[str] = []
        while True:
            if self.pos >= len(self.src):
                raise self._fail("unterminated character class")
            char = self._peek()
            if char == "]":
                self.pos += 1
                break
            item = self._class_atom()
            if item[0] == "set":
                items.append(item[1])
                if self.unicode and self._peek() == "-" and self._peek(1) not in ("]", ""):
                    raise self._fail("invalid character class")
                continue
            # A single character: a range when ``-`` and another single character follow.
            if self._peek() == "-" and self._peek(1) not in ("]", ""):
                self.pos += 1
                end_item = self._class_atom()
                if end_item[0] == "set":
                    if self.unicode:
                        raise self._fail("invalid character class")
                    items.extend([_lit(item[1]), _lit("-"), end_item[1]])
                    continue
                if ord(end_item[1]) < ord(item[1]):
                    raise self._fail("range out of order in character class")
                items.append(f"{_lit(item[1])}-{_lit(end_item[1])}")
                continue
            items.append(_lit(item[1]))
        body = "".join(items)
        if not items:
            result = "[\\s\\S]" if negated else "(?!)"
        else:
            result = f"[{'^' if negated else ''}{body}]"
        return result

    def _class_atom(self) -> tuple[str, str, bool]:
        """One class member: ``("char", char, False)`` or ``("set", python class body, False)``."""
        char = self._peek()
        self.pos += 1
        if char != "\\":
            return ("char", char, False)
        escaped = self._peek()
        word = self.word
        if escaped == "d":
            self.pos += 1
            return ("set", "0-9", False)
        if escaped == "w":
            self.pos += 1
            return ("set", word, False)
        if escaped == "s":
            self.pos += 1
            return ("set", JS_SPACE_CLASS, False)
        if escaped == "D":
            self.pos += 1
            return ("set", _complement_body(_DIGIT_INTERVALS), False)
        if escaped == "W":
            self.pos += 1
            return ("set", _complement_body(_WORD_IU_INTERVALS if self.word != "A-Za-z0-9_" else _WORD_INTERVALS), False)
        if escaped == "S":
            self.pos += 1
            return ("set", _complement_body(_SPACE_INTERVALS), False)
        if escaped == "b":
            self.pos += 1
            return ("char", "\b", False)
        if escaped == "-" :
            self.pos += 1
            return ("char", "-", False)
        if escaped in ("p", "P") and self.unicode:
            return ("set", self._property_escape(), False)
        if escaped in "123456789" or escaped == "0":
            if self.unicode:
                if escaped == "0" and not _ascii_digit(self._peek(1)):
                    self.pos += 1
                    return ("char", "\x00", False)
                raise self._fail("invalid class escape")
            octal = re.compile("[0-3][0-7]{0,2}|[4-7][0-7]?").match(self.src, self.pos)
            if octal is None:
                self.pos += 1
                return ("char", escaped, False)
            self.pos = octal.end()
            return ("char", _chr(int(octal.group(0), 8)), False)
        value = self._character_escape(True)
        if value is None:
            raise self._fail("invalid class escape")
        if value == "\\" and escaped == "c":
            return ("char", "\\", False)
        return ("char", value, False)


@dataclass(frozen=True)
class UserRegex:
    """A translated user pattern: the Python regex and the JavaScript flags that shape matching."""

    regex: re.Pattern[str]
    source: str
    flags: str
    unicode: bool
    sticky: bool


def translate_user_regex(source: str, flags: str) -> UserRegex:
    """Translate JavaScript regex ``source``/``flags`` (see the module docstring).

    Raises :class:`InvalidRegexError` where ``new RegExp`` throws and
    :class:`UnsupportedRegexError` where this port cannot translate a valid pattern.
    """
    if len(set(flags)) != len(flags) or any(flag not in "dgimsuvy" for flag in flags):
        raise InvalidRegexError("invalid flags")
    if "v" in flags:
        raise UnsupportedRegexError("the v flag")
    translated = _Translator(source, flags).translate()
    try:
        compiled = re.compile(translated, re.IGNORECASE if "i" in flags else 0)
    except re.error as error:
        text = str(error)
        if "look-behind" in text:
            raise UnsupportedRegexError(text) from error
        raise InvalidRegexError(text) from error
    except (OverflowError, RecursionError) as error:
        raise UnsupportedRegexError(str(error)) from error
    return UserRegex(compiled, source, flags, "u" in flags, "y" in flags)


# --- parseRedactPatternSource / compileConfigRegex -----------------------------------------------
def parse_redact_pattern_source(raw: str) -> tuple[str, str]:
    """``parseRedactPatternSource``: a ``/literal/flags`` keeps its flags, any other string is ``gi``."""
    literal = _LITERAL_RE.match(raw)
    if literal is None:
        return raw, "gi"
    flags = literal.group(2)
    return literal.group(1), flags if "g" in flags else f"{flags}g"


@dataclass(frozen=True)
class CompiledConfigRegex:
    """``compileConfigRegex``: ``regex`` is ``None`` with a ``reason`` when the entry is rejected."""

    regex: UserRegex | None
    pattern: str
    flags: str
    reason: RejectReason | None


def compile_config_regex(pattern: str, flags: str = "") -> CompiledConfigRegex | None:
    """Compile one user-configured regex; ``None`` for a blank entry (skipped silently)."""
    trimmed = js_trim(pattern)
    if not trimmed:
        return None
    return _compile_safe(trimmed, flags)


@lru_cache(maxsize=256)
def _compile_safe(trimmed: str, flags: str) -> CompiledConfigRegex:
    if _has_nested_repetition(to_units(trimmed)):
        return CompiledConfigRegex(None, trimmed, flags, "unsafe-nested-repetition")
    try:
        return CompiledConfigRegex(translate_user_regex(trimmed, flags), trimmed, flags, None)
    except InvalidRegexError:
        return CompiledConfigRegex(None, trimmed, flags, "invalid-regex")
    except UnsupportedRegexError:
        return CompiledConfigRegex(None, trimmed, flags, "unsupported-syntax")


def compile_redact_pattern(raw: str) -> CompiledConfigRegex | None:
    """One ``logging.redactPatterns`` entry: ``compileConfigRegex(...parseRedactPatternSource(raw))``."""
    if not js_trim(raw):
        return None
    source, flags = parse_redact_pattern_source(raw)
    return compile_config_regex(source, flags)
