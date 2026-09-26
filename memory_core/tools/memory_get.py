"""The ``memory_get`` tool (OpenClaw ``extensions/memory-core/src/tools.ts``).

Two entry points, like ``memory_search``:

- :func:`execute_memory_get_tool` takes the model's raw tool-call arguments and
  reads them exactly like ``createMemoryGetTool`` (tools.ts:720-725):
  ``readStringParam(path, required)`` (JavaScript trim; a missing, non-string
  or blank path raises ``path required``) and ``readPositiveIntegerParam`` for
  ``from`` and ``lines`` (``from must be a positive integer``, ``lines must be
  a positive integer``). Invalid input raises
  :class:`~memory_core.tools.common.MemoryToolInputError` tagged ``memory_get``; a
  host tool loop sends the model ``error.to_tool_error()``.
- :func:`memory_get` is the Python-call form below the param readers: the
  tool body after validation (``readAgentMemoryFile`` / ``readMemoryFile`` and
  ``resolveMemoryReadFailureResult``). Like ``buildMemoryReadResult`` it
  clamps ``from_line``/``lines`` to at least 1, and a blank path returns the
  ``path required`` failure payload instead of raising.

:func:`memory_get_tool_definition` returns the model-facing name,
description and parameter schema, verbatim from upstream.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from memory_core.bootstrap._js import js_trim
from memory_core.config import MemoryConfig
from memory_core.supplements import MemoryCorpusSupplement
from memory_core.tools.common import (
    MemoryToolInputError,
    as_tool_params_record,
    format_error_message,
    read_positive_integer_param,
    read_string_param,
)
from memory_core.workspace import MemoryWorkspace

MEMORY_GET_TOOL_NAME = "memory_get"
# tools.ts createMemoryGetTool description (verbatim).
MEMORY_GET_TOOL_DESCRIPTION = (
    "Safe exact excerpt read from MEMORY.md or memory/*.md. Defaults to a bounded excerpt "
    "when lines are omitted, includes truncation/continuation info when more content "
    "exists, and `corpus=wiki` reads from registered compiled-wiki supplements."
)
# tools.shared.ts MemoryGetSchema as JSON Schema (TypeBox output).
MEMORY_GET_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "required": ["path"],
    "properties": {
        "path": {"type": "string"},
        "from": {"type": "integer"},
        "lines": {"type": "integer"},
        "corpus": {"type": "string", "enum": ["memory", "wiki", "all"]},
    },
}


def memory_get_tool_definition() -> dict[str, Any]:
    """``{"name", "description", "parameters"}`` of the upstream ``memory_get`` tool.

    Same provider-neutral shape as ``MemoryCurator.tool_definitions()``; wrap it
    in the host's tool format. The schema's ``corpus`` enum is enforced by the
    host's argument validation, not by :func:`execute_memory_get_tool`.
    """
    return {
        "name": MEMORY_GET_TOOL_NAME,
        "description": MEMORY_GET_TOOL_DESCRIPTION,
        "parameters": copy.deepcopy(MEMORY_GET_TOOL_PARAMETERS),
    }


@dataclass(frozen=True)
class MemoryGetParams:
    """Validated ``memory_get`` params; ``None`` means the caller omitted it."""

    path: str
    from_line: int | None
    lines: int | None
    corpus: str | None


def read_memory_get_params(params: object) -> MemoryGetParams:
    """Read tool-call params exactly like ``createMemoryGetTool`` (tools.ts:720-725)."""
    raw = as_tool_params_record(params)
    try:
        path = read_string_param(raw, "path", required=True)
        from_line = read_positive_integer_param(raw, "from")
        lines = read_positive_integer_param(raw, "lines")
        corpus = read_string_param(raw, "corpus")
    except MemoryToolInputError as error:
        error.tool = MEMORY_GET_TOOL_NAME
        raise
    return MemoryGetParams(path=path, from_line=from_line, lines=lines, corpus=corpus)


def execute_memory_get_tool(
    config: MemoryConfig,
    params: object,
    *,
    supplements: list[MemoryCorpusSupplement] | None = None,
) -> dict:
    """Run ``memory_get`` on raw tool-call params (the model's arguments).

    Raises :class:`MemoryToolInputError` (``tool == "memory_get"``) on invalid
    params; read failures come back as ``{"path", "text": "", "disabled": True,
    "error"}`` payloads, as upstream.
    """
    parsed = read_memory_get_params(params)
    return memory_get(
        config,
        path=parsed.path,
        from_line=parsed.from_line,
        lines=parsed.lines,
        corpus=parsed.corpus if parsed.corpus is not None else "memory",
        supplements=supplements,
    )


def _continuation_notice(*, next_from: int | None, suggest_read_fallback: bool) -> str:
    if next_from is not None:
        base = f"[More content available. Use from={next_from} to continue.]"
    else:
        base = "[More content available. Requested excerpt exceeded the default maxChars budget.]"
    fallback = " If you need the full raw line, use read on the source file." if suggest_read_fallback else ""
    return f"\n\n{base[:-1]}{fallback}]"


def _fit_lines_to_char_budget(lines: list[str], *, max_chars: int) -> tuple[str, int, bool]:
    if not lines:
        return "", 0, False

    included_lines = len(lines)
    text = "\n".join(lines)
    while included_lines > 1 and len(text) > max_chars:
        included_lines -= 1
        text = "\n".join(lines[:included_lines])

    if len(text) <= max_chars:
        return text, included_lines, False

    return text[:max_chars], 1, True


def memory_get(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None = None,
    lines: int | None = None,
    corpus: str = "memory",
    supplements: list[MemoryCorpusSupplement] | None = None,
) -> dict:
    workspace = MemoryWorkspace(config.workspace_dir)
    if corpus == "wiki":
        return _memory_get_supplement(
            config,
            path=workspace.normalize_memory_path(path),
            from_line=from_line,
            lines=lines,
            corpus=corpus,
            supplements=supplements or [],
        )
    # Builtin read (OpenClaw extensions/memory-core/src/tools.ts createMemoryGetTool
    # -> readAgentMemoryFile -> readMemoryFile). memory_search session hits
    # (`sessions/<agent>/*.jsonl` and memory/.dreams/session-corpus/*.txt) are
    # not readable upstream either: they fail the memory-path/`.md` gate with
    # "path required"; a session-corpus `.md` file is an ordinary memory file.
    requested_path = js_trim(path)
    rel_path = requested_path
    try:
        rel_path, memory_path = workspace.resolve_memory_read_path(path)
        if memory_path is None:
            return {"text": "", "path": rel_path}
        # Buffer.toString("utf-8"): no newline translation, invalid bytes replaced.
        content = memory_path.read_bytes().decode("utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return {"text": "", "path": rel_path}
    except Exception as exc:
        return _memory_read_failure(
            config,
            error=exc,
            path=requested_path,
            from_line=from_line,
            lines=lines,
            corpus=corpus,
            supplements=supplements or [],
        )

    return _memory_get_text(
        config,
        path=rel_path,
        content=content,
        from_line=from_line,
        lines=lines,
    )


def _memory_read_failure(
    config: MemoryConfig,
    *,
    error: Exception,
    path: str,
    from_line: int | None,
    lines: int | None,
    corpus: str,
    supplements: list[MemoryCorpusSupplement],
) -> dict:
    # tools.ts resolveMemoryReadFailureResult: only corpus=all retries the
    # registered supplements before returning the disabled error payload.
    if corpus == "all":
        for supplement in supplements:
            if supplement.get(path=path, corpus=corpus) is not None:
                return _memory_get_supplement(
                    config,
                    path=path,
                    from_line=from_line,
                    lines=lines,
                    corpus=corpus,
                    supplements=[supplement],
                )
    return {"path": path, "text": "", "disabled": True, "error": format_error_message(error)}


def _memory_get_supplement(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None,
    lines: int | None,
    corpus: str,
    supplements: list[MemoryCorpusSupplement],
) -> dict:
    result = None
    for supplement in supplements:
        result = supplement.get(path=path, corpus=corpus)
        if result is not None:
            break
    if result is None:
        return {
            "path": path,
            "text": "",
            "disabled": True,
            "error": "wiki corpus result not found",
        }
    content = result.get("content") or result.get("snippet") or ""
    text_result = _memory_get_text(
        config,
        path=path,
        content=str(content),
        from_line=from_line,
        lines=lines,
    )
    text_result["corpus"] = result.get("corpus", corpus)
    return text_result


def _memory_get_text(
    config: MemoryConfig,
    *,
    path: str,
    content: str,
    from_line: int | None,
    lines: int | None,
) -> dict:
    file_lines = content.split("\n")
    start = max(1, from_line or 1)
    requested_count = max(1, lines if lines is not None else config.memory_get_default_lines)
    selected_lines = file_lines[start - 1 : start - 1 + requested_count]
    more_source_lines_remain = start - 1 + len(selected_lines) < len(file_lines)
    text, included_lines, hard_truncated_single_line = _fit_lines_to_char_budget(
        selected_lines,
        max_chars=max(1, config.memory_get_max_chars),
    )
    char_cap_truncated = hard_truncated_single_line or included_lines < len(selected_lines)
    next_from = (
        start + included_lines
        if not hard_truncated_single_line
        and (more_source_lines_remain or included_lines < len(selected_lines))
        else None
    )
    truncated = char_cap_truncated or more_source_lines_remain
    if truncated and text:
        text = f"{text}{_continuation_notice(next_from=next_from, suggest_read_fallback=hard_truncated_single_line)}"

    output = {
        "text": text,
        "path": path,
        "from": start,
        "lines": included_lines,
    }
    if truncated:
        output["truncated"] = True
    if next_from is not None:
        output["nextFrom"] = next_from
    return output
