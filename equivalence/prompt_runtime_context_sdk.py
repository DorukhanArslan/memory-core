"""Observe the SDK's real host admission, model boundary and durable catalog.

The offline model only returns literal replies/tool requests. Prompt composition,
projection, tool execution and persistence belong to production SDK owners.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
import inspect
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from equivalence.embedding_cache_lifecycle_sdk import _failure, _owner, _sources
from equivalence.forget_lineage_sdk import _owned, _write
from equivalence.recall_signals_sdk import _capture, _database
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.current_time import resolve_cron_style_now
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, HostModelResult, HostSessionRunner, HostTurn, SessionState
from memory_core.index import temporal_decay
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.model_prompt import MEMORY_PROMPT_TOOL_NAMES, ModelPrompt, RuntimePromptInput, normalize_model_messages
from memory_core.prompt_section import build_prompt_section
from memory_core.runtime_context_prompt import project_runtime_context_fragments, resolve_runtime_context_prompt_parts
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.turn_tool_dispatch import TurnTool, TurnToolDispatcher

SESSION_KEY = "agent:main:main"
SESSION_ID = "prompt-runtime-session"
MODEL = {"id": "fixture-model", "api": "openai-completions", "provider": "fixture-prompt-runtime-model"}


def _wire(value):
    if is_dataclass(value):
        return {field.name: _wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return {"type": type(value).__name__, "values": [_wire(item) for item in value]}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    return value


def _returned(value):
    return {"type": type(value).__name__, "value": _wire(value)}


def _iso(now):
    return datetime.fromtimestamp(now / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _FixtureModel:
    """A real host model callback with no prompt assembly or expected messages."""

    def __init__(self, operation, calls, tool_calls, clock, operation_index):
        self.operation, self.calls, self.tool_calls, self.clock = operation, calls, tool_calls, clock
        self.operation_index = operation_index

    async def __call__(self, turn):
        scripted = self.operation.get("scriptedTools", [])
        for ordinal in range(len(scripted) + 1):
            request = turn.model_request()
            tool = scripted[ordinal] if ordinal < len(scripted) else None
            response = {"role": "assistant", "content": [
                {"type": "toolCall", **deepcopy(tool)} if tool else {"type": "text", "text": "prompt fixture complete"}],
                "api": MODEL["api"], "provider": MODEL["provider"], "model": MODEL["id"],
                "stopReason": "toolUse" if tool else "stop", "timestamp": self.clock(),
                "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
                          "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}
            if tool:
                response["responseId"] = f"prompt-tool-response-{self.operation_index}-{ordinal}"
            call = {"request": {"model": deepcopy(MODEL), "context": deepcopy(request), "options": {}},
                    "response": deepcopy(response)}
            self.calls.append(call)
            saved = turn.record_message(response)
            call["recordMessageReturn"] = _returned(saved)
            if tool:
                receipt = {"tool": tool["name"], "arguments": deepcopy(tool["arguments"]),
                           "toolCallId": tool["id"], "beforeMessages": turn.messages}
                self.tool_calls.append(receipt)
                try:
                    returned = turn.dispatch(tool["id"], tool["name"], tool["arguments"])
                    receipt["apiOutcome"] = {"kind": "return", "returnValue": _returned(returned)}
                except BaseException as error:
                    receipt["apiOutcome"] = {"kind": "throw", "error": _failure(error)}
                    raise
                finally:
                    receipt["afterMessages"] = turn.messages
            else:
                return HostModelResult(payloads=(response,))


class _Owners:
    def __init__(self, root, value, now):
        self.root, self.value, self.now = root, value, now
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True)
        self.catalog_path, self.index_path, self.trust_path = (
            root / "catalog.sqlite", root / "index.sqlite", root / "trust.sqlite")
        self.file_writes = []
        for relative, text in value["files"].items():
            path = _owned(self.workspace, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf8")
            before = _sources(self.workspace)
            returned = os.utime(path, ns=(value["fileMtimeMs"] * 1_000_000,) * 2)
            self.file_writes.append({"owner": "os.utime", "arguments": {"path": str(path),
                "ns": [value["fileMtimeMs"] * 1_000_000] * 2}, "returnValue": _returned(returned),
                "sourcesBefore": before, "sourcesAfter": _sources(self.workspace)})
        self.open(seed=True)

    def open(self, *, seed=False):
        self.catalog = MemorySessionCatalog(self.catalog_path, clock_ms=lambda: self.now[0])
        if seed:
            self.catalog.upsert_session(SESSION_KEY, {"sessionId": SESSION_ID, "updatedAt": self.now[0]})
            events = [{"type": "session", "version": self.value["sessionVersion"], "id": SESSION_ID,
                       "timestamp": _iso(self.now[0]), "cwd": str(self.workspace)}]
            previous = None
            for ordinal, message in enumerate(self.value["messages"]):
                identifier = f"prompt-seed-{ordinal}"
                event = {"id": identifier, "parentId": previous, "timestamp": _iso(message["timestamp"])}
                if message["role"] == "custom":
                    event.update(type="custom_message", **{key: deepcopy(item) for key, item in message.items()
                        if key not in {"role", "timestamp"}})
                else:
                    event.update(type="message", message=deepcopy(message))
                events.append(event)
                previous = identifier
            self.catalog.replace_events(SESSION_ID, events, session_key=SESSION_KEY, updated_at_ms=self.now[0])
            self.seed_events = deepcopy(events)
        self.trust = MemoryArtifactProvenanceStore(self.trust_path)
        self.trust.list(self.workspace)
        config = MemoryConfig(workspace_dir=self.workspace, store_path=self.index_path,
            session_search=False, flags=FeatureFlags(vector_search=False))
        self.memory = Memory.from_workspace(self.workspace, config=config, embedding_provider=None,
            initialize=False, reindex=False, artifact_provenance=self.trust, session_catalog=self.catalog)
        self.index_return = self.memory.store.reindex(self.memory.workspace)
        self.kit = HostKit(self.memory, seed_bootstrap=False, timezone=self.value["hostTimezone"],
            time_format=self.value["hostTimeFormat"], identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
            artifact_provenance=self.trust, now_ms=lambda: self.now[0])
        extra = []
        for name in ("sessions_search", "sessions_history", "session_status"):
            definition = {"name": name, "description": "Bounded fixture host capability: " + name,
                          "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}

            def execute(call_id, arguments, *, registered_name=name):
                return {"capability": registered_name, "toolCallId": call_id, "arguments": deepcopy(dict(arguments))}

            extra.append(TurnTool(name, execute, definition=definition))
        self.runner = HostSessionRunner(self.kit, self.catalog,
            session=SessionState.new(session_key=SESSION_KEY, session_id=SESSION_ID), extra_tools=extra)
        self.registrations = [*self.kit.tools(), *(deepcopy(tool.definition) for tool in extra)]

    def state(self):
        return {"transcript": deepcopy(self.catalog.read_transcript(SESSION_ID).events),
                "sql": {"catalog": _database(self.catalog_path), "index": _database(self.index_path),
                        "trust": _database(self.trust_path)}, "sources": _sources(self.workspace)}

    async def invoke(self, operation, ordinal, actual):
        if operation["op"] == "reopen":
            self.open()
            actual["apiOutcome"] = {"kind": "return", "returnValue": _returned(None)}
            return {"operation": deepcopy(operation), "memoryGuidance": None, "clock": None, "modelCalls": []}
        actual["registeredTools"] = deepcopy(self.registrations)
        options = RuntimePromptInput(fragments=operation["fragments"],
            transcript_prompt=operation.get("transcriptPrompt"),
            current_inbound_context=operation.get("currentInboundContext"),
            suppress_next_user_message_persistence=operation.get("suppressNextUserMessagePersistence", False),
            offered_tool_names=operation["tools"], citations_mode=operation["citationsMode"],
            timezone=operation.get("timezone"), host_timezone=self.value["hostTimezone"],
            host_time_format=self.value["hostTimeFormat"], include_clock=operation["includeClock"])
        actual["callArguments"] = {"user_message": operation["effectivePrompt"], "prompt_context": _wire(options),
                                   "request_id": f"prompt-runtime-{ordinal}"}
        callback = _FixtureModel(operation, actual["providerCalls"], actual["toolCalls"], lambda: self.now[0], ordinal)
        try:
            returned = await self.runner.run_turn(operation["effectivePrompt"], execute=callback,
                prompt_context=options, request_id=f"prompt-runtime-{ordinal}")
            actual["apiOutcome"] = {"kind": "return", "returnValue": _returned(returned)}
        except BaseException as error:
            actual["apiOutcome"] = {"kind": "throw", "error": _failure(error)}
            raise
        owner = self.runner.last_model_prompt
        if owner is None:
            raise RuntimeError("The actual host did not prepare a model prompt")
        actual["effectiveMemoryGuidance"] = deepcopy(owner.memory_guidance)
        if owner.clock_call is not None:
            actual["clockCall"] = deepcopy(owner.clock_call)
        actual["modelPromptClosed"] = owner.closed
        return {"operation": deepcopy(operation), "memoryGuidance": deepcopy(owner.memory_guidance),
                "clock": deepcopy(owner.clock), "modelCalls": [
                    {"messages": deepcopy(call["request"]["context"]["messages"])} for call in actual["providerCalls"]]}


def _run(value, directory):
    from equivalence.prompt_runtime_context import validate_input

    validate_input(value)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "sdk-fixture"
    if root.exists():
        raise ValueError("Prompt runtime context requires a fresh SDK fixture directory")
    now = [value["nowMs"]]
    original_ns, original_time = time.time_ns, time.time
    original_monotonic, original_sleep = time.monotonic, time.sleep
    original_datetime = temporal_decay.datetime
    original_profiler = sys.getprofile()
    active_operation, prompt_frames = [None], {}

    def observe_prompt_owner(frame, event, returned):
        if frame.f_code is build_prompt_section.__code__ and active_operation[0] is not None:
            if event == "call":
                available = frame.f_locals["available_tools"]
                receipt = {"owner": "build_prompt_section", "arguments": {
                    "available_tools": _wire(available), "citations_mode": frame.f_locals["citations_mode"]},
                    "toolAvailability": {name: name in available for name in MEMORY_PROMPT_TOOL_NAMES}}
                active_operation[0]["memoryPromptCalls"].append(receipt)
                prompt_frames[id(frame)] = receipt
            elif event == "return" and id(frame) in prompt_frames:
                prompt_frames.pop(id(frame))["returnValue"] = deepcopy(returned)
        if original_profiler is not None:
            original_profiler(frame, event, returned)

    class PhaseDateTime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(now[0] / 1000, tz=tz)

    raw = {"kind": "prompt-runtime-context-sdk", "input": deepcopy(value), "fixtureRoot": str(root),
           "workspace": str(root / "workspace"), "catalogDatabasePath": str(root / "catalog.sqlite"),
           "databasePaths": {name: str(root / (name + ".sqlite")) for name in ("catalog", "index", "trust")},
           "host": {"timezone": value["hostTimezone"], "timeFormat": value["hostTimeFormat"]},
           "owners": [_owner(owner) for owner in (HostSessionRunner.run_turn, HostSessionRunner._prepare_model_prompt,
               HostTurn.model_request, HostTurn.record_message, HostTurn.dispatch, HostKit.before_turn, HostKit.dispatch,
               MemorySessionCatalog.read_continuation, MemorySessionCatalog.read_transcript,
               MemorySessionCatalog.append_message, Memory.from_workspace, SQLiteMemoryStore.reindex, ModelPrompt,
               normalize_model_messages, build_prompt_section, resolve_cron_style_now,
               project_runtime_context_fragments, resolve_runtime_context_prompt_parts, TurnToolDispatcher.dispatch)],
           "operations": [], "states": [], "physical": [], "clock": {"reads": []}, "closed": False}
    observations = []
    def clock_read(phase, ordinal=None):
        return {"phase": phase, "operationIndex": ordinal, "requestedNowMs": now[0],
                "timeNs": time.time_ns(), "timeMs": time.time() * 1000,
                "temporalDecayNowMs": int(temporal_decay.datetime.now(UTC).timestamp() * 1000),
                "monotonicUnchanged": time.monotonic is original_monotonic,
                "sleepUnchanged": time.sleep is original_sleep}

    with patch.object(time, "time_ns", lambda: now[0] * 1_000_000), \
            patch.object(time, "time", lambda: now[0] / 1000), patch.object(temporal_decay, "datetime", PhaseDateTime):
        raw["clock"]["reads"].append(clock_read("initial"))
        owners = _Owners(root, value, now)
        raw["transcriptSeeds"], raw["mtimeWrites"] = owners.seed_events, owners.file_writes
        raw["registeredTools"] = deepcopy(owners.registrations)
        raw["initialIndexReturn"] = _returned(owners.index_return)
        raw["initialState"] = owners.state()
        raw["states"].append(deepcopy(raw["initialState"]))
        raw["physical"].append(_capture(root, directory, "initial"))

        async def drive():
            for ordinal, operation in enumerate(value["operations"]):
                now[0] = operation["nowMs"]
                actual = {"operation": deepcopy(operation), "providerCalls": [], "toolCalls": [], "memoryPromptCalls": []}
                before = owners.state()
                actual.update(beforeTranscript=before["transcript"], beforeSql=before["sql"], sourcesBefore=before["sources"])
                raw["operations"].append(actual)
                raw["clock"]["reads"].append(clock_read("operation", ordinal))
                active_operation[0] = actual
                try:
                    observation = await owners.invoke(operation, ordinal, actual)
                finally:
                    active_operation[0] = None
                actual["observation"] = deepcopy(observation)
                observations.append(observation)
                after = owners.state()
                actual.update(afterTranscript=after["transcript"], afterSql=after["sql"], sourcesAfter=after["sources"])
                raw["states"].append(after)
                raw["physical"].append(_capture(root, directory, f"operation-{ordinal:03d}"))

        sys.setprofile(observe_prompt_owner)
        try:
            asyncio.run(drive())
        finally:
            sys.setprofile(original_profiler)
        raw["closed"] = all(operation.get("modelPromptClosed", True) for operation in raw["operations"])
    raw["clock"]["restored"] = {"timeNs": time.time_ns is original_ns, "time": time.time is original_time,
        "monotonic": time.monotonic is original_monotonic, "sleep": time.sleep is original_sleep,
        "temporalDecayDatetime": temporal_decay.datetime is original_datetime,
        "profiler": sys.getprofile() is original_profiler}
    raw["clock"]["inheritedDatetimeMethodsUnchanged"] = {name:
        inspect.getattr_static(PhaseDateTime, name) is inspect.getattr_static(original_datetime, name)
        for name in ("fromtimestamp", "timestamp", "isoformat", "astimezone")}
    raw["output"] = {"observations": observations}
    _write(directory / "python-raw.json", [raw])
    return raw["output"]


def run_prompt_runtime_context(value, *, evidence_directory=None):
    if evidence_directory is not None:
        return _run(value, evidence_directory)
    with TemporaryDirectory(prefix="memory-core-prompt-runtime-") as directory:
        return _run(value, directory)
