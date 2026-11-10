"""Real SDK host turns that replace a saved preference and prove isolation.

The producers are the SDK's registered curated-memory tools; their extension
receipts are retained separately from the native coding-tool receipts.
Equivalence concerns the resulting source bytes, the explicit publication
outcomes and every later real memory-tool retrieval. Declared faults are real
filesystem states applied at the same lifecycle points as the native actor.
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
from typing import Any

from equivalence.host_restart_sdk import _model_input, _observed_tool_result, _plain, _source, _source_metadata, _sqlite_snapshot

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."
SOURCE = "MEMORY.md"
FAULTS = ("source-hard-link-during-update", "index-publication-sidecar-symlink")
POLICY = {"configuredSources": ["memory"], "rememberAcrossConversations": False, "configuredSessionMemory": False,
          "producerPublication": {"operation": "force-rebuild-after-source-metadata"},
          "indexLifecycle": "session-managed", "runtimeIdentity": "openclaw-compatible"}
MAIN_SESSIONS = ("writer", "before", "updater", "stale", "current", "superseded", "unrelated")
ISOLATED_SESSIONS = ("isolatedWriter", "isolatedBefore", "isolated")
MODEL = {"provider": "host-update-offline-model", "model": "actual-result-reader"}


def _validate_policy(policy):
    if (not isinstance(policy, dict) or set(policy) != set(POLICY) | {"sourceMtimeMs"}
            or any(policy[key] != value for key, value in POLICY.items())
            or type(policy["sourceMtimeMs"]) is not int or policy["sourceMtimeMs"] < 0):
        raise ValueError("The update experiment accepts only its explicit session-managed host policy")


def _validate_phase(phase):
    label = phase.get("label") if isinstance(phase, dict) else None
    if label == "produce":
        valid = set(phase) == {"label", "save", "isolatedSave", "recall"}
    elif label == "update":
        valid = set(phase) in ({"label", "update", "recalls"}, {"label", "update", "recalls", "fault"})
        valid = valid and (("fault" not in phase) or (set(phase["fault"]) == {"operation"}
                                                      and phase["fault"]["operation"] in FAULTS))
    else:
        valid = False
    if not valid:
        raise ValueError("A host phase accepts only its own declared instructions")
    return label


def _path_observation(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"absolutePath": str(path), "kind": "missing"}
    kind = ("symlink" if path.is_symlink() else "directory" if path.is_dir() else "file" if path.is_file() else "other")
    result = {"absolutePath": str(path), "kind": kind, "size": info.st_size, "mtimeNs": str(info.st_mtime_ns),
              "nlink": info.st_nlink}
    if kind == "symlink":
        result["target"] = os.readlink(path)
    if kind == "file":
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


async def _run_phase(request):
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.host.lifecycle import HostModelResult
    from memory_core.host.managed_session import ManagedHostSession
    from memory_core.host.session import SessionState, TurnUsage
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_visibility import resolve_memory_search_source_policy

    if set(request) != {"identity", "nowMs", "phase", "directory", "sourcePath", "policy"} or request["sourcePath"] != SOURCE:
        raise ValueError("A host child accepts only identity, clock, its own phase, policy and owned locations")
    policy, identity, phase, now = request["policy"], request["identity"], request["phase"], request["nowMs"]
    _validate_policy(policy)
    label = _validate_phase(phase)
    fault = phase.get("fault", {}).get("operation")
    resolved_policy = resolve_memory_search_source_policy(policy["configuredSources"],
        remember_across_conversations=policy["rememberAcrossConversations"],
        configured_session_memory=policy["configuredSessionMemory"])
    root = Path(request["directory"])
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("A host phase requires its real absolute owned directory")
    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The host child imported an SDK outside its owning worktree")
    raw = {"kind": "host-update-isolation", "label": label, "pid": os.getpid(), "ppid": os.getppid(),
           "implementationRoot": str(Path(memory_core.__file__).resolve().parents[1]),
           "request": deepcopy(request), "environmentKeys": sorted(os.environ),
           "policyResolution": {"input": deepcopy(policy), "result": deepcopy(resolved_policy)},
           "ownerAcquisitions": [], "opens": [], "turns": [], "mutations": [], "publications": [], "snapshots": []}
    owners, unsubscribers, runners = {}, {}, []
    mtime_ns = policy["sourceMtimeMs"] * 1_000_000

    def agent_of(session_name):
        if session_name in ISOLATED_SESSIONS:
            return identity["isolatedAgentId"]
        if session_name in MAIN_SESSIONS:
            return identity["agentId"]
        raise ValueError("An undeclared session was requested")

    def locations(agent):
        state = root / "state" / "agents" / agent
        return {"workspace": root / ("workspace" if agent == identity["agentId"] else "isolated-workspace"),
                "catalog": state / "sessions/session-authority.sqlite", "sessionStore": state / "sessions/sessions.json",
                "index": state / "agent/openclaw-agent.sqlite"}

    def owner_identity(owner, agent):
        return {"ownerId": id(owner), "storeId": id(owner.store), "controllerId": id(owner.controller),
                "catalogId": id(owner.catalog), "kitId": id(owner.kit), "agentId": agent}

    def owner_for(agent):
        if agent not in owners:
            paths = locations(agent)
            catalog = MemorySessionCatalog(paths["catalog"], agent_id=agent, store_path=paths["sessionStore"], clock_ms=lambda: now)
            config = MemoryConfig(workspace_dir=paths["workspace"], agent_id=agent, store_path=paths["index"],
                citation_mode="off", session_search=resolved_policy["sessionMemory"],
                search_max_results=5, search_min_score=0,
                flags=FeatureFlags(vector_search=False, temporal_decay=False))
            owner = ManagedHostSession.open(paths["workspace"], catalog=catalog, config=config,
                source_policy=deepcopy(resolved_policy), initialize=False,
                identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, timezone="UTC", now_ms=lambda: now)
            owners[agent] = owner
            receipt = {**owner_identity(owner, agent), "paths": _plain(paths), "config": _plain(config),
                "managedLifecycleAfterConstruction": owner.store.lifecycle_snapshot(),
                "publicationAfterConstruction": owner.publication_status(), "transcriptChanges": []}
            raw["ownerAcquisitions"].append(receipt)
            unsubscribers[agent] = catalog.subscribe_transcript_changes(
                lambda change, receipt=receipt: receipt["transcriptChanges"].append(_plain(change)))
        return owners[agent]

    def open_runner(session_name):
        agent = agent_of(session_name)
        paths, selected = locations(agent), identity[session_name]
        record = {"sessionName": session_name, "agentId": agent, "paths": _plain(paths),
                  "sourceBefore": _source(paths["workspace"], SOURCE), "ownerReused": agent in owners}
        owner = owner_for(agent)
        if owner.catalog.get_session_entry(selected["sessionKey"]) is not None:
            raise RuntimeError("A declared fresh session already has a persisted catalog entry")
        runner = owner.runner(SessionState.new(session_key=selected["sessionKey"], session_id=selected["sessionId"]))
        record.update(sessionManagedOwner=owner_identity(owner, agent), session=runner.session.to_json(),
                      managedStatusAfterOpen=deepcopy(owner.store.status()),
                      indexAfterOpen=runner.kit.memory.store.read_published_index())
        raw["opens"].append(record)
        runners.append((session_name, runner))
        return owner, runner

    def finish(record, owner, runner, outcome):
        record.update(outcome=_plain(outcome), outcomeReady=outcome.ready,
            lifecycleAfterTurn=deepcopy(runner.catalog.get_session_entry(runner.session.session_key)["sdkHostLifecycle"]),
            sessionPublicationAfterTurn=owner.publication_status())

    def assistant(turn, content):
        return turn.record_message({"role": "assistant", "content": content, **MODEL})

    async def dispatch(turn, record, name, arguments, call_id):
        message = assistant(turn, [{"type": "toolCall", "id": call_id, "name": name, "arguments": deepcopy(arguments)}])
        returned = await turn.dispatch_async(call_id, name, arguments)
        observed = _observed_tool_result(turn, call_id)
        record["toolCalls"].append({"name": name, "id": call_id, "arguments": deepcopy(arguments),
            "assistant": message, "returned": deepcopy(returned), "observed": observed})
        return observed

    def set_source_mtime(record, workspace):
        path = workspace / SOURCE
        metadata = {"operation": "os.utime", "path": str(path), "before": _source_metadata(workspace, SOURCE),
                    "arguments": {"ns": [str(mtime_ns), str(mtime_ns)]}}
        metadata["returnedNone"] = os.utime(path, ns=(mtime_ns, mtime_ns)) is None
        metadata["after"] = _source_metadata(workspace, SOURCE)
        if metadata["before"]["source"] != metadata["after"]["source"]:
            raise RuntimeError("The source metadata operation changed the actual saved corpus bytes")
        record.setdefault("sourceMetadata", []).append(metadata)

    def publish(agent, stage):
        owner = owner_for(agent)
        record = {"stage": stage, "agentId": agent, "operation": "ManagedHostSession.reindex", "request": {"force": True},
                  "publishedBefore": owner.store.read_published_index(), "publicationBefore": owner.publication_status()}
        raw["publications"].append(record)
        try:
            record.update(failed=False, returned=owner.reindex(force=True))
        except Exception as error:
            record.update(failed=True, error={"name": type(error).__name__, "message": str(error)})
        record.update(publishedAfter=owner.store.read_published_index(), publicationAfter=owner.publication_status(),
                      statusAfter=deepcopy(owner.store.status()))
        return {"agentId": agent, "stage": stage, "failed": record["failed"],
                "error": record["error"]["message"] if record["failed"] else None}

    def snapshot(name):
        observed = {"label": name, "owners": []}
        for agent, owner in owners.items():
            workspace = locations(agent)["workspace"]
            files = []
            for path in sorted(workspace.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    data = path.read_bytes()
                    files.append({"path": str(path.relative_to(workspace)), "size": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest()})
            observed["owners"].append({"agentId": agent, "source": _source(workspace, SOURCE), "files": files,
                "published": owner.store.read_published_index(), "status": deepcopy(owner.store.status()),
                "managedLifecycle": owner.store.lifecycle_snapshot(), "publication": owner.publication_status(),
                "catalog": _sqlite_snapshot(owner.catalog.path)})
        raw["snapshots"].append(observed)

    async def save(session_name, instruction):
        owner, runner = open_runner(session_name)
        workspace = runner.kit.memory.workspace.root
        if _source(workspace, SOURCE)["kind"] != "missing":
            raise ValueError("Every genuine producer source must begin absent")
        record = {"session": session_name, "kind": "save", "prompt": instruction["prompt"], "toolCalls": []}
        raw["turns"].append(record)

        async def execute(turn):
            record["modelInput"] = _model_input(turn)
            for index, entry in enumerate(instruction["entries"]):
                observed = await dispatch(turn, record, "add_memory_entry",
                    {"section": entry["section"], "text": entry["text"]}, f"save-entry-{index}")
                if observed["message"].get("isError"):
                    raise RuntimeError("The genuine producer failed; its complete result is retained")
            source = _source(workspace, SOURCE)
            if source.get("text") != instruction["content"]:
                raise RuntimeError("The registered producer did not write the declared corpus bytes")
            set_source_mtime(record, workspace)
            record["terminalInput"] = _model_input(turn)
            record["assistant"] = assistant(turn, [{"type": "text", "text": instruction["ack"]}])
            return HostModelResult(TurnUsage(20, 3))

        finish(record, owner, runner, await runner.run_turn(instruction["prompt"], execute=execute,
            request_id="host-update-save-" + session_name))

    async def update(instruction):
        owner, runner = open_runner("updater")
        workspace = runner.kit.memory.workspace.root
        record = {"session": "updater", "kind": "update", "prompt": instruction["prompt"], "toolCalls": []}
        raw["turns"].append(record)
        linked = root / "retained-source-link.md"
        public = {}

        async def execute(turn):
            record["modelInput"] = _model_input(turn)
            if fault == "source-hard-link-during-update":
                mutation = {"operation": fault, "stage": "before-update-tool", "before": _path_observation(workspace / SOURCE)}
                raw["mutations"].append(mutation)
                os.link(workspace / SOURCE, linked)
                mutation["after"] = _path_observation(workspace / SOURCE)
            observed = await dispatch(turn, record, "replace_memory_entry",
                {"old": instruction["old"], "new": instruction["new"]}, "update-entry")
            public["committed"] = observed["message"].get("isError") is not True
            if fault == "source-hard-link-during-update":
                mutation = {"operation": fault, "stage": "after-update-tool", "before": _path_observation(workspace / SOURCE)}
                raw["mutations"].append(mutation)
                linked.unlink()
                mutation["after"] = _path_observation(workspace / SOURCE)
            if public["committed"]:
                set_source_mtime(record, workspace)
            public["answer"] = instruction["ack"] if public["committed"] else instruction["failureAck"]
            record["terminalInput"] = _model_input(turn)
            record["assistant"] = assistant(turn, [{"type": "text", "text": public["answer"]}])
            return HostModelResult(TurnUsage(20, 3))

        finish(record, owner, runner, await runner.run_turn(instruction["prompt"], execute=execute,
            request_id="host-update-replace"))
        if (fault == "source-hard-link-during-update") == public["committed"]:
            raise RuntimeError("The declared update outcome did not occur; the complete result is retained")
        return public

    async def recall(session_name, instruction):
        owner, runner = open_runner(session_name)
        record = {"session": session_name, "kind": "recall", "prompt": instruction["prompt"], "toolCalls": []}
        raw["turns"].append(record)
        public = {"session": session_name, "query": instruction["query"]}

        async def execute(turn):
            record["modelInput"] = _model_input(turn)
            observed = await dispatch(turn, record, "memory_search", {"query": instruction["query"],
                "maxResults": 5, "minScore": 0, "corpus": "memory"}, "search-saved-source")
            if observed["message"].get("isError"):
                raise RuntimeError("A genuine memory tool failed; its complete result is retained")
            public["search"] = observed["payload"]
            hits = public["search"].get("results", [])
            public["get"] = None
            if hits:
                hit = hits[0]
                observed = await dispatch(turn, record, "memory_get", {"path": hit["path"], "from": hit["startLine"],
                    "lines": hit["endLine"] - hit["startLine"] + 1, "corpus": "memory"}, "read-saved-source")
                if observed["message"].get("isError"):
                    raise RuntimeError("A genuine memory tool failed; its complete result is retained")
                public["get"] = observed["payload"]
            actual = public["get"]
            answer = ((actual.get("text") or json.dumps(actual, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
                      if actual is not None else EMPTY_ANSWER)
            record["terminalInput"] = _model_input(turn)
            record["assistant"] = assistant(turn, [{"type": "text", "text": answer}])
            public["answer"] = answer
            return HostModelResult(TurnUsage(20, 3))

        finish(record, owner, runner, await runner.run_turn(instruction["prompt"], execute=execute,
            request_id="host-update-recall-" + session_name))
        return public

    main, isolated = identity["agentId"], identity["isolatedAgentId"]
    reads, publications, result = [], [], {"label": label}
    if label == "produce":
        await save("writer", phase["save"])
        await save("isolatedWriter", phase["isolatedSave"])
        publications += [publish(main, "produce"), publish(isolated, "produce")]
        if any(item["failed"] for item in publications):
            raise RuntimeError("The producer publication failed; the complete result is retained")
        snapshot("after-real-writes-and-explicit-publication")
        reads += [await recall("before", phase["recall"]), await recall("isolatedBefore", phase["recall"])]
    else:
        index = locations(main)["index"]
        sidecar = index.with_name(index.name + "-journal")
        if fault == "index-publication-sidecar-symlink":
            mutation = {"operation": fault, "stage": "before-update", "sidecar": str(sidecar), "before": _path_observation(sidecar)}
            raw["mutations"].append(mutation)
            if mutation["before"]["kind"] != "missing":
                raise RuntimeError("The publication sidecar path must be free before the declared fault")
            os.symlink(root / "missing-sidecar-directory" / "journal", sidecar)
            mutation["after"] = _path_observation(sidecar)
        result["update"] = await update(phase["update"])
        if fault == "index-publication-sidecar-symlink":
            faulted = publish(main, "faulted")
            publications.append(faulted)
            if not faulted["failed"]:
                raise RuntimeError("The declared publication failure did not occur; the complete result is retained")
            reads.append(await recall("stale", phase["recalls"]["current"]))
            mutation = {"operation": fault, "stage": "after-stale-read", "sidecar": str(sidecar), "before": _path_observation(sidecar)}
            raw["mutations"].append(mutation)
            sidecar.unlink()
            mutation["after"] = _path_observation(sidecar)
        final = publish(main, "final")
        publications.append(final)
        if final["failed"]:
            raise RuntimeError("The final producer publication failed; the complete result is retained")
        snapshot("after-update-and-explicit-publication")
        for name in ("current", "superseded", "unrelated", "isolated"):
            reads.append(await recall(name, phase["recalls"][name]))
    snapshot("after-active-recall")
    result.update(publications=publications, reads=reads,
                  source=_source(locations(main)["workspace"], SOURCE),
                  isolatedSource=_source(locations(isolated)["workspace"], SOURCE))
    raw["result"] = deepcopy(result)
    raw["settlement"] = [{"session": name, "activeTurn": runner._active_turn is not None,
                           "outstandingBlockingSources": runner._blocking_count} for name, runner in runners]
    raw["closeReceipts"] = []
    for agent, owner in owners.items():
        receipt = {"owner": owner_identity(owner, agent),
            "sessions": [name for name, runner in runners if runner.catalog is owner.catalog],
            "before": owner.store.lifecycle_snapshot(), "publicationBefore": owner.publication_status()}
        raw["closeReceipts"].append(receipt)
        returned = owner.close()
        unsubscribers[agent]()
        receipt.update(returnedNone=returned is None, after=owner.store.lifecycle_snapshot(),
                       publicationAfter=owner.publication_status())
    return {"result": result, "raw": raw}


def run_host_update_isolation_phase(request: dict[str, Any]) -> dict[str, Any]:
    """Run one actual host process; no phase reconstructs its predecessor's results."""
    return asyncio.run(_run_phase(deepcopy(request)))


def run_host_update_isolation(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    """Execute the producer host, exit it, then start the independent updating/reading host."""
    value = deepcopy(arguments)
    if (value.get("kind") != "host-update-isolation" or value.get("source") != SOURCE
            or [phase.get("label") for phase in value.get("phases", [])] != ["produce", "update"]):
        raise ValueError("Host update requires a producer process followed by one updating reader process")
    _validate_policy(value.get("policy"))
    for phase in value["phases"]:
        _validate_phase(phase)
    raw = {"kind": "host-update-isolation", "coordinatorPid": os.getpid(), "input": value, "phases": []}
    results = []
    with tempfile.TemporaryDirectory(prefix="python-host-update-") as temporary:
        root = Path(temporary)
        raw["fixtureBase"] = str(root)
        environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                       "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
                       "OPENCLAW_STATE_DIR": str(root / "state"), "OPENCLAW_HOME": str(root)}
        try:
            for phase in value["phases"]:
                request = {"identity": value["identity"], "nowMs": value["nowMs"], "phase": phase,
                           "directory": str(root), "sourcePath": SOURCE, "policy": deepcopy(value["policy"])}
                wire = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                argv = [sys.executable, "-m", "equivalence.host_update_isolation_phase_cli"]
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
