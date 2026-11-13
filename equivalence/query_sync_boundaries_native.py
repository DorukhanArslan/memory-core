"""Separate protected original manager/tool caller for query-sync boundaries."""
from pathlib import Path
import json
import os
import re
import signal
import stat
import subprocess
import time

from equivalence.host_restart_native import digest, write_json
from equivalence.query_sync_boundaries import CASE_HASHES, case_wire, validate_case
from equivalence.query_sync_boundaries_bindings import (
    REQUIRED_MAIN_ARTIFACTS, REQUIRED_WORKER_ARTIFACTS,
)
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import validate_release_sources

ROOT = Path(__file__).resolve().parents[1]
PROFILE_KEY = "querySyncBoundariesProfile"
BOOTSTRAP_EVENT = "query-sync-boundaries-bootstrap"
PROFILE_KIND = "query-sync-boundaries"
NATIVE_KIND = "official-release-query-sync-boundaries"
ENTRY = "query-sync-boundaries-entry.mjs"
PRELOAD = "query-sync-boundaries-preload.mjs"
ACTOR = "query-sync-boundaries-runtime.mjs"
LOCAL = (ENTRY, PRELOAD, ACTOR)


def _regular(path):
    path = Path(path)
    info = path.lstat()
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink() and path.resolve() == path)


