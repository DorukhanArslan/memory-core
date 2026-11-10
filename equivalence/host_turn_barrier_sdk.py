"""Natural SDK save/follow-up turns, without a fixture publication barrier.

The model fixture selects real registered tools and reads their complete actual
messages. Producer metadata is a declared filesystem input, applied before the
terminal model reply. No synchronization is inserted between host calls.
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

from equivalence.host_restart_sdk import (
    _model_input, _observed_tool_result, _plain, _source, _source_metadata, _sqlite_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."
MODEL = {"provider": "host-turn-barrier-offline-model", "model": "actual-result-reader"}


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
    sequence = 0

    def event(event_name, **fields):
        nonlocal sequence
        sequence += 1
        row = {"event": event_name, "sequence": sequence, "atNs": str(time.monotonic_ns()), **fields}
        raw["events"].append(row)
        return row

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
        event("close-call")
        await owner.aclose()
        event("close-return")
        raw["closedLifecycle"] = owner.store.lifecycle_snapshot()
        raw["closedStatus"] = owner.publication_status()
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
