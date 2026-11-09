"""The memory flush run a host executes after a turn (docs/host_kit.md, entry point 4).

``HostKit.after_turn`` returns a :class:`FlushRequest` when the flush is due (and the extension
``HostKit.request_flush`` one on the host's demand): the messages and tools of the flush
run, a ``dispatch`` for that tool's calls and ``complete`` for the session entry. The host runs
the model (later in the same process, detached from the reply, as upstream runs flush
maintenance) and never delivers or records the flush reply; the session's next ``after_turn``
waits for ``complete`` (one maintenance lane per session).

The tool is upstream's ``write`` restricted to appending the daily target
(src/agents/agent-tools.memory-flush.ts keeps ``read`` and an append-only ``write``). A host may
delegate its generic ``read`` definition and callback; the SDK does not implement a second
general filesystem/image tool. Write content is preserved exactly, including empty content,
whitespace and ``NO_REPLY``. Symlinked or hard-linked targets remain explicitly refused.
"""

from __future__ import annotations

import copy
import asyncio
import concurrent.futures
import hashlib
import os
import re
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import unquote, urlsplit

from memory_core._memory_flush_constants import (
    MEMORY_FLUSH_WRITE_APPENDED_TEMPLATE,
    MEMORY_FLUSH_WRITE_DESCRIPTION_TEMPLATE,
    MEMORY_FLUSH_WRITE_RESTRICTED_TEMPLATE,
    WRITE_TOOL_CONTENT_DESCRIPTION,
    WRITE_TOOL_DESCRIPTION,
    WRITE_TOOL_PATH_DESCRIPTION,
)
from memory_core.client import Memory
from memory_core.bootstrap._js import js_json_stringify, js_trim, js_truthy, js_utf8_encode
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
from memory_core.workspace import append_memory_flush_file

WRITE_TOOL_NAME = "write"


def _optional_text(value: Any) -> str | None:
    text = js_trim(value) if isinstance(value, str) else ""
    return text or None


def _error_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    # The native definition adapter uses jsonResult(payload); the complete
    # agent loop marks the resulting refused tool message isError=True.
    # This remains recoverable by the model, rather than a failed final reply.
    return {**payload, "content": [{"type": "text", "text": js_json_stringify(payload, indent=2)}],
            "details": dict(payload), "isError": True}


def _renderable_error_payload(payload: Mapping[str, Any]) -> bool:
    """The canonical text/media payload surface; richer UI metadata belongs to the host."""
    media = payload.get("mediaUrls")
    if (
        _optional_text(payload.get("text"))
        or _optional_text(payload.get("mediaUrl"))
        or (isinstance(media, (list, tuple)) and any(_optional_text(item) for item in media))
        or (isinstance(payload.get("channelData"), Mapping) and bool(payload["channelData"]))
        or payload.get("location") is not None
        or js_truthy(payload.get("audioAsVoice"))
    ):
        return True
    if any(payload.get(key) is not None for key in ("presentation", "interactive", "tts")):
        raise ValueError(
            "presentation, interactive and TTS-only error payloads require payload_is_renderable"
        )
    return False


def _is_cancelled(error: BaseException | str | None) -> bool:
    if isinstance(error, (asyncio.CancelledError, concurrent.futures.CancelledError)):
        return True
    if not isinstance(error, BaseException):
        return False
    return (
        getattr(error, "name", type(error).__name__) == "AbortError"
        or str(error) == "This operation was aborted"
    )


def _write_parameter_error(args: Mapping[str, Any]) -> str | None:
    missing = [key for key in ("path", "content")
               if not isinstance(args.get(key), str)
               or (key == "path" and not js_trim(args[key]))]
    if not missing:
        return None
    received = []
    for key, value in args.items():
        if value is None:
            continue
        hint = ""
        if isinstance(value, str):
            hint = "=<empty-string>" if key != "content" and not js_trim(value) else ""
        elif isinstance(value, list):
            hint = "=<array>"
        elif isinstance(value, bool):
            hint = "=<boolean>"
        elif isinstance(value, int | float):
            hint = "=<number>"
        else:
            hint = "=<object>"
        received.append(f"{key}{hint}")
    noun = "parameter" if len(missing) == 1 else "parameters"
    suffix = f" (received: {', '.join(received)})" if received else ""
    return f"Missing required {noun}: {', '.join(missing)}{suffix}. Supply correct parameters before retrying."


