"""Strict incremental report reader; no host execution or acceptance credit.

Promoted from the independently reviewed stream_reader.py, original SHA-256
adf493396ff9060c306503f37d35075248d014679e2e0d42284a94dacab7b6d4.
The tracked reader is self-contained and never imports the work archive.

The root must be an object. Its array-valued members are decoded one item at a
time; nested objects/arrays remain ordinary JSON values. Only successful return
from ``top`` establishes that the entire document was valid.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Callable, TextIO


_WHITESPACE = " \t\r\n"
_DELIMITERS = _WHITESPACE + ",]}:"
_SCALAR_DELIMITER = re.compile(r"[ \t\r\n,\]}:]")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise ValueError(f"Nonfinite JSON constant: {value}")


def _integer(value: str) -> int:
    # Avoid the process-global integer-string digit cap without changing that
    # setting. A long undecided integer prefix may later become a valid float
    # when its decimal/exponent suffix arrives in another input chunk.
    if len(value) < 4000:
        return int(value)
    negative = value.startswith("-")
    digits = value[1:] if negative else value
    result = 0
    for offset in range(0, len(digits), 1000):
        part = digits[offset:offset + 1000]
        result = result * (10 ** len(part)) + int(part)
    return -result if negative else result


def _finite(value: Any) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON number exceeds finite float range")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


class Reader:
    """Read one root object using a bounded input buffer per decoded value.

    ``callback(key, value, True)`` receives each top-level array item, followed
    by ``callback(key, None, 'array-done')`` even for an empty array. Non-array
    members use ``callback(key, value, False)``. Duplicate keys at every depth,
    nonfinite numbers, malformed delimiters and trailing document data fail.
    """

    def __init__(self, path: Path | str, chunk_size: int = 1024 * 1024):
        if type(chunk_size) is not int or chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        self.stream: TextIO = Path(path).open(encoding="utf-8", newline="")
        self.chunk_size = chunk_size
        self.buffer = ""
        self.offset = 0
        self.eof = False
        self.decoder = json.JSONDecoder(
            object_pairs_hook=_object, parse_constant=_constant, parse_int=_integer,
        )

    def close(self) -> None:
        self.stream.close()

    def more(self) -> None:
        if self.eof:
            return
        if self.offset:
            self.buffer = self.buffer[self.offset:]
            self.offset = 0
        chunk = self.stream.read(self.chunk_size)
        self.eof = not chunk
        self.buffer += chunk

    def whitespace(self) -> None:
        while True:
            while self.offset < len(self.buffer) and self.buffer[self.offset] in _WHITESPACE:
                self.offset += 1
            if self.offset < len(self.buffer) or self.eof:
                return
            self.more()

    def peek(self) -> str:
        self.whitespace()
        if self.offset == len(self.buffer):
            raise ValueError("Unexpected end of JSON document")
        return self.buffer[self.offset]

    def char(self, expected: str | None = None) -> str:
        value = self.peek()
        if expected is not None and value != expected:
            raise ValueError(f"Expected JSON token {expected!r}, found {value!r}")
        self.offset += 1
        return value

    def value(self) -> Any:
        first = self.peek()
        if first not in '"{[tfn-0123456789':
            raise ValueError(f"Invalid JSON value start: {first!r}")
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.offset)
            except json.JSONDecodeError:
                if self.eof:
                    raise
                self.more()
                continue
            # A scalar may be only a prefix of a longer number in the next
            # chunk. Keep its entire undecided wire until lookahead is known.
            if end == len(self.buffer) and not self.eof:
                self.more()
                continue
            if end < len(self.buffer) and self.buffer[end] not in _DELIMITERS:
                numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
                if not numeric or self.eof or _SCALAR_DELIMITER.search(self.buffer, end):
                    raise ValueError("Invalid JSON value continuation")
                self.more()
                continue
            # Validate finite numbers only after the entire value is known.
            # An overflowing mantissa prefix can acquire a negative exponent
            # in the next chunk and become finite; rejecting it early is wrong.
            _finite(value)
            self.offset = end
            return value

    def array(self):
        self.char("[")
        if self.peek() == "]":
            self.char("]")
            return
        while True:
            yield self.value()
            separator = self.char()
            if separator == "]":
                return
            if separator != ",":
                raise ValueError("Expected comma or closing bracket in JSON array")
            # The next iteration must parse a value; a trailing comma fails.

    def top(self, callback: Callable[[str, Any, bool | str], Any]) -> None:
        if self.stream.closed:
            raise ValueError("The JSON reader is closed")
        try:
            self.char("{")
            seen = set()
            if self.peek() == "}":
                self.char("}")
            else:
                while True:
                    if self.peek() != '"':
                        raise ValueError("JSON root object keys must be strings")
                    key = self.value()
                    if not isinstance(key, str):
                        raise ValueError("JSON root object keys must be strings")
                    if key in seen:
                        raise ValueError(f"Duplicate JSON root key: {key!r}")
                    seen.add(key)
                    self.char(":")
                    if self.peek() == "[":
                        for item in self.array():
                            callback(key, item, True)
                        callback(key, None, "array-done")
                    else:
                        callback(key, self.value(), False)
                    separator = self.char()
                    if separator == "}":
                        break
                    if separator != ",":
                        raise ValueError("Expected comma or closing brace in JSON object")
                    # A comma requires another quoted key, including at EOF.
            self.whitespace()
            if not self.eof or self.offset != len(self.buffer):
                raise ValueError("Trailing JSON document data")
        finally:
            self.close()
