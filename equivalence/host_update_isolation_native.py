"""Authenticated original update/isolation host processes under one closed capability.

The transport mirrors the reviewed host-restart lane but owns its own profile,
preload, entry and actors: no earlier capability, literal or capture is widened.
"""
from pathlib import Path
import json
import os
import re
import signal
import stat
import subprocess

from equivalence.host_restart_native import digest, write_json
from equivalence.host_update_isolation import CASE_HASHES, case_wire, validate_case
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import validate_release_sources

ROOT = Path(__file__).resolve().parents[1]
PROFILE_KEY = "hostUpdateIsolationProfile"
BOOTSTRAP_EVENT = "host-update-isolation-bootstrap"
PROFILE_KIND = "host-update-isolation-acceptance"
NATIVE_KIND = "official-release-host-update-isolation-acceptance"
PRELOAD = "host-update-isolation-preload.mjs"
ENTRY = "host-update-isolation-entry.mjs"
COORDINATOR = "host-update-isolation-runtime.mjs"
PHASE_ACTORS = ("host-update-isolation-phase-cli.mjs", "host-update-isolation-phase.mjs")
LOCAL = (ENTRY, PRELOAD, COORDINATOR, PHASE_ACTORS[1], PHASE_ACTORS[0],
         "release-preload.mjs", "model-runtime-observation.mjs")


def required_host_artifacts():
    """Every host child writes, publishes and reads, so both need the whole owner set."""
    from equivalence.host_restart_bindings import (
        REQUIRED_HOST_ARTIFACTS, WRITE_ARTIFACTS, READ_ARTIFACTS,
        PUBLICATION_PARENT_ARTIFACTS, PLUGIN_STATE_PARENT_ARTIFACTS,
    )
    from equivalence.host_restart_policy_bindings import ADDITIONAL_REQUIRED_HOST_ARTIFACTS as policy
    from equivalence.host_restart_publication_bindings import ADDITIONAL_REQUIRED_HOST_ARTIFACTS as publication
    from equivalence.host_update_isolation_bindings import ADDITIONAL_REQUIRED_HOST_ARTIFACTS as update

    # The report publishes ``update`` as requiredLoadedArtifacts; it is enforced
    # here by name rather than through its overlap with the restart owner sets.
    return tuple(dict.fromkeys((*REQUIRED_HOST_ARTIFACTS, *READ_ARTIFACTS, *PUBLICATION_PARENT_ARTIFACTS,
                                *PLUGIN_STATE_PARENT_ARTIFACTS, *WRITE_ARTIFACTS, *policy, *publication,
                                *update)))


