"""The ``memory_get`` tool (OpenClaw ``extensions/memory-core/src/tools.ts``).

Two entry points, like ``memory_search``:

- :func:`execute_memory_get_tool` takes the model's raw tool-call arguments and
  reads them exactly like ``createMemoryGetTool``:
  ``readStringParam(path, required)`` (JavaScript trim; a missing, non-string
  or blank path raises ``path required``) and ``readPositiveIntegerParam`` for
  ``from`` and ``lines`` (``from must be a positive integer``, ``lines must be
  a positive integer``). Invalid path or numeric input raises
  :class:`~memory_core.tools.common.MemoryToolInputError` (native name
  ``ToolInputError``, status 400). An unknown corpus raises the ordinary
  :class:`~memory_core.tools.common.MemoryToolError` (native name ``Error``,
  no status). Both are tagged ``memory_get``; a host tool loop sends the model
  ``error.to_tool_error()``.
- :func:`memory_get` is the Python-call form below the param readers: the
  tool body after validation (``readAgentMemoryFile`` / ``readMemoryFile`` and
  ``executeMemoryReadResult``). Like ``buildMemoryReadResult`` it
  clamps ``from_line``/``lines`` to at least 1, and a blank path returns the
  ``path required`` failure payload instead of raising.

:func:`memory_get_tool_definition` returns the model-facing name,
description and parameter schema, verbatim from upstream.
"""

from __future__ import annotations

