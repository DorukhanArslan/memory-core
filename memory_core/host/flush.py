"""The memory flush run a host executes after a turn (docs/host_kit.md, entry point 4).

``HostKit.after_turn`` returns a :class:`FlushRequest` when the flush is due (and the extension
``HostKit.request_flush`` one on the host's demand): the messages and the one tool of the flush
run, a ``dispatch`` for that tool's calls and ``complete`` for the session entry. The host runs
the model (later in the same process, detached from the reply, as upstream runs flush
maintenance) and never delivers or records the flush reply; the session's next ``after_turn``
waits for ``complete`` (one maintenance lane per session).

The tool is upstream's ``write`` restricted to appending the daily target
(src/agents/agent-tools.ts:665-692 keeps ``read`` and an append-only ``write`` for flush runs;
memory-core has no generic ``read``). Texts are script-extracted from the tag. Labelled deviations:
the append goes through ``append_daily_memory`` (trailing newlines of the content are stripped
and the entry always ends with ``\\n``), empty content and the exact ``NO_REPLY`` token write
nothing (the curated daily note's rule; upstream appends even the token), the missing-parameter
messages are memory-core's, and symlinked or hard-linked targets are refused.
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
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.host._calls import ToolCallRefused, read_tool_call, tool_error
from memory_core.host.session import SessionState
from memory_core.memory_flush import (
    MemoryFlushFailureOutcome,
    record_memory_flush_failure,
    record_memory_flush_success,
)
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver
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
    """One memory flush run: ``messages`` and ``tools`` for the host's model.

    Built by ``HostKit.after_turn`` for a due flush (``reason`` is the trigger's,
    ``token_threshold`` or ``transcript_size``) or by ``HostKit.request_flush`` (``forced``). Tool
    calls of the run go to :meth:`dispatch`; the run ends with one :meth:`complete`. Parallel
    tool calls are safe (the append is locked). Completion rejects an in-flight dispatch;
    the host completes after its tool calls have returned.
    """

    def __init__(
        self,
        memory: Memory,
        *,
        session_id: str,
        compaction_count: int,
        target: str,
        reason: str,
        messages: tuple[dict[str, str], ...],
        provenance: MemoryArtifactProvenanceStore | None = None,
        untrusted: bool | Callable[[], bool] = False,
        session_key: str | None = None,
        assert_current: Callable[[], None] | None = None,
    ) -> None:
        self.target = target
        self.reason = reason
        self.messages = messages
        self.tools = (memory_flush_write_tool(target),)
        self._memory = memory
        self._session_id = session_id
        self._provenance = provenance
        self._untrusted = untrusted
        self._session_key = session_key
        self._compaction_count = compaction_count
        self._assert_current = assert_current
        self._entries: list[str] = []
        self._lock = threading.Lock()
        self._completed = False
        self._active_dispatches = 0

    def dispatch(self, name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
        """Run one tool call of the flush run and return the payload for the model.

        Only ``write`` of ``{path, content}`` to the target exists: another path (or one
        starting with ``@``) gets upstream's restriction (agent-tools.read.ts:787-790), empty
        content and the exact ``NO_REPLY`` token are skipped, anything else is appended, the
        store reindexed and upstream's ``Appended content to <target>.`` returned. Errors are
        payloads, as in ``HostKit.dispatch``; a call after :meth:`complete` raises
        ``RuntimeError``. An authority check supplied by the host may also raise.
        """
        with self._lock:
            if self._completed:
                raise RuntimeError("the flush request is already completed")
            self._active_dispatches += 1
        try:
            # Host callbacks run outside the state lock. The reservation prevents completion
            # from returning while a callback, append, provenance update or index refresh runs.
            return self._dispatch(name, arguments)
        finally:
            with self._lock:
                self._active_dispatches -= 1

    def _dispatch(self, name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
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
        if content.strip() in ("", SILENT_REPLY_TOKEN):
            return {"status": "ok", "tool": name, "path": self.target, "action": "skipped"}
        authority_error: BaseException | None = None

        def check_current() -> None:
            nonlocal authority_error
            if self._assert_current is not None:
                try:
                    self._assert_current()
                except BaseException as error:
                    authority_error = error
                    raise

        check_current()
        try:
            append_daily_memory_file(
                root,
                self.target,
                content,
                provenance=self._write_observer(root),
                assert_current=check_current if self._assert_current is not None else None,
            )
        except Exception as error:
            if error is authority_error:
                raise
            if authority_error is not None:
                raise authority_error from error
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
            if self._assert_current is not None:
                self._assert_current()
            self._memory.store.reindex(self._memory.workspace)
        except Exception as error:  # the append is committed; report, never retry
            payload["afterWriteError"] = format_error_message(error)
        return payload

    def _write_observer(self, root: Any) -> MemoryWriteProvenanceObserver | None:
        """The trust record of the append (upstream: the observer of the flush run's agent tools).

        ``untrusted`` (a bool, or a callable read at the write like ``isTurnTainted``) marks a turn
        that must not become trusted memory: the record is ``untrusted`` and stays so.
        """
        if self._provenance is None:
            return None
        untrusted = self._untrusted
        return MemoryWriteProvenanceObserver(
            store=self._provenance,
            mutation_root=root,
            workspace_dir=root,
            resolve_origin_class=lambda: "untrusted" if (untrusted() if callable(untrusted) else untrusted) else "agent",
            session_id=self._session_id,
            session_key=self._session_key,
        )

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
        another session, ``RuntimeError`` for a second call or an in-flight dispatch. An
        authority check may raise before recording either result; the request then stays closed.
        """
        with self._lock:
            if self._completed:
                raise RuntimeError("the flush request is already completed")
            if session.session_id != self._session_id:
                raise ValueError(
                    f"the flush belongs to session {self._session_id!r}, not {session.session_id!r}"
                )
            if self._active_dispatches:
                raise RuntimeError("the flush request has an in-flight dispatch")
            self._completed = True
            entries = tuple(self._entries)
        # Claim completion before calling host code: a reentrant dispatch is refused and an
        # abandoned/cancelled request cannot subsequently write or stamp a session result.
        if self._assert_current is not None:
            self._assert_current()
        entry = copy.deepcopy(dict(session.entry))
        failure = None
        if error is None:
            entry = record_memory_flush_success(
                entry, flushed_compaction_count=self._compaction_count
            )
        else:
            failure = record_memory_flush_failure(entry, error=error, redact=redact)
            entry = failure.entry
        return FlushOutcome(
            session=replace(session, entry=entry),
            wrote=bool(entries),
            entries=entries,
            failure=failure,
        )