def _normalized_write_path(file_path: str, root: Any) -> str:
    # Match the model path repairs before comparing the one permitted target.
    repaired = re.sub(r"</arg_value>>+$", "", file_path)
    candidate = repaired
    if re.match(r"^file://", candidate, re.IGNORECASE):
        try:
            parsed = urlsplit(candidate)
            if (parsed.scheme.lower() == "file" and parsed.netloc.lower() in {"", "localhost"}
                    and not re.search(r"%(?:2f|5c)", parsed.path, re.IGNORECASE)
                    and not re.search(r"%(?![0-9a-fA-F]{2})", parsed.path)):
                candidate = unquote(parsed.path, errors="strict")
        except (UnicodeError, ValueError):
            pass
    result = os.path.normpath(os.path.join(root, candidate))
    return "/" + result.lstrip("/") if result.startswith("//") else result


def _execution_identity(agent_id: str, run_id: str) -> tuple[str, str]:
    normalized_agent = re.sub(r"[^a-z0-9_-]+", "-", js_trim(agent_id).lower()).strip("-")[:64] or "main"
    units = run_id.encode("utf-16-le", errors="surrogatepass")
    js_units = "".join(chr(int.from_bytes(units[index:index + 2], "little"))
                       for index in range(0, len(units), 2))
    readable = re.sub(r"[^a-zA-Z0-9._-]", "_", js_units)[:48] or "run"
    suffix = f"{readable}-{hashlib.sha256(js_utf8_encode(run_id)).hexdigest()[:16]}"
    key_suffix = f"legacy-{suffix}" if suffix.startswith("incognito-") else suffix
    return (
        f"internal-session-effects-{suffix}",
        f"agent:{normalized_agent}:internal-session-effects:{key_suffix}",
    )


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
    cancelled: bool = False


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
        read_tool: Mapping[str, Any] | None = None,
        read_dispatch: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
        run_id: str | None = None,
        agent_id: str = "main",
        maintenance: bool = True,
        index_refresh: Callable[[], bool] | None = None,
    ) -> None:
        self.target = target
        self.reason = reason
        self.messages = messages
        if (read_tool is None) != (read_dispatch is None):
            raise ValueError("read_tool and read_dispatch must be supplied together")
        if read_tool is not None and read_tool.get("name") != "read":
            raise ValueError("the delegated flush read tool must be named read")
        if read_dispatch is not None and not callable(read_dispatch):
            raise TypeError("read_dispatch must be callable")
        self.tools = (
            *((copy.deepcopy(dict(read_tool)),) if read_tool is not None else ()),
            memory_flush_write_tool(target),
        )
        self._read_dispatch = read_dispatch
        self._memory = memory
        self._index_refresh = index_refresh or memory._refresh_index
        self._session_id = session_id
        self._provenance = provenance
        self._untrusted = untrusted
        # The native maintenance followup clears senderIsOwner, regardless of
        # the source turn's ownership. A flush cannot elevate that writer.
        self._maintenance = maintenance
        self._session_key = session_key
        self._run_id = run_id if run_id is not None else str(uuid.uuid4())
        self._execution_session_id, self._execution_session_key = _execution_identity(agent_id, self._run_id)
        self._compaction_count = compaction_count
        self._assert_current = assert_current
        self._entries: list[str] = []
        self._lock = threading.Lock()
        self._completed = False
        self._active_dispatches = 0

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def execution_session_id(self) -> str:
        return self._execution_session_id

    @property
    def execution_session_key(self) -> str:
        return self._execution_session_key

    def dispatch(self, name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
        """Run one tool call of the flush run and return the payload for the model.

        ``write`` of ``{path, content}`` appends to the target: another path (or one
        starting with ``@``) gets upstream's restriction. Every string is appended exactly;
        the store is reindexed and upstream's ``Appended content to <target>.`` returned.
        A configured ``read`` is delegated to the host unchanged. Errors are
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
            return _error_receipt(refused.payload)
        if name == "read" and self._read_dispatch is not None:
            if self._assert_current is not None:
                self._assert_current()
            try:
                result = self._read_dispatch(args)
            except Exception as error:
                return _error_receipt(to_tool_error(error, tool=name))
            if self._assert_current is not None:
                self._assert_current()
            return result
        if name != WRITE_TOOL_NAME:
            return _error_receipt(tool_error(name, f"tool {name} is not available"))
        path = args.get("path")
        content = args.get("content")
        parameter_error = _write_parameter_error(args)
        if parameter_error is not None:
            return _error_receipt(tool_error(name, parameter_error))
        assert isinstance(path, str) and isinstance(content, str)
        root = self._memory.workspace.root
        allowed = os.path.normpath(os.path.join(root, self.target))
        if path.startswith("@") or _normalized_write_path(path, root) != allowed:
            return _error_receipt(tool_error(
                name, MEMORY_FLUSH_WRITE_RESTRICTED_TEMPLATE.format(relative_path=self.target)
            ))
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
            append_memory_flush_file(
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
            return _error_receipt(to_tool_error(error, tool=name))
        with self._lock:
            self._entries.append(content)
        payload: dict[str, Any] = {
            "status": "ok",
            "tool": name,
            "path": self.target,
            "action": "appended",
            "text": MEMORY_FLUSH_WRITE_APPENDED_TEMPLATE.format(relative_path=self.target),
            "content": [{"type": "text", "text": MEMORY_FLUSH_WRITE_APPENDED_TEMPLATE.format(
                relative_path=self.target
            )}],
            "details": {"changed": True},
        }
        try:
            if self._assert_current is not None:
                self._assert_current()
        except Exception as error:  # native tool rejection after a committed append
            payload.update(_error_receipt(to_tool_error(error, tool=name)))
            payload["afterWriteError"] = format_error_message(error)
            return payload
        try:
            if not self._index_refresh():
                payload["indexStatus"] = "pending"
        except Exception as error:  # the append is committed; report, never retry
            payload["afterWriteError"] = format_error_message(error)
        return payload

    def _write_observer(self, root: Any) -> MemoryWriteProvenanceObserver | None:
        """The trust record of the append (upstream: the observer of the flush run's agent tools).

        ``untrusted`` (a bool, or a callable read at the write like ``isTurnTainted``) marks a turn
        that must not become trusted memory. Native automatic maintenance additionally clears
        sender ownership, so its record is always ``untrusted``; the explicit forced extension
        retains its caller-supplied trust policy. Existing quarantine remains sticky.
        """
        if self._provenance is None:
            return None
        untrusted = self._untrusted

        def resolve_origin_class():
            turn_untrusted = untrusted() if callable(untrusted) else untrusted
            return "untrusted" if self._maintenance or turn_untrusted else "agent"

        return MemoryWriteProvenanceObserver(
            store=self._provenance,
            mutation_root=root,
            workspace_dir=root,
            resolve_origin_class=resolve_origin_class,
            session_id=self.execution_session_id,
            session_key=self.execution_session_key,
        )

    def complete(
        self,
        session: SessionState,
        *,
        error: BaseException | str | None = None,
        redact: Callable[[str], str] | None = None,
        payloads: Sequence[Mapping[str, Any]] | None = None,
        cancelled: bool = False,
        payload_is_renderable: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> FlushOutcome:
        """Record the run in the host's current state of this session.

        Success stamps ``memoryFlush`` for the compaction cycle the request was made in
        (``flushedCompactionCount``, agent-runner-memory.ts:1517, 1665-1671); ``error`` records a
        failure strike (three mark the cycle flushed) with ``redact`` applied to its message. A
        cancelled run is not completed (upstream records nothing for it). ``ValueError`` for
        another session, ``RuntimeError`` for a second call or an in-flight dispatch. An
        authority check may raise before recording either result; the request then stays closed.
        ``payloads`` are resolved model payloads: renderable ``isError`` rows prevent success.
        Canonical text/media fields have a default classifier; interactive/TTS-only errors
        require the host's ``payload_is_renderable`` callback. A cancelled run records no stamp.
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
        entry = copy.deepcopy(dict(session.entry))
        if cancelled or _is_cancelled(error):
            return FlushOutcome(replace(session, entry=entry), bool(entries), entries, None, True)
        if self._assert_current is not None:
            self._assert_current()
        if error is None and payloads is not None:
            renderable = payload_is_renderable or _renderable_error_payload
            visible_errors = [payload for payload in payloads
                              if payload.get("isError") is True and renderable(payload)]
            if visible_errors:
                text = "\n".join(text for payload in visible_errors
                                 if (text := _optional_text(payload.get("text"))))
                error = RuntimeError(text or "Memory flush returned an error response")
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