import copy
import math
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_trim, truncate_utf16_safe, utf16_len
from memory_core.config import MemoryConfig
from memory_core.cancellation import CancellationSignal
from memory_core.supplements import MemoryCorpusSupplement, RegisteredMemoryCorpusSupplement
from memory_core.tools.common import (
    MemoryToolError,
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
from memory_core.tools.get_paths import resolve_memory_get_read_path
from memory_core.memory_read import read_memory_file_bytes
from memory_core.memory_paths import MemoryReadPathError
from memory_core._memory_scan_io import MemorySourceIOError
from memory_core.tools.deadline import MemoryToolDeadlineContext, run_memory_corpus_deadline

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


def memory_get_tool_definition(*, extra_paths: Sequence[str | Path | Mapping[str, str]] = ()) -> dict[str, Any]:
    """``{"name", "description", "parameters"}`` of the upstream ``memory_get`` tool.

    Same provider-neutral shape as ``MemoryCurator.tool_definitions()``; wrap it
    in the host's tool format. The schema publishes the closed ``corpus`` enum.
    :func:`execute_memory_get_tool` also rejects an unknown corpus independently,
    raising ordinary ``MemoryToolError`` with native name ``Error`` and no status.
    """
    return {
        "name": MEMORY_GET_TOOL_NAME,
        "description": MEMORY_GET_TOOL_DESCRIPTION.replace(
            MEMORY_TOOL_FILES_DESCRIPTION,
            MEMORY_TOOL_FILES_DESCRIPTION + (", configured extra paths" if extra_paths else ""),
            1,
        ),
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
    """Read tool-call params exactly like ``createMemoryGetTool``."""
    raw = as_tool_params_record(params)
    try:
        path = read_string_param(raw, "path", required=True)
        from_line = read_positive_integer_param(raw, "from")
        lines = read_positive_integer_param(raw, "lines")
        corpus = read_corpus_param(raw, MEMORY_GET_CORPORA)
    except MemoryToolError as error:
        error.tool = MEMORY_GET_TOOL_NAME
        raise
    return MemoryGetParams(path=path, from_line=from_line, lines=lines, corpus=corpus)


def execute_memory_get_tool(
    config: MemoryConfig,
    params: object,
    *,
    supplements: list[MemoryCorpusSupplement] | None = None,
    extra_paths: Sequence[str | Path | Mapping[str, str]] = (),
    agent_session_key: str | None = None,
    sandboxed: bool | None = None,
    execution: MemoryToolDeadlineContext | None = None,
) -> dict:
    """Run ``memory_get`` on raw tool-call params (the model's arguments).

    Invalid path or numeric input raises ``MemoryToolInputError`` (native
    ``ToolInputError``, status 400); an unknown corpus raises ordinary
    ``MemoryToolError`` (native ``Error``, no status). Both are tagged
    ``memory_get``. Read failures come back as ``{"path", "text": "", "status": "error",
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
        extra_paths=extra_paths,
        agent_session_key=agent_session_key,
        sandboxed=sandboxed,
        execution=execution,
    )


def _continuation_notice(*, next_from: int | None, suggest_read_fallback: bool) -> str:
    if next_from is not None:
        base = f"[More content available. Use from={next_from} to continue.]"
    else:
        base = "[More content available. Requested excerpt exceeded the default maxChars budget.]"
    fallback = " If you need the full raw line, use read on the source file." if suggest_read_fallback else ""
    return f"\n\n{base[:-1]}{fallback}]"


def _fit_lines_to_char_budget(lines: list[str], *, max_chars: int) -> tuple[str, int, bool]:
    included_lines = 0
    chars = 0
    for line in lines:
        next_chars = chars + utf16_len(line) + (1 if included_lines else 0)
        if included_lines and next_chars > max_chars:
            break
        included_lines += 1
        chars = next_chars
    return (truncate_utf16_safe("\n".join(lines[:included_lines]), max_chars),
            included_lines, chars > max_chars)


def _resolve_integer_option(value: object, fallback: int) -> int:
    try:
        finite = isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        finite = False
    return max(1, math.floor(float(value) if finite else fallback))


def build_memory_read_result_from_slice(
    *, selected_lines: Sequence[str], rel_path: str, start_line: int,
    more_source_lines_remain: bool = False, max_chars: int | None = None,
    suggest_read_fallback: bool = False,
) -> dict[str, Any]:
    """Native read-file-shared result builder over an already selected excerpt."""
    start = _resolve_integer_option(start_line, 1)
    text, included_lines, hard_truncated_single_line = _fit_lines_to_char_budget(
        list(selected_lines), max_chars=_resolve_integer_option(max_chars, 12_000),
    )
    char_cap_truncated = hard_truncated_single_line or included_lines < len(selected_lines)
    next_from = (
        start + included_lines
        if not hard_truncated_single_line
        and (more_source_lines_remain or included_lines < len(selected_lines))
        else None
    )
    truncated = char_cap_truncated or more_source_lines_remain
    if truncated and (text or hard_truncated_single_line):
        text += _continuation_notice(
            next_from=next_from,
            suggest_read_fallback=hard_truncated_single_line and suggest_read_fallback,
        )
    output: dict[str, Any] = {
        "status": "ok", "text": text, "path": rel_path, "from": start, "lines": included_lines,
    }
    if truncated:
        output["truncated"] = True
    if next_from is not None:
        output["nextFrom"] = next_from
    return output


def build_memory_read_result(
    *, content: str, rel_path: str, from_line: int | None = None, lines: int | None = None,
    default_lines: int | None = None, max_chars: int | None = None,
    suggest_read_fallback: bool = False,
) -> dict[str, Any]:
    """Native UTF-16 excerpt builder used by the actual workspace reader."""
    file_lines = content.split("\n")
    if file_lines[-1] == "":
        file_lines.pop()
    start = _resolve_integer_option(from_line, 1)
    count = _resolve_integer_option(lines if lines is not None else default_lines, 120)
    selected = file_lines[start - 1 : start - 1 + count]
    return build_memory_read_result_from_slice(
        selected_lines=selected, rel_path=rel_path, start_line=start,
        more_source_lines_remain=start - 1 + len(selected) < len(file_lines),
        max_chars=max_chars, suggest_read_fallback=suggest_read_fallback,
    )


def memory_get(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None = None,
    lines: int | None = None,
    corpus: str = "memory",
    supplements: list[MemoryCorpusSupplement] | None = None,
    extra_paths: Sequence[str | Path | Mapping[str, str]] = (),
    agent_session_key: str | None = None,
    sandboxed: bool | None = None,
    execution: MemoryToolDeadlineContext | None = None,
) -> dict:
    """The tool body (``createMemoryGetTool`` + ``memory-read-tool.ts``).

    The result always carries ``status``: ``ok``, ``not_found`` or ``error`` (with a
    ``code``); ``corpus=wiki`` and ``corpus=all`` add the per-corpus ``corpora``
    metadata. Wiki and combined reads share one absolute 30 s deadline; the
    built-in-only read follows the native unguarded file-reader path.
    """
    supplements = supplements or []
    requested_path = js_trim(path)
    def read() -> dict:
        return _read_builtin(
            config, path=path, from_line=from_line, lines=lines, extra_paths=extra_paths,
        )

    if corpus not in {"all", "wiki"}:
        try:
            return read()
        except Exception as exc:
            return _read_failure(requested_path, exc)

    def guarded(signal: CancellationSignal, _control: Any) -> dict:
        memory_box: dict[str, Any] = {}
        memory_done = threading.Event()
        if corpus == "all":
            def read_memory() -> None:
                try:
                    memory_box["attempt"] = attempt_corpus(
                        "memory", None, read, signal=signal, context=execution,
                    )
                except BaseException as error:
                    memory_box["exception"] = error
                finally:
                    memory_done.set()

            threading.Thread(target=read_memory, name="memory-get-reader", daemon=True).start()
        wiki = _read_wiki(
            config, path=requested_path, from_line=from_line, lines=lines, corpus=corpus,
            supplements=supplements, agent_session_key=agent_session_key, sandboxed=sandboxed,
            signal=signal, execution=execution,
        )
        if corpus == "wiki":
            if wiki.value is not None:
                result = wiki.value
            elif wiki.outcome == "ok":
                result = _not_found(requested_path)
            else:
                result = {"path": requested_path, "text": ""}
            return {**result, **compose_memory_corpus_metadata([wiki])}
        memory_done.wait()
        if "exception" in memory_box:
            raise memory_box["exception"]
        memory = memory_box["attempt"]
        memory_result, wiki_result = memory.value, wiki.value
        if memory_result is not None and memory_result.get("status") != "not_found":
            result = memory_result
        elif wiki_result is not None:
            result = wiki_result
        elif memory.outcome == "ok" or wiki.outcome == "ok":
            result = _not_found(requested_path)
        else:
            result = {"status": "error", "path": requested_path, "text": ""}
        return {**result, **compose_memory_corpus_metadata([memory, wiki])}

    return run_memory_corpus_deadline("memory_get", guarded, context=execution)


def _read_builtin(
    config: MemoryConfig, *, path: str, from_line: int | None, lines: int | None,
    extra_paths: Sequence[str | Path | Mapping[str, str]] = (),
) -> dict:
    """``readAgentMemoryFile`` -> ``readMemoryFile``; a refusal or an OS error raises."""
    # memory_search session hits (`sessions/<agent>/*.jsonl` and
    # memory/.dreams/session-corpus/*.txt) are not readable upstream either: they fail
    # the memory-path/`.md` gate; a session-corpus `.md` file is an ordinary memory file.
    rel_path = js_trim(path)
    try:
        admitted = resolve_memory_get_read_path(
            config.workspace_dir, path, extra_paths,
        )
        rel_path = admitted.rel_path
        raw = read_memory_file_bytes(admitted)
        if raw is None:
            return _not_found(rel_path)
        # Buffer.toString("utf-8"): no newline translation, invalid bytes replaced.
        content = raw.decode("utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return _not_found(rel_path)
    except MemorySourceIOError as error:
        if error.code in {"ENOENT", "ENOTDIR"}:
            return _not_found(rel_path)
        raise
    except MemoryReadPathError as error:
        if error.code in {"path-mismatch", "not-found"}:
            return _not_found(rel_path)
        raise
    return _memory_get_text(
        config, path=rel_path, content=content, from_line=from_line, lines=lines,
        suggest_read_fallback=admitted.suggest_read_fallback,
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
    agent_session_key: str | None = None,
    sandboxed: bool | None = None,
    signal: CancellationSignal | None = None,
    execution: MemoryToolDeadlineContext | None = None,
) -> CorpusAttempt:
    """``readMemoryCorpusSupplements``: the first supplement that has the path."""

    def run(supplement: MemoryCorpusSupplement) -> dict | None:
        if isinstance(supplement, RegisteredMemoryCorpusSupplement):
            result = supplement.read(
                lookup=path, from_line=from_line, line_count=lines, agent_id=config.agent_id,
                agent_session_key=agent_session_key, sandboxed=sandboxed,
            )
        else:
            result = supplement.get(path=path, corpus=corpus)
        if result is None:
            return None
        presented = dict(result)
        if "content" in presented:
            presented["text"] = presented.pop("content")
        else:
            # Native undefined overwrites an existing text property and is
            # omitted by the JSON transport. Empty and null content stay exact.
            presented.pop("text", None)
        presented["status"] = "ok"
        return presented

    return settle_supplements(
        supplements,
        run,
        lambda results: next((result for result in results if result is not None), None),
        signal=signal, context=execution,
    )


def _memory_get_text(
    config: MemoryConfig,
    *,
    path: str,
    content: str,
    from_line: int | None,
    lines: int | None,
    suggest_read_fallback: bool = True,
) -> dict:
    return build_memory_read_result(
        content=content, rel_path=path, from_line=from_line, lines=lines,
        default_lines=config.memory_get_default_lines, max_chars=config.memory_get_max_chars,
        suggest_read_fallback=suggest_read_fallback,
    )
