"""Closed original manager/status/tool execution for identity boundary inputs."""
from pathlib import Path
import json
import os
import re
import signal
import stat
import subprocess

from equivalence.host_restart_native import digest, write_json
from equivalence.index_identity_boundaries import CASE_HASHES, case_wire, validate_case
from equivalence.index_identity_boundaries_bindings import (
    REQUIRED_MAIN_ARTIFACTS, REQUIRED_WORKER_ARTIFACTS,
)
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import validate_release_sources

ROOT = Path(__file__).resolve().parents[1]
PROFILE_KEY = "indexIdentityBoundariesProfile"
BOOTSTRAP_EVENT = "index-identity-boundaries-bootstrap"
PROFILE_KIND = "index-identity-boundaries"
NATIVE_KIND = "official-release-index-identity-boundaries"
ENTRY = "index-identity-boundaries-entry.mjs"
PRELOAD = "index-identity-boundaries-preload.mjs"
ACTOR = "index-identity-boundaries-runtime.mjs"
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
        raise ValueError("Missing or excessive actual identity traces")
    total, seen, bootstraps, main, workers, local_main = 0, {}, [], set(), set(), set()
    for file in files:
        if not _regular(file) or not re.fullmatch(r"[1-9][0-9]*-[0-9]+\.jsonl", file.name):
            raise ValueError("Aliased or unknown identity trace")
        raw = file.read_bytes()
        total += len(raw)
        if not raw or not raw.endswith(b"\n") or len(raw) > 8 * 1024 * 1024 or total > 128 * 1024 * 1024:
            raise ValueError("Incomplete or excessive identity trace bytes")
        rows = [json.loads(line) for line in raw.splitlines()]
        first = rows[0]
        if (first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("pid") != process_pid or first.get("ppid") != parent_pid
                or first.get("fetchDenied") is not True or first.get("providerMode") != "none"
                or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != local[str(ROOT / "equivalence" / PRELOAD)]
                or first.get("isMainThread") is not (first.get("threadId") == 0)
                or file.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Wrong identity process, worker, context or approved executable")
        bootstraps.append(first)
        own = [row for row in rows if row.get("event") == BOOTSTRAP_EVENT]
        if (len(own) != 1 or own[0].get("profile") != context[PROFILE_KEY]
                or own[0].get("preloadSha256") != first["preloadSha256"]
                or own[0].get("clock") != {"owner": "node:test", "apis": ["Date"],
                    "nowMs": context[PROFILE_KEY]["clockNowMs"], "dateConstructorReplaced": True,
                    "setTimeoutUnchanged": True, "performanceNowUnchanged": True}):
            raise ValueError("The real identity worker lost its independent Date-only profile")
        for row in rows[1:]:
            if (row.get("event") not in {"load", "resolve-native", BOOTSTRAP_EVENT}
                    or row.get("pid") != first["pid"] or row.get("threadId") != first["threadId"]):
                raise ValueError("Unknown, rejected or reassigned identity trace event")
            if row["event"] == BOOTSTRAP_EVENT:
                continue
            if row.get("kind") == "release":
                key = row["package"], row["path"]
                if originals.get(key) != row["sha256"]:
                    raise ValueError("An actual imported identity owner changed")
                seen[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                (main if first["isMainThread"] else workers).add(row["path"])
            elif row.get("kind") == "oracle" and local.get(row.get("path")) == row.get("sha256"):
                if first["isMainThread"]:
                    local_main.add(row["path"])
            else:
                raise ValueError("The identity runtime imported an undeclared source")
    if (len([row for row in bootstraps if row["isMainThread"]]) != 1
            or not any(not row["isMainThread"] for row in bootstraps)
            or not {str(ROOT / "equivalence" / name) for name in (ENTRY, ACTOR)} <= local_main
            or not set(REQUIRED_MAIN_ARTIFACTS) <= main
            or not set(REQUIRED_WORKER_ARTIFACTS) <= workers):
        raise ValueError("The actual identity caller or its required publication/read workers did not execute")
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
    with (directory / "stdout.json").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen([str(node), str(ROOT / "equivalence" / ENTRY)], env=env, cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   start_new_session=os.name == "posix")
        try:
            process.communicate(case_wire(case), timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
            raise ValueError("Actual Native identity caller timed out; original streams retained without retry") from None
    stdout_path = directory / "stdout.json"
    if stdout_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("The actual identity result exceeded its original transport bound")
    returned = json.loads(stdout_path.read_text())
    if (process.returncode or set(returned) != {"id", "ok", "result"}
            or returned.get("id") != case["id"] or returned.get("ok") is not True):
        raise ValueError("Original identity manager/tool observation failed; complete streams retained")
    raw_path = evidence / "native-raw.json"
    if not _regular(raw_path) or raw_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("The original identity custody file is aliased or excessive")
    raw = json.loads(raw_path.read_text())
    if (not isinstance(raw, list) or len(raw) != 1 or raw[0].get("pid") != process.pid
            or raw[0].get("ppid") != os.getpid() or Path(raw[0]["fixtureBase"]) != state
            or raw[0].get("input") != case["input"] or raw[0].get("caseId") != case["id"]
            or raw[0].get("result") != returned["result"] or raw[0].get("completed") is not True
            or raw[0].get("allManagersClosed") is not True or raw[0].get("teardownError")):
        raise ValueError("The identity custody is detached from its actual process, source or close")
    trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                            process_pid=process.pid, parent_pid=os.getpid())
    for item in context["allowedLocal"]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("A protected identity actor changed during execution")
    if prepare_model_node_authority(node) != authority:
        raise ValueError("The actual identity executable changed during execution")
    return {"kind": NATIVE_KIND, "results": [returned], "releaseSources": trace["loaded"],
            "releaseTrace": trace, "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}