def validate_traces(directory, context, runtime, authority, *, process_pid, coordinator_pid, raw):
    from equivalence.host_restart_bindings import PRODUCER_WORKER_ROUTES, CANONICAL_PUBLICATION_WORKER_ARTIFACTS

    originals = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    locals_ = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    children = raw["children"]
    if raw["coordinatorPid"] != process_pid or raw["coordinatorPpid"] != coordinator_pid:
        raise ValueError("The host coordinator is detached from its actual parent process")
    pids = {process_pid, *(child["pid"] for child in children)}
    if len(pids) != 3 or [child["label"] for child in children] != ["produce", "update"]:
        raise ValueError("Update requires three distinct real coordinator/host process identities")
    seen, bootstraps, worker_loads, main_loads, local_loads = {}, [], {}, {}, {}
    traces = sorted(directory.iterdir())
    if not traces or len(traces) > 512:
        raise ValueError("Missing or excessive update process traces")
    total = 0
    for trace in traces:
        info = trace.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not re.fullmatch(r"[1-9][0-9]*-[0-9]+\.jsonl", trace.name):
            raise ValueError("An unowned or unknown update trace was supplied")
        content = trace.read_bytes()
        total += len(content)
        if not content or not content.endswith(b"\n") or len(content) > 8 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise ValueError("Incomplete or excessive update trace")
        rows = [json.loads(line) for line in content.splitlines()]
        first = rows[0]
        if (first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("pid") not in pids or first.get("fetchDenied") is not True
                or first.get("providerMode") != "none" or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != locals_[str(ROOT / "equivalence/release-preload.mjs")]
                or first.get("isMainThread") is not (first.get("threadId") == 0)
                or trace.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Missing exact update process/worker authority")
        bootstraps.append(first)
        own = [row for row in rows if row.get("event") == BOOTSTRAP_EVENT]
        if (len(own) != 1 or own[0].get("profile") != context[PROFILE_KEY]
                or own[0].get("preloadSha256") != locals_[str(ROOT / "equivalence" / PRELOAD)]):
            raise ValueError("Missing independent update capability attestation")
        for row in rows[1:]:
            if (row.get("event") not in {"load", "resolve-native", BOOTSTRAP_EVENT}
                    or row.get("pid") != first["pid"] or row.get("threadId") != first["threadId"]):
                raise ValueError("Unknown, rejected or reassigned update trace event")
            if row["event"] == BOOTSTRAP_EVENT:
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
                raise ValueError("Update execution cannot import source substitutions or unknown adapters")
    mains = [row for row in bootstraps if row["isMainThread"]]
    if (len(mains) != 3 or {row["pid"] for row in mains} != pids
            or any(row["ppid"] != (coordinator_pid if row["pid"] == process_pid else process_pid) for row in mains)):
        raise ValueError("The real update process ancestry differs from the protected coordinator")
    for pid in pids:
        actors = (ENTRY, COORDINATOR) if pid == process_pid else PHASE_ACTORS
        if not {str(ROOT / "equivalence" / name) for name in actors} <= local_loads.get(pid, set()):
            raise ValueError("A real coordinator/host omitted its protected role adapter")
    required = required_host_artifacts()
    for child in children:
        if child["request"]["runtimeRoot"] != runtime["runtimeRoot"] or child["executable"] != authority["execPath"]:
            raise ValueError("A host child borrowed another runtime location or executable")
        missing = sorted(set(required) - main_loads.get(child["pid"], set()))
        if missing:
            raise ValueError(f"The actual host omitted declared original owners: {missing}")
        for route in PRODUCER_WORKER_ROUTES:
            if not any(pid == child["pid"] and set(route) <= paths for (pid, _), paths in worker_loads.items()):
                raise ValueError(f"The original worker route did not execute: {route}")
        if not any(pid == child["pid"] and set(CANONICAL_PUBLICATION_WORKER_ARTIFACTS) <= paths
                   for (pid, _), paths in worker_loads.items()):
            raise ValueError("A real host did not publish through the canonical agent SQLite worker")
    validate_release_sources(runtime, list(seen.values()))
    return {"bootstraps": bootstraps, "loaded": list(seen.values()),
            "traces": [{"name": path.name, "sha256": digest(path), "text": path.read_text()} for path in traces]}


def run_native_case(case, node, runtime, directory, *, timeout=120):
    """One protected dispatch of a frozen literal; failures retain every stream and are never retried."""
    validate_case(case)
    node = Path(node).resolve()
    authority = prepare_model_node_authority(node)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    traces, evidence = directory / "traces", directory / "evidence"
    traces.mkdir()
    evidence.mkdir()
    profile = {"kind": PROFILE_KIND, "operation": case["operation"],
               "caseId": case["id"], "caseWireSha256": CASE_HASHES[case["id"]],
               "nodeRuntime": authority, "acceptancePointsAwarded": 0}
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
               "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
               PROFILE_KEY: profile,
               "allowedLocal": [{"path": str(ROOT / "equivalence" / name), "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
               "traceDirectory": str(traces), "evidenceDirectory": str(evidence),
               "stateDirectory": str(directory / "state"), "configPath": str(directory / "openclaw.json"),
               "approvedReferenceSources": [], "fixtureSourceCaptures": []}
    context_path = directory / "context.json"
    write_json(context_path, context)
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "NODE_OPTIONS": f'--import={ROOT / "equivalence" / PRELOAD}',
           "MEMORY_EQ_RELEASE_CONTEXT": str(context_path)}
    with (directory / "stdout.json").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen([str(node), str(ROOT / "equivalence" / ENTRY)],
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
            raise ValueError("Update reference timed out; original streams retained without retry") from None
    if (directory / "stdout.json").stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Update stdout exceeded its complete result bound")
    returned = json.loads((directory / "stdout.json").read_text())
    if (process.returncode or set(returned) != {"id", "ok", "result"}
            or returned.get("id") != case["id"] or returned.get("ok") is not True):
        raise ValueError("Original update observation failed; complete streams retained without retry")
    raw = json.loads((evidence / "native-raw.json").read_text())
    if not isinstance(raw, list) or len(raw) != 1 or Path(raw[0]["fixtureBase"]).parent != evidence:
        raise ValueError("Update borrowed another case's evidence directory")
    trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                            process_pid=process.pid, coordinator_pid=os.getpid(), raw=raw[0])
    from equivalence.host_update_isolation_evidence import validate_capture

    validate_capture(case, raw[0], returned["result"], native=True)
    for item in context["allowedLocal"]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("A protected update adapter changed during execution")
    if prepare_model_node_authority(node) != authority:
        raise ValueError("Update executable changed during execution")
    return {"kind": NATIVE_KIND, "results": [returned],
            "releaseSources": trace["loaded"], "releaseTrace": trace,
            "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}
