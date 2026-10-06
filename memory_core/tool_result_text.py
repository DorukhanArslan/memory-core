"""Tool-result text extraction (packages/ai/src/providers/tool-result-text.ts).

``extractToolResultText`` turns the content blocks of a tool result into the text a provider
transport sends: text blocks verbatim, other blocks as redacted, bounded JSON. Also here:
``sanitizeSurrogates`` (utils/sanitize-unicode.ts) and the transport payload text helpers
(``sanitizeTransportPayloadText``, ``sanitizeNonEmptyTransportPayloadText``).

Redaction: upstream redacts through the host's ``redactModelVisibleSecrets``; the default here is
:func:`memory_core.redact.redact_model_visible_secrets` (tool-payload patterns, field-name masks);
a host passes its own ``redact`` to replace it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from typing import Any

from memory_core.bootstrap._js import (
    JS_SPACE_CLASS,
    _from_units,
    _units,
    js_json_stringify,
    js_trim,
    truncate_utf16_safe,
    utf16_len,
)
from memory_core.compaction_replay import _js_number_to_string
from memory_core.redact import redact_model_visible_secrets

STRUCTURED_TOOL_RESULT_MAX_CHARS = 8000
EMPTY_TOOL_RESULT_TEXT = "(no output)"
_IMAGE_TYPES = frozenset({"image", "image_url", "input_image"})
_AUDIO_TYPES = frozenset({"audio", "input_audio", "output_audio"})
_MEDIA_ONLY_TYPES = _IMAGE_TYPES | _AUDIO_TYPES
_MIME_KEYS = (
    "mimeType",
    "mime_type",
    "mediaType",
    "media_type",
    "contentType",
    "content_type",
)
_INLINE_DATA_URI = re.compile(
    r"(^|[^A-Za-z0-9_])data:([a-z][a-z0-9.+-]*/[a-z0-9.+-]+"
    r"(?:;[a-z0-9.+-]+=[^,;\"'" + JS_SPACE_CLASS + r"]+|;base64)*"
    r",[^" + JS_SPACE_CLASS + r"\"'<>)]+)",
    re.IGNORECASE | re.ASCII,
)
_TEXTUAL_MIME = re.compile(
    r"^(?:text/|application/(?:json|ld\+json|x-ndjson|xml|javascript|"
    r"x-www-form-urlencoded)|[^/]+/[^+]+\+(?:json|xml)$)",
    re.IGNORECASE | re.ASCII,
)
_OPAQUE_FIELD = re.compile(
    r"^(?:blob|buffer|bytes|encrypted_content|encrypted_stdout)$", re.IGNORECASE | re.ASCII
)
_ARRAY_INDEX = re.compile(r"^(?:0|[1-9][0-9]{0,9})$")

Redactor = Callable[[Any], Any]


def sanitize_surrogates(text: str) -> str:
    """``sanitizeSurrogates``: drop unpaired UTF-16 surrogates (pairs are kept)."""

    if text.isascii():
        return text
    joined = _from_units(_units(text))
    return re.sub("[\ud800-\udfff]", "", joined)


def sanitize_transport_payload_text(text: Any) -> str:
    """``sanitizeTransportPayloadText``: ``""`` for a non-string."""

    return sanitize_surrogates(text) if isinstance(text, str) else ""


def sanitize_non_empty_transport_payload_text(
    text: Any, fallback: str = EMPTY_TOOL_RESULT_TEXT
) -> str:
    sanitized = sanitize_transport_payload_text(text)
    return sanitized if js_trim(sanitized) else fallback


default_redact_model_visible_secrets = redact_model_visible_secrets


def _read_mime_type(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in _MIME_KEYS:
        mime = value.get(key)
        if isinstance(mime, str) and js_trim(mime):
            return mime
    return None


def _is_binary_mime_type(mime: str) -> bool:
    normalized = js_trim(mime.split(";", 1)[0]).lower()
    return bool(normalized) and not _TEXTUAL_MIME.search(normalized)


def _describe_omitted_value(value: Any, label: str) -> str:
    length = utf16_len(value) if isinstance(value, str) else utf16_len(_stringify(value, None))
    return f"[{label} omitted: {length} chars]" if length else f"[{label} omitted]"


def _redact_inline_data_uris(value: str) -> str:
    return _INLINE_DATA_URI.sub(
        lambda m: f"{m.group(1)}[inline data URI: {utf16_len(m.group(2))} chars]", value
    )


def _js_key_order(keys: Sequence[str]) -> list[str]:
    """Own property order of a JS object: array-index keys ascending, then insertion order."""

    index_keys = [key for key in keys if _ARRAY_INDEX.match(key) and int(key) < 2**32 - 1]
    index_keys.sort(key=int)
    others = [key for key in keys if key not in set(index_keys)]
    return index_keys + others


def _stringify(value: Any, replacer: Callable[[Any, str, Any], Any] | None) -> str:
    """``JSON.stringify(value, replacer)`` for JSON values (the replacer gets ``this, key, value``)."""

    def walk(holder: Any, key: str, node: Any) -> str | None:
        if replacer is not None:
            node = replacer(holder, key, node)
        if node is None:
            return "null"
        if isinstance(node, bool):
            return "true" if node else "false"
        if isinstance(node, str):
            return js_json_stringify(node)
        if isinstance(node, int | float):
            if isinstance(node, float) and not math.isfinite(node):
                return "null"
            return _js_number_to_string(node)
        if isinstance(node, list):
            parts = [walk(node, str(i), item) or "null" for i, item in enumerate(node)]
            return "[" + ",".join(parts) + "]"
        parts = []
        for name in _js_key_order(list(node)):
            text = walk(node, name, node[name])
            if text is not None:
                parts.append(f"{js_json_stringify(name)}:{text}")
        return "{" + ",".join(parts) + "}"

    return walk({"": value}, "", value) or ""


def js_stringify(value: Any) -> str:
    """``JSON.stringify(value)`` for JSON values (JS number text and property order)."""

    return _stringify(value, None)


def _stringify_structured_block(block: Any, redact: Redactor) -> str | None:
    seen: set[int] = set()

    def replacer(holder: Any, key: str, value: Any) -> Any:
        if _OPAQUE_FIELD.match(key):
            return f"[omitted {key}]"
        if key == "data":
            mime = _read_mime_type(holder)
            if mime and _is_binary_mime_type(mime):
                return _describe_omitted_value(value, "binary data")
        if isinstance(value, str):
            return _redact_inline_data_uris(redact(value))
        if not isinstance(value, dict | list):
            return value
        if id(value) in seen:
            return "[Circular]"
        seen.add(id(value))
        return value

    try:
        redacted = redact({"structuredToolResult": block})["structuredToolResult"]
        serialized = _stringify(redacted, replacer)
    except (TypeError, ValueError, RecursionError, KeyError):
        return None
    return None if not serialized or serialized == "{}" else serialized


def _truncate_structured_tool_text(text: str) -> str:
    if utf16_len(text) <= STRUCTURED_TOOL_RESULT_MAX_CHARS:
        return text
    return f"{truncate_utf16_safe(text, STRUCTURED_TOOL_RESULT_MAX_CHARS)}\n…(truncated)…"


def has_media_payload(block: Any) -> bool:
    """``hasMediaPayload``: a record with a non-blank string ``data``."""

    return (
        isinstance(block, dict)
        and isinstance(block.get("data"), str)
        and bool(js_trim(block["data"]))
    )


def is_image_with_media_payload(block: Any) -> bool:
    """``isImageWithMediaPayload``."""

    return isinstance(block, dict) and block.get("type") == "image" and has_media_payload(block)


def _classify_media(blocks: Sequence[Any]) -> tuple[bool, bool]:
    has_image = has_audio = False
    for block in blocks:
        if not has_media_payload(block) or block.get("type") == "text":
            continue
        kind = block.get("type") if isinstance(block.get("type"), str) else None
        mime = (_read_mime_type(block) or "").lower()
        has_image = has_image or bool((kind and kind in _IMAGE_TYPES) or mime.startswith("image/"))
        has_audio = has_audio or bool((kind and kind in _AUDIO_TYPES) or mime.startswith("audio/"))
    return has_image, has_audio


def describe_tool_result_media_placeholder(blocks: Sequence[Any]) -> str | None:
    has_image, has_audio = _classify_media(blocks)
    if has_image and has_audio:
        return "(see attached media)"
    if has_audio:
        return "(see attached audio)"
    return "(see attached image)" if has_image else None


def extract_tool_result_block_text(
    block: Any, redact: Redactor = default_redact_model_visible_secrets
) -> str | None:
    if not isinstance(block, dict | list):
        return None
    record = block if isinstance(block, dict) else {}
    kind = record.get("type")
    if isinstance(kind, str) and kind in _MEDIA_ONLY_TYPES:
        return None
    if kind == "text":
        text = record.get("text") if isinstance(record.get("text"), str) else ""
        return sanitize_surrogates(text) if text else None
    structured = _stringify_structured_block(block, redact)
    return sanitize_surrogates(_truncate_structured_tool_text(structured)) if structured else None


def extract_tool_result_text(
    blocks: Sequence[Any],
    *,
    include_structured: bool = False,
    redact: Redactor = default_redact_model_visible_secrets,
) -> str:
    """``extractToolResultText``. ``blocks`` must be a list (upstream iterates it)."""

    if not isinstance(blocks, list):
        raise TypeError("blocks is not iterable")
    explicit: list[str] = []
    structured_blocks: list[Any] = []
    for block in blocks:
        if not isinstance(block, dict | list):
            continue
        if isinstance(block, dict) and block.get("type") == "text":
            text = extract_tool_result_block_text(block, redact)
            if text:
                explicit.append(text)
        else:
            structured_blocks.append(block)
    if explicit and not include_structured:
        return "\n".join(explicit)
    structured_texts = [
        text
        for text in (extract_tool_result_block_text(b, redact) for b in structured_blocks)
        if text
    ]
    if explicit:
        if structured_texts:
            explicit.append(_truncate_structured_tool_text("\n".join(structured_texts)))
        return "\n".join(explicit)
    return _truncate_structured_tool_text("\n".join(structured_texts))
