"""Real SDK host turns across fresh chats and sequential host processes.

The only producer is the SDK's registered daily-note tool. Its extension receipt
is retained separately from the native coding-write receipt; equivalence here
concerns the resulting source and subsequent real memory-tool retrieval.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import closing
from copy import deepcopy
from dataclasses import fields, is_dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."


def _plain(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"blobHex": value.hex()}
    return value


def _source_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 2 or path.parts[0] != "memory" or path.suffix != ".md":
        raise ValueError("The saved source must be a relative daily memory Markdown path")
    return str(path)


def _validate_policy(policy):
    required = {"configuredSources", "rememberAcrossConversations", "configuredSessionMemory", "sourceMtimeMs"}
    managed = required | {"producerPublication", "indexLifecycle", "runtimeIdentity"}
    if (not isinstance(policy, dict) or set(policy) not in (required, required | {"producerPublication"}, managed)
            or policy["configuredSources"] != ["memory"]
            or type(policy["rememberAcrossConversations"]) is not bool or policy["configuredSessionMemory"] is not False
            or type(policy["sourceMtimeMs"]) not in (int, float) or not math.isfinite(policy["sourceMtimeMs"])
            or policy["sourceMtimeMs"] < 0):
        raise ValueError("The source-policy experiment accepts only its explicit bounded host policy")
    if "producerPublication" in policy and policy["producerPublication"] != {
            "operation": "force-rebuild-after-source-metadata"}:
        raise ValueError("The producer publication experiment requires its exact explicit rebuild operation")
    if "indexLifecycle" in policy and (policy["indexLifecycle"] != "managed"
            or policy["runtimeIdentity"] != "openclaw-compatible"):
        raise ValueError("The managed index requires its exact declared lifecycle and runtime identity")


def _source_metadata(workspace, relative):
    source = _source(workspace, relative)
    info = (workspace / relative).lstat()
    return {"source": source, "stat": {"dev": info.st_dev, "ino": info.st_ino, "mode": info.st_mode,
        "nlink": info.st_nlink, "size": info.st_size, "atimeNs": str(info.st_atime_ns),
        "mtimeNs": str(info.st_mtime_ns), "ctimeNs": str(info.st_ctime_ns)}}


def _source(workspace: Path, relative: str):
    path = workspace / relative
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"path": relative, "kind": "missing"}
    if not stat.S_ISREG(info.st_mode):
        kind = "symlink" if stat.S_ISLNK(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode) else "other"
        return {"path": relative, "kind": kind}
    data = path.read_bytes()
    return {"path": relative, "kind": "file", "text": data.decode("utf-8"), "hex": data.hex()}


def _sqlite_snapshot(path: Path):
    if not path.is_file():
        return {"path": str(path), "kind": "missing"}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        schema = [dict(row) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        tables = {row["name"]: [_plain(dict(item)) for item in db.execute(
            'SELECT * FROM "' + row["name"].replace('"', '""') + '"')]
            for row in schema if row["type"] == "table"}
        return {"path": str(path), "kind": "sqlite", "schema": schema, "tables": tables}


def _assistant_call(turn, name, arguments, call_id):
    return turn.record_message({"role": "assistant", "content": [
        {"type": "toolCall", "id": call_id, "name": name, "arguments": deepcopy(arguments)}],
        "provider": "host-restart-offline-model", "model": "actual-result-reader"})


def _assistant_text(turn, text):
    return turn.record_message({"role": "assistant", "content": [{"type": "text", "text": text}],
        "provider": "host-restart-offline-model", "model": "actual-result-reader"})


def _model_input(turn):
    return {"systemPrompt": turn.context.system_prompt, "runtimeContext": turn.context.runtime_context,
            "tools": deepcopy(list(turn.tools)), "messages": turn.messages}


def _observed_tool_result(turn, call_id):
    messages = turn.messages
    matches = [message for message in messages if message.get("role") == "toolResult"
               and message.get("toolCallId") == call_id]
    if len(matches) != 1:
        raise RuntimeError("The host did not emit exactly one actual result for its dispatched call")
    message = matches[0]
    text = "\n".join(block["text"] for block in message.get("content", []) if block.get("type") == "text")
    decoded = json.loads(text)
    if decoded != message.get("details"):
        raise RuntimeError("The actual model-visible result text differs from its complete details")
    return {"message": message, "payload": decoded}


async def _run_phase(request):
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.host.lifecycle import HostModelResult, HostSessionRunner
    from memory_core.host.session import SessionState, TurnUsage
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_visibility import resolve_memory_search_source_policy

    required = {"identity", "nowMs", "phase", "directory", "sourcePath"}
    if set(request) not in (required, required | {"policy"}):
        raise ValueError("A host child accepts only identity, clock, its own phase and owned locations")
    selected_policy = request.get("policy")
    if "policy" in request:
        _validate_policy(selected_policy)
    resolved_policy = (resolve_memory_search_source_policy(selected_policy["configuredSources"],
        remember_across_conversations=selected_policy["rememberAcrossConversations"],
        configured_session_memory=selected_policy["configuredSessionMemory"])
        if selected_policy is not None else None)
    managed = selected_policy is not None and selected_policy.get("indexLifecycle") == "managed"
    root = Path(request["directory"])
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("A host phase requires its real absolute owned directory")
    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The host child imported an SDK outside its owning worktree")
    identity, phase, now = request["identity"], request["phase"], request["nowMs"]
    label = phase.get("label")
    if label not in {"produce", "restart"} or (label == "restart" and set(phase) not in (
            {"label", "recall"}, {"label", "recall", "beforeGet"})):
        raise ValueError("A restarted reader must receive no writer instruction or saved fact")
    if "beforeGet" in phase and phase["beforeGet"] != {"operation": "replace-source-with-directory"}:
        raise ValueError("Only the declared source-read failure boundary is admitted")
    relative = _source_path(request["sourcePath"])
    raw = {"kind": "host-restart-recall", "label": label, "pid": os.getpid(), "ppid": os.getppid(),
           "implementationRoot": str(Path(memory_core.__file__).resolve().parents[1]),
           "request": deepcopy(request), "environmentKeys": sorted(os.environ),
           "opens": [], "turns": [], "snapshots": []}
    if selected_policy is not None:
        raw["policyResolution"] = {"input": deepcopy(selected_policy), "result": deepcopy(resolved_policy)}
    runners = []

    def locations(agent):
        state = root / "state" / "agents" / agent
        return {"workspace": root / ("workspace" if agent == identity["agentId"] else "isolated-workspace"),
                "catalog": state / "sessions/session-authority.sqlite", "sessionStore": state / "sessions/sessions.json",
                "index": state / "agent/openclaw-agent.sqlite"}

    def open_runner(session_name):
        agent = identity["isolatedAgentId"] if session_name == "isolated" else identity["agentId"]
        paths, selected = locations(agent), identity[session_name]
        record = {"sessionName": session_name, "agentId": agent, "paths": _plain(paths),
                  "sourceBefore": _source(paths["workspace"], relative),
                  "catalogBefore": _sqlite_snapshot(paths["catalog"]), "indexBefore": _sqlite_snapshot(paths["index"])}
        catalog = MemorySessionCatalog(paths["catalog"], agent_id=agent, store_path=paths["sessionStore"], clock_ms=lambda: now)
        config = MemoryConfig(workspace_dir=paths["workspace"], agent_id=agent, store_path=paths["index"],
            citation_mode="off", session_search=resolved_policy["sessionMemory"] if resolved_policy is not None else False,
            search_max_results=5, search_min_score=0,
            flags=FeatureFlags(vector_search=False, temporal_decay=False))
        session = SessionState.new(session_key=selected["sessionKey"], session_id=selected["sessionId"])
        if managed:
            from memory_core.client import Memory
            from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
            from memory_core.host import HostKit
            from memory_core.host.managed_index import ManagedSQLiteMemoryStore
            from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
            from memory_core.session_visibility import SessionVisibilityContext
            from memory_core.workspace import MemoryWorkspace

            workspace = MemoryWorkspace(paths["workspace"], agent_id=agent, session_catalog=catalog,
                                        index_sources=resolved_policy["sources"])
            ledger = MemoryArtifactProvenanceStore(paths["index"].with_name(f"{paths['index'].stem}.provenance.sqlite"))
            store = ManagedSQLiteMemoryStore(config, workspace, artifact_provenance=ledger,
                                            runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
            memory = Memory(config, workspace, store, SessionVisibilityContext.from_catalog(catalog),
                            deepcopy(resolved_policy))
            kit = HostKit(memory, artifact_provenance=ledger, timezone="UTC", now_ms=lambda: now,
                          identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
            runner = HostSessionRunner(kit, catalog, session=session)
            record["managedStatusAfterOpen"] = deepcopy(store.status())
            record["managedLifecycleAfterOpen"] = store.lifecycle_snapshot()
        else:
            runner = HostSessionRunner.open(paths["workspace"], config=config, catalog=catalog,
                session=session, source_policy=resolved_policy if resolved_policy is not None else {"sources": ["memory"]},
                timezone="UTC", now_ms=lambda: now)
        record.update(config=_plain(config), session=runner.session.to_json(),
                      indexAfterOpen=runner.kit.memory.store.read_published_index())
        raw["opens"].append(record)
        runners.append((session_name, runner))
        return runner

    def snapshot(session_name, runner):
        workspace = runner.kit.memory.workspace.root
        catalog = runner.catalog
        continuations = []
        for name in ("writer", "fresh", "restarted", "isolated"):
            selected = identity[name]
            if name == "isolated" and catalog.agent_id != identity["isolatedAgentId"] or name != "isolated" and catalog.agent_id != identity["agentId"]:
                continue
            entry = catalog.get_session_entry(selected["sessionKey"])
            continuations.append({"session": name, "entry": entry, "continuation": catalog.read_continuation(
                selected["sessionId"], session_key=selected["sessionKey"]) if entry is not None else None})
        files = []
        for path in sorted(workspace.rglob("*")):
            if path.is_file() and not path.is_symlink():
                data = path.read_bytes()
                files.append({"path": str(path.relative_to(workspace)), "hex": data.hex(),
                              "sha256": hashlib.sha256(data).hexdigest()})
        observed = {"session": session_name, "workspace": str(workspace),
            "source": _source(workspace, relative), "files": files,
            "catalog": _sqlite_snapshot(catalog.path), "continuations": continuations,
            "published": runner.kit.memory.store.read_published_index(),
            "provenance": _sqlite_snapshot(runner.artifact_provenance.path),
            "settlement": {"activeTurn": runner._active_turn is not None,
                           "outstandingBlockingSources": runner._blocking_count}}
        if managed:
            observed["managedLifecycle"] = runner.kit.memory.store.lifecycle_snapshot()
        raw["snapshots"].append(observed)

    async def save():
        write = phase["write"]
        if write["path"] != relative:
            raise ValueError("The genuine producer must write the predeclared source location")
        raw["initialSource"] = _source(locations(identity["agentId"])["workspace"], relative)
        if raw["initialSource"]["kind"] != "missing":
            raise ValueError("The genuine producer source must begin absent")
        runner = open_runner("writer")
        record = {"session": "writer", "prompt": phase["savePrompt"], "toolCalls": []}
        raw["turns"].append(record)

        async def execute(turn):
            record["modelInput"] = _model_input(turn)
            arguments = {"text": write["text"]}
            assistant = _assistant_call(turn, "append_daily_note", arguments, "save-daily-note")
            before = runner.kit.memory.store.lifecycle_snapshot() if managed else None
            result = await turn.dispatch_async("save-daily-note", "append_daily_note", arguments)
            observed = _observed_tool_result(turn, "save-daily-note")
            call = {"name": "append_daily_note", "id": "save-daily-note", "arguments": arguments,
                    "assistant": assistant, "returned": deepcopy(result), "observed": observed}
            if managed:
                call.update(managedLifecycleBefore=before,
                            managedLifecycleAfter=runner.kit.memory.store.lifecycle_snapshot())
            record["toolCalls"].append(call)
            if selected_policy is not None:
                source_relative = result["path"]
                path = runner.kit.memory.workspace.resolve_memory_path(source_relative)
                metadata = {"operation": "os.utime", "path": str(path),
                    "before": _source_metadata(runner.kit.memory.workspace.root, source_relative),
                    "publishedBefore": runner.kit.memory.store.read_published_index()}
                instant_ns = int(selected_policy["sourceMtimeMs"] * 1_000_000)
                metadata["arguments"] = {"ns": [str(instant_ns), str(instant_ns)]}
                returned = os.utime(path, ns=(instant_ns, instant_ns))
                metadata["returnedNone"] = returned is None
                metadata["after"] = _source_metadata(runner.kit.memory.workspace.root, source_relative)
                metadata["publishedAfterMetadataChange"] = runner.kit.memory.store.read_published_index()
                record["sourceMetadata"] = metadata
            record["terminalInput"] = _model_input(turn)
            record["assistant"] = _assistant_text(turn, phase.get("saveAck", "Saved the note."))
            return HostModelResult(TurnUsage(20, 3))

        outcome = await runner.run_turn(phase["savePrompt"], execute=execute, request_id="host-restart-save")
        record["outcome"] = _plain(outcome)
        if selected_policy is not None and "producerPublication" in selected_policy:
            publication = {"operation": "SQLiteMemoryStore.reindex", "request": {"force": True},
                "publishedBefore": runner.kit.memory.store.read_published_index(),
                "sourceBefore": _source_metadata(runner.kit.memory.workspace.root, relative)}
            record["producerPublication"] = publication
            publication["returned"] = runner.kit.memory.store.reindex(runner.kit.memory.workspace, force=True)
            publication["publishedAfter"] = runner.kit.memory.store.read_published_index()
            publication["sourceAfter"] = _source_metadata(runner.kit.memory.workspace.root, relative)
        snapshot("writer", runner)

    async def recall(session_name):
        runner = open_runner(session_name)
        instruction = phase["recall"]
        record = {"session": session_name, "prompt": instruction["prompt"], "toolCalls": []}
        raw["turns"].append(record)
        public = {"session": session_name, "query": instruction["query"]}

        async def execute(turn):
            record["modelInput"] = _model_input(turn)

            async def dispatch(name, arguments, call_id):
                assistant = _assistant_call(turn, name, arguments, call_id)
                before = runner.kit.memory.store.lifecycle_snapshot() if managed else None
                returned = await turn.dispatch_async(call_id, name, arguments)
                observed = _observed_tool_result(turn, call_id)
                call = {"name": name, "id": call_id, "arguments": deepcopy(arguments),
                    "assistant": assistant, "returned": deepcopy(returned), "observed": observed}
                if managed:
                    call.update(managedLifecycleBefore=before,
                                managedLifecycleAfter=runner.kit.memory.store.lifecycle_snapshot())
                record["toolCalls"].append(call)
                return observed["payload"]

            public["search"] = await dispatch("memory_search", {"query": instruction["query"],
                "maxResults": 5, "minScore": 0, "corpus": "memory"}, "search-saved-source")
            hits = public["search"].get("results", [])
            public["get"] = None
            if hits:
                hit = hits[0]
                if phase.get("beforeGet") is not None and session_name == "restarted":
                    path = runner.kit.memory.workspace.resolve_memory_path(hit["path"])
                    retired = root / "retired-source.md"
                    mutation = {"operation": "replace-source-with-directory", "source": str(path),
                                "retired": str(retired), "before": _source(runner.kit.memory.workspace.root, hit["path"])}
                    path.rename(retired)
                    mutation["renameReturned"] = str(retired)
                    path.mkdir()
                    mutation["mkdirReturnedNone"] = True
                    mutation["after"] = _source(runner.kit.memory.workspace.root, hit["path"])
                    mutation["retiredSource"] = _source(root, "retired-source.md")
                    record["sourceMutation"] = mutation
                public["get"] = await dispatch("memory_get", {"path": hit["path"], "from": hit["startLine"],
                    "lines": hit["endLine"] - hit["startLine"] + 1, "corpus": "memory"}, "read-saved-source")
            record["terminalInput"] = _model_input(turn)
            actual = public["get"]
            answer = ((actual.get("text") or json.dumps(actual, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
                      if actual is not None else EMPTY_ANSWER)
            record["assistant"] = _assistant_text(turn, answer)
            public["answer"] = answer
            return HostModelResult(TurnUsage(20, 3))

        outcome = await runner.run_turn(instruction["prompt"], execute=execute,
            request_id="host-restart-recall-" + session_name)
        record["outcome"] = _plain(outcome)
        snapshot(session_name, runner)
        return public

    if label == "produce":
        await save()
        reads = [await recall("fresh")]
    else:
        reads = [await recall("restarted"), await recall("isolated")]
    result = {"label": label, "reads": reads, "source": _source(locations(identity["agentId"])["workspace"], relative)}
    raw["result"] = deepcopy(result)
    raw["settlement"] = [{"session": name, "activeTurn": runner._active_turn is not None,
                           "outstandingBlockingSources": runner._blocking_count} for name, runner in runners]
    if managed:
        raw["closeReceipts"] = []
        for name, runner in runners:
            store = runner.kit.memory.store
            before = store.lifecycle_snapshot()
            returned = store.close()
            raw["closeReceipts"].append({"session": name, "before": before,
                "returnedNone": returned is None, "after": store.lifecycle_snapshot()})
    return {"result": result, "raw": raw}


def run_host_restart_phase(request: dict[str, Any]) -> dict[str, Any]:
    """Run one actual host process; no phase reconstructs its predecessor's results."""
    return asyncio.run(_run_phase(deepcopy(request)))


