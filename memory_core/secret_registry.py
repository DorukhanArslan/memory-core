"""Port of OpenClaw's exact-secret-value registry (``src/logging/secret-redaction-registry.ts``).

A host registers the secrets it resolved (API keys, tokens, passwords) and every redaction entry
point in :mod:`memory_core.redact` replaces the exact occurrences of those values before any
pattern runs, whatever the surrounding text looks like. The registry is process-global, like the
upstream singleton.

Rules ported verbatim:

- a value shorter than 6 UTF-16 units is ignored (``MIN_SECRET_VALUE_LENGTH``);
- registering a value also registers its ``encodeURIComponent`` form (URL egress percent-encodes
  injected values) and its ``JSON.stringify`` string-content form (structured payloads are
  serialized before persistence), each only when it differs from the raw value, and the raw value
  last, so it is the newest entry when the bounded registry evicts;
- at most 512 distinct entries are kept, oldest first out (insertion order); registering a value
  that is already present only moves it to the newest position and does not invalidate;
- the matcher buckets the values by their first 6 units, longest value first (stable among equal
  lengths), scans for those prefixes left to right, takes the first bucket entry that continues
  at that position and resumes after it; a rejected prefix resumes one unit later. Matches never
  overlap and the earliest start wins, the longest value wins at a start;
- the revision counter changes whenever the membership changes (insertion of a new value,
  eviction) and is what upstream caches key on.

JavaScript strings are UTF-16: lengths, the 6-unit prefix and match indexes count code units. A
Python ``str`` here is read as code points and converted for those three purposes, so an
astral character counts as two units, exactly as upstream. ``encodeURIComponent`` throws on a lone
surrogate; :func:`register_secret_value_for_redaction` raises ``ValueError`` for it, before it
registers anything.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterable
from typing import NamedTuple
from urllib.parse import quote

MIN_SECRET_VALUE_LENGTH = 6
MAX_SECRET_VALUES = 512

_LOCK = threading.RLock()
_registered: dict[str, bool] = {}
_revision = 0
_redactor: Callable[[str, Callable[[str, int], str]], str] | None = None

_ASTRAL_RE = re.compile("[\U00010000-\U0010ffff]")
_SURROGATE_PAIR_RE = re.compile("[\ud800-\udbff][\udc00-\udfff]")
_LONE_SURROGATE_RE = re.compile("[\ud800-\udfff]")


def _to_units(text: str) -> str:
    """The string as UTF-16 code units (astral characters become two surrogate characters)."""
    return (
        text
        if text.isascii()
        else _ASTRAL_RE.sub(
            lambda m: chr(0xD800 + ((ord(m.group(0)) - 0x10000) >> 10))
            + chr(0xDC00 + ((ord(m.group(0)) - 0x10000) & 0x3FF)),
            text,
        )
    )


def _from_units(text: str) -> str:
    """Join adjacent surrogate halves back into code points."""
    return (
        text
        if text.isascii()
        else _SURROGATE_PAIR_RE.sub(
            lambda m: chr(0x10000 + ((ord(m.group(0)[0]) - 0xD800) << 10) + (ord(m.group(0)[1]) - 0xDC00)),
            text,
        )
    )


def _invalidate() -> None:
    global _revision, _redactor
    _revision += 1
    _redactor = None


def _register_one(value: str) -> None:
    if value in _registered:
        del _registered[value]
        _registered[value] = True
        return
    _registered[value] = True
    while len(_registered) > MAX_SECRET_VALUES:
        del _registered[next(iter(_registered))]
    _invalidate()


def encode_uri_component(value: str) -> str:
    """JavaScript ``encodeURIComponent`` (raises ``ValueError`` on a lone surrogate, like URIError)."""
    units = _to_units(value)
    if _LONE_SURROGATE_RE.search(_from_units(units)):
        raise ValueError("URI malformed")
    return quote(_from_units(units), safe="-_.!~*'()")


def json_string_content(value: str) -> str:
    """``JSON.stringify(value).slice(1, -1)``: the escaped content without the quotes."""
    encoded = json.dumps(value, ensure_ascii=False)[1:-1]
    # JSON.stringify writes a lone surrogate as a lower-case \udXXX escape.
    return _LONE_SURROGATE_RE.sub(lambda m: f"\\u{ord(m.group(0)):04x}", encoded)


def register_secret_value_for_redaction(value: str) -> None:
    """Register one resolved secret for exact-value redaction (``registerSecretValueForRedaction``)."""
    value = _from_units(value)
    if len(_to_units(value)) < MIN_SECRET_VALUE_LENGTH:
        return
    with _LOCK:
        encoded = encode_uri_component(value)
        if encoded != value:
            _register_one(encoded)
        json_escaped = json_string_content(value)
        if json_escaped != value:
            _register_one(json_escaped)
        # The raw value stays newest so bounded eviction cannot drop the active credential.
        _register_one(value)


def register_secret_values_for_redaction(values: Iterable[str]) -> None:
    """Register several secrets in order (each as :func:`register_secret_value_for_redaction`)."""
    for value in values:
        register_secret_value_for_redaction(value)


def is_secret_value_registered_for_redaction(value: str) -> bool:
    """Whether the exact value (raw, percent-encoded or JSON-escaped form) is registered."""
    with _LOCK:
        return value in _registered


def has_registered_secret_values_for_redaction() -> bool:
    with _LOCK:
        return bool(_registered)


def get_secret_redaction_registry_revision() -> int:
    """Changes with registry membership, including bounded eviction and resets."""
    with _LOCK:
        return _revision


class RegistrySnapshot(NamedTuple):
    """``captureSecretRedactionRegistrySnapshot``: the revision and every exact surface form."""

    revision: int
    values: tuple[str, ...]


def capture_secret_redaction_registry_snapshot() -> RegistrySnapshot:
    """Exact surface forms are already expanded; a snapshot must not register them again."""
    with _LOCK:
        return RegistrySnapshot(_revision, tuple(_registered))


def reset_secret_redaction_registry() -> None:
    """Drop every registered value (a host's shutdown or test hook; bumps the revision)."""
    with _LOCK:
        _registered.clear()
        _invalidate()


def create_secret_value_redactor(
    values: Iterable[str],
) -> Callable[[str, Callable[[str, int], str]], str]:
    """``createSecretValueRedactor``: ``redact(text, mask)`` over a fixed value list.

    ``mask(value, index)`` receives the matched value and its UTF-16 offset in the text and
    returns the replacement.
    """
    unit_values = [_to_units(value) for value in values]
    compiled: tuple[re.Pattern[str], dict[str, list[str]]] | None = None

    def redact(text: str, mask: Callable[[str, int], str]) -> str:
        nonlocal compiled
        if not text or not unit_values:
            return text
        units = _to_units(text)
        if compiled is None:
            buckets: dict[str, list[str]] = {}
            # Stable longest-first sort, like Array.prototype.toSorted.
            for value in sorted(unit_values, key=lambda item: -len(item)):
                buckets.setdefault(value[:MIN_SECRET_VALUE_LENGTH], []).append(value)
            compiled = (re.compile("|".join(re.escape(prefix) for prefix in buckets)), buckets)
        prefixes, buckets = compiled
        matches: list[tuple[int, str]] = []
        position = 0
        while True:
            found = prefixes.search(units, position)
            if found is None:
                break
            index = found.start()
            value = next(
                (candidate for candidate in buckets.get(found.group(0), ()) if units.startswith(candidate, index)),
                None,
            )
            if value is not None:
                matches.append((index, value))
            # A rejected prefix may overlap a real match beginning one code unit later.
            position = index + (len(value) if value is not None else 1)
        if not matches:
            return text
        result: list[str] = []
        cursor = 0
        for index, value in matches:
            result.append(units[cursor:index])
            result.append(_to_units(mask(_from_units(value), index)))
            cursor = index + len(value)
        result.append(units[cursor:])
        return _from_units("".join(result))

    return redact


def redact_registered_secret_values(text: str, mask: Callable[[str, int], str]) -> str:
    """Replace every exact occurrence of a registered value (``redactRegisteredSecretValues``)."""
    global _redactor
    if not text:
        return text
    with _LOCK:
        if not _registered:
            return text
        if _redactor is None:
            _redactor = create_secret_value_redactor(tuple(_registered))
        redactor = _redactor
    return redactor(text, mask)
