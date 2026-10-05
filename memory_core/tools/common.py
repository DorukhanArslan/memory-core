"""Tool parameter readers and the tool-facing error contract.

Port of OpenClaw's built-in tool helpers:

- ``src/agents/tools/common.ts``: ``ToolInputError`` (status 400),
  ``asToolParamsRecord``, ``readStringParam``, ``readNumberParam`` (strict
  mode), ``readPositiveIntegerParam`` and ``readFiniteNumberParam``.
- ``src/param-key.ts``: a camelCase key also resolves its snake_case alias
  (``maxResults`` -> ``max_results``) when the camelCase key is absent.
- ``packages/normalization-core/src/number-coercion.ts``:
  ``parseStrictFiniteNumber`` and ``asPositiveSafeInteger``.
- ``src/agents/agent-tool-definition-adapter.ts``: a thrown tool error reaches
  the model as ``{"status": "error", "tool": <name>, "error": <message>}``
  (``buildToolExecutionErrorResult`` with ``describeToolExecutionError``).
- ``src/infra/errors.ts``: ``formatErrorMessage`` (cause chain, no redaction).

Values follow JavaScript semantics: ``True``/``False`` are not numbers,
strings are trimmed with the ECMAScript whitespace set, and numeric strings
must match the strict decimal/scientific token regex before they parse.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from memory_core.bootstrap._js import js_trim

# Number.MAX_SAFE_INTEGER.
MAX_SAFE_INTEGER = 2**53 - 1

# number-coercion.ts parseStrictFiniteNumber: /^[+-]?(?:(?:\d+\.?\d*)|(?:\.\d+))(?:e[+-]?\d+)?$/i
# (JavaScript \d is ASCII-only and `$` does not match before a trailing newline).
_STRICT_FINITE_NUMBER_RE = re.compile(
    r"[+-]?(?:(?:[0-9]+\.?[0-9]*)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?"
)
_SNAKE_ACRONYM_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_SNAKE_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")

_MISSING = object()


class MemoryToolInputError(ValueError):
    """Invalid tool input (OpenClaw ``ToolInputError``, HTTP-like status 400).

    Raised before any search work starts. Hosts that run a tool loop turn it
    into the tool result the model sees with :meth:`to_tool_error`.
    """

    status = 400

    def __init__(self, message: str, *, tool: str | None = None):
        super().__init__(message)
        self.message = message
        self.tool = tool

    def to_tool_error(self, tool: str | None = None) -> dict[str, str]:
        return to_tool_error(self, tool=tool or self.tool or "tool")


def to_tool_error(error: BaseException, *, tool: str) -> dict[str, str]:
    """Tool-facing serialization of an exception raised by a tool.

    ``agent-tool-definition-adapter.ts`` ``buildToolExecutionErrorResult``:
    ``{"status": "error", "tool": <name>, "error": <message>}``, where the
    message is the error message, or the error's string form when the message
    is blank (``describeToolExecutionError``).
    """
    message = str(error)
    if not message.strip():
        message = type(error).__name__
    return {"status": "error", "tool": tool, "error": message}


def format_error_message(error: object) -> str:
    """``formatErrorMessage`` (``src/infra/errors.ts:69-111``) without redaction.

    An exception reads as its message (its type name when blank), followed by
    each explicit ``raise ... from`` cause message and string/number ``code``
    as `` | <text>``, skipping repeats. Upstream then runs a best-effort token
    redaction (``redactSensitiveText``); memory-core does not port it, so hosts
    whose provider errors can carry secrets should redact tool results.
    """
    if isinstance(error, BaseException):
        formatted = str(error) or type(error).__name__
        seen: set[int] = {id(error)}
        seen_messages = {formatted}

        def append(message: str) -> None:
            nonlocal formatted
            if not message or message in seen_messages:
                return
            formatted += f" | {message}"
            seen_messages.add(message)

        cause = error.__cause__
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            append(str(cause))
            code = getattr(cause, "code", None)
            if isinstance(code, str):
                append(code)
            elif isinstance(code, int | float) and not isinstance(code, bool):
                append(str(code))
            cause = cause.__cause__
        return formatted
    if isinstance(error, str):
        return error
    return str(error)


def as_tool_params_record(params: object) -> Mapping[str, Any]:
    """``asToolParamsRecord``: anything but a mapping reads as ``{}``."""
    return params if isinstance(params, Mapping) else {}


def _to_snake_case_key(key: str) -> str:
    return _SNAKE_BOUNDARY_RE.sub(r"\1_\2", _SNAKE_ACRONYM_RE.sub(r"\1_\2", key)).lower()


def resolve_snake_case_param_key(params: Mapping[str, Any], key: str) -> str | None:
    """``param-key.ts`` ``resolveSnakeCaseParamKey``: the exact key wins."""
    if key in params:
        return key
    snake_key = _to_snake_case_key(key)
    if snake_key != key and snake_key in params:
        return snake_key
    return None


def _read_param_raw(params: Mapping[str, Any], key: str) -> Any:
    resolved = resolve_snake_case_param_key(params, key)
    return params[resolved] if resolved is not None else _MISSING


def _is_nullish(raw: Any) -> bool:
    # JavaScript `raw == null`: undefined (missing key) or null (None).
    return raw is _MISSING or raw is None


def _is_blank_string(raw: Any) -> bool:
    return isinstance(raw, str) and js_trim(raw) == ""


def _as_js_number(raw: Any) -> float | int | None:
    """The finite JavaScript number a Python value stands for, else None."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    if isinstance(raw, int):
        try:
            as_float = float(raw)
        except OverflowError:
            return None
        return raw if math.isfinite(as_float) else None
    return raw if math.isfinite(raw) else None


