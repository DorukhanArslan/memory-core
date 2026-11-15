"""Host v4 SDK launcher with separate non-repository execution/capture roots.

The observed startup execs the unchanged original Host v1 CLI. Its complete
stdout and public result remain intact; no reply or warning is projected here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

from equivalence.host_turn_barrier_v4 import (
    CONTRACT_SHA256, business_case, case_wire, validate_case,
)
from equivalence.host_turn_barrier_v4_environment import (
    ROOT, allocate_execution, digest, directory, expected_environment,
    git_source_authority, path_observation, prepare_git_probe, regular,
    run_git_probe, validate_git_proof, write_exclusive,
)
from equivalence.host_turn_barrier_v4_sdk_start import (
    HOST_MODULE, START_MODULE, read_json, source_seals, startup_code_sha256,
)

_MAX_STREAM_BYTES = 32 * 1024 * 1024


def _seal(path):
    path = regular(path)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def _capture_stream(path, value):
    with Path(path).open("xb") as stream:
        if stream.write(value) != len(value):
            raise OSError("Host v4 could not retain the complete original stream")
    # Even rejected oversize streams remain lossless evidence. This seal is
    # retention metadata; successful admission still enforces the fixed bound.
    path = regular(path, limit=len(value))
    return {"path": str(path), "bytes": len(value), "sha256": digest(path)}


def run_sdk_case(case, directory_path, *, node, node_authority, runtime,
                 reference_root, python=None, timeout=120, registered=False):
    """One actual original SDK host; this helper never retries or awards credit."""
    validate_case(case, registered=registered)
    if type(timeout) is not int or timeout != 120:
        raise ValueError("Host v4 preserves the original SDK process bound of 120 seconds")
    executable = Path(python or sys.executable).absolute()
    if executable != Path(sys.executable).absolute():
        raise ValueError("Host v4 SDK launch must use its current sealed Python interpreter")
    capture = Path(directory_path).absolute()
    capture.mkdir(parents=True, exist_ok=True)
    capture = directory(capture)
    if any(capture.iterdir()):
        raise ValueError("Host v4 SDK needs a new empty owned capture directory")
    mapping = allocate_execution(capture, "sdk")
    context_path, git_path = capture / "host-v4-context.json", capture / "git-before-context.json"
    environment = expected_environment(mapping, source_root=ROOT, executable=executable)
    git_context = prepare_git_probe(mapping, node=node, node_authority=node_authority,
                                    runtime=runtime, reference_root=reference_root, path=git_path)
    original = business_case(case)
    request = {"input": original["input"], "directory": mapping["state"]}
    wire = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    initial_argv = [str(executable), "-m", START_MODULE, str(context_path)]
    exec_argv = [str(executable), "-m", HOST_MODULE]
    sources = source_seals()
    context = {
        "schemaVersion": 1, "kind": "host-turn-barrier-v4-sdk-start-context",
        "contractSha256": CONTRACT_SHA256, "case": case, "registered": registered,
        "caseWireSha256": hashlib.sha256(case_wire(case)).hexdigest(),
        "mapping": mapping, "environment": environment,
        "initialArgv": initial_argv, "execArgv": exec_argv,
        "executable": {"launchPath": str(executable), "realPath": str(executable.resolve(strict=True)),
                       "sha256": digest(executable), "pythonVersion": platform.python_version(),
                       "cacheTag": sys.implementation.cache_tag},
        "sourceRoot": str(ROOT), "sourceFiles": sources,
        "startupCodeSha256": startup_code_sha256(),
        "gitContextPath": str(git_path), "gitContextSha256": digest(git_path),
        "gitSourceAuthority": git_source_authority(git_path, git_context),
        "requestSha256": hashlib.sha256(wire.encode()).hexdigest(),
    }
    write_exclusive(context_path, context)
    before = path_observation(mapping)
    write_exclusive(capture / "environment-before-launch.json", before)
    envelope = {
        "kind": "host-turn-barrier-v4-sdk-dispatch", "version": 4,
        "caseId": case["id"], "caseWireSha256": context["caseWireSha256"],
        "contractSha256": CONTRACT_SHA256, "mapping": mapping,
        "context": _seal(context_path), "gitContext": _seal(git_path),
        "initialArgv": initial_argv, "execArgv": exec_argv,
        "launchCwd": mapping["cwd"], "environment": environment,
        "sourceFilesBefore": sources, "timeoutSeconds": timeout,
        "argvQualification": "initialArgv is actual Popen startup; legacy argv is the exact original-host exec vector, retained separately and bound by same-PID startup receipt",
        "acceptancePointsAwarded": 0,
    }
    dispatch = {
        "kind": "host-turn-barrier-sdk-dispatch", "input": original["input"],
        "coordinatorPid": os.getpid(), "request": request, "requestJson": wire,
        "requestSha256": context["requestSha256"], "argv": exec_argv,
        "environmentKeys": sorted(environment), "startedAtNs": str(time.monotonic_ns()),
        "hostV4": envelope,
    }
    stdout = stderr = b""
    with subprocess.Popen(initial_argv, cwd=mapping["cwd"], env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name == "posix") as child:
        dispatch["pid"] = child.pid
        try:
            stdout, stderr = child.communicate(wire.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            envelope["timedOut"] = True
            try:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
            except ProcessLookupError:
                pass
            stdout, stderr = child.communicate()
        dispatch.update(exit={"code": child.returncode}, finishedAtNs=str(time.monotonic_ns()))
        envelope.update(actualExitObserved=True, actualReturnCode=child.returncode)
    envelope["stdout"] = _capture_stream(capture / "stdout.json", stdout)
    envelope["stderr"] = _capture_stream(capture / "stderr.log", stderr)
    decode_failure = False
    for label, data in (("stdout", stdout), ("stderr", stderr)):
        try:
            dispatch[label] = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            decode_failure = True
            envelope[label + "DecodeError"] = {"name": type(error).__name__, "message": str(error)}
    after = {"kind": "host-turn-barrier-v4-sdk-after-exit", "pid": dispatch["pid"],
             "coordinatorPid": dispatch["coordinatorPid"], "actualExitObserved": True,
             "actualReturnCode": dispatch["exit"]["code"], "mapping": mapping}
    try:
        after["paths"] = path_observation(mapping)
    except Exception as error:
        after["pathError"] = {"name": type(error).__name__, "message": str(error)}
    try:
        after["originalGitProof"] = run_git_probe(git_path, git_context,
                                                  prefix=capture / "git-after")
        validate_git_proof(after["originalGitProof"], mapping, node_authority=node_authority,
                           source_authority=context["gitSourceAuthority"])
        after["gitProcess"] = _seal(capture / "git-after.process.json")
        after["gitProof"] = _seal(capture / "git-after.proof.json")
    except Exception as error:
        after["gitError"] = {"name": type(error).__name__, "message": str(error)}
    after["atNs"] = str(time.monotonic_ns())
    write_exclusive(capture / "environment-after-exit.json", after)
    envelope["afterExit"] = _seal(capture / "environment-after-exit.json")
    receipt_path = capture / "environment-before-exec.json"
    if receipt_path.exists():
        envelope["beforeExec"] = _seal(receipt_path)
    envelope["sourceFilesAfter"] = source_seals()
    failure = None
    try:
        if (envelope.get("timedOut") or dispatch["exit"]["code"] != 0
                or len(stdout) > _MAX_STREAM_BYTES or len(stderr) > _MAX_STREAM_BYTES):
            raise ValueError("Host v4 original SDK process failed or exceeded its retained stream bound")
        if decode_failure:
            raise ValueError("Host v4 original SDK streams are not strict UTF-8; original bytes retained")
        output = json.loads(dispatch["stdout"])
        if (not isinstance(output, dict) or set(output) != {"result", "raw"}
                or output["raw"].get("pid") != dispatch["pid"]
                or output["raw"].get("ppid") != os.getpid()):
            raise ValueError("Host v4 original SDK stdout lost its exact process identity")
        dispatch["observation"] = output
        if (envelope["sourceFilesAfter"] != sources
                or "pathError" in after or "gitError" in after):
            raise ValueError("Host v4 SDK source or actual filesystem environment changed")
        if not receipt_path.exists():
            raise ValueError("Host v4 SDK omitted its actual pre-exec environment receipt")
        receipt = read_json(receipt_path)
        if (receipt.get("pid") != dispatch["pid"] or receipt.get("ppid") != os.getpid()
                or receipt.get("initialArgv") != initial_argv or receipt.get("execArgv") != exec_argv
                or receipt.get("context") != _seal(context_path)):
            raise ValueError("Host v4 SDK startup is detached from actual same-PID host exec")
    except Exception as error:
        failure = error
        envelope["observationFailure"] = {"name": type(error).__name__, "message": str(error)}
    write_exclusive(capture / "python-raw.json", [dispatch])
    if failure is not None:
        raise failure
    write_exclusive(capture / "sdk-output.json", dispatch["observation"]["result"])
    return {"result": dispatch["observation"]["result"], "dispatch": dispatch, "v4": envelope}


def run_host_turn_barrier_v4_case(case, *, node, runtime, reference_root,
                                 evidence_directory, timeout=120, registered=False):
    """Shared-harness entry: return the WHOLE actual result, with no projection."""
    from equivalence.model_runtime_authority import prepare_model_node_authority

    return run_sdk_case(case, evidence_directory, node=node,
        node_authority=prepare_model_node_authority(node), runtime=runtime,
        reference_root=reference_root, timeout=timeout, registered=registered)["result"]
