"""Observe the actual SDK process, then exec its unchanged original Host v1 CLI.

The startup never reads stdin or calls a memory API. Kernel exec preserves its
PID, cwd, environment and stdin for the genuine original host process.
"""
from __future__ import annotations

import hashlib
import json
import marshal
import math
import os
from pathlib import Path
import platform
import sys
import traceback
from types import CodeType

from equivalence.host_turn_barrier_v4 import (
    CONTRACT_SHA256, business_case, case_wire, validate_case,
)
from equivalence.host_turn_barrier_v4_environment import (
    ROOT, digest, expected_environment, git_source_authority, regular,
    run_git_probe, sdk_process_observation, validate_git_proof,
    validate_mapping, write_exclusive,
)

START_MODULE = "equivalence.host_turn_barrier_v4_sdk_start"
HOST_MODULE = "equivalence.host_turn_barrier_sdk_cli"
SOURCE_FILES = (
    "equivalence/host_turn_barrier_v4_sdk_start.py",
    "equivalence/host_turn_barrier_v4_sdk.py",
    "equivalence/host_turn_barrier_v4_environment.py",
    "equivalence/host_turn_barrier_v4.py",
    "equivalence/host-turn-barrier-v4-git-probe.mjs",
    "equivalence/host_turn_barrier_sdk_cli.py",
    "equivalence/host_turn_barrier_sdk.py",
    "equivalence/host_turn_barrier.py",
    "docs/host_turn_barrier_v4_environment.json",
    "docs/host_turn_barrier_v4_literals.json",
    "docs/host_turn_barrier_outcomes_literals.json",
    "docs/next_turn_notice_observation_contract.json",
)
CONTEXT_KEYS = {
    "schemaVersion", "kind", "contractSha256", "case", "registered", "caseWireSha256",
    "mapping", "environment", "initialArgv", "execArgv", "executable", "sourceRoot",
    "sourceFiles", "startupCodeSha256", "gitContextPath", "gitContextSha256",
    "gitSourceAuthority", "requestSha256",
}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Host v4 startup JSON has duplicate keys")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("Host v4 startup JSON has a nonfinite number")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        _constant(value)
    return result


def read_json(path):
    return json.loads(regular(path).read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                      parse_constant=_constant, parse_float=_float)


def source_seals():
    return {name: digest(regular(ROOT / name)) for name in SOURCE_FILES}


def startup_code_sha256():
    source = regular(ROOT / "equivalence/host_turn_barrier_v4_sdk_start.py")
    compiled = compile(source.read_bytes(), str(source), "exec", dont_inherit=True,
                       optimize=sys.flags.optimize)
    function = next(value for value in compiled.co_consts
                    if isinstance(value, CodeType) and value.co_name == "main")
    return hashlib.sha256(marshal.dumps(function)).hexdigest()