def parse_strict_finite_number(value: object) -> float | int | None:
    """``parseStrictFiniteNumber``: finite numbers and strict numeric strings."""
    if not isinstance(value, str):
        return _as_js_number(value)
    normalized = js_trim(value)
    if not normalized or _STRICT_FINITE_NUMBER_RE.fullmatch(normalized) is None:
        return None
    parsed = float(normalized)
    return parsed if math.isfinite(parsed) else None


def _as_positive_safe_integer(value: float | int) -> int | None:
    if isinstance(value, float) and not value.is_integer():
        return None
    if abs(value) > MAX_SAFE_INTEGER or value <= 0:
        return None
    return int(value)


def _read_strict_number(params: Mapping[str, Any], key: str) -> float | int | None:
    # readNumberParam(params, key, { strict: true }) without `required`.
    raw = _read_param_raw(params, key)
    number = _as_js_number(raw)
    if number is not None:
        return number
    if isinstance(raw, str):
        trimmed = js_trim(raw)
        if trimmed:
            return parse_strict_finite_number(trimmed)
    return None


def read_string_param(
    params: Mapping[str, Any],
    key: str,
    *,
    required: bool = False,
    trim: bool = True,
    label: str | None = None,
    allow_empty: bool = False,
) -> str | None:
    """``readStringParam``: non-strings and blank strings read as missing."""
    label = label or key
    raw = _read_param_raw(params, key)
    if not isinstance(raw, str):
        if required:
            raise MemoryToolInputError(f"{label} required")
        return None
    value = js_trim(raw) if trim else raw
    if not value and not allow_empty:
        if required:
            raise MemoryToolInputError(f"{label} required")
        return None
    return value


def read_positive_integer_param(
    params: Mapping[str, Any],
    key: str,
    *,
    message: str | None = None,
    max_value: int | None = None,
) -> int | None:
    """``readPositiveIntegerParam``: present but not a positive safe integer raises."""
    number = _read_strict_number(params, key)
    value = _as_positive_safe_integer(number) if number is not None else None
    error_message = message or f"{key} must be a positive integer"
    raw = _read_param_raw(params, key)
    # A blank string reads as omitted (common.ts isBlankParamValue).
    if value is None and not _is_nullish(raw) and not _is_blank_string(raw):
        raise MemoryToolInputError(error_message)
    if value is not None and max_value is not None and value > max_value:
        raise MemoryToolInputError(error_message)
    return value


def read_finite_number_param(
    params: Mapping[str, Any],
    key: str,
    *,
    message: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    min_exclusive: bool = False,
    max_exclusive: bool = False,
) -> float | None:
    """``readFiniteNumberParam``: present but not a finite number raises."""
    value = _read_strict_number(params, key)
    error_message = message or f"{key} must be a finite number"
    if value is None:
        if not _is_nullish(_read_param_raw(params, key)):
            raise MemoryToolInputError(error_message)
        return None
    if min_value is not None:
        below = value <= min_value if min_exclusive else value < min_value
        if below:
            raise MemoryToolInputError(error_message)
    if max_value is not None:
        above = value >= max_value if max_exclusive else value > max_value
        if above:
            raise MemoryToolInputError(error_message)
    return float(value)


def read_corpus_param(
    params: Mapping[str, Any], allowed: Sequence[str]
) -> str | None:
    """``readCorpusParam`` (tools.ts): an unknown corpus fails closed, not as a wider search."""
    raw = read_string_param(params, "corpus")
    if raw is None:
        return None
    if raw in allowed:
        return raw
    raise MemoryToolInputError(f"corpus must be one of: {', '.join(allowed)}")
