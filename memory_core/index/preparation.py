"""Index preparation metadata from the pinned native memory entry contract.

Callers supply validated canonical source paths and optional recorded host
provenance. Comments can carry recall annotations; they never grant trust.
Chunk provenance is reduced before session line ranges are remapped.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import math
import ntpath
import posixpath
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_iu_keyword_pattern, js_trim, js_trim_end
from memory_core.consolidation.curated_annotations import extract_project_keys_from_curated_entry
from memory_core.index.publication import ChunkProvenance, ChunkRecallMetadata

import re


INVALID_PROJECT_ANNOTATION_KEY = "!invalid-project-annotation"
_KINDS = "|".join(js_iu_keyword_pattern(word) for word in ("trigger", "importance", "project"))
_MARKER = re.compile(rf"<!--[{JS_SPACE_CLASS}]*({_KINDS})[{JS_SPACE_CLASS}]*:")
_USER_FILE = re.compile(r"users/[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}/USER\.md\Z")
_ASCII_DIGITS = re.compile(r"[0-9]+\Z")
_LINE_BREAK = re.compile(r"[\r\n]")
_HORIZONTAL_SPACE = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class _Annotation:
    start: int
    end: int
    kind: str
    value: str


def _scan_memory_annotations(text: str, *, line_scoped: bool = False) -> Iterator[_Annotation]:
    closing = newline = -1
    position = 0
    while (match := _MARKER.search(text, position)) is not None:
        value_start = match.end()
        position = value_start
        # Keep delimiter positions forward-only. Failed line-scoped carriers
        # can contain later openers, which must still be considered.
        if closing < value_start:
            closing = text.find("-->", value_start)
            if closing < 0:
                return
        if line_scoped:
            if newline < value_start:
                line_break = _LINE_BREAK.search(text, value_start)
                newline = line_break.start() if line_break else len(text)
            if newline < closing:
                continue
        yield _Annotation(match.start(), closing + 3, match[1].lower(),
                          js_trim(text[value_start:closing]))
        position = closing + 3


def strip_memory_annotation_carriers(text: str) -> str:
    """Remove only complete line-scoped native trigger/importance/project carriers."""
    parts = []
    cursor = 0
    for annotation in _scan_memory_annotations(text, line_scoped=True):
        parts.append(text[cursor:annotation.start])
        cursor = annotation.end
    if cursor == 0:
        return text
    parts.append(text[cursor:])
    result = "".join(parts)

    def trim_line_tail(match: re.Match) -> str:
        return "" if match.end() == len(result) or result[match.end()] in "\r\n\u2028\u2029" else match[0]

    return _HORIZONTAL_SPACE.sub(trim_line_tail, result)


def extract_curated_entry_recall_metadata(
    *,
    source_lines: Sequence[str],
    curated_root: bool,
    project_scope_eligible: bool,
) -> ChunkRecallMetadata:
    """Preserve ordered trigger phrases and fail-closed project annotations."""
    phrases: dict[str, None] = {}
    importance = None
    project = (extract_project_keys_from_curated_entry("\n".join(source_lines))
               if project_scope_eligible else None)
    for line in source_lines if curated_root else ():
        if not js_trim_end(line).endswith("-->"):
            continue
        for annotation in _scan_memory_annotations(line):
            if annotation.kind == "trigger":
                for part in re.split(r"[,;]", annotation.value):
                    phrase = js_trim(part)
                    if phrase:
                        phrases[phrase] = None
            elif annotation.kind == "importance" and _ASCII_DIGITS.fullmatch(annotation.value):
                # Values outside 1..10 do not need conversion to an arbitrarily
                # large Python integer (native parseInt can return Infinity).
                digits = annotation.value.lstrip("0") or "0"
                if len(digits) <= 2:
                    parsed = int(digits)
                    if 1 <= parsed <= 10:
                        importance = max(importance if importance is not None else parsed, parsed)
    if project is not None and project.annotated and not project.valid:
        project_key = INVALID_PROJECT_ANNOTATION_KEY
    elif project is not None and project.keys:
        project_key = "; ".join(project.keys)
    else:
        project_key = None
    return ChunkRecallMetadata(importance, "; ".join(phrases) if phrases else None, project_key)


def classify_memory_path(
    relative_path: str,
    source: str = "memory",
    recorded_origin: str | None = None,
) -> dict[str, Any]:
    """Classify a canonical relative path already checked by its filesystem owner.

    Actual realpath/containment and recorded-provenance lookup belong to the
    source reader. A noncanonical or non-memory input remains untrusted here.
    """
    untrusted = {"curatedRoot": False, "originClass": "untrusted"}
    if (source != "memory" or not relative_path or relative_path in (".", "..")
            or relative_path.startswith("../") or posixpath.isabs(relative_path)
            or ntpath.isabs(relative_path) or "\\" in relative_path or "\0" in relative_path
            or posixpath.normpath(relative_path) != relative_path):
        return untrusted
    segments = relative_path.split("/")
    curated = len(segments) == 1 and segments[0] in ("MEMORY.md", "memory.md", "USER.md")
    if ((len(segments) == 1 and segments[0] in ("DREAMS.md", "dreams.md"))
            or (len(segments) > 1 and segments[0] == "memory"
                and segments[1] in ("dreaming", ".dreams"))):
        return {"curatedRoot": curated, "originClass": "system"}
    workspace_memory = (curated or _USER_FILE.fullmatch(relative_path) is not None
                        or (segments[0] == "memory" and segments[-1].endswith(".md")))
    origin = (recorded_origin if workspace_memory and recorded_origin in ("agent", "untrusted")
              else "agent" if workspace_memory else "untrusted")
    return {"curatedRoot": curated, "originClass": origin}


def _value(item: ChunkProvenance | Mapping[str, Any], snake: str, camel: str, default: Any) -> Any:
    return item.get(camel, item.get(snake, default)) if isinstance(item, Mapping) else getattr(item, snake)


def resolve_chunk_provenance(
    *,
    source: str,
    path_origin_class: str,
    mtime_ms: float,
    start_line: int,
    end_line: int,
    line_provenance: Sequence[ChunkProvenance | Mapping[str, Any]] | None = None,
) -> ChunkProvenance:
    """Reduce original rendered line provenance before source-line remapping."""
    lines = (line_provenance or ())[start_line - 1:end_line]
    if source == "sessions" and lines:
        origins = {_value(item, "origin_class", "originClass", "untrusted") for item in lines}
        origin = next((value for value in ("untrusted", "system", "agent", "owner") if value in origins),
                      "untrusted")
        kinds = {_value(item, "session_kind", "sessionKind", "unknown") for item in lines}
        keys = {_value(item, "supersedes_key", "supersedesKey", None) for item in lines
                if _value(item, "supersedes_key", "supersedesKey", None)}
        kind = next(iter(kinds)) if len(kinds) == 1 else "unknown"
        return ChunkProvenance(
            origin, kind if kind is not None else "unknown",
            max(_value(item, "observed_at", "observedAt", 0) for item in lines),
            next(iter(keys)) if len(keys) == 1 else None,
        )
    if math.isnan(mtime_ms):
        observed_at = math.nan
    elif math.isinf(mtime_ms):
        observed_at = max(0, mtime_ms)
    else:
        observed_at = max(0, math.floor(mtime_ms))
    return ChunkProvenance(path_origin_class, "unknown", observed_at)


def prepare_chunk_metadata(
    *,
    path: str,
    source: str,
    text: str,
    mtime_ms: float,
    chunk: Any,
    line_provenance: Sequence[ChunkProvenance | Mapping[str, Any]] | None = None,
    recorded_origin: str | None = None,
    classification: Mapping[str, Any] | None = None,
    source_lines: Sequence[str] | None = None,
) -> tuple[ChunkProvenance, ChunkRecallMetadata]:
    """Prepare metadata from original entry spans, never stripped chunk text.

    Sources with many chunks should pass a single pre-split ``source_lines``
    and cache recall metadata per entry span, as the native owner does.
    """
    path_class = classification or classify_memory_path(path, source, recorded_origin)
    provenance = resolve_chunk_provenance(
        source=source, path_origin_class=path_class["originClass"], mtime_ms=mtime_ms,
        start_line=chunk.start_line, end_line=chunk.end_line, line_provenance=line_provenance,
    )
    start = chunk.entry_start_line if chunk.entry_start_line is not None else chunk.start_line
    end = chunk.entry_end_line if chunk.entry_end_line is not None else chunk.end_line
    original_lines = (source_lines if source_lines is not None
                      else text.replace("\r\n", "\n").split("\n") if source == "memory" else ())
    recall = extract_curated_entry_recall_metadata(
        source_lines=original_lines[start - 1:end], curated_root=path_class["curatedRoot"],
        project_scope_eligible=source == "memory" and path.upper() != "USER.MD",
    )
    return provenance, recall
