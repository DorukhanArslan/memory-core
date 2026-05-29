from __future__ import annotations

from dataclasses import dataclass


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
