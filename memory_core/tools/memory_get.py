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
    read_corpus_param,
    read_positive_integer_param,
    read_string_param,
)
from memory_core.tools.corpus import (
    CorpusAttempt,
    attempt_corpus,
    compose_memory_corpus_metadata,
    error_code,
    settle_supplements,
)
from memory_core.workspace import MemoryWorkspace

MEMORY_GET_TOOL_NAME = "memory_get"
MEMORY_GET_CORPORA = ("memory", "wiki", "all")
# memory-tool-contract.ts: the files the tools cover (`resolveMemorySourceContract`;
# memory-core has no extra paths), and the outcome guidance shared by both tools.
MEMORY_TOOL_FILES_DESCRIPTION = "MEMORY.md, USER.md, Markdown files recursively under memory/"
MEMORY_TOOL_CORPUS_OUTCOME_GUIDANCE = (
    "Corpus outcomes cover each requested corpus; a corpus warning means results are partial "
    "and must be surfaced to the user."
)
MEMORY_GET_READ_OUTCOME_GUIDANCE = (
    "status=ok means the requested excerpt was read; status=not_found means every requested "
    "available corpus missed; status=error means the requested read failed, not that memory "
    "is disabled."
)
# MEMORY_GET_TOOL_CONTRACT.describe (verbatim).
MEMORY_GET_TOOL_DESCRIPTION = (
    f"Safe exact excerpt read from {MEMORY_TOOL_FILES_DESCRIPTION}. Session transcript paths "
    "are unsupported; use the available session-history workflow for session hits. Defaults "
    "to a bounded excerpt when lines are omitted and includes truncation/continuation info "
    "when more content exists. `corpus=wiki` reads registered compiled-wiki supplements. "
    f"{MEMORY_GET_READ_OUTCOME_GUIDANCE} {MEMORY_TOOL_CORPUS_OUTCOME_GUIDANCE}"
)
# MemoryGetSchema (memory-tool-contract.ts) as JSON Schema.
MEMORY_GET_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "from": {"type": "integer", "minimum": 1},
        "lines": {"type": "integer", "minimum": 1},
        "corpus": {"type": "string", "enum": ["memory", "wiki", "all"]},
    },
    "required": ["path"],
    "additionalProperties": False,
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
    """The tool body (``createMemoryGetTool`` + ``memory-read-tool.ts``).

    The result always carries ``status``: ``ok``, ``not_found`` or ``error`` (with a
    ``code``); ``corpus=wiki`` and ``corpus=all`` add the per-corpus ``corpora``
    metadata. Deviation: no 30 s deadline, the host's supplements are plain calls.
    """
    supplements = supplements or []
    requested_path = js_trim(path)
    if corpus == "wiki":
        wiki = _read_wiki(
            config,
            path=MemoryWorkspace(config.workspace_dir).normalize_memory_path(path),
            from_line=from_line,
            lines=lines,
            corpus=corpus,
            supplements=supplements,
        )
        if wiki.value is not None:
            result: dict = wiki.value
        elif wiki.outcome == "ok":
            result = _not_found(requested_path)
        else:
            result = {"path": requested_path, "text": ""}
        return {**result, **compose_memory_corpus_metadata([wiki])}

    def read() -> dict:
        return _read_builtin(config, path=path, from_line=from_line, lines=lines)

    if corpus != "all":
        try:
            return read()
        except Exception as exc:
            return _read_failure(requested_path, exc)
    memory = attempt_corpus("memory", None, read)
    wiki = _read_wiki(
        config,
        path=requested_path,
        from_line=from_line,
        lines=lines,
        corpus=corpus,
        supplements=supplements,
    )
    memory_result = memory.value
    wiki_result = wiki.value
    if memory_result is not None and memory_result.get("status") != "not_found":
        result = memory_result
    elif wiki_result is not None:
        result = wiki_result
    elif memory.outcome == "ok" or wiki.outcome == "ok":
        result = _not_found(requested_path)
    else:
        result = {"status": "error", "path": requested_path, "text": ""}
    return {**result, **compose_memory_corpus_metadata([memory, wiki])}


def _read_builtin(
    config: MemoryConfig, *, path: str, from_line: int | None, lines: int | None
) -> dict:
    """``readAgentMemoryFile`` -> ``readMemoryFile``; a refusal or an OS error raises."""
    workspace = MemoryWorkspace(config.workspace_dir)
    # memory_search session hits (`sessions/<agent>/*.jsonl` and
    # memory/.dreams/session-corpus/*.txt) are not readable upstream either: they fail
    # the memory-path/`.md` gate; a session-corpus `.md` file is an ordinary memory file.
    rel_path = js_trim(path)
    try:
        rel_path, memory_path = workspace.resolve_memory_read_path(path)
        if memory_path is None:
            return _not_found(rel_path)
        # Buffer.toString("utf-8"): no newline translation, invalid bytes replaced.
        content = memory_path.read_bytes().decode("utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return _not_found(rel_path)
    return _memory_get_text(
        config, path=rel_path, content=content, from_line=from_line, lines=lines
    )


def _read_failure(path: str, error: BaseException) -> dict:
    """``executeMemoryReadResult``'s error payload for a failed read."""
    return {
        "path": path,
        "text": "",
        "status": "error",
        "code": error_code(error) or "MEMORY_READ_FAILED",
        "error": format_error_message(error),
    }


def _not_found(path: str) -> dict:
    return {"status": "not_found", "text": "", "path": path}


def _read_wiki(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None,
    lines: int | None,
    corpus: str,
    supplements: list[MemoryCorpusSupplement],
) -> CorpusAttempt:
    """``readMemoryCorpusSupplements``: the first supplement that has the path."""

    def run(supplement: MemoryCorpusSupplement) -> dict | None:
        result = supplement.get(path=path, corpus=corpus)
        if result is None:
            return None
        content = result.get("content") or result.get("snippet") or ""
        text_result = _memory_get_text(
            config, path=path, content=str(content), from_line=from_line, lines=lines
        )
        text_result["corpus"] = result.get("corpus", corpus)
        return text_result

    return settle_supplements(
        supplements,
        run,
        lambda results: next((result for result in results if result is not None), None),
    )


def _memory_get_text(
    config: MemoryConfig,
    *,
    path: str,
    content: str,
    from_line: int | None,
    lines: int | None,
) -> dict:
    file_lines = content.split("\n")
    # A terminal newline closes the previous line; its split sentinel is not a
    # readable extra blank line (read-file-shared.ts buildMemoryReadResult).
    if file_lines[-1] == "":
        file_lines.pop()
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
        "status": "ok",
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
