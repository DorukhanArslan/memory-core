"""Natural SDK save/follow-up turns, without a fixture publication barrier.

The model fixture selects real registered tools and reads their complete actual
messages. Producer metadata is a declared filesystem input, applied before the
terminal model reply. No synchronization is inserted between host calls.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import importlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from equivalence.host_restart_sdk import (
    _model_input, _observed_tool_result, _plain, _source, _source_metadata, _sqlite_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."
MODEL = {"provider": "host-turn-barrier-offline-model", "model": "actual-result-reader"}
_ABSENT = object()


class _NoticeObservations:
    """Reversible raw-only forwarding; no engine calls belong to this observer."""

    METHODS = ("status", "search", "reindex", "reindex_sources", "_defer_memory_publication",
               "_on_search_snapshot", "_submit_memory_publication", "_run_memory_publication",
               "_record_rebuild_request", "_on_index_preparation_admitted",
               "_on_index_publication_write", "publish_prepared_index")

    def __init__(self, owner, stamp, context, *, header=None):
        self.owner, self.stamp, self.context = owner, stamp, context
        self._objects, self._restorations = {}, []
        self._local = threading.local()
        self.data = {"version": 1, **(header or {}), "references": [], "calls": [],
                     "events": [], "captures": [], "hookDescriptors": []}
        self.manager_ref = self.reference(owner, "manager")
        self.data["managerRef"] = self.manager_ref

    def reference(self, value, kind):
        identifier = id(value)
        if identifier not in self._objects:
            ref = f"ref-{len(self._objects) + 1}"
            row = {"ref": ref, "kind": kind, "objectId": str(identifier),
                   "module": type(value).__module__, "qualname": type(value).__qualname__}
            self._objects[identifier] = (value, row)
            self.data["references"].append(row)
        return self._objects[identifier][1]["ref"]

    def notice(self, value=_ABSENT):
        if value is _ABSENT:
            value = vars(self.owner).get("_automatic_rebuild_notice")
        scalar = {"sequencePresent": isinstance(value, dict) and dict.__contains__(value, "sequence"),
                  "warningPresent": isinstance(value, dict) and dict.__contains__(value, "warning")}
        if scalar["sequencePresent"]:
            scalar["sequence"] = dict.__getitem__(value, "sequence")
        if scalar["warningPresent"]:
            scalar["warning"] = dict.__getitem__(value, "warning")
        return {"noticeRef": self.reference(value, "notice"), "noticeScalar": scalar}

    def emit(self, method, phase, **fields):
        row = {**self.stamp(), "threadId": threading.get_ident(), **self.context(),
               "method": method, "phase": phase, "managerRef": self.manager_ref, **fields}
        self.data["events"].append(row)
        return row

    def _begin(self, method, original, args):
        stack = getattr(self._local, "calls", ())
        entered = self.emit(method, "enter", **self.notice())
        call = {"callId": f"call-{entered['sequence']}", "method": method,
                "managerRef": self.manager_ref, "originalFunctionRef": self.reference(original, "function"),
                "parentSynchronousCallId": stack[-1] if stack else None,
                "enterSequence": entered["sequence"], "args": args,
                "beforeNotice": {key: entered[key] for key in ("noticeRef", "noticeScalar")},
                "originalInvocations": 0}
        entered.update(callId=call["callId"], originalFunctionRef=call["originalFunctionRef"],
                       parentSynchronousCallId=call["parentSynchronousCallId"])
        if method in {"status", "_record_rebuild_request"}:
            entered["callerStack"] = traceback.format_stack()
        self.data["calls"].append(call)
        self._local.calls = (*stack, call["callId"])
        return call

    def _finish(self, call, *, returned=_ABSENT, error=None):
        fields = {"callId": call["callId"], "originalFunctionRef": call["originalFunctionRef"],
                  "parentSynchronousCallId": call["parentSynchronousCallId"], **self.notice()}
        if error is not None:
            fields["errorRef"] = call["errorRef"] = self.reference(error, "exception")
        elif returned is None or isinstance(returned, (str, int, float, bool)):
            fields["returnPrimitive"] = call["returnPrimitive"] = returned
        else:
            fields["returnRef"] = call["returnRef"] = self.reference(returned, "return")
        finished = self.emit(call["method"], "error" if error is not None else "return", **fields)
        call.update(returnSequence=finished["sequence"], afterNotice={key: fields[key]
                    for key in ("noticeRef", "noticeScalar")})
        self._local.calls = self._local.calls[:-1]

    def _local_notice(self):
        record = getattr(self.owner._local, "automatic_repair_notice", None)
        return None if record is None else {"ref": self.reference(record, "local-repair-notice"),
                                            "recorded": record.get("recorded"),
                                            "unopened": record.get("unopened")}

    def _method_wrapper(self, name, original):
        def observed(*args, **kwargs):
            primitives = {key: value for key, value in kwargs.items()
                          if value is None or isinstance(value, (str, int, float, bool))}
            if name == "search" and args:
                primitives["query"] = args[0]
            if name == "publish_prepared_index" and len(args) > 1:
                primitives["expectedRevision"] = args[1]
            call = self._begin(name, original, primitives)
            call["originalReceiverIsExactOwner"] = getattr(original, "__self__", None) is self.owner
            if name == "_on_index_publication_write":
                call["localRepairNoticeBefore"] = self._local_notice()
                if kwargs.get("error") is not None:
                    call["publicationErrorRef"] = self.reference(kwargs["error"], "exception")
            try:
                call["originalInvocations"] += 1
                result = original(*args, **kwargs)
            except BaseException as error:
                self._finish(call, error=error)
                raise
            else:
                if name == "status":
                    custom = result.get("custom")
                    notice = custom.get("automaticRebuildNotice") if isinstance(custom, dict) else None
                    call["statusReturn"] = {"statusRef": self.reference(result, "status"),
                        "customRef": self.reference(custom, "status-custom"), **self.notice(notice),
                        "noticeIsOwnerObject": notice is vars(self.owner).get("_automatic_rebuild_notice")}
                if name == "_on_index_publication_write":
                    call["localRepairNoticeAfter"] = self._local_notice()
                self._finish(call, returned=result)
                return result
        return observed

    def _capture_wrapper(self, original):
        def capture(status):
            call = self._begin("_capture_rebuild_notice", original,
                               {"statusRef": self.reference(status, "status")})
            try:
                call["originalInvocations"] += 1
                reader = original(status)
            except BaseException as error:
                self._finish(call, error=error)
                raise
            cells = dict(zip(reader.__code__.co_freevars,
                             (cell.cell_contents for cell in reader.__closure__ or ()), strict=True))
            notice, sequence = cells["notice"], cells["sequence"]
            captured = {"captureCallId": call["callId"], "statusRef": self.reference(status, "status"),
                **self.notice(notice), "capturedSequence": sequence,
                "originalReaderRef": self.reference(reader, "original-reader"),
                "closureFreevars": list(reader.__code__.co_freevars),
                "closureCellRefs": {name: self.reference(value, "closure-cell") for name, value in cells.items()},
                "noticeIsOwnerObject": notice is vars(self.owner).get("_automatic_rebuild_notice")}

            def observed_reader():
                reading = self._begin("notice-reader", reader, {})
                reading.update(originalReaderRef=captured["originalReaderRef"],
                    observedReaderRef=captured["observedReaderRef"], captureCallId=call["callId"],
                    capturedSequence=sequence, capturedNoticeBefore=self.notice(notice))
                try:
                    reading["originalInvocations"] += 1
                    result = reader()
                except BaseException as error:
                    reading["capturedNoticeAfter"] = self.notice(notice)
                    self._finish(reading, error=error)
                    raise
                reading["capturedNoticeAfter"] = self.notice(notice)
                self._finish(reading, returned=result)
                return result

            captured["observedReaderRef"] = self.reference(observed_reader, "observed-reader")
            self.data["captures"].append(captured)
            call.update(originalReaderRef=captured["originalReaderRef"],
                        observedReaderRef=captured["observedReaderRef"])
            self._finish(call, returned=reader)
            return observed_reader
        return capture

    def _replace(self, target, name, replacement, original):
        previous = vars(target).get(name, _ABSENT)
        descriptor = {"name": name, "targetRef": self.reference(target, "hook-target"),
            "originalFunctionRef": self.reference(original, "function"),
            "inherited": previous is _ABSENT, "replacementRef": self.reference(replacement, "observer")}
        function = getattr(original, "__func__", original)
        descriptor["originalCodeFunctionRef"] = self.reference(function, "code-function")
        if hasattr(function, "__code__"):
            descriptor["originalCode"] = {"path": function.__code__.co_filename,
                                          "line": function.__code__.co_firstlineno,
                                          "qualname": function.__qualname__}
        descriptor["declaringClass"] = next((f"{cls.__module__}.{cls.__qualname__}"
            for cls in type(target).__mro__ if name in vars(cls)), None)
        if previous is not _ABSENT:
            descriptor["previousOwnRef"] = self.reference(previous, "own-descriptor")
        self.data["hookDescriptors"].append(descriptor)
        setattr(target, name, replacement)
        self._restorations.append((target, name, previous, descriptor))

    def install(self, module):
        for name in self.METHODS:
            original = getattr(self.owner, name)
            self._replace(self.owner, name, self._method_wrapper(name, original), original)
        original = module._capture_rebuild_notice
        self._replace(module, "_capture_rebuild_notice", self._capture_wrapper(original), original)
        installed = self.emit("observer", "installed", **self.notice())
        self.data.update(installSequence=installed["sequence"], installAtNs=installed["atNs"])

    def checkpoint(self, event):
        self.emit("host-event", "existing-host-event", hostEventSequence=event["sequence"],
                  hostEvent=event["event"], **self.notice())

    def restore(self):
        receipts = []
        for target, name, previous, descriptor in reversed(self._restorations):
            if previous is _ABSENT:
                delattr(target, name)
            else:
                setattr(target, name, previous)
            restored = vars(target).get(name, _ABSENT)
            receipts.append({"name": name, "targetRef": descriptor["targetRef"],
                "inherited": previous is _ABSENT, "restoredExactOwnDescriptor": restored is previous,
                "observerInstanceAttributeAbsent": name not in vars(target)})
        self.data["restoration"] = receipts
        for value, row in self._objects.values():
            if row["kind"] == "exception":
                row["error"] = {"name": type(value).__name__, "message": str(value),
                                "traceback": "".join(traceback.format_exception(value))}


async def _run_host(request):
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.host.lifecycle import HostModelResult
    from memory_core.host.managed_session import ManagedHostSession
    from memory_core.host.session import SessionState, TurnUsage
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_visibility import resolve_memory_search_source_policy

    if set(request) != {"input", "directory"}:
        raise ValueError("The SDK host accepts only its frozen input and owned directory")
    value, directory = request["input"], Path(request["directory"])
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("An absolute owned host directory is required")
    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The host imported an SDK outside its owning worktree")
    now, identity = value["nowMs"], value["identity"]
    policy = value["policy"]
    workspace = directory / "workspace"
    workspace.mkdir()
    catalog = MemorySessionCatalog(directory / "catalog.sqlite", agent_id=identity["agentId"], clock_ms=lambda: now)
    config = MemoryConfig(workspace, agent_id=identity["agentId"], store_path=directory / "index.sqlite",
        citation_mode="off", flags=FeatureFlags(vector_search=False, temporal_decay=False))
    source_policy = resolve_memory_search_source_policy(policy["searchSources"],
        remember_across_conversations=False, configured_session_memory=policy["sessionMemory"])
    owner = ManagedHostSession.open(workspace, catalog=catalog, config=config, source_policy=source_policy,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, memory_publication="on-search", now_ms=lambda: now,
        flush_config={"enabled": policy["memoryFlushEnabled"],
            "softThresholdTokens": policy["softThresholdTokens"]})
    runner = owner.runner(SessionState.new(session_key=identity["sessionKey"], session_id=identity["sessionId"]))
    raw = {"kind": "host-turn-barrier", "engine": "sdk", "input": deepcopy(value),
        "fixtureBase": str(directory), "pid": os.getpid(), "ppid": os.getppid(),
        "implementationRoot": str(Path(memory_core.__file__).resolve().parents[1]),
        "clock": {"owner": "public-host-clock", "nowMs": now, "monotonicAndTimers": "unmodified"},
        "ownerPolicy": "on-search", "turns": [], "events": [], "metadata": [], "snapshots": []}
    sequence = itertools.count(1)
    observer = None
    context = {"turnLabel": None, "toolCallId": None}

    def stamp():
        return {"sequence": next(sequence), "atNs": str(time.monotonic_ns())}

    def event(event_name, **fields):
        if event_name == "host-call":
            context.update(turnLabel=fields["label"], toolCallId=None)
        elif event_name == "tool-dispatch":
            context["toolCallId"] = fields["id"]
        row = {"event": event_name, **stamp(), **fields}
        raw["events"].append(row)
        if observer is not None:
            observer.checkpoint(row)
        if event_name in {"tool-result", "host-return"}:
            context["toolCallId"] = None
        return row

    from equivalence.host_turn_barrier import CASE_HASHES, build_cases, case_wire
    case = next(case for case in build_cases() if case["input"] == value)
    contract = ROOT / "docs/next_turn_notice_observation_contract.json"
    observer = _NoticeObservations(owner.store, stamp, lambda: dict(context), header={
        "contractSha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
        "caseWireSha256": hashlib.sha256(case_wire(case)).hexdigest(),
        "pid": os.getpid(), "ppid": os.getppid(), "caseId": case["id"],
        "instrumentedActorSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "originalSourceBindings": [{"module": name, "path": str(Path(sys.modules[name].__file__).resolve()),
            "sha256": hashlib.sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()}
            for name in ("memory_core.host.managed_index", "memory_core.host.managed_session",
                         "memory_core.host.kit", "memory_core.host.lifecycle", "memory_core.tools.memory_search")],
        "compiledBindings": []})
    if observer.data["caseWireSha256"] != CASE_HASHES[case["id"]]:
        raise RuntimeError("The notice observer requires an unchanged original host input")
    observer.install(importlib.import_module("memory_core.tools.memory_search"))
    raw["noticeObservations"] = observer.data

    def snapshot(label):
        row = {"label": label, "source": _source(workspace, value["source"]),
            "index": owner.store.read_published_index(), "lifecycle": owner.store.lifecycle_snapshot(),
            "status": owner.publication_status(), "catalog": _sqlite_snapshot(catalog.path)}
        raw["snapshots"].append(deepcopy(row))
        return row

    def assistant(turn, content):
        return turn.record_message({"role": "assistant", "content": content, **MODEL})

    async def dispatch(turn, record, name, arguments, identifier):
        call = assistant(turn, [{"type": "toolCall", "id": identifier, "name": name,
                                 "arguments": deepcopy(arguments)}])
        event("tool-dispatch", label=record["label"], name=name, id=identifier)
        returned = await turn.dispatch_async(identifier, name, arguments)
        observed = _observed_tool_result(turn, identifier)
        event("tool-result", label=record["label"], name=name, id=identifier)
        record["toolCalls"].append({"id": identifier, "name": name, "arguments": deepcopy(arguments),
            "assistant": call, "returned": deepcopy(returned), "observed": observed})
        record["modelCalls"].append(_model_input(turn))
        return observed["payload"]

    def metadata(record):
        spec = value["sourceMetadataFixture"]
        target = workspace / value["source"]
        before = _source_metadata(workspace, value["source"])
        args = [int(spec["atimeMs"] * 1_000_000), int(spec["mtimeMs"] * 1_000_000)]
        operation = {"operation": "os.utime", "label": record["label"], "path": str(target),
            "arguments": {"ns": [str(item) for item in args]}, "before": before,
            "startedAtNs": str(time.monotonic_ns())}
        operation["returnedNone"] = os.utime(target, ns=tuple(args)) is None
        operation["after"] = _source_metadata(workspace, value["source"])
        operation["finishedAtNs"] = str(time.monotonic_ns())
        if operation["before"]["source"] != operation["after"]["source"]:
            raise RuntimeError("The metadata fixture changed source bytes")
        raw["metadata"].append(operation)
        event("source-metadata", label=record["label"])

    async def run(label, directive, *, save=False):
        record = {"label": label, "directive": deepcopy(directive), "toolCalls": [], "modelCalls": [],
            "sourceBefore": _source(workspace, value["source"])}
        raw["turns"].append(record)

        async def execute(turn):
            event("model-enter", label=label)
            record["modelCalls"].append(_model_input(turn))
            if save:
                observed = await dispatch(turn, record, "add_memory_entry",
                    {"section": directive["section"], "text": directive["text"]}, f"{label}:write")
                if observed.get("status") == "ok":
                    metadata(record)
                    answer = "Saved."
                else:
                    answer = json.dumps(observed, ensure_ascii=False, separators=(",", ":"))
            else:
                search = await dispatch(turn, record, "memory_search", directive["search"], f"{label}:search")
                hits = search.get("results", [])
                got = None
                if hits:
                    first = hits[0]
                    got = await dispatch(turn, record, "memory_get", {"path": first["path"],
                        "from": first["startLine"], "lines": first["endLine"] - first["startLine"] + 1},
                        f"{label}:get")
                answer = got["text"] if got is not None else EMPTY_ANSWER
                record["read"] = {"search": deepcopy(search), "get": deepcopy(got)}
            terminal = assistant(turn, [{"type": "text", "text": answer}])
            record["terminalMessage"] = terminal
            record["terminalInput"] = _model_input(turn)
            event("terminal-reply", label=label)
            payload = {"text": answer, "replyToTag": False, "audioAsVoice": False}
            usage = value["firstTurnUsage"]
            return HostModelResult(usage=TurnUsage(prompt_tokens=usage["input"], completion_tokens=usage["output"]),
                payloads=(payload,))

        event("host-call", label=label)
        outcome = await runner.run_turn(directive["prompt"], execute=execute, request_id=label,
                                        context_window_tokens=policy["contextWindowTokens"])
        event("host-return", label=label)
        record.update(outcome=_plain(outcome), sourceAfter=_source(workspace, value["source"]),
                      lifecycleAfter=owner.store.lifecycle_snapshot())
        if not outcome.transcript_committed or outcome.failures:
            raise RuntimeError(f"The genuine SDK host did not complete its {label} turn")
        if len(outcome.payloads) != 1:
            raise RuntimeError("The host returned no single complete model reply")
        record["reply"] = deepcopy(dict(outcome.payloads[0]))
        return None if save else {**record["read"], "reply": record["reply"]}

    result = None
    try:
        snapshot("before-first-host-call")
        warmup = None
        if value["initialState"] == "warm":
            await run("warmup-save", value["warmup"]["save"], save=True)
            warmup = await run("warmup-recall", value["warmup"]["recall"])
            snapshot("warm-index-positive-control")
        await run("save", value["save"], save=True)
        source = _source(workspace, value["source"])
        # No publication or scheduler wait between these real host calls.
        followup = await run("followup", value["followup"])
        result = {"provider": "none", "warmup": warmup, "source": source, "followup": followup}
        raw["result"] = deepcopy(result)
        snapshot("after-followup-host-return")
        return {"result": result, "raw": raw}
    finally:
        # Joining actual publishers at teardown does not supply a pre-read barrier.
        try:
            event("close-call")
            await owner.aclose()
            event("close-return")
            raw["closedLifecycle"] = owner.store.lifecycle_snapshot()
            raw["closedStatus"] = owner.publication_status()
        finally:
            observer.restore()
            (directory / "sdk-host-raw.json").write_text(json.dumps(raw, ensure_ascii=False, allow_nan=False) + "\n")


def run_host_turn_barrier_sdk_host(request):
    return asyncio.run(_run_host(request))


def run_host_turn_barrier_case(value, *, evidence_directory=None):
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-natural-host-", dir=evidence_directory)).resolve()
    request = {"input": value, "directory": str(directory)}
    wire = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
        "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state")}
    argv = [sys.executable, "-m", "equivalence.host_turn_barrier_sdk_cli"]
    raw = {"kind": "host-turn-barrier-sdk-dispatch", "input": value, "coordinatorPid": os.getpid(),
        "request": request, "requestJson": wire, "requestSha256": hashlib.sha256(wire.encode()).hexdigest(),
        "argv": argv, "environmentKeys": sorted(environment), "startedAtNs": str(time.monotonic_ns())}
    with subprocess.Popen(argv, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
        raw["pid"] = child.pid
        try:
            stdout, stderr = child.communicate(wire, timeout=120)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            raw.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                       finishedAtNs=str(time.monotonic_ns()))
            (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False) + "\n")
            raise RuntimeError("The actual SDK host timed out; streams are retained") from None
    raw.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
               finishedAtNs=str(time.monotonic_ns()))
    if not child.returncode:
        raw["observation"] = json.loads(stdout)
    destination = Path(evidence_directory) if evidence_directory is not None else directory
    (destination / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False, allow_nan=False) + "\n")
    if child.returncode or "observation" not in raw:
        raise RuntimeError("The genuine SDK host failed; complete streams are retained")
    return raw["observation"]["result"]