def validate_traces(directory, context, runtime, authority, *, process_pid, parent_pid):
    """Recheck each actual import and each inherited worker clock/binary."""
    originals = {(package["location"], file["path"]): file["sha256"]
                 for package in runtime["packages"] for file in package["files"]}
    local = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    files = sorted(Path(directory).iterdir())
    if not files or len(files) > 512:
        raise ValueError("Missing or excessive actual query-sync traces")
    total, seen, bootstraps, main, workers, local_main = 0, {}, [], set(), set(), set()
    for file in files:
        if not _regular(file) or not re.fullmatch(r"[1-9][0-9]*-[0-9]+\.jsonl", file.name):
            raise ValueError("Aliased or unknown query-sync trace")
        raw = file.read_bytes()
        total += len(raw)
        if not raw or not raw.endswith(b"\n") or len(raw) > 8 * 1024 * 1024 or total > 128 * 1024 * 1024:
            raise ValueError("Incomplete or excessive query-sync trace bytes")
        rows = [json.loads(line) for line in raw.splitlines()]
        first = rows[0]
        if (first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("pid") != process_pid or first.get("ppid") != parent_pid
                or first.get("fetchDenied") is not True or first.get("providerMode") != "none"
                or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != local[str(ROOT / "equivalence" / PRELOAD)]
                or first.get("isMainThread") is not (first.get("threadId") == 0)
                or file.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Wrong query-sync process, worker, context or approved executable")
        bootstraps.append(first)
        own = [row for row in rows if row.get("event") == BOOTSTRAP_EVENT]
        if (len(own) != 1 or own[0].get("profile") != context[PROFILE_KEY]
                or own[0].get("preloadSha256") != first["preloadSha256"]
                or own[0].get("clock") != {"owner": "node:test", "apis": ["Date"],
                    "nowMs": context[PROFILE_KEY]["clockNowMs"], "dateConstructorReplaced": True,
                    "setTimeoutUnchanged": True, "performanceNowUnchanged": True}):
            raise ValueError("The real query-sync worker lost its independent Date-only profile")
        for row in rows[1:]:
            if (row.get("event") not in {"load", "resolve-native", BOOTSTRAP_EVENT}
                    or row.get("pid") != first["pid"] or row.get("threadId") != first["threadId"]):
                raise ValueError("Unknown, rejected or reassigned query-sync trace event")
            if row["event"] == BOOTSTRAP_EVENT:
                continue
            if row.get("kind") == "release":
                key = row["package"], row["path"]
                if originals.get(key) != row["sha256"]:
                    raise ValueError("An actual imported query-sync owner changed")
                seen[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                (main if first["isMainThread"] else workers).add(row["path"])
            elif row.get("kind") == "oracle" and local.get(row.get("path")) == row.get("sha256"):
                if first["isMainThread"]:
                    local_main.add(row["path"])
            else:
                raise ValueError("The query-sync runtime imported an undeclared source")
    if (len([row for row in bootstraps if row["isMainThread"]]) != 1
            or not any(not row["isMainThread"] for row in bootstraps)
            or not {str(ROOT / "equivalence" / name) for name in (ENTRY, ACTOR)} <= local_main
            or not set(REQUIRED_MAIN_ARTIFACTS) <= main
            or not set(REQUIRED_WORKER_ARTIFACTS) <= workers):
        raise ValueError("The actual query-sync caller or its required publication/read workers did not execute")
    validate_release_sources(runtime, list(seen.values()))
    return {"bootstraps": bootstraps, "loaded": list(seen.values()),
            "traces": [{"name": file.name, "sha256": digest(file), "text": file.read_text()} for file in files]}


def run_native_case(case, node, runtime, directory, *, timeout=120):
    """One original immutable attempt; complete failures remain retained."""
    validate_case(case)
    node = Path(node).resolve(strict=True)
    authority = prepare_model_node_authority(node)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    traces, evidence, state = directory / "traces", directory / "evidence", directory / "state"
    for folder in (traces, evidence, state):
        folder.mkdir()
    profile = {"kind": PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
               "caseWireSha256": CASE_HASHES[case["id"]], "clockNowMs": case["input"]["nowMs"],
               "nodeRuntime": authority, "acceptancePointsAwarded": 0}
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
               "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
               PROFILE_KEY: profile,
               "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                                 "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
               "traceDirectory": str(traces), "evidenceDirectory": str(evidence),
               "stateDirectory": str(state), "configPath": str(state / "openclaw.json"),
               "approvedReferenceSources": [], "fixtureSourceCaptures": []}
    context_path = directory / "context.json"
    write_json(context_path, context)
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "NODE_OPTIONS": f'--import={ROOT / "equivalence" / PRELOAD}',
           "MEMORY_EQ_RELEASE_CONTEXT": str(context_path),
           "OPENCLAW_STATE_DIR": str(state), "OPENCLAW_CONFIG_PATH": context["configPath"]}
    wire = case_wire(case)
    (directory / "request.json").write_bytes(wire)
    argv = [str(node), str(ROOT / "equivalence" / ENTRY)]
    process_record = {"argv": argv, "cwd": str(ROOT), "environment": env,
                      "requestPath": str(directory / "request.json"),
                      "requestSha256": digest(directory / "request.json"),
                      "contextPath": str(context_path), "contextSha256": digest(context_path),
                      "parentPid": os.getpid(), "startedAtNs": str(time.monotonic_ns())}
    with (directory / "stdout.json").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, env=env, cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   start_new_session=os.name == "posix")
        process_record["pid"] = process.pid
        try:
            process.communicate(wire, timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
            process_record["timedOut"] = True
            raise ValueError("Actual Native query-sync caller timed out; original streams retained without retry") from None
        finally:
            process_record.update(returncode=process.returncode, finishedAtNs=str(time.monotonic_ns()),
                                  stdoutPath=str(directory / "stdout.json"),
                                  stderrPath=str(directory / "stderr.log"))
            write_json(directory / "process.json", process_record)
    stdout_path = directory / "stdout.json"
    if stdout_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("The actual query-sync result exceeded its original transport bound")
    returned = json.loads(stdout_path.read_text())
    if (process.returncode or set(returned) != {"id", "ok", "result"}
            or returned.get("id") != case["id"] or returned.get("ok") is not True):
        raise ValueError("Original query-sync manager/tool observation failed; complete streams retained")
    raw_path = evidence / "native-raw.json"
    if not _regular(raw_path) or raw_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("The original query-sync custody file is aliased or excessive")
    raw = json.loads(raw_path.read_text())
    if (not isinstance(raw, list) or len(raw) != 1 or raw[0].get("pid") != process.pid
            or raw[0].get("ppid") != os.getpid() or Path(raw[0]["fixtureBase"]) != state
            or raw[0].get("input") != case["input"] or raw[0].get("caseId") != case["id"]
            or raw[0].get("result") != returned["result"] or raw[0].get("completed") is not True
            or raw[0].get("allManagersClosed") is not True or raw[0].get("teardownError")
            or raw[0].get("faultCleanupError") or raw[0].get("gateCleanupError")
            or raw[0].get("observationErrors") or raw[0].get("revisionErrors")):
        raise ValueError("The query-sync custody is detached from its actual process, source or close")
    trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                            process_pid=process.pid, parent_pid=os.getpid())
    for item in context["allowedLocal"]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("A protected query-sync actor changed during execution")
    if prepare_model_node_authority(node) != authority:
        raise ValueError("The actual query-sync executable changed during execution")
    return {"kind": NATIVE_KIND, "results": [returned], "releaseSources": trace["loaded"],
            "releaseTrace": trace, "runtimeDiagnostics": raw, "evidenceDirectory": str(directory),
            "process": {**process_record, "stdoutSha256": digest(directory / "stdout.json"),
                        "stderrSha256": digest(directory / "stderr.log"),
                        "stdout": (directory / "stdout.json").read_text(),
                        "stderr": (directory / "stderr.log").read_text()}}
