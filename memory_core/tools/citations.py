from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory_core.bootstrap._js import js_trim, js_trim_end
from memory_core.index.preparation import strip_memory_annotation_carriers


def resolve_memory_citations_mode(mode: object) -> str:
    """Resolve the configured ``memory.citations`` value, defaulting to auto."""
    return mode if isinstance(mode, str) and mode in ("on", "off", "auto") else "auto"


def should_include_citations(mode: str, session_key: str | None = None) -> bool:
    """Native citation policy for an agent-scoped session key.

    Parsing only needs the ownership head and folded rest tokens. Preserving
    opaque Signal/Matrix peer bytes cannot affect this decision: those spans
    already follow a structural ``group`` or ``channel`` token.
    """
    if mode == "on":
        return True
    if mode == "off":
        return False
    if not isinstance(session_key, str):
        return True
    key = js_trim(session_key).lower()
    if not key.startswith("agent:"):
        return True
    end = key.find(":", 6)
    if end == -1:
        return True
    agent_id, rest = js_trim(key[6:end]), key[end + 1 :]
    if not agent_id or not rest or rest.startswith(":"):
        return True
    tokens = set(js_trim(rest).split(":"))
    return "channel" not in tokens and "group" not in tokens


def build_memory_search_presentation(
    results: Sequence[Mapping[str, Any]], include: bool
) -> list[dict[str, Any]]:
    """Present native memory rows without losing provider or provenance fields.

    Native code returns a Map keyed by each original row. The Python boundary
    returns its presented values in input order; citation-off ``undefined`` is
    represented by an absent property, as on the JSON transport.
    """
    presentation: list[dict[str, Any]] = []
    for entry in results:
        presented = dict(entry)
        presented["corpus"] = entry["source"]
        presented["snippet"] = strip_memory_annotation_carriers(entry["snippet"])
        if include:
            presented["citation"] = citation_label(
                entry["path"], entry["startLine"], entry["endLine"]
            )
            presented["snippet"] = (
                f"{js_trim_end(presented['snippet'])}\n\nSource: {presented['citation']}"
            )
        else:
            presented.pop("citation", None)
        presentation.append(presented)
    return presentation


@dataclass(frozen=True)
class ClampedText:
    text: str
    truncated: bool
    original_chars: int


def citation_label(path: str, start_line: int, end_line: int) -> str:
    line_range = f"#L{start_line}" if start_line == end_line else f"#L{start_line}-L{end_line}"
    return f"{path}{line_range}"


def source_label(path: str, start_line: int, end_line: int | None = None) -> str:
    return f"Source: {citation_label(path, start_line, end_line or start_line)}"


def clamp_text(text: str, *, max_chars: int) -> ClampedText:
    if len(text) <= max_chars:
        return ClampedText(text=text, truncated=False, original_chars=len(text))
    return ClampedText(text=text[:max_chars], truncated=True, original_chars=len(text))
