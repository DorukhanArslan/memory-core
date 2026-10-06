"""Curated-entry ``<!-- project: ... -->`` annotation parsing.

Port of the project half of ``packages/memory-host-sdk/src/host/curated-annotations.ts``
(``scanMemoryAnnotations``, ``normalizeProjectAnnotationKey``,
``extractProjectKeysFromCuratedEntry``) at OpenClaw v2026.9.6.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_iu_keyword_pattern, js_trim

# Upstream: /giu (simple case folding), not Python's wider re.IGNORECASE.
_PROJECT_WORD = js_iu_keyword_pattern("project")
_PROJECT_MARKER = re.compile(rf"<!--[{JS_SPACE_CLASS}]*({_PROJECT_WORD})[{JS_SPACE_CLASS}]*:")
_PROJECT_OPENER = re.compile(rf"<!--[{JS_SPACE_CLASS}]*{_PROJECT_WORD}[{JS_SPACE_CLASS}]*:")
_KEY_FORBIDDEN = re.compile(r"[\r\n<>]")


@dataclass(frozen=True)
class CuratedProjectAnnotations:
    annotated: bool
    valid: bool
    keys: tuple[str, ...]
    raw_count: int
    valid_count: int


def _scan_project_annotations(text: str) -> Iterator[str]:
    """Yield the value of every terminated ``<!-- project: ... -->`` carrier."""
    closing = -1
    position = 0
    while True:
        match = _PROJECT_MARKER.search(text, position)
        if match is None:
            return
        value_start = match.end()
        # Failed carriers can contain later openers; reuse the forward-only delimiter position.
        if closing < value_start:
            closing = text.find("-->", value_start)
            if closing < 0:
                return
        yield js_trim(text[value_start:closing])
        position = closing + 3


def normalize_project_annotation_key(value: str) -> str | None:
    """``normalizeProjectAnnotationKey``: the host part of a remote key is lower-cased."""
    trimmed = js_trim(value)
    if not trimmed or _KEY_FORBIDDEN.search(trimmed):
        return None
    if trimmed.startswith("path:"):
        return trimmed
    separator = trimmed.find("/")
    if separator < 1:
        return trimmed
    return f"{trimmed[:separator].lower()}{trimmed[separator:]}"


def extract_project_keys_from_curated_entry(text: str) -> CuratedProjectAnnotations:
    """``extractProjectKeysFromCuratedEntry``."""
    keys: dict[str, None] = {}
    marker_count = len(_PROJECT_OPENER.findall(text))
    parsed_count = 0
    raw_count = 0
    valid_count = 0
    for value in _scan_project_annotations(text):
        parsed_count += 1
        for raw_key in value.split(";"):
            raw_count += 1
            key = normalize_project_annotation_key(raw_key)
            if key:
                keys[key] = None
                valid_count += 1
    annotated = marker_count > 0
    return CuratedProjectAnnotations(
        annotated=annotated,
        valid=not annotated
        or (parsed_count == marker_count and raw_count > 0 and raw_count == valid_count),
        keys=tuple(keys),
        raw_count=raw_count,
        valid_count=valid_count,
    )
