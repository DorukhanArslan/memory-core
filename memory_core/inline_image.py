"""Inline image data-URL sanitiser (packages/media-core/src/{base64,inline-image-data-url}.ts).

Provider egress replaces an inline image whose bytes do not match a supported format with a text
placeholder; :mod:`memory_core.responses_egress` builds the Responses payload projection on top of
:func:`sanitize_inline_image_data_url`.

Node's ``Buffer.toString("ascii")`` clears the high bit of every byte, so a signature such as
``RIFF`` also matches ``0xD2 0xC9 0xC6 0xC6``; :func:`_ascii` reproduces that.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from memory_core.bootstrap._js import js_trim, utf16_slice

INLINE_IMAGE_DATA_URL_PREFIX = "data:"
_SIGNATURE_PREFIX_BASE64_CHARS = 128
_PROVIDER_MIMES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
_HEIC_BRANDS = frozenset({"heic", "heix", "hevc", "hevx", "heis", "heim", "hevm", "hevs"})
_HEIF_BRANDS = frozenset({"mif1", "msf1"})


def _base64_value(code: int) -> int:
    if 0x41 <= code <= 0x5A:
        return code - 0x41
    if 0x61 <= code <= 0x7A:
        return code - 0x61 + 26
    if 0x30 <= code <= 0x39:
        return code - 0x30 + 52
    if code == 0x2B:
        return 62
    return 63 if code == 0x2F else -1


def canonicalize_base64(text: str) -> str | None:
    """``canonicalizeBase64``: whitespace-free, padded base64 or ``None`` when malformed."""

    kept: list[str] = []
    padding = 0
    saw_padding = False
    last_value = 0
    for char in text:
        code = ord(char)
        if code <= 0x20:
            continue
        if code == 0x3D:
            padding += 1
            if padding > 2:
                return None
            saw_padding = True
        else:
            value = _base64_value(code)
            if saw_padding or value < 0:
                return None
            last_value = value
        kept.append(char)
    cleaned = "".join(kept)
    if not cleaned:
        return None
    remainder = len(cleaned) % 4
    if remainder != 0 and (saw_padding or remainder == 1):
        return None
    effective_padding = padding if remainder == 0 else 4 - remainder
    mask = 0x0F if effective_padding == 2 else 0x03 if effective_padding == 1 else 0
    if mask and (last_value & mask) != 0:
        return None
    return cleaned if remainder == 0 else cleaned + "=" * (4 - remainder)


def _ascii(data: bytes) -> str:
    """Node's ``"ascii"`` decoding: the high bit of each byte is dropped."""

    return bytes(byte & 0x7F for byte in data).decode("ascii")


def _sniff_iso_bmff(data: bytes) -> str | None:
    if len(data) < 12 or _ascii(data[4:8]) != "ftyp":
        return None
    brands = [_ascii(data[8:12])]
    offset = 16
    while offset + 4 <= len(data):
        brands.append(_ascii(data[offset : offset + 4]))
        offset += 4
    if any(brand in _HEIC_BRANDS for brand in brands):
        return "image/heic"
    if any(brand in _HEIF_BRANDS for brand in brands):
        return "image/heif"
    return None


def sniff_inline_image_mime(data: bytes) -> str | None:
    """``sniffInlineImageMime``: the format named by the leading bytes."""

    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 3 and data[0] == 0xFF and data[1] == 0xD8 and data[2] == 0xFF:
        return "image/jpeg"
    if len(data) >= 12 and _ascii(data[:4]) == "RIFF" and _ascii(data[8:12]) == "WEBP":
        return "image/webp"
    if len(data) >= 6 and _ascii(data[:6]) in ("GIF87a", "GIF89a"):
        return "image/gif"
    if len(data) >= 2 and data[0] == 0x42 and data[1] == 0x4D:
        return "image/bmp"
    return _sniff_iso_bmff(data)


def _is_image_mime(value: str) -> bool:
    return js_trim(value).lower().startswith("image/")


@dataclass(frozen=True)
class SanitizedInlineImageBase64:
    mime_type: str
    base64: str


def sanitize_inline_image_base64(mime_type: str, payload: str) -> SanitizedInlineImageBase64 | None:
    """``sanitizeInlineImageBase64``: canonical base64 whose bytes are a supported image."""

    if not _is_image_mime(mime_type):
        return None
    canonical = canonicalize_base64(payload)
    if not canonical:
        return None
    prefix = canonical[:_SIGNATURE_PREFIX_BASE64_CHARS]
    sniffed = sniff_inline_image_mime(base64.b64decode(prefix))
    if sniffed is None:
        return None
    return SanitizedInlineImageBase64(sniffed, canonical)


def _starts_with_data_url(value: str) -> bool:
    return utf16_slice(value, 0, len(INLINE_IMAGE_DATA_URL_PREFIX)).lower() == "data:"


def _parse(value: str) -> tuple[list[str], str] | None:
    if not _starts_with_data_url(value):
        return [], value
    comma = value.find(",")
    if comma < 0:
        return None
    metadata = [
        js_trim(part) for part in value[len(INLINE_IMAGE_DATA_URL_PREFIX) : comma].split(";")
    ]
    return metadata, value[comma + 1 :]


def _metadata_allows_image_base64(metadata: list[str]) -> bool:
    mime, *options = metadata
    return _is_image_mime(mime) and any(part.lower() == "base64" for part in options)


def _sanitize(image_url: str, allowed: frozenset[str] | None) -> str | None:
    parsed = _parse(image_url)
    if parsed is None:
        return None
    metadata, payload = parsed
    if not metadata:
        return image_url
    if not _metadata_allows_image_base64(metadata):
        return None
    sanitized = sanitize_inline_image_base64(metadata[0], payload)
    if sanitized is None:
        return None
    if allowed is not None and sanitized.mime_type not in allowed:
        return None
    # The byte signature wins over the caller's metadata before the URL is re-inlined.
    return f"data:{sanitized.mime_type};base64,{sanitized.base64}"


def sanitize_inline_image_data_url_for_storage(image_url: str) -> str | None:
    """``sanitizeInlineImageDataUrlForStorage``: every supported signature is accepted."""

    return _sanitize(image_url, None)


def sanitize_inline_image_data_url(image_url: str) -> str | None:
    """``sanitizeInlineImageDataUrl``: provider-safe formats (PNG, JPEG, WebP, GIF) only.

    A value that is not a ``data:`` URL is returned unchanged (remote references pass).
    """

    return _sanitize(image_url, _PROVIDER_MIMES)
