"""Literal offline replies through genuine SDK history/model/catalog owners.

This adapter supplies trusted inputs and passively retains actual outputs. It
does not sanitize, window, filter, normalize, or repair any model message.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from equivalence.embedding_cache_lifecycle_sdk import _failure, _owner, _sources
from equivalence.forget_lineage_sdk import _owned, _write
from equivalence.prompt_history_repair import SESSION_ID, validate_input
from equivalence.prompt_runtime_context_sdk import _iso, _returned, _wire
from equivalence.recall_signals_sdk import _capture, _database
from memory_core.client import Memory
from memory_core.compaction_replay import ReplayModel
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host import (
    HistoryReplayContext, HostKit, HostModelResult, HostSessionRunner, HostTurn, SessionState,
)
from memory_core.history_replay import HistoryReplay, resolve_history_replay_policy
from memory_core.model_prompt import ModelPrompt, RuntimePromptInput
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import resolve_memory_search_source_policy
from memory_core.turn_tool_dispatch import TurnTool


class _Owners:
    def __init__(self, root, value, now):
        self.root, self.value, self.now = root, value, now
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True)
        for relative, text in value["files"].items():
            path = _owned(self.workspace, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf8")
        self.paths = {name: root / (name + ".sqlite") for name in ("catalog", "index", "trust")}
        self.current_model = deepcopy(value["model"])
        self.open(seed=True)

    def open(self, *, seed=False):
        self.catalog = MemorySessionCatalog(self.paths["catalog"], clock_ms=lambda: self.now[0])
        if seed:
            self.catalog.upsert_session(self.value["sessionKey"], {"sessionId": SESSION_ID, "updatedAt": self.now[0]})
            events = [{"type": "session", "version": self.value["sessionVersion"], "id": SESSION_ID,
                       "timestamp": _iso(self.now[0]), "cwd": str(self.workspace)},
                      *deepcopy(self.value["transcriptEvents"])]
            self.catalog.replace_events(SESSION_ID, events, session_key=self.value["sessionKey"], updated_at_ms=self.now[0])
            self.seed_events = deepcopy(events)
        self.trust = MemoryArtifactProvenanceStore(self.paths["trust"])
        self.trust.list(self.workspace)
        self.source_policy = resolve_memory_search_source_policy(configured_sources=["memory"],
            remember_across_conversations=False, configured_session_memory=False)
        config = MemoryConfig(workspace_dir=self.workspace, store_path=self.paths["index"],
            session_search=False, flags=FeatureFlags(vector_search=False))
        self.memory = Memory.from_workspace(self.workspace, config=config, embedding_provider=None,
            initialize=False, reindex=False, artifact_provenance=self.trust, session_catalog=self.catalog,
            source_policy=self.source_policy)
        self.index_return = self.memory.store.reindex(self.memory.workspace)
        self.kit = HostKit(self.memory, seed_bootstrap=False, timezone=self.value["hostTimezone"],
            time_format=self.value["hostTimeFormat"], now_ms=lambda: self.now[0], source_policy=self.source_policy,
            artifact_provenance=self.trust, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        extra = []
        for name in ("sessions_search", "sessions_history", "session_status"):
            definition = {"name": name, "description": "Bounded fixture host capability: " + name,
                          "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}

            def execute(call_id, arguments, *, registered_name=name):
                return {"capability": registered_name, "toolCallId": call_id, "arguments": deepcopy(dict(arguments))}

            extra.append(TurnTool(name, execute, definition=definition))
        self.runner = HostSessionRunner(self.kit, self.catalog,
            session=SessionState.new(session_key=self.value["sessionKey"], session_id=SESSION_ID), extra_tools=extra)
        self.registrations = [*self.kit.tools(), *(deepcopy(tool.definition) for tool in extra)]

    def state(self):
        return {"transcript": deepcopy(self.catalog.read_transcript(SESSION_ID).events),
                "sql": {name: _database(path) for name, path in self.paths.items()},
                "sources": _sources(self.workspace)}

    async def invoke(self, operation, ordinal, actual):
        if operation["op"] == "reopen":
            self.catalog.close()
            self.open()
            actual["apiOutcome"] = {"kind": "return", "returnValue": _returned(None)}
            return {"operation": deepcopy(operation), "modelCalls": []}
        if "model" in operation:
            self.current_model = deepcopy(operation["model"])
        model = deepcopy(self.current_model)
        replay = HistoryReplayContext(model=ReplayModel(**model),
            config={"channels": deepcopy(self.value["channelConfig"])}, route=deepcopy(self.value["route"]))
        options = RuntimePromptInput(history_replay=replay, offered_tool_names=operation["tools"],
            host_timezone=self.value["hostTimezone"], host_time_format=self.value["hostTimeFormat"])
        actual["model"] = model
        actual["registeredTools"] = deepcopy(self.registrations)
        actual["callArguments"] = {"user_message": operation["prompt"], "prompt_context": _wire(options),
                                   "request_id": f"prompt-history-{ordinal}"}

        async def callback(turn):
            scripts = operation.get("scriptedTools", [])
            for index in range(len(scripts) + 1):
                request = turn.model_request()
                script = scripts[index] if index < len(scripts) else None
                response = {"role": "assistant", "content": [
                    {"type": "toolCall", **deepcopy(script)} if script
                    else {"type": "text", "text": "history fixture complete"}],
                    "api": model["api"], "provider": model["provider"], "model": model["id"],
                    "stopReason": "toolUse" if script else "stop", "timestamp": self.now[0],
                    "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
                              "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}
                if script:
                    response["responseId"] = f"prompt-history-tool-response-{ordinal}-{index}"
                receipt = {"request": {"model": deepcopy(model), "context": deepcopy(request), "options": {}},
                           "response": deepcopy(response)}
                actual["providerCalls"].append(receipt)
                receipt["recordMessageReturn"] = _returned(turn.record_message(response))
                if script:
                    tool = {"tool": script["name"], "arguments": deepcopy(script["arguments"]),
                            "toolCallId": script["id"], "beforeMessages": turn.messages}
                    actual["toolCalls"].append(tool)
                    try:
                        returned = turn.dispatch(script["id"], script["name"], script["arguments"])
                        tool["apiOutcome"] = {"kind": "return", "returnValue": _returned(returned)}
                    except BaseException as error:
                        tool["apiOutcome"] = {"kind": "throw", "error": _failure(error)}
                        raise
                    finally:
                        tool["afterMessages"] = turn.messages
                else:
                    return HostModelResult(payloads=(response,))

        try:
            result = await self.runner.run_turn(operation["prompt"], execute=callback,
                prompt_context=options, request_id=f"prompt-history-{ordinal}")
            actual["apiOutcome"] = {"kind": "return", "returnValue": _returned(result)}
        except BaseException as error:
            actual["apiOutcome"] = {"kind": "throw", "error": _failure(error)}
            raise
        owner = self.runner.last_model_prompt
        if owner is None or owner.history_replay is None:
            raise RuntimeError("The actual host did not prepare its production history replay owner")
        history = owner.history_replay
        actual["historyReplay"] = {"policy": _wire(history.policy), "historyLimit": history.history_limit,
            "snapshotState": _wire(history.snapshot_state), "stages": deepcopy(history.stages),
            "context": _wire(history.context), "allowedToolNames": list(history.allowed_tool_names)}
        actual["modelPromptClosed"] = owner.closed
        return {"operation": deepcopy(operation), "modelCalls": [
            {"messages": deepcopy(call["request"]["context"]["messages"])} for call in actual["providerCalls"]]}


def _run(value, directory):
    validate_input(value)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "sdk-fixture"
    if root.exists():
        raise ValueError("History repair requires a fresh SDK fixture directory")
    now = [value["nowMs"]]
    original_time, original_ns = time.time, time.time_ns
    monotonic, sleep = time.monotonic, time.sleep
    raw = {"kind": "prompt-history-repair-sdk", "input": deepcopy(value), "fixtureRoot": str(root),
           "workspace": str(root / "workspace"), "catalogDatabasePath": str(root / "catalog.sqlite"),
           "databasePaths": {name: str(root / (name + ".sqlite")) for name in ("catalog", "index", "trust")},
           "owners": [_owner(owner) for owner in (HostSessionRunner.run_turn, HostSessionRunner._prepare_model_prompt,
               HostTurn.model_request, HostTurn.record_message, MemorySessionCatalog.read_continuation,
               MemorySessionCatalog.read_transcript, MemorySessionCatalog.append_message,
               MemorySessionCatalog.replace_events, ModelPrompt, HistoryReplay, HistoryReplay.prepare,
               HistoryReplay.request, resolve_history_replay_policy)],
           "operations": [], "states": [], "physical": [], "clock": {"readings": []}, "closed": False}
    observations = []
    owners, business_error, catalog_closed = None, None, False
    try:
        with patch.object(time, "time_ns", lambda: now[0] * 1_000_000), \
                patch.object(time, "time", lambda: now[0] / 1000):
            owners = _Owners(root, value, now)
            raw["transcriptSeeds"] = owners.seed_events
            raw["initialState"] = owners.state()
            raw["states"].append(deepcopy(raw["initialState"]))
            raw["physical"].append(_capture(root, directory, "initial"))

            async def drive():
                for ordinal, operation in enumerate(value["operations"]):
                    now[0] = operation["nowMs"]
                    actual = {"operation": deepcopy(operation), "providerCalls": [], "toolCalls": []}
                    raw["operations"].append(actual)
                    before = owners.state()
                    actual.update(beforeTranscript=before["transcript"], beforeSql=before["sql"], sourcesBefore=before["sources"])
                    raw["clock"]["readings"].append({"operationIndex": ordinal, "requestedNowMs": now[0],
                        "actualNowMs": time.time_ns() // 1_000_000})
                    observation = await owners.invoke(operation, ordinal, actual)
                    actual["observation"] = deepcopy(observation)
                    observations.append(observation)
                    after = owners.state()
                    actual.update(afterTranscript=after["transcript"], afterSql=after["sql"], sourcesAfter=after["sources"])
                    raw["states"].append(after)
                    raw["physical"].append(_capture(root, directory, f"operation-{ordinal:03d}"))

            asyncio.run(drive())
            owners.catalog.close()
            catalog_closed = True
            raw["closed"] = all(operation.get("modelPromptClosed", True) for operation in raw["operations"])
        raw["completionStatus"] = "completed-unverified"
    except BaseException as error:
        business_error = error
        raw["error"] = _failure(error)
        raw["completionStatus"] = "rejected-unverified"
        raw["closed"] = False
        # Preserve independently observed failure facts without pretending that
        # an interrupted operation completed its normal after-state protocol.
        if owners is not None and not catalog_closed:
            try:
                raw["failureState"] = owners.state()
            except BaseException as capture_error:
                raw.setdefault("captureErrors", []).append({"operation": "failure-state", "error": _failure(capture_error)})
        if root.exists():
            try:
                raw["failurePhysical"] = _capture(root, directory, "failure-unverified")
            except BaseException as capture_error:
                raw.setdefault("captureErrors", []).append({"operation": "failure-physical", "error": _failure(capture_error)})
        raise
    finally:
        if owners is not None and not catalog_closed:
            try:
                owners.catalog.close()
            except BaseException as close_error:
                raw.setdefault("closeErrors", []).append(_failure(close_error))
        raw["clock"]["restored"] = {"time": time.time is original_time, "timeNs": time.time_ns is original_ns,
                                     "monotonic": time.monotonic is monotonic, "sleep": time.sleep is sleep}
        raw["output"] = {"observations": observations}
        try:
            _write(directory / "python-raw.json", [raw])
        except BaseException as capture_error:
            raw.setdefault("captureErrors", []).append({"operation": "write-python-raw", "error": _failure(capture_error)})
            raw["completionStatus"] = "rejected-unverified"
            raw["closed"] = False
            try:
                _write(directory / "python-raw-failure-unverified.json", [raw])
            except BaseException as fallback_error:
                raw.setdefault("captureErrors", []).append({"operation": "write-failure-raw", "error": _failure(fallback_error)})
            if business_error is None:
                raise
    return raw["output"]


def run_prompt_history_repair(value, *, evidence_directory=None):
    if evidence_directory is None:
        with TemporaryDirectory(prefix="memory-history-repair-") as directory:
            return _run(value, directory)
    return _run(value, evidence_directory)
