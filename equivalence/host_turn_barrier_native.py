"""Independent authenticated full Native caller for natural next-turn observations."""
from pathlib import Path
import json
import os
import re
import signal
import stat
import subprocess

from equivalence.host_restart_native import digest, write_json
from equivalence.host_turn_barrier import CASE_HASHES, case_wire, validate_case
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import validate_release_sources

ROOT = Path(__file__).resolve().parents[1]
PROFILE_KEY = "hostTurnBarrierProfile"
BOOTSTRAP_EVENT = "host-turn-barrier-bootstrap"
PROFILE_KIND = "host-turn-barrier-outcomes"
NATIVE_KIND = "official-release-host-turn-barrier-outcomes"
PRELOAD = "host-turn-barrier-preload.mjs"
ENTRY = "host-turn-barrier-entry.mjs"
ACTOR = "host-turn-barrier-runtime.mjs"
PROVIDER = "host-turn-barrier-provider/index.mjs"
LOCAL = (ENTRY, PRELOAD, ACTOR, PROVIDER, "host-turn-barrier-provider/openclaw.plugin.json")


def _regular(path):
    info = Path(path).lstat()
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not Path(path).is_symlink()


def validate_traces(directory, context, runtime, authority, *, process_pid, parent_pid):
    """Every loaded original/fixture byte and inherited worker clock is authenticated."""
    originals = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    locals_ = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    seen, bootstraps, main_loads, local_loads, captures = {}, [], set(), set(), []
    traces = sorted(Path(directory).iterdir())
    if not traces or len(traces) > 512:
        raise ValueError("Missing or excessive full-caller traces")
    total = 0
    for trace in traces:
        if not _regular(trace) or not re.fullmatch(r"[1-9][0-9]*-[0-9]+\.jsonl", trace.name):
            raise ValueError("Unknown full-caller trace")
        content = trace.read_bytes()
        total += len(content)
        if not content or not content.endswith(b"\n") or len(content) > 8 * 1024 * 1024 or total > 128 * 1024 * 1024:
            raise ValueError("Incomplete or excessive full-caller trace")
        rows = [json.loads(line) for line in content.splitlines()]
        first = rows[0]
        if (first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("pid") != process_pid or first.get("ppid") != parent_pid
                or first.get("fetchDenied") is not True or first.get("providerMode") != "none"
                or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != locals_[str(ROOT / "equivalence" / PRELOAD)]
                or first.get("isMainThread") is not (first.get("threadId") == 0)
                or trace.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Missing exact full-caller process/worker authority")
        bootstraps.append(first)
        own = [row for row in rows if row.get("event") == BOOTSTRAP_EVENT]
        if (len(own) != 1 or own[0].get("profile") != context[PROFILE_KEY]
                or own[0].get("preloadSha256") != first["preloadSha256"]
                or own[0].get("clock") != {"owner": "node:test", "apis": ["Date"],
                    "nowMs": context[PROFILE_KEY]["clockNowMs"], "dateConstructorReplaced": True,
                    "setTimeoutUnchanged": True, "performanceNowUnchanged": True}):
            raise ValueError("Missing independent whole-caller/worker Date-only clock attestation")
        for row in rows[1:]:
            if (row.get("event") not in {"load", "resolve-native", BOOTSTRAP_EVENT}
                    or row.get("pid") != first["pid"] or row.get("threadId") != first["threadId"]):
                raise ValueError("Rejected or reassigned full-caller trace event")
            if row["event"] == BOOTSTRAP_EVENT:
                continue
            if row["kind"] == "release":
                key = row["package"], row["path"]
                if originals.get(key) != row["sha256"]:
                    raise ValueError("An imported original changed")
                seen[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                if first["isMainThread"]:
                    main_loads.add(row["path"])
            elif row["kind"] == "oracle" and locals_.get(row["path"]) == row["sha256"]:
                if first["isMainThread"]:
                    local_loads.add(row["path"])
            elif row["kind"] == "fixture-capture":
                if (row.get("sourcePath") != str(ROOT / "equivalence" / PROVIDER)
                        or row.get("sha256") != locals_[row["sourcePath"]]
                        or not re.fullmatch(r"fixture-source-captures/[0-9a-f]{64}\.mjs", row.get("proofPath", ""))):
                    raise ValueError("Unknown provider capture")
                proof = Path(context["evidenceDirectory"]) / row["proofPath"]
                if not _regular(proof) or digest(proof) != row["sha256"]:
                    raise ValueError("The retained exact provider source capture changed")
                captures.append(row)
            else:
                raise ValueError("Whole-caller execution imported an unknown module source")
    if len([b for b in bootstraps if b["isMainThread"]]) != 1:
        raise ValueError("The declared host requires one real process and inherited workers")
    if not {str(ROOT / "equivalence" / name) for name in (ENTRY, ACTOR)} <= local_loads:
        raise ValueError("Missing protected actual whole-caller actor")
    from equivalence.host_turn_barrier_bindings import ADDITIONAL_REQUIRED_HOST_ARTIFACTS
    missing = set(ADDITIONAL_REQUIRED_HOST_ARTIFACTS) - main_loads
    if missing:
        raise ValueError(f"The actual full caller omitted pinned owners: {sorted(missing)}")
    if not captures or not any(not b["isMainThread"] for b in bootstraps):
        raise ValueError("Actual original plugin capture and inherited worker execution are required")
    validate_release_sources(runtime, list(seen.values()))
    return {"bootstraps": bootstraps, "loaded": list(seen.values()), "fixtureCaptures": captures,
            "traces": [{"name": p.name, "sha256": digest(p), "text": p.read_text()} for p in traces]}


def run_native_case(case, node, runtime, directory, *, timeout=180):
    """One immutable dispatch; honest failed attempts retain all original streams."""
    validate_case(case)
    node = Path(node).resolve()
    authority = prepare_model_node_authority(node)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    traces, evidence, state = directory / "traces", directory / "evidence", directory / "state"
    for folder in (traces, evidence, state):
        folder.mkdir()
    profile = {"kind": PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
               "caseWireSha256": CASE_HASHES[case["id"]], "clockNowMs": case["input"]["nowMs"],
               "nodeRuntime": authority, "acceptancePointsAwarded": 0}
    provider = ROOT / "equivalence" / PROVIDER
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
               "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
               PROFILE_KEY: profile,
               "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                                 "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
               "traceDirectory": str(traces), "evidenceDirectory": str(evidence),
               "stateDirectory": str(state), "configPath": str(state / "openclaw.json"),
               "approvedReferenceSources": [], "fixtureSourceCaptures": [
                   {"basename": "index.mjs", "capturePackage": "host-turn-barrier-provider",
                    "sourcePath": str(provider), "sha256": digest(provider)}]}
    context_path = directory / "context.json"
    write_json(context_path, context)
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "NODE_OPTIONS": f'--import={ROOT / "equivalence" / PRELOAD}',
           "MEMORY_EQ_RELEASE_CONTEXT": str(context_path)}
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
            raise ValueError("Full Native host timed out; original streams retained without retry") from None
    stdout_path = directory / "stdout.json"
    if stdout_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Complete host outcome exceeded the reviewed transport bound")
    returned = json.loads(stdout_path.read_text())
    if (process.returncode or set(returned) != {"id", "ok", "result"}
            or returned.get("id") != case["id"] or returned.get("ok") is not True):
        raise ValueError("Original full-caller observation failed; original streams retained")
    raw = json.loads((evidence / "native-raw.json").read_text())
    if (not isinstance(raw, list) or len(raw) != 1 or raw[0].get("pid") != process.pid
            or raw[0].get("ppid") != os.getpid() or Path(raw[0]["fixtureBase"]) != state
            or raw[0].get("input") != case["input"] or raw[0].get("result") != returned["result"]):
        raise ValueError("The full-caller capture is detached from its literal or process")
    trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                            process_pid=process.pid, parent_pid=os.getpid())
    for item in context["allowedLocal"]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("A protected whole-caller adapter changed during execution")
    if prepare_model_node_authority(node) != authority:
        raise ValueError("The full-caller executable changed during execution")
    return {"kind": NATIVE_KIND, "results": [returned], "releaseSources": trace["loaded"],
            "releaseTrace": trace, "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}
