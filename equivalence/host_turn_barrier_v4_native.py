"""Authenticated Native Host v4 execution with separate physical state/captures."""
from pathlib import Path
import json
import os
import re
import signal
import stat
import subprocess
import time

from equivalence.host_restart_native import digest, write_json
from equivalence.host_turn_barrier import CASE_HASHES as BUSINESS_HASHES
from equivalence.host_turn_barrier_v4 import (
    CASE_HASHES, CONTRACT_SHA256, OPERATION, business_case, case_wire, environment_contract, validate_case,
)
from equivalence.host_turn_barrier_v4_environment import (
    ROOT, allocate_execution, directory as canonical_directory, expected_environment,
    path_observation, prepare_git_probe, regular, seal_sources, write_exclusive,
)
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import validate_release_sources

PROFILE_KEY = "hostTurnBarrierV4Profile"
BOOTSTRAP_EVENT = "host-turn-barrier-v4-bootstrap"
PROFILE_KIND = "host-turn-barrier-v4-isolated-environment"
NATIVE_KIND = "official-release-host-turn-barrier-v4-outcomes"
PRELOAD = "host-turn-barrier-v4-preload.mjs"
ENTRY = "host-turn-barrier-v4-entry.mjs"
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


def process_timeout(registered):
    """Preserve both existing entry-point bounds without widening either."""
    if type(registered) is not bool:
        raise ValueError("Host v4 requires an explicit Boolean registration mode")
    return 120 if registered else 180


def run_native_case(case, node, runtime, directory, *, reference_root, timeout=None, registered=False):
    """One original full host in the explicitly frozen isolated environment."""
    validate_case(case, registered=registered)
    expected_timeout = process_timeout(registered)
    if timeout is None:
        timeout = expected_timeout
    if type(timeout) is not int or timeout != expected_timeout:
        raise ValueError(f"Host v4 preserves the original Native {expected_timeout} second process bound")
    node = Path(node).resolve(strict=True)
    authority = prepare_model_node_authority(node)
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    directory = canonical_directory(directory)
    traces, evidence = directory / "traces", directory / "evidence"
    traces.mkdir(mode=0o700)
    evidence.mkdir(mode=0o700)
    mapping = allocate_execution(directory, "native")
    state, context_path = Path(mapping["state"]), directory / "context.json"
    git_path, env_path = directory / "git-context.json", directory / "host-v4-environment-context.json"
    original = business_case(case)
    sources = seal_sources()
    prepare_git_probe(mapping, node=node, node_authority=authority, runtime=runtime,
                      reference_root=reference_root, path=git_path)
    environment = expected_environment(mapping, source_root=ROOT, executable=node,
                                       context_path=context_path)
    environment_context = {
        "kind": "host-turn-barrier-v4-native-environment-context", "version": 4,
        "case": case, "registered": registered, "caseWireSha256": CASE_HASHES[case["id"]],
        "contractSha256": CONTRACT_SHA256, "mapping": mapping, "environment": environment,
        "temporaryRoot": environment_contract()["environment"]["temporaryRoot"],
        "node": authority, "runtime": runtime, "referenceRoot": str(Path(reference_root).resolve()),
        "sourceRoot": str(ROOT), "sourceFiles": sources,
        "gitContext": {"path": str(git_path), "sha256": digest(git_path)},
    }
    write_exclusive(env_path, environment_context)
    business_profile = {"kind": "host-turn-barrier-outcomes", "operation": original["operation"],
        "caseId": original["id"], "caseWireSha256": BUSINESS_HASHES[original["id"]],
        "clockNowMs": original["input"]["nowMs"], "nodeRuntime": authority, "acceptancePointsAwarded": 0}
    profile = {"kind": PROFILE_KIND, "operation": OPERATION, "caseId": case["id"],
        "caseWireSha256": CASE_HASHES[case["id"]], "businessCaseWireSha256": BUSINESS_HASHES[original["id"]],
        "environmentContractSha256": CONTRACT_SHA256, "clockNowMs": original["input"]["nowMs"],
        "nodeRuntime": authority, "acceptancePointsAwarded": 0}
    provider = ROOT / "equivalence" / PROVIDER
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
        "hostTurnBarrierProfile": business_profile, PROFILE_KEY: profile,
        "hostV4EnvironmentContext": {"path": str(env_path), "sha256": digest(env_path)},
        "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                          "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
        "traceDirectory": str(traces), "evidenceDirectory": str(evidence),
        "stateDirectory": str(state), "configPath": str(state / "openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": [{"basename": "index.mjs",
            "capturePackage": "host-turn-barrier-provider", "sourcePath": str(provider),
            "sha256": digest(provider)}]}
    write_json(context_path, context)
    before = path_observation(mapping)
    write_exclusive(directory / "environment-before-launch.json", before)
    argv = [str(node), str(ROOT / "equivalence" / ENTRY)]
    process_record = {"kind": "host-turn-barrier-v4-native-process", "argv": argv,
        "cwd": mapping["cwd"], "environment": environment, "mapping": mapping,
        "coordinatorPid": os.getpid(), "startedAtNs": str(time.monotonic_ns()),
        "sourceFilesBefore": sources, "contextSha256": digest(context_path),
        "environmentContextSha256": digest(env_path), "timeoutSeconds": timeout}
    with (directory / "stdout.json").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen(argv, env=environment, cwd=mapping["cwd"], stdin=subprocess.PIPE,
                                   stdout=stdout, stderr=stderr, start_new_session=os.name == "posix")
        process_record["pid"] = process.pid
        try:
            process.communicate(case_wire(case), timeout=timeout)
        except subprocess.TimeoutExpired:
            process_record["timedOut"] = True
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
    process_record.update(actualExitObserved=True, actualReturnCode=process.returncode,
                          finishedAtNs=str(time.monotonic_ns()), sourceFilesAfter=seal_sources())
    try:
        process_record["afterPaths"] = path_observation(mapping)
    except Exception as error:
        process_record["pathError"] = {"name": type(error).__name__, "message": str(error)}
    write_exclusive(directory / "process.json", process_record)
    if process.returncode or process_record.get("timedOut") or "pathError" in process_record:
        raise ValueError("Original Host v4 Native failed; all actual streams/state remain retained")
    returned = json.loads(regular(directory / "stdout.json", limit=32 * 1024 * 1024).read_text())
    if (set(returned) != {"id", "ok", "result"} or returned["id"] != case["id"]
            or returned["ok"] is not True):
        raise ValueError("Host v4 Native output lost its exact original result")
    raw = json.loads(regular(evidence / "native-raw.json", limit=32 * 1024 * 1024).read_text())
    if (not isinstance(raw, list) or len(raw) != 1 or raw[0].get("pid") != process.pid
            or raw[0].get("ppid") != os.getpid() or raw[0].get("fixtureBase") != mapping["state"]
            or raw[0].get("input") != original["input"] or raw[0].get("result") != returned["result"]):
        raise ValueError("Host v4 Native raw is detached from its actual business/process")
    trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                            process_pid=process.pid, parent_pid=os.getpid())
    if (seal_sources() != sources or prepare_model_node_authority(node) != authority):
        raise ValueError("Host v4 sources or original Node changed during execution")
    return {"kind": NATIVE_KIND, "results": [returned], "releaseSources": trace["loaded"],
            "releaseTrace": trace, "runtimeDiagnostics": raw,
            "evidenceDirectory": str(directory), "environmentDirectory": str(directory),
            "executionRoot": mapping["executionRoot"]}


