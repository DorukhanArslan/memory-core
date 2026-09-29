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
  tool body after validation (``executeMemoryReadResult`` over
  ``readAgentMemoryFile`` / ``readMemoryFile``, memory-read-tool.ts and
  host/read-file.ts; the read itself is :mod:`memory_core.memory_read`). Like
  ``buildMemoryReadResult`` it clamps ``from_line``/``lines`` to at least 1,
  and a blank path returns the ``path required`` failure payload instead of
  raising.

Results carry ``status`` (35e0bc22ead #125979): ``"ok"`` with the excerpt,
``"not_found"`` (``{"status", "text": "", "path"}``) when the file is missing,
and ``"error"`` (``{"path", "text": "", "status", "code", "error"}``) when the
read was refused or failed; ``code`` is the failure's own code
(``MEMORY_PATH_NOT_ALLOWED``, fs-safe's ``outside-workspace`` or
``invalid-path``, an errno name such as ``EACCES``) or ``MEMORY_READ_FAILED``.
There is no ``disabled`` flag any more: a failed read is not a disabled memory.

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
from memory_core.memory_read import build_memory_read_result, read_memory_file
from memory_core.tools.common import (
    MemoryToolInputError,
    as_tool_params_record,
    extract_error_code,
    format_error_message,
    read_corpus_param,
    read_positive_integer_param,
    read_string_param,
)
from memory_core.tools._memory_tool_constants import MEMORY_GET_CORPORA, MEMORY_READ_FAILED_CODE
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
    """Read tool-call params exactly like ``createMemoryGetTool`` (tools.ts:590-594).

    Order: path, from, lines, corpus; blank ``from``/``lines`` read as omitted and the
    corpus must be one of ``memory, wiki, all``.
    """
    raw = as_tool_params_record(params)
    try:
        path = read_string_param(raw, "path", required=True)
        from_line = read_positive_integer_param(raw, "from")
        lines = read_positive_integer_param(raw, "lines")
        corpus = read_corpus_param(raw, MEMORY_GET_CORPORA)
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
    params; read failures come back as ``{"path", "text": "", "status": "error",
    "code", "error"}`` payloads, as upstream.
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


def memory_get(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None = None,
    lines: int | None = None,
    corpus: str = "memory",
    supplements: list[MemoryCorpusSupplement] | None = None,
) -> dict:
    # The Python-call form validates the corpus like the tool (readCorpusParam): blank reads as
    # omitted (a memory read), anything outside memory/wiki/all raises MemoryToolInputError.
    try:
        corpus = read_corpus_param({"corpus": corpus}, MEMORY_GET_CORPORA) or "memory"
    except MemoryToolInputError as error:
        error.tool = MEMORY_GET_TOOL_NAME
        raise
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
    # Builtin read (tools.ts createMemoryGetTool -> memory-read-tool.ts executeMemoryReadResult
    # -> readAgentMemoryFile -> readMemoryFile). memory_search session hits
    # (`sessions/<agent>/*.jsonl` and memory/.dreams/session-corpus/*.txt) are not readable
    # upstream either: they fail the memory-path/`.md` gate with MEMORY_PATH_NOT_ALLOWED; a
    # session-corpus `.md` file is an ordinary memory file.
    requested_path = js_trim(path)
    try:
        return read_memory_file(
            workspace.root,
            path,
            from_line=from_line,
            lines=lines,
            default_lines=config.memory_get_default_lines,
            max_chars=config.memory_get_max_chars,
        )
    except Exception as error:
        return _memory_read_failure(
            config,
            error=error,
            path=requested_path,
            from_line=from_line,
            lines=lines,
            corpus=corpus,
            supplements=supplements or [],
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
    # corpus=all retries the registered supplements (interim, before the memory-read-tool.ts
    # port of the per-corpus outcomes); every other failure is executeMemoryReadResult's error
    # payload (memory-read-tool.ts:58-69).
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
    return {
        "path": path,
        "text": "",
        "status": "error",
        "code": extract_error_code(error) or MEMORY_READ_FAILED_CODE,
        "error": format_error_message(error),
    }


def _memory_get_supplement(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None,
    lines: int | None,
    corpus: str,
    supplements: list[MemoryCorpusSupplement],
) -> dict:
    # Interim until the memory-read-tool.ts wiki read is ported: the supplement's content is
    # sliced like a memory file (documented deviation, decision D7).
    result = None
    for supplement in supplements:
        result = supplement.get(path=path, corpus=corpus)
        if result is not None:
            break
    if result is None:
        return {"status": "not_found", "text": "", "path": path}
    content = result.get("content") or result.get("snippet") or ""
    text_result = build_memory_read_result(
        content=str(content),
        rel_path=path,
        from_line=from_line,
        lines=lines,
        default_lines=config.memory_get_default_lines,
        max_chars=config.memory_get_max_chars,
    )
    text_result["corpus"] = result.get("corpus", corpus)
    return text_result
