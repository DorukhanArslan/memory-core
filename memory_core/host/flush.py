"""The memory flush run a host executes after a turn (docs/host_kit.md, entry point 4).

``HostKit.after_turn`` returns a :class:`FlushRequest` when the flush is due: the messages and
the one tool of the flush run, a ``dispatch`` for that tool's calls and ``complete`` for the
session entry. The host runs the model (later in the same process, detached from the reply, as
upstream runs flush maintenance) and never delivers or records the flush reply; the session's
next ``after_turn`` waits for ``complete`` (one maintenance lane per session).

The tool is upstream's ``write`` restricted to appending the daily target
(src/agents/agent-tools.ts:665-692 keeps ``read`` and an append-only ``write`` for flush runs;
memory-core has no generic ``read``). Texts are script-extracted from the tag. Labelled deviations:
the append goes through ``append_daily_memory`` (trailing newlines of the content are stripped
and the entry always ends with ``\\n``), empty and ``NO_REPLY`` content writes nothing, the
missing-parameter messages are memory-core's, and symlinked or hard-linked targets are refused.
"""

from __future__ import annotations

import copy
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from memory_core._memory_flush_constants import (
    MEMORY_FLUSH_WRITE_APPENDED_TEMPLATE,
    MEMORY_FLUSH_WRITE_DESCRIPTION_TEMPLATE,
    MEMORY_FLUSH_WRITE_RESTRICTED_TEMPLATE,
    SILENT_REPLY_TOKEN,
    WRITE_TOOL_CONTENT_DESCRIPTION,
    WRITE_TOOL_DESCRIPTION,
    WRITE_TOOL_PATH_DESCRIPTION,
)
from memory_core.client import Memory
from memory_core.host._calls import ToolCallRefused, read_tool_call, tool_error
from memory_core.host.session import SessionState
from memory_core.memory_flush import (
    MemoryFlushFailureOutcome,
    record_memory_flush_failure,
    record_memory_flush_success,
)
from memory_core.tools.common import format_error_message, to_tool_error
from memory_core.workspace import append_daily_memory_file

WRITE_TOOL_NAME = "write"


def memory_flush_write_tool(target: str) -> dict[str, Any]:
    """Upstream's ``write`` tool as its flush wrapper offers it for ``target``.

    Schema and description of src/agents/sessions/tools/write.ts:42-47 and :525, plus the
    suffix of ``wrapToolMemoryFlushAppendOnlyWrite`` (src/agents/agent-tools.read.ts:760).
    """
    return {
        "name": WRITE_TOOL_NAME,
        "description": MEMORY_FLUSH_WRITE_DESCRIPTION_TEMPLATE.format(
            description=WRITE_TOOL_DESCRIPTION, relative_path=target
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": WRITE_TOOL_PATH_DESCRIPTION},
                "content": {"type": "string", "description": WRITE_TOOL_CONTENT_DESCRIPTION},
            },
            "required": ["path", "content"],
        },
    }


@dataclass(frozen=True)
class FlushOutcome:
    """The session after the flush run, and what the run appended."""

    session: SessionState
    wrote: bool
    entries: tuple[str, ...]
    failure: MemoryFlushFailureOutcome | None


class FlushRequest:
    """One due memory flush run: ``messages`` and ``tools`` for the host's model.

    Built by ``HostKit.after_turn``. Tool calls of the run go to :meth:`dispatch`; the run ends
    with one :meth:`complete`. Parallel tool calls are safe (the append is locked).
    """

    def __init__(
        self,
        memory: Memory,
        *,
        session_id: str,
        compaction_count: int,
        target: str,
        messages: tuple[dict[str, str], ...],
    ) -> None:
        self.target = target
        self.messages = messages
        self.tools = (memory_flush_write_tool(target),)
        self._memory = memory
        self._session_id = session_id
        self._compaction_count = compaction_count
        self._entries: list[str] = []
        self._lock = threading.Lock()
        self._completed = False

    def dispatch(self, name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
        """Run one tool call of the flush run and return the payload for the model.

        Only ``write`` of ``{path, content}`` to the target exists: another path (or one
        starting with ``@``) gets upstream's restriction (agent-tools.read.ts:787-790), empty or
        ``NO_REPLY`` content is skipped, anything else is appended, the store reindexed and
        upstream's ``Appended content to <target>.`` returned. Errors are payloads, as in
        ``HostKit.dispatch``; a call after :meth:`complete` raises ``RuntimeError``.
        """
        if self._completed:
            raise RuntimeError("the flush request is already completed")
        try:
            args = read_tool_call(name, arguments)
        except ToolCallRefused as refused:
            return refused.payload
        if name != WRITE_TOOL_NAME:
            return tool_error(name, f"tool {name} is not available")
        path = args.get("path")
        content = args.get("content")
        if not isinstance(path, str) or not path.strip():
            return tool_error(name, "path required")
        if not isinstance(content, str):
            return tool_error(name, "content required")
        root = self._memory.workspace.root
        allowed = os.path.normpath(os.path.join(root, self.target))
        if path.startswith("@") or os.path.normpath(os.path.join(root, path)) != allowed:
            return tool_error(
                name, MEMORY_FLUSH_WRITE_RESTRICTED_TEMPLATE.format(relative_path=self.target)
            )
        stripped = content.strip()
        if not stripped or stripped.startswith(SILENT_REPLY_TOKEN):
            return {"status": "ok", "tool": name, "path": self.target, "action": "skipped"}
        try:
            append_daily_memory_file(root, self.target, content)
        except Exception as error:
            return to_tool_error(error, tool=name)
        with self._lock:
            self._entries.append(content)
        payload: dict[str, Any] = {
            "status": "ok",
            "tool": name,
            "path": self.target,
            "action": "appended",
            "text": MEMORY_FLUSH_WRITE_APPENDED_TEMPLATE.format(relative_path=self.target),
        }
        try:
            self._memory.store.reindex(self._memory.workspace)
        except Exception as error:  # the append is committed; report, never retry
            payload["afterWriteError"] = format_error_message(error)
        return payload

    def complete(
        self,
        session: SessionState,
        *,
        error: BaseException | str | None = None,
        redact: Callable[[str], str] | None = None,
    ) -> FlushOutcome:
        """Record the run in the host's current state of this session.

        Success stamps ``memoryFlush`` for the compaction cycle the request was made in
        (``flushedCompactionCount``, agent-runner-memory.ts:1517, 1665-1671); ``error`` records a
        failure strike (three mark the cycle flushed) with ``redact`` applied to its message. A
        cancelled run is not completed (upstream records nothing for it). ``ValueError`` for
        another session, ``RuntimeError`` for a second call.
        """
        if self._completed:
            raise RuntimeError("the flush request is already completed")
        if session.session_id != self._session_id:
            raise ValueError(
                f"the flush belongs to session {self._session_id!r}, not {session.session_id!r}"
            )
        self._completed = True
        entry = copy.deepcopy(dict(session.entry))
        failure = None
        if error is None:
            entry = record_memory_flush_success(
                entry, flushed_compaction_count=self._compaction_count
            )
        else:
            failure = record_memory_flush_failure(entry, error=error, redact=redact)
            entry = failure.entry
        with self._lock:
            entries = tuple(self._entries)
        return FlushOutcome(
            session=replace(session, entry=entry),
            wrote=bool(entries),
            entries=entries,
            failure=failure,
        )
