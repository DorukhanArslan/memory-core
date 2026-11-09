"""Ordinary inline-image transcript normalization before credential redaction.

Ports ``agents/transcript-redact-images.ts`` and reuses the actual base64/data
URL byte-signature owner. This does not migrate media or provider replay state.
"""
from collections.abc import Mapping
from typing import Any

from memory_core.bootstrap._js import js_trim
from memory_core.inline_image import sanitize_inline_image_base64, sanitize_inline_image_data_url_for_storage


def _mime(value: object) -> str | None:
    if isinstance(value, str) and js_trim(value).lower().startswith("image/"):
        return js_trim(value).lower()
    return None


def sanitize_transcript_image_record(source: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if source.get("type") not in ("image", "base64") or not isinstance(source.get("data"), str):
        return None
    fields = [key for key in ("mimeType", "mediaType", "media_type") if _mime(source.get(key)) is not None]
    if not fields:
        return None
    sanitized = sanitize_inline_image_base64(_mime(source[fields[0]]), source["data"])
    if sanitized is None:
        return None
    if source["data"] == sanitized.base64 and all(source[key] == sanitized.mime_type for key in fields):
        return source
    return {**source, "data": sanitized.base64, **{key: sanitized.mime_type for key in fields}}


def sanitize_transcript_image_data_url_field(
    source: Mapping[str, Any], key: str, value: str, preserve_image_data_url_fields: bool,
) -> str | None:
    if value[:5].lower() != "data:":
        return None
    image_field = (
        preserve_image_data_url_fields and key == "url"
        or source.get("type") == "input_image" and key == "image_url"
        or source.get("type") in ("image", "image_url") and key == "url"
        or source.get("type") == "image" and key in ("source", "data")
    )
    return sanitize_inline_image_data_url_for_storage(value) if image_field else None


def should_preserve_nested_transcript_image_data_url_fields(source: Mapping[str, Any], key: str) -> bool:
    return key == "image_url" and source.get("type") in ("image_url", "input_image", "image")
