from __future__ import annotations

from memory_core.config import MemoryConfig
from memory_core.tools.citations import clamp_text
from memory_core.workspace import MemoryWorkspace


def memory_get(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None = None,
    lines: int | None = None,
) -> dict:
    try:
        read = MemoryWorkspace(config.workspace_dir).read_text(
            path,
            from_line=from_line,
            line_count=lines if lines is not None else config.memory_get_default_lines,
        )
        clamped = clamp_text(read.text, max_chars=config.memory_get_max_chars)
        return {
            "path": read.path,
            "text": clamped.text,
            "startLine": read.start_line,
            "endLine": read.end_line,
            "truncated": clamped.truncated,
            "originalChars": clamped.original_chars,
        }
    except Exception as exc:
        return {"path": path, "text": "", "disabled": True, "error": str(exc)}
