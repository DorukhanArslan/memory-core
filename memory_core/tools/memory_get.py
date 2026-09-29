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
from memory_core.memory_read import build_memory_read_result, read_memory_file
from memory_core.supplements import MemoryCorpusResult, MemoryCorpusSupplement
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
from memory_core.tools.corpus import (
    MemoryCorpusAttempt,
    MemoryCorpusDeadline,
    attempt_memory_corpus,
    compose_memory_corpus_metadata,
    read_memory_corpus_supplements,
    run_concurrently,
    run_memory_corpus_deadline,
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
    # params.relPath: the trimmed path as requested, also for failures and supplement lookups.
    requested_path = js_trim(path)
    registered = list(supplements or [])

    def read() -> dict:
        # tools.ts createMemoryGetTool -> readAgentMemoryFile -> readMemoryFile. memory_search
        # session hits (`sessions/<agent>/*.jsonl`, memory/.dreams/session-corpus/*.txt) are not
        # readable upstream either: they fail the memory-path/`.md` gate with
        # MEMORY_PATH_NOT_ALLOWED; a session-corpus `.md` file is an ordinary memory file.
        return read_memory_file(
            workspace.root,
            path,
            from_line=from_line,
            lines=lines,
            default_lines=config.memory_get_default_lines,
            max_chars=config.memory_get_max_chars,
        )

    def read_wiki(deadline: MemoryCorpusDeadline) -> MemoryCorpusAttempt:
        return read_memory_corpus_supplements(
            supplements=registered,
            deadline=deadline,
            lookup=requested_path,
            corpus=corpus,
            to_read_result=lambda result: _supplement_read_result(
                config, result, path=requested_path, from_line=from_line, lines=lines
            ),
        )

    if corpus == "wiki":
        # memory-read-tool.ts:39-53 executeWikiMemoryReadResult.
        def wiki_result(deadline: MemoryCorpusDeadline) -> dict:
            wiki = read_wiki(deadline)
            value = _attempt_value(wiki)
            if value is None:
                value = (
                    {"status": "not_found", "path": requested_path, "text": ""}
                    if wiki.outcome == "ok"
                    else {"path": requested_path, "text": ""}
                )
            return {**value, **compose_memory_corpus_metadata([wiki])}

        return run_memory_corpus_deadline(MEMORY_GET_TOOL_NAME, wiki_result)
    if corpus != "all":
        # memory-read-tool.ts:58-69: a direct read, its failure as the tool's error payload.
        try:
            return read()
        except Exception as error:
            return _memory_read_failure(requested_path, error)

    # memory-read-tool.ts:71-95: memory and wiki together under one deadline.
    def all_result(deadline: MemoryCorpusDeadline) -> dict:
        memory, wiki = run_concurrently(
            [
                lambda: attempt_memory_corpus(
                    corpus="memory", deadline=deadline, unavailable_value=None, run=read
                ),
                lambda: read_wiki(deadline),
            ]
        )
        memory_result = _attempt_value(memory)
        wiki_result = _attempt_value(wiki)
        if memory_result is not None and memory_result.get("status") != "not_found":
            result = memory_result
        elif wiki_result is not None:
            result = wiki_result
        elif memory.outcome == "ok" or wiki.outcome == "ok":
            result = {"status": "not_found", "path": requested_path, "text": ""}
        else:
            result = {"status": "error", "path": requested_path, "text": ""}
        return {**result, **compose_memory_corpus_metadata([memory, wiki])}

    return run_memory_corpus_deadline(MEMORY_GET_TOOL_NAME, all_result)


def _attempt_value(attempt: MemoryCorpusAttempt) -> dict | None:
    # memory-read-tool.ts:35-37 attemptValue.
    return None if attempt.outcome == "not-registered" else attempt.value


def _memory_read_failure(path: str, error: BaseException) -> dict:
    # memory-read-tool.ts:61-68.
    return {
        "path": path,
        "text": "",
        "status": "error",
        "code": extract_error_code(error) or MEMORY_READ_FAILED_CODE,
        "error": format_error_message(error),
    }


def _supplement_read_result(
    config: MemoryConfig,
    result: MemoryCorpusResult,
    *,
    path: str,
    from_line: int | None,
    lines: int | None,
) -> dict:
    # Documented deviation (D7): upstream passes fromLine/lineCount to the supplement and returns
    # {...details, status: "ok", text: content} as the supplement gave it; memory-core's
    # supplement protocol has no line window, so the content is sliced like a memory file.
    content = result.get("content") or result.get("snippet") or ""
    read = build_memory_read_result(
        content=str(content),
        rel_path=path,
        from_line=from_line,
        lines=lines,
        default_lines=config.memory_get_default_lines,
        max_chars=config.memory_get_max_chars,
    )
    read["corpus"] = result.get("corpus", "wiki")
    return read