def validate_context(path, context):
    path = regular(path)
    if (not isinstance(context, dict) or set(context) != CONTEXT_KEYS
            or type(context["schemaVersion"]) is not int or context["schemaVersion"] != 1
            or context["kind"] != "host-turn-barrier-v4-sdk-start-context"
            or context["contractSha256"] != CONTRACT_SHA256
            or type(context["registered"]) is not bool):
        raise ValueError("Host v4 SDK startup context has another profile")
    validate_case(context["case"], registered=context["registered"])
    if hashlib.sha256(case_wire(context["case"])).hexdigest() != context["caseWireSha256"]:
        raise ValueError("Host v4 SDK startup changed its exact case wire")
    mapping = validate_mapping(context["mapping"])
    if (mapping["engine"] != "sdk" or path != Path(mapping["captureRoot"]) / "host-v4-context.json"
            or context["sourceRoot"] != str(ROOT)):
        raise ValueError("Host v4 SDK startup changed its process/source owner")
    executable = context["executable"]
    if (not isinstance(executable, dict) or set(executable) != {
            "launchPath", "realPath", "sha256", "pythonVersion", "cacheTag"}
            or not Path(executable["launchPath"]).is_absolute()
            or str(Path(executable["launchPath"]).resolve(strict=True)) != executable["realPath"]
            or digest(regular(executable["realPath"])) != executable["sha256"]
            or executable["pythonVersion"] != platform.python_version()
            or executable["cacheTag"] != sys.implementation.cache_tag):
        raise ValueError("Host v4 SDK startup changed its actual interpreter authority")
    launch = executable["launchPath"]
    if (context["initialArgv"] != [launch, "-m", START_MODULE, str(path)]
            or context["execArgv"] != [launch, "-m", HOST_MODULE]
            or context["environment"] != expected_environment(
                mapping, source_root=ROOT, executable=launch)
            or context["sourceFiles"] != source_seals()
            or context["startupCodeSha256"] != startup_code_sha256()):
        raise ValueError("Host v4 SDK startup changed its argv/environment/source authority")
    git_path = regular(context["gitContextPath"])
    if (git_path != path.parent / "git-before-context.json"
            or digest(git_path) != context["gitContextSha256"]):
        raise ValueError("Host v4 SDK startup changed its original Git context")
    git_context = read_json(git_path)
    if (git_context["contractSha256"] != CONTRACT_SHA256
            or git_context["paths"] != {"cwd": mapping["cwd"], "workspace": mapping["workspace"]}
            or git_source_authority(git_path, git_context) != context["gitSourceAuthority"]):
        raise ValueError("Host v4 SDK startup changed its original Git source authority")
    request = {"input": business_case(context["case"])["input"], "directory": mapping["state"]}
    wire = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if hashlib.sha256(wire.encode()).hexdigest() != context["requestSha256"]:
        raise ValueError("Host v4 SDK startup changed the original host stdin binding")
    return context, git_context


def main():
    if len(sys.argv) != 2:
        raise ValueError("Host v4 SDK startup needs one explicit context path")
    path = regular(sys.argv[1])
    context, git_context = validate_context(path, read_json(path))
    # Qualify actual OS facts before the source-only helper subprocess too.
    if (os.getcwd() != context["mapping"]["cwd"]
            or dict(os.environ) != context["environment"]
            or sys.orig_argv != context["initialArgv"]
            or str(Path("/proc/self/exe").resolve(strict=True)) != context["executable"]["realPath"]):
        raise ValueError("Host v4 SDK startup is not the declared actual process")
    actual_code = hashlib.sha256(marshal.dumps(sys._getframe().f_code)).hexdigest()
    if actual_code != context["startupCodeSha256"]:
        raise ValueError("Host v4 SDK startup executed another code object")
    proof = run_git_probe(context["gitContextPath"], git_context,
                          prefix=path.parent / "git-before")
    validate_git_proof(proof, context["mapping"],
                       node_authority=git_context["approvedNodeRuntime"],
                       source_authority=context["gitSourceAuthority"])
    # Repeat after qualification and immediately before the genuine kernel exec.
    context, _ = validate_context(path, context)
    receipt = sdk_process_observation(context, proof)
    receipt["startupSource"] = {"path": str(Path(__file__).resolve()), "sha256": digest(__file__),
                                "functionCodeSha256": actual_code}
    receipt["context"] = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}
    write_exclusive(path.parent / "environment-before-exec.json", receipt)
    os.execve(context["execArgv"][0], context["execArgv"], dict(os.environ))
    raise RuntimeError("Host v4 SDK original-host exec unexpectedly returned")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        json.dump({"kind": "host-turn-barrier-v4-sdk-start-failure", "pid": os.getpid(),
                   "error": {"name": type(error).__name__, "message": str(error),
                             "traceback": "".join(traceback.format_exception(error))}},
                  sys.stderr, ensure_ascii=True, allow_nan=False)
        sys.stderr.write("\n")
        raise SystemExit(2) from None
