"""Authenticated original host processes; development observations give no credit."""
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import stat
import subprocess

from equivalence.host_restart import CASE_HASHES, case_wire, validate_case
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import validate_release_sources

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ("host-restart-entry.mjs", "host-restart-preload.mjs", "host-restart-runtime.mjs",
         "host-restart-phase.mjs", "host-restart-phase-cli.mjs", "release-preload.mjs",
         "model-runtime-observation.mjs")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf8")


def validate_traces(directory, context, runtime, authority, *, process_pid, coordinator_pid, raw):
    from equivalence.host_restart_bindings import (
        REQUIRED_HOST_ARTIFACTS, WRITE_ARTIFACTS, READ_ARTIFACTS,
        PUBLICATION_PARENT_ARTIFACTS, PLUGIN_STATE_PARENT_ARTIFACTS,
        PRODUCER_WORKER_ROUTES, READER_WORKER_ROUTES, CANONICAL_PUBLICATION_WORKER_ARTIFACTS,
    )

    originals = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    locals_ = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    children = raw["children"]
    if raw["coordinatorPid"] != process_pid or raw["coordinatorPpid"] != coordinator_pid:
        raise ValueError("The host coordinator is detached from its actual parent process")
    pids = {process_pid, *(child["pid"] for child in children)}
    if len(pids) != 3 or len(children) != 2:
        raise ValueError("Restart requires three distinct real coordinator/host process identities")
    seen, bootstraps, worker_loads, main_loads, local_loads = {}, [], {}, {}, {}
    traces = sorted(directory.iterdir())
    if not traces or len(traces) > 512:
        raise ValueError("Missing or excessive restart process traces")
    total = 0
    for trace in traces:
        info = trace.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not re.fullmatch(r"[1-9][0-9]*-[0-9]+\.jsonl", trace.name):
            raise ValueError("An unowned or unknown restart trace was supplied")
        content = trace.read_bytes()
        total += len(content)
        if not content or not content.endswith(b"\n") or len(content) > 8 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise ValueError("Incomplete or excessive restart trace")
        rows = [json.loads(line) for line in content.splitlines()]
        first = rows[0]
        if (first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("pid") not in pids or first.get("fetchDenied") is not True
                or first.get("providerMode") != "none" or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != locals_[str(ROOT / "equivalence/release-preload.mjs")]
                or first.get("isMainThread") is not (first.get("threadId") == 0)
                or trace.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Missing exact restart process/worker authority")
        bootstraps.append(first)
        own = [row for row in rows if row.get("event") == "host-restart-bootstrap"]
        if (len(own) != 1 or own[0].get("profile") != context["hostRestartProfile"]
                or own[0].get("preloadSha256") != locals_[str(ROOT / "equivalence/host-restart-preload.mjs")]):
            raise ValueError("Missing independent restart capability attestation")
        for row in rows[1:]:
            if (row.get("event") not in {"load", "resolve-native", "host-restart-bootstrap"}
                    or row.get("pid") != first["pid"] or row.get("threadId") != first["threadId"]):
                raise ValueError("Unknown, rejected or reassigned restart trace event")
            if row["event"] == "host-restart-bootstrap":
                continue
            if row["kind"] == "release":
                key = row["package"], row["path"]
                if originals.get(key) != row["sha256"]:
                    raise ValueError("Unverified original import")
                seen[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                if first["isMainThread"]:
                    main_loads.setdefault(first["pid"], set()).add(row["path"])
                else:
                    worker_loads.setdefault((first["pid"], first["threadId"]), set()).add(row["path"])
            elif row["kind"] == "oracle" and locals_.get(row["path"]) == row["sha256"]:
                if first["isMainThread"]:
                    local_loads.setdefault(first["pid"], set()).add(row["path"])
            else:
                raise ValueError("Restart execution cannot import source substitutions or unknown adapters")
    mains = [row for row in bootstraps if row["isMainThread"]]
    if (len(mains) != 3 or {row["pid"] for row in mains} != pids
            or any(row["ppid"] != (coordinator_pid if row["pid"] == process_pid else process_pid) for row in mains)):
        raise ValueError("The real restart process ancestry differs from the protected coordinator")
    for pid in pids:
        actors = ("host-restart-entry.mjs", "host-restart-runtime.mjs") if pid == process_pid else ("host-restart-phase-cli.mjs", "host-restart-phase.mjs")
        if not {str(ROOT / "equivalence" / name) for name in actors} <= local_loads.get(pid, set()):
            raise ValueError("A real coordinator/host omitted its protected role adapter")
    for child in children:
        if child["request"]["runtimeRoot"] != runtime["runtimeRoot"] or child["executable"] != authority["execPath"]:
            raise ValueError("A host child borrowed another runtime location or executable")
        loaded = main_loads.get(child["pid"], set())
        required = (*REQUIRED_HOST_ARTIFACTS, *READ_ARTIFACTS, *PUBLICATION_PARENT_ARTIFACTS,
                    *PLUGIN_STATE_PARENT_ARTIFACTS, *(WRITE_ARTIFACTS if child["label"] == "produce" else ()))
        missing = sorted(set(required) - loaded)
        if missing:
            raise ValueError(f"The actual host omitted declared original owners: {missing}")
        routes = PRODUCER_WORKER_ROUTES if child["label"] == "produce" else READER_WORKER_ROUTES
        for route in routes:
            if not any(pid == child["pid"] and set(route) <= paths for (pid, _), paths in worker_loads.items()):
                raise ValueError(f"The original worker route did not execute: {route}")
        if child["label"] == "produce" and not any(
                pid == child["pid"] and set(CANONICAL_PUBLICATION_WORKER_ARTIFACTS) <= paths
                for (pid, _), paths in worker_loads.items()):
            raise ValueError("The real producer did not publish through the canonical agent SQLite worker")
    # The independent role manifest above requires the actual AgentLoop facade.
    # Keep the central release validator's existing reviewed manager entry.
    validate_release_sources(runtime, list(seen.values()))
    return {"bootstraps": bootstraps, "loaded": list(seen.values()),
            "traces": [{"name": path.name, "sha256": digest(path), "text": path.read_text()} for path in traces]}


def run_native_case(case, node, runtime, directory, *, timeout=120):
    validate_case(case)
    node = Path(node).resolve()
    authority = prepare_model_node_authority(node)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    traces, evidence = directory / "traces", directory / "evidence"
    traces.mkdir()
    evidence.mkdir()
    profile = {"kind": "host-restart-recall-development", "operation": case["operation"],
               "caseId": case["id"], "caseWireSha256": CASE_HASHES[case["id"]],
               "nodeRuntime": authority, "acceptancePointsAwarded": 0}
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
               "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
               "hostRestartProfile": profile,
               "allowedLocal": [{"path": str(ROOT / "equivalence" / name), "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
               "traceDirectory": str(traces), "evidenceDirectory": str(evidence),
               "stateDirectory": str(directory / "state"), "configPath": str(directory / "openclaw.json"),
               "approvedReferenceSources": [], "fixtureSourceCaptures": []}
    context_path = directory / "context.json"
    write_json(context_path, context)
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "NODE_OPTIONS": f'--import={ROOT / "equivalence/host-restart-preload.mjs"}',
           "MEMORY_EQ_RELEASE_CONTEXT": str(context_path)}
    with (directory / "stdout.json").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen([str(node), str(ROOT / "equivalence/host-restart-entry.mjs")],
            env=env, cwd=ROOT, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
            start_new_session=os.name == "posix")
        try:
            process.communicate(case_wire(case), timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
            raise ValueError("Restart reference timed out; original streams retained without retry") from None
    if (directory / "stdout.json").stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Restart stdout exceeded its complete result bound")
    returned = json.loads((directory / "stdout.json").read_text())
    if (process.returncode or set(returned) != {"id", "ok", "result"}
            or returned.get("id") != case["id"] or returned.get("ok") is not True):
        raise ValueError("Original restart observation failed; complete streams retained without retry")
    raw = json.loads((evidence / "native-raw.json").read_text())
    if not isinstance(raw, list) or len(raw) != 1 or Path(raw[0]["fixtureBase"]).parent != evidence:
        raise ValueError("Restart borrowed another case's evidence directory")
    trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                            process_pid=process.pid, coordinator_pid=os.getpid(), raw=raw[0])
    from equivalence.host_restart_evidence import validate_capture
    validate_capture(case, raw[0], returned["result"], native=True)
    for item in context["allowedLocal"]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("A protected restart adapter changed during execution")
    if prepare_model_node_authority(node) != authority:
        raise ValueError("Restart executable changed during execution")
    return {"kind": "official-release-host-restart-development", "results": [returned],
            "releaseSources": trace["loaded"], "releaseTrace": trace,
            "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}
