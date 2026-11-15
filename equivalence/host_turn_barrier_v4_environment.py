"""Actual filesystem/process admission for the frozen Host v4 environment.

No memory API belongs here. Actual execution data stays in its owned temporary
root; a different directory retains source, process and packet evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

from equivalence.host_turn_barrier_v4 import CONTRACT_SHA256, environment_contract

ROOT = Path(__file__).resolve().parents[1]
MAPPING_KEYS = {"version", "engine", "executionRoot", "cwd", "state", "workspace", "captureRoot"}
GIT_HELPER = "dist/git-root-DRBSRg7z.mjs"
GIT_HELPER_SHA256 = "7e7b5a2994f3ca326cb9ccb31393916d1d71fa5262a4e19e386eb920603a10fd"
GIT_REFERENCE_SHA256 = "84157c2595515ef21f098ab67ef31944cbddc004b9fef456220411870586f87c"
GIT_FUNCTION_SHA256 = "940791e2a9454c03e4982ee57f5e73ca4c0378e6aaff7feb92d24f3c8ed8e0fd"
SOURCE_FILES = (
    "equivalence/host_turn_barrier_v4.py", "equivalence/host_turn_barrier_v4_environment.py",
    "equivalence/host_turn_barrier_v4_native.py", "equivalence/host_turn_barrier_v4_sdk.py",
    "equivalence/host_turn_barrier_v4_sdk_start.py", "equivalence/host_turn_barrier_v4_evidence.py",
    "equivalence/host-turn-barrier-v4-entry.mjs", "equivalence/host-turn-barrier-v4-preload.mjs",
    "equivalence/host-turn-barrier-v4-git-probe.mjs", "equivalence/host-turn-barrier-runtime.mjs",
    "equivalence/host_turn_barrier_native.py", "equivalence/host_turn_barrier_sdk.py",
    "equivalence/host_turn_barrier_sdk_cli.py", "equivalence/host_turn_barrier_evidence.py",
    "equivalence/host_turn_barrier.py", "equivalence/host-turn-barrier-provider/index.mjs",
    "equivalence/host-turn-barrier-provider/openclaw.plugin.json",
    "docs/host_turn_barrier_v4_environment.json", "docs/host_turn_barrier_v4_literals.json",
    "docs/host_turn_barrier_v4_freeze.json", "docs/host_turn_barrier_outcomes_literals.json",
    "docs/next_turn_notice_observation_contract.json",
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path, *, limit=64 * 1024 * 1024):
    path = Path(path).absolute()
    info = path.lstat()
    if (".." in path.parts or path.resolve(strict=True) != path or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1 or info.st_size > limit):
        raise ValueError("Host v4 requires a bounded singly owned canonical evidence file")
    return path


def directory(path, *, missing=False):
    path = Path(path).absolute()
    if ".." in path.parts or path.resolve(strict=not missing) != path:
        raise ValueError("Host v4 rejects an aliased or traversing directory")
    cursor = path
    while True:
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if not missing or cursor != path:
                raise ValueError("Host v4 directory is missing") from None
        else:
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise ValueError("Host v4 directory is not a genuine directory")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    return path


def identity(path):
    info = Path(path).lstat()
    return {"device": str(info.st_dev), "inode": str(info.st_ino),
            "mode": info.st_mode, "uid": info.st_uid}


def ancestor_facts(path):
    path = directory(path, missing=True)
    rows = []
    for cursor in (path, *path.parents):
        try:
            (cursor / ".git").lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("Host v4 execution directory has Git ancestry")
        exists = cursor.exists()
        rows.append({"path": str(cursor), "exists": exists,
                     "identity": identity(cursor) if exists else None, "gitEntryPresent": False})
    return rows


def validate_mapping(mapping):
    contract = environment_contract()
    if (not isinstance(mapping, dict) or set(mapping) != MAPPING_KEYS
            or type(mapping["version"]) is not int or mapping["version"] != 4
            or mapping["engine"] not in {"native", "sdk"}):
        raise ValueError("Host v4 path mapping has foreign fields or identity")
    execution = directory(mapping["executionRoot"])
    temporary = directory(contract["environment"]["temporaryRoot"])
    capture = directory(mapping["captureRoot"])
    if (execution.parent != temporary or not execution.name.startswith("memory-host-v4-")
            or execution == capture or execution.is_relative_to(capture) or capture.is_relative_to(execution)
            or execution.lstat().st_uid != os.getuid() or stat.S_IMODE(execution.lstat().st_mode) != 0o700
            or capture.lstat().st_uid != os.getuid()):
        raise ValueError("Host v4 needs separate owned execution and capture roots")
    for field, relative in contract["environment"]["layout"].items():
        if mapping[field] != str(execution / relative):
            raise ValueError("Host v4 path mapping escaped its frozen layout")
        directory(mapping[field], missing=field == "workspace")
    ancestor_facts(mapping["cwd"])
    ancestor_facts(mapping["workspace"])
    return dict(mapping)


def allocate_execution(capture_root, engine):
    if engine not in {"native", "sdk"}:
        raise ValueError("Unknown Host v4 engine")
    capture = directory(capture_root)
    contract = environment_contract()
    execution = Path(tempfile.mkdtemp(prefix="memory-host-v4-",
                                     dir=contract["environment"]["temporaryRoot"]))
    for name in ("cwd", "state"):
        (execution / name).mkdir(mode=0o700)
    mapping = {"version": 4, "engine": engine, "executionRoot": str(execution),
               "captureRoot": str(capture), **{name: str(execution / relative)
                for name, relative in contract["environment"]["layout"].items()}}
    return validate_mapping(mapping)


def path_observation(mapping):
    validate_mapping(mapping)
    return {"mapping": dict(mapping), "executionIdentity": identity(mapping["executionRoot"]),
            "captureIdentity": identity(mapping["captureRoot"]),
            "cwdAncestors": ancestor_facts(mapping["cwd"]),
            "workspaceAncestors": ancestor_facts(mapping["workspace"])}


def expected_environment(mapping, *, source_root, executable, context_path=None):
    validate_mapping(mapping)
    source = directory(source_root)
    executable = Path(executable).absolute()
    base = {"PATH": str(executable.parent) + os.pathsep + os.defpath,
            "LANG": "C.UTF-8", "TZ": "UTC"}
    if mapping["engine"] == "native":
        if context_path is None:
            raise ValueError("Native Host v4 needs its explicit context path")
        base.update(NODE_OPTIONS=f"--import={source / 'equivalence/host-turn-barrier-v4-preload.mjs'}",
                    MEMORY_EQ_RELEASE_CONTEXT=str(Path(context_path).absolute()))
    else:
        base.update(PYTHONPATH=str(source), OPENCLAW_HOME=mapping["state"],
                    OPENCLAW_STATE_DIR=str(Path(mapping["state"]) / "state"))
    key = "nativeInitialEnvironmentKeys" if mapping["engine"] == "native" else "sdkEnvironmentKeys"
    if sorted(base) != environment_contract()["environment"][key]:
        raise ValueError("Host v4 implementation changed the frozen environment whitelist")
    return base


def validate_git_proof(proof, mapping, *, node_authority, source_authority):
    """Bind actual original helper observations, never replace their results."""
    if (not isinstance(proof, dict) or proof.get("kind") != "host-turn-barrier-v4-original-git-probe"
            or proof.get("node") != node_authority or proof.get("sourceAuthority") != source_authority
            or proof.get("paths") != {"cwd": mapping["cwd"], "workspace": mapping["workspace"]}
            or proof.get("results") != {"cwd": None, "workspace": None}
            or type(proof.get("pid")) is not int or proof["pid"] <= 0
            or type(proof.get("ppid")) is not int or proof["ppid"] <= 0):
        raise ValueError("Host v4 lacks unchanged actual original findGitRoot evidence")


def validate_path_observation(observed, mapping, *, before):
    if (not isinstance(observed, dict) or set(observed) != {
            "mapping", "executionIdentity", "captureIdentity", "cwdAncestors", "workspaceAncestors"}
            or observed["mapping"] != mapping
            or observed["executionIdentity"] != identity(mapping["executionRoot"])
            or observed["captureIdentity"] != identity(mapping["captureRoot"])):
        raise ValueError("Host v4 path ownership evidence changed")
    validate_mapping(mapping)
    for field, name in (("cwdAncestors", "cwd"), ("workspaceAncestors", "workspace")):
        path = Path(mapping[name])
        expected_paths = [str(item) for item in (path, *path.parents)]
        rows = observed[field]
        if not isinstance(rows, list) or [row.get("path") for row in rows] != expected_paths:
            raise ValueError("Host v4 ancestor evidence is omitted or reassigned")
        for row in rows:
            if (set(row) != {"path", "exists", "identity", "gitEntryPresent"}
                    or type(row["exists"]) is not bool or row["gitEntryPresent"] is not False):
                raise ValueError("Host v4 ancestor evidence has invalid facts")
            if row["exists"]:
                if row["identity"] != identity(row["path"]):
                    raise ValueError("Host v4 ancestor identity changed")
            elif not before or row["path"] != mapping["workspace"] or row["identity"] is not None:
                raise ValueError("Host v4 invented an absent execution ancestor")
        ancestor_facts(path)


def write_exclusive(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")


def seal_sources(source_root=ROOT):
    root = directory(source_root)
    return {name: digest(regular(root / name)) for name in SOURCE_FILES}


def sdk_process_observation(context, git_proof):
    """Called by the owned startup process immediately before same-PID exec."""
    import sys

    mapping = context["mapping"]
    validate_mapping(mapping)
    actual = dict(os.environ)
    if os.getcwd() != mapping["cwd"] or actual != context["environment"]:
        raise ValueError("Host v4 actual SDK cwd or environment differs from dispatch")
    actual_executable = str(Path("/proc/self/exe").resolve(strict=True))
    if digest(actual_executable) != context["executable"]["sha256"]:
        raise ValueError("Host v4 actual SDK executable changed")
    if sys.orig_argv != context["initialArgv"]:
        raise ValueError("Host v4 SDK startup argv differs from actual OS interpreter arguments")
    return {"kind": "host-turn-barrier-v4-sdk-before-exec", "version": 4,
            "contractSha256": CONTRACT_SHA256, "caseWireSha256": context["caseWireSha256"],
            "pid": os.getpid(), "ppid": os.getppid(), "atNs": str(time.monotonic_ns()),
            "cwd": os.getcwd(), "environment": actual,
            "initialArgv": list(sys.orig_argv), "execArgv": list(context["execArgv"]),
            "actualExecutable": actual_executable, "executableSha256": digest(actual_executable),
            "paths": path_observation(mapping), "originalGitProof": git_proof,
            "source": {"path": str(Path(__file__).resolve()), "sha256": digest(__file__)}}


def prepare_git_probe(mapping, *, node, node_authority, runtime, reference_root, path):
    validate_mapping(mapping)
    node, reference = Path(node).absolute(), directory(reference_root)
    source = regular(reference / "src/infra/git-root.ts")
    if digest(source) != GIT_REFERENCE_SHA256:
        raise ValueError("Host v4 original Git reference source changed")
    probe = regular(ROOT / "equivalence/host-turn-barrier-v4-git-probe.mjs")
    context = {"schemaVersion": 1, "kind": "host-turn-barrier-v4-git-probe-context",
        "contractSha256": CONTRACT_SHA256,
        "paths": {"cwd": mapping["cwd"], "workspace": mapping["workspace"]},
        "expectedEnvironment": {"PATH": str(node.parent) + os.pathsep + os.defpath,
                                "LANG": "C.UTF-8", "TZ": "UTC"},
        "approvedNodeRuntime": node_authority, "runtime": runtime,
        "referenceRoot": str(reference), "probe": {"path": str(probe), "sha256": digest(probe)}}
    write_exclusive(path, context)
    return context


def git_source_authority(context_path, context):
    context_path = regular(context_path)
    helper = Path(context["runtime"]["runtimeRoot"]) / GIT_HELPER
    package = next((item["location"] for item in context["runtime"]["packages"]
                    if any(Path(item["directory"]) / row["path"] == helper
                           and row["sha256"] == GIT_HELPER_SHA256 for row in item["files"])), None)
    if package is None or digest(regular(helper)) != GIT_HELPER_SHA256:
        raise ValueError("Host v4 original Git helper lost its runtime authority")
    reference = Path(context["referenceRoot"]) / "src/infra/git-root.ts"
    return {"probe": context["probe"],
        "context": {"path": str(context_path), "bytes": context_path.stat().st_size,
                    "sha256": digest(context_path)},
        "reference": {"path": str(reference), "sha256": GIT_REFERENCE_SHA256},
        "helper": {"package": package, "path": GIT_HELPER, "absolutePath": str(helper),
                   "sha256": GIT_HELPER_SHA256, "exportName": "t", "functionName": "findGitRoot",
                   "functionSourceSha256": GIT_FUNCTION_SHA256}}


def run_git_probe(context_path, context, *, prefix):
    """Run the original pure helper once; retain even rejected scope results."""
    path = regular(context_path)
    prefix = Path(prefix)
    argv = [context["approvedNodeRuntime"]["execPath"], context["probe"]["path"], str(path)]
    wire = json.dumps(context["paths"], ensure_ascii=True, separators=(",", ":"))
    record = {"kind": "host-turn-barrier-v4-git-probe-process", "argv": argv,
              "cwd": context["paths"]["cwd"], "environment": context["expectedEnvironment"],
              "stdin": wire, "startedAtNs": str(time.monotonic_ns())}
    with subprocess.Popen(argv, cwd=context["paths"]["cwd"], env=context["expectedEnvironment"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        record.update(pid=process.pid, coordinatorPid=os.getpid())
        try:
            stdout, stderr = process.communicate(wire, timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            record["timedOut"] = True
        record.update(actualExitObserved=True, actualReturnCode=process.returncode,
                      stdout=stdout, stderr=stderr, finishedAtNs=str(time.monotonic_ns()))
    write_exclusive(prefix.with_suffix(".process.json"), record)
    if record.get("timedOut") or process.returncode or len(stdout.encode()) > 4 * 1024 * 1024:
        raise ValueError("Host v4 original Git qualification failed; streams retained")
    proof = json.loads(stdout)
    write_exclusive(prefix.with_suffix(".proof.json"), proof)
    return proof
