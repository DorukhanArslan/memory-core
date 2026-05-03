from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClampedText:
    text: str
    truncated: bool
    original_chars: int


def source_label(path: str, start_line: int) -> str:
    return f"Source: {path}#{start_line}"


def clamp_text(text: str, *, max_chars: int) -> ClampedText:
    if len(text) <= max_chars:
        return ClampedText(text=text, truncated=False, original_chars=len(text))
    return ClampedText(text=text[:max_chars], truncated=True, original_chars=len(text))
