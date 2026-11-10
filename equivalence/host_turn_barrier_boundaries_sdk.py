"""Actual SDK host/channel execution for the frozen next-turn boundary family.

Only the model/provider transport and declared filesystem recipes belong to
this adapter. Foreground lanes, optional owners, flush preparation, registered
writes, cancellation and memory tools are the production SDK implementations.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from equivalence.host_restart_sdk import _plain, _source, _source_metadata, _sqlite_snapshot
from equivalence.host_turn_barrier_boundaries import build_cases


ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."
MODEL = {"provider": "host-turn-barrier-boundaries-offline-model", "model": "actual-result-reader"}
LEASE_MODULE = "equivalence.host_turn_barrier_boundaries_lease"


def _literal(value):
    cases = [case for case in build_cases() if case["input"] == value]
    if len(cases) != 1:
        raise ValueError("The SDK boundary host requires an exact frozen input")
    return cases[0]


def _model_input(turn):
    return {"systemPrompt": turn.context.system_prompt if turn.context else None,
            "runtimeContext": turn.context.runtime_context if turn.context else None,
            "tools": deepcopy(list(turn.tools)), "messages": turn.messages,
            "session": turn.session.to_json(),
            "trust": turn.trust.to_json(),
            "flushTarget": turn.flush_request.target if turn.flush_request else None}


class _Lease:
    def __init__(self, workspace, relative, raw, event):
        self.workspace, self.relative, self.raw, self.event = workspace, relative, raw, event
        self.process = None
        self.receipts = []
        self.changed = asyncio.Event()
        self.reader = None
        self.commands = 0

    async def start(self):
        argv = [sys.executable, "-m", LEASE_MODULE, "--workspace", str(self.workspace),
                "--relative-path", self.relative, "--owner-pid", str(os.getpid())]
        helper = ROOT / "equivalence/host_turn_barrier_boundaries_lease.py"
        self.raw.update(argv=argv, executable=str(Path(sys.executable).resolve()),
            executableSha256=hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
            helperPath=str(helper), helperSha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
            parentPid=os.getpid(), stdin=[], stdout=[], receipts=self.receipts)
        self.process = await asyncio.create_subprocess_exec(*argv, cwd=ROOT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC"})
        self.raw["pid"] = self.process.pid

        async def read():
            while wire := await self.process.stdout.readline():
                self.raw["stdout"].append(wire.decode())
                row = json.loads(wire)
                self.receipts.append(row)
                self.event("lease-receipt", receipt=deepcopy(row))
                self.changed.set()

        self.reader = asyncio.create_task(read())
        await self.wait("ARMED")

    async def wait(self, name, request_id=None):
        async def find():
            while True:
                self.changed.clear()
                for row in self.receipts:
                    if row["event"] == "ERROR":
                        raise RuntimeError(f"The real lease helper failed: {row}")
                    if row["event"] == name and (request_id is None or row.get("id") == request_id):
                        return row
                if self.reader.done():
                    raise RuntimeError("The real lease helper ended before its required receipt")
                await self.changed.wait()
        return await asyncio.wait_for(find(), 10)

    async def command(self, command, expected):
        self.commands += 1
        request_id = f"sdk-{self.commands}-{command.lower()}"
        wire = json.dumps({"command": command, "id": request_id}, separators=(",", ":")) + "\n"
        self.raw["stdin"].append(wire)
        self.event("lease-command", command=command, id=request_id)
        self.process.stdin.write(wire.encode())
        await self.process.stdin.drain()
        return await self.wait(expected, request_id)

    async def close(self):
        if self.process is None:
            return
        if self.process.returncode is None:
            await self.command("STOP", "CLOSED")
        await asyncio.wait_for(self.process.wait(), 10)
        await self.reader
        self.raw.update(exitCode=self.process.returncode, stderr=(await self.process.stderr.read()).decode())
        if self.process.returncode:
            raise RuntimeError("The real lease helper exited unsuccessfully")


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
        raise ValueError("The SDK boundary host accepts only its input and owned directory")
    value, directory = request["input"], Path(request["directory"])
    case = _literal(value)
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("An absolute owned boundary host directory is required")
    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The SDK boundary host imported another worktree")
    now, identity, policy = value["nowMs"], value["identity"], value["policy"]
    scenario = value["scenario"]
    workspace = directory / "workspace"
    workspace.mkdir()
    catalog = MemorySessionCatalog(directory / "catalog.sqlite", agent_id=identity["agentId"], clock_ms=lambda: now)
    config = MemoryConfig(workspace, agent_id=identity["agentId"], store_path=directory / "index.sqlite",
        citation_mode="off", flags=FeatureFlags(vector_search=False, temporal_decay=False))
    source_policy = resolve_memory_search_source_policy(policy["searchSources"],
        remember_across_conversations=False, configured_session_memory=policy["sessionMemory"])
    owner = ManagedHostSession.open(workspace, catalog=catalog, config=config, source_policy=source_policy,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, memory_publication="on-search", maintenance="background",
        initialize=False, timezone="UTC", now_ms=lambda: now,
        flush_config={"enabled": policy["memoryFlushEnabled"], "softThresholdTokens": policy["softThresholdTokens"]})
    session = SessionState.new(session_key=identity["sessionKey"], session_id=identity["sessionId"])
    runner = owner.runner(session)
    daily = value.get("maintenance", {}).get("relativePath")
    raw = {"kind": "host-turn-barrier-boundaries", "engine": "sdk", "caseId": case["id"],
        "input": deepcopy(value), "fixtureBase": str(directory), "pid": os.getpid(), "ppid": os.getppid(),
        "implementationRoot": str(Path(memory_core.__file__).resolve().parents[1]),
        "clock": {"owner": "public-host-clock", "nowMs": now, "monotonicAndTimers": "unmodified"},
        "ownerPolicy": {"memoryPublication": "on-search", "optionalMaintenance": "background"},
        "foregroundAuthority": {"channel": "webchat", "senderId": "fixture-user",
            "configuredOwnerGrant": False, "senderIsOwner": False},
        "turns": [], "events": [], "metadata": [], "snapshots": [], "faults": [], "fixtures": [],
        "maintenance": [], "lease": None}
    sequence = 0
    delivery_started, acknowledgment, maintenance_consumed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    lease = None
    active_tasks = []
    observed_jobs = set()

    def event(event_name, **fields):
        nonlocal sequence
        sequence += 1
        row = {"event": event_name, "sequence": sequence, "atNs": str(time.monotonic_ns()), **fields}
        raw["events"].append(row)
        return row

    def sources():
        return {"source": _source(workspace, value["source"]),
                "maintenanceSource": _source(workspace, daily) if daily else None}

    def snapshot(label):
        row = {"label": label, **sources(), "index": owner.store.read_published_index(),
            "lifecycle": owner.store.lifecycle_snapshot(), "status": owner.publication_status(),
            "catalog": _sqlite_snapshot(catalog.path),
            "provenance": _sqlite_snapshot(owner.store.artifact_provenance.path),
            "maintenance": owner.maintenance_status()}
        raw["snapshots"].append(deepcopy(row))
        return row

    def observe_jobs():
        for job in tuple(owner._maintenance_jobs):
            if job.identifier in observed_jobs:
                continue
            observed_jobs.add(job.identifier)

            def done(_future, job=job):
                event("optional-done-observed", job=job.snapshot(), catalogSnapshot=_sqlite_snapshot(catalog.path))

            job.done.add_done_callback(done)

    def metadata(record, relative):
        spec = value["sourceMetadataFixture"]
        before = _source_metadata(workspace, relative)
        ns = tuple(int(spec[key] * 1_000_000) for key in ("atimeMs", "mtimeMs"))
        row = {"operation": "os.utime", "label": record["label"], "path": str(workspace / relative),
            "arguments": {"ns": [str(item) for item in ns]}, "before": before,
            "startedAtNs": str(time.monotonic_ns())}
        row["returnedNone"] = os.utime(workspace / relative, ns=ns) is None
        row["after"] = _source_metadata(workspace, relative)
        row["finishedAtNs"] = str(time.monotonic_ns())
        if row["before"]["source"] != row["after"]["source"]:
            raise RuntimeError("The declared metadata operation changed source bytes")
        raw["metadata"].append(row)
        event("source-metadata", label=record["label"], path=relative)

    def hardlink(relative, label):
        target, link = workspace / relative, directory / (label + "-hardlink")
        before = _source_metadata(workspace, relative)
        os.link(target, link)
        row = {"recipe": "actual-source-second-hard-link", "label": label, "target": str(target),
            "link": str(link), "before": before, "armed": _source_metadata(workspace, relative),
            "linkStat": {"ino": link.stat().st_ino, "dev": link.stat().st_dev, "nlink": link.stat().st_nlink}}
        raw["faults"].append(row)
        event("hardlink-armed", label=label, target=relative)
        return row, link

    def remove_link(record, link):
        link.unlink()
        relative = str(Path(record["target"]).relative_to(workspace))
        record["removed"] = _source_metadata(workspace, relative)
        record["linkExistsAfter"] = link.exists()
        event("hardlink-removed", label=record["label"], target=relative)

    def assistant(turn, content):
        return turn.record_message({"role": "assistant", "content": content, **MODEL})

    async def dispatch(turn, record, name, arguments, identifier):
        call = assistant(turn, [{"type": "toolCall", "id": identifier, "name": name,
                                 "arguments": deepcopy(arguments)}])
        event("tool-dispatch", label=record["label"], name=name, id=identifier)
        returned = await turn.dispatch_async(identifier, name, arguments)
        matches = [message for message in turn.messages if message.get("role") == "toolResult"
                   and message.get("toolCallId") == identifier]
        if len(matches) != 1:
            raise RuntimeError("A dispatched SDK tool did not emit exactly one actual result")
        message = matches[0]
        observed = {"message": deepcopy(message), "payload": deepcopy(message.get("details"))}
        row = {"id": identifier, "name": name, "arguments": deepcopy(arguments), "assistant": call,
               "returned": deepcopy(returned), "observed": observed}
        record["toolCalls"].append(row)
        record["modelCalls"].append(_model_input(turn))
        event("tool-result", label=record["label"], name=name, id=identifier, isError=message.get("isError", False))
        return row

    async def recall(turn, record, options):
        row = await dispatch(turn, record, "memory_search", options, record["label"] + "search")
        search = row["observed"]["payload"]
        record["public"]["search"] = deepcopy(search)
        got = None
        if search.get("results"):
            first = search["results"][0]
            row = await dispatch(turn, record, "memory_get", {"path": first["path"], "from": first["startLine"],
                "lines": first["endLine"] - first["startLine"] + 1}, record["label"] + "get")
            got = row["observed"]["payload"]
        record["public"]["get"] = deepcopy(got)
        warning = "\n".join(str(search[key]) for key in ("warning", "action") if search.get(key))
        return "\n".join(item for item in (got["text"] if got is not None else None, warning) if item) or EMPTY_ANSWER

    async def execute_flush(turn):
        record = {"label": "maintenance", "modelCalls": [_model_input(turn)], "toolCalls": []}
        raw["maintenance"].append(record)
        event("maintenance-model-enter", session=turn.session.to_json(), target=turn.flush_request.target,
              catalogSnapshot=_sqlite_snapshot(catalog.path), maintenanceStatus=owner.maintenance_status())
        texts = [message.get("content") for message in turn.messages if message.get("role") == "user"
                 and isinstance(message.get("content"), str)]
        instruction = next((text.split("Also remember for daily memory: ", 1)[1]
            for text in texts if "Also remember for daily memory: " in text), None)
        if instruction is None:
            raise RuntimeError("The maintenance model received no actual persisted daily instruction")
        content = "- " + instruction.strip() + "\n"
        fault = link = None
        if scenario == "refused-maintenance":
            fault, link = hardlink(turn.flush_request.target, "maintenance")
        try:
            row = await dispatch(turn, record, "write", {"path": turn.flush_request.target, "content": content}, "maintenancewrite")
            if not row["observed"]["message"].get("isError"):
                metadata(record, turn.flush_request.target)
        finally:
            if link is not None:
                remove_link(fault, link)
        record["consumedResult"] = deepcopy(row)
        record["sourceAfterResult"] = _source(workspace, turn.flush_request.target)
        event("maintenance-result-consumed", isError=row["observed"]["message"].get("isError", False))
        maintenance_consumed.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            event("maintenance-provider-abort", cancelRequested=turn.cancel_requested.is_set())
            await asyncio.sleep(0)
            event("maintenance-provider-cleanup-return")
        record["terminalInput"] = _model_input(turn)
        return HostModelResult()

    async def stage(label, directive, *, save=False):
        public = {"deliveries": [], "dispatchReturn": None, "search": None, "get": None}
        record = {"label": label, "directive": deepcopy(directive), "public": public,
                  "modelCalls": [], "toolCalls": [], "sourcesBefore": sources()}
        raw["turns"].append(record)

        async def execute(turn):
            event("model-enter", label=label, catalogSnapshot=_sqlite_snapshot(catalog.path),
                  maintenanceStatus=owner.maintenance_status())
            record["modelCalls"].append(_model_input(turn))
            if save:
                row = await dispatch(turn, record, "add_memory_entry",
                    {"section": directive["section"], "text": directive["text"]}, label + "write")
                failed = row["observed"]["message"].get("isError", False)
                if not failed:
                    metadata(record, value["source"])
                answer = "The memory write failed." if failed else "Saved."
                if label == "save" and scenario == "cold-publication-failure":
                    sidecar = Path(str(owner.store.path) + "-journal")
                    missing = directory / "owned-missing-sidecar-directory" / "journal"
                    sidecar.symlink_to(missing)
                    raw["faults"].append({"recipe": "actual-index-publication-sidecar-dangling-symlink",
                        "target": str(sidecar), "pointsTo": os.readlink(sidecar),
                        "targetExists": sidecar.exists(), "isSymlink": sidecar.is_symlink()})
                    event("publication-fault-armed", target=str(sidecar))
                    answer = await recall(turn, record, directive["verificationSearch"])
                if label == "save" and scenario == "refused-foreground":
                    remove_link(*foreground_link)
            else:
                answer = await recall(turn, record, directive["search"])
            terminal = assistant(turn, [{"type": "text", "text": answer}])
            record["terminalMessage"] = terminal
            record["terminalInput"] = _model_input(turn)
            event("terminal-reply", label=label)
            user = next(message for message in reversed(turn.messages) if message.get("role") == "user")
            payload = {"text": answer, "replyToTag": False, "replyToId": user["id"], "audioAsVoice": False}
            usage = value["firstTurnUsage"] if label == "save" else value["followupUsage"]
            return HostModelResult(TurnUsage(usage["input"], usage["output"]), payloads=(payload,))

        counts = {"tool": 0, "block": 0, "final": 0}

        async def deliver(outcome):
            observe_jobs()
            event("delivery-call", label=label, maintenance=owner.maintenance_status())
            for payload in outcome.payloads:
                public["deliveries"].append(deepcopy(dict(payload)))
                counts["final"] += 1
                event("channel-final-delivered", label=label, payload=deepcopy(dict(payload)))
            if label == "save" and scenario == "pending-optional-preemption":
                delivery_started.set()
                await acknowledgment.wait()
            event("delivery-ack", label=label, counts=deepcopy(counts))

        event("host-call", label=label)
        outcome = await runner.run_turn({"role": "user", "content": directive["prompt"], "id": "fixture-" + label},
            execute=execute, execute_flush=execute_flush, request_id=label, deliver=deliver,
            context_window_tokens=policy["contextWindowTokens"], sender_is_owner=False)
        event("host-return", label=label)
        record.update(outcome=_plain(outcome), sourcesAfter=sources(), lifecycleAfter=owner.store.lifecycle_snapshot(),
                      maintenanceAfter=owner.maintenance_status())
        if not outcome.transcript_committed or len(outcome.payloads) != 1:
            raise RuntimeError("The real SDK host did not return its actual admitted terminal reply")
        public["dispatchReturn"] = {"queuedFinal": bool(counts["final"]), "counts": deepcopy(counts)}
        return deepcopy(public)

    foreground_link = None
    try:
        for spec in value.get("fixtureFiles", []):
            path = workspace / spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(spec["content"], encoding="utf8")
            os.utime(path, ns=tuple(spec[key] * 1_000_000 for key in ("atimeMs", "mtimeMs")))
            raw["fixtures"].append({"specification": deepcopy(spec), "actual": _source_metadata(workspace, spec["path"])})
        if scenario == "target-open-preparation":
            raw["lease"] = {}
            lease = _Lease(workspace, daily, raw["lease"], event)
            await lease.start()
        snapshot("before-first-host-call")
        warmup = None
        if value.get("warmup"):
            warmup = await stage("warmup-save", value["warmup"]["save"], save=True)
            foreground_link = hardlink(value["source"], "foreground")
        save_task = asyncio.create_task(stage("save", value["save"], save=True))
        active_tasks.append(save_task)
        if scenario == "pending-optional-preemption":
            await asyncio.wait_for(delivery_started.wait(), 10)
        else:
            await save_task
        if scenario == "target-open-preparation":
            await lease.wait("BREAK")
            snapshot("target-open-physically-pending")
        elif scenario in {"committed-maintenance", "refused-maintenance"}:
            await asyncio.wait_for(maintenance_consumed.wait(), 10)
            snapshot("maintenance-result-consumed")
        # Submission is an actual independent caller; no inherited model lane.
        followup_task = asyncio.create_task(stage("followup", value["followup"]))
        active_tasks.append(followup_task)
        if scenario in {"pending-optional-preemption", "target-open-preparation"}:
            job = next(job for job in owner._maintenance_jobs if not job.done.done())
            await asyncio.wait_for(job.cancel_requested.wait(), 10)
            event("optional-abort-observed", job=job.snapshot(), catalogSnapshot=_sqlite_snapshot(catalog.path))
            if scenario == "pending-optional-preemption":
                event("delivery-ack-release", label="save")
                acknowledgment.set()
            else:
                await asyncio.sleep(0)
                event("event-loop-live-after-actual-abort")
                await lease.command("RELEASE", "RELEASED")
        save_public, followup_public = await asyncio.gather(save_task, followup_task)
        if lease is not None:
            await lease.command("VERIFY", "VERIFIED")
            await lease.close()
        result = {"provider": "none", "scenario": scenario, **sources(), "warmup": warmup,
                  "save": save_public, "followup": followup_public}
        raw["result"] = deepcopy(result)
        snapshot("after-followup-host-return")
        return {"result": result, "raw": raw}
    finally:
        acknowledgment.set()
        if lease is not None and lease.process is not None and lease.process.returncode is None:
            await lease.close()
        event("close-call")
        await owner.aclose()
        for task in active_tasks:
            if not task.done():
                await task
        event("close-return")
        raw["closedLifecycle"] = owner.store.lifecycle_snapshot()
        raw["closedStatus"] = owner.publication_status()
        raw["closedMaintenance"] = owner.maintenance_status()
        (directory / "sdk-host-raw.json").write_text(json.dumps(raw, ensure_ascii=False, allow_nan=False) + "\n")


def run_host_turn_barrier_boundaries_sdk_host(request):
    return asyncio.run(_run_host(request))


def run_host_turn_barrier_boundaries_case(value, *, evidence_directory=None):
    _literal(value)
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-boundary-host-", dir=evidence_directory)).resolve()
    request = {"input": value, "directory": str(directory)}
    wire = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
        "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state")}
    argv = [sys.executable, "-m", "equivalence.host_turn_barrier_boundaries_sdk_cli"]
    raw = {"kind": "host-turn-barrier-boundaries-sdk-dispatch", "input": value, "coordinatorPid": os.getpid(),
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
            raise RuntimeError("The actual SDK boundary host timed out; streams are retained") from None
    raw.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
               finishedAtNs=str(time.monotonic_ns()))
    if not child.returncode:
        raw["observation"] = json.loads(stdout)
    destination = Path(evidence_directory) if evidence_directory is not None else directory
    (destination / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False, allow_nan=False) + "\n")
    if child.returncode or "observation" not in raw:
        raise RuntimeError("The genuine SDK boundary host failed; complete streams are retained")
    return raw["observation"]["result"]