def run_host_restart(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    """Execute writer/fresh-chat, exit it, then start the independent reader host."""
    value = deepcopy(arguments)
    if value.get("kind") != "host-restart-recall" or [phase.get("label") for phase in value.get("phases", [])] != ["produce", "restart"]:
        raise ValueError("Host restart requires a producer process followed by one restarted reader process")
    if "policy" in value:
        _validate_policy(value["policy"])
    raw = {"kind": "host-restart-recall", "coordinatorPid": os.getpid(), "input": value, "phases": []}
    results = []
    with tempfile.TemporaryDirectory(prefix="python-host-restart-") as temporary:
        root = Path(temporary)
        raw["fixtureBase"] = str(root)
        relative = _source_path(value["phases"][0]["write"]["path"])
        environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                       "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
                       "OPENCLAW_STATE_DIR": str(root / "state"), "OPENCLAW_HOME": str(root)}
        try:
            for phase in value["phases"]:
                request = {"identity": value["identity"], "nowMs": value["nowMs"], "phase": phase,
                           "directory": str(root), "sourcePath": relative}
                if "policy" in value:
                    request["policy"] = deepcopy(value["policy"])
                wire = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                argv = [sys.executable, "-m", "equivalence.host_restart_phase_cli"]
                record = {"label": phase["label"], "request": deepcopy(request), "requestJson": wire,
                          "requestSha256": hashlib.sha256(wire.encode()).hexdigest(), "argv": argv,
                          "environmentKeys": sorted(environment), "startedAtNs": str(time.monotonic_ns())}
                raw["phases"].append(record)
                with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, cwd=ROOT, env=environment) as child:
                    record["pid"] = child.pid
                    try:
                        stdout, stderr = child.communicate(wire, timeout=60)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        stdout, stderr = child.communicate()
                        record.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                                      finishedAtNs=str(time.monotonic_ns()))
                        raise RuntimeError("The genuine SDK host phase exceeded its process bound") from None
                    record.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                                  finishedAtNs=str(time.monotonic_ns()))
                if child.returncode:
                    raise RuntimeError("The genuine SDK host phase failed; complete process streams were retained")
                observation = json.loads(stdout)
                record["observation"] = observation
                results.append(observation["result"])
        finally:
            if evidence_directory is not None:
                evidence = Path(evidence_directory)
                evidence.mkdir(parents=True, exist_ok=True)
                (evidence / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False,
                    allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return {"provider": "none", "phases": results}
