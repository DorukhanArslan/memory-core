"""Host v4 transport/environment custody plus unchanged Host v1 business proof.

All original packets are consumed as retained. Startup argv and actual exec argv
are distinct facts; this module never rewrites a capture to resemble Host v1.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from equivalence.host_turn_barrier import CASE_HASHES as BUSINESS_HASHES
from equivalence.host_turn_barrier_evidence import _same as same, validate_pair as validate_business_pair
from equivalence.host_turn_barrier_v4 import (
    CASE_HASHES, CONTRACT_SHA256, business_case, environment_contract, validate_case,
)
from equivalence.host_turn_barrier_v4_environment import (
    ROOT, digest, directory, expected_environment, git_source_authority, regular, seal_sources,
    validate_git_proof, validate_mapping, validate_path_observation,
)
from equivalence.host_turn_barrier_v4_sdk_start import (
    _constant, _float, _pairs, read_json, source_seals, startup_code_sha256, validate_context,
)
from equivalence.model_runtime_authority import prepare_model_node_authority


def require(value, message):
    if not value:
        raise ValueError(message)


def strict_json(text):
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)


def seal(path):
    path = regular(path)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path)}


def tick(value):
    require(isinstance(value, str) and value.isascii() and value.isdecimal(),
            "Host v4 monotonic time is not an actual integer-string observation")
    return int(value)


def raw_interval(raw):
    rows = raw["events"] + raw.get("noticeObservations", {}).get("events", [])
    values = [tick(row["atNs"]) for row in rows if "atNs" in row]
    require(bool(values), "Host v4 business packet omitted its actual chronology")
    return min(values), max(values)


def git_capture(capture, phase, context_path, mapping, *, node, runtime, reference, parent_pid):
    """Consume every original-helper call/import/process fact, not a null label."""
    context_path = regular(context_path)
    context = read_json(context_path)
    clean_environment = {"PATH": str(Path(node["execPath"]).parent) + os.pathsep + os.defpath,
                         "LANG": "C.UTF-8", "TZ": "UTC"}
    require(isinstance(context, dict) and set(context) == {
                "schemaVersion", "kind", "contractSha256", "paths", "expectedEnvironment",
                "approvedNodeRuntime", "runtime", "referenceRoot", "probe"}
            and type(context["schemaVersion"]) is int and context["schemaVersion"] == 1
            and context["kind"] == "host-turn-barrier-v4-git-probe-context"
            and context["expectedEnvironment"] == clean_environment
            and context["runtime"] == runtime and context["approvedNodeRuntime"] == node
            and context["referenceRoot"] == str(reference)
            and context["contractSha256"] == CONTRACT_SHA256
            and context["paths"] == {"cwd": mapping["cwd"], "workspace": mapping["workspace"]}
            and context["probe"] == {"path": str(ROOT / "equivalence/host-turn-barrier-v4-git-probe.mjs"),
                                     "sha256": digest(ROOT / "equivalence/host-turn-barrier-v4-git-probe.mjs")},
            "Host v4 Git context differs from independently approved original authorities")
    proof = read_json(capture / f"git-{phase}.proof.json")
    process = read_json(capture / f"git-{phase}.process.json")
    authority = git_source_authority(context_path, context)
    validate_git_proof(proof, mapping, node_authority=node, source_authority=authority)
    argv = [node["execPath"], context["probe"]["path"], str(context_path)]
    require(process.get("kind") == "host-turn-barrier-v4-git-probe-process"
            and process.get("actualExitObserved") is True
            and type(process.get("actualReturnCode")) is int and process["actualReturnCode"] == 0
            and not process.get("timedOut") and not process.get("error")
            and process.get("pid") == proof["pid"] and process.get("coordinatorPid") == parent_pid
            and proof["ppid"] == parent_pid and process["argv"] == argv
            and process["cwd"] == proof["cwd"] == mapping["cwd"]
            and process["environment"] == proof["environment"] == clean_environment
            and proof["argv"] == argv and proof["execArgv"] == []
            and strict_json(process["stdin"]) == context["paths"]
            and strict_json(process["stdout"]) == proof,
            "Host v4 original Git result is detached from its actual OS process/carrier")
    start, finish = tick(process["startedAtNs"]), tick(process["finishedAtNs"])
    require(start < finish and type(proof.get("acceptancePointsAwarded")) is int
            and proof["acceptancePointsAwarded"] == 0,
            "Host v4 Git qualification changed its time or zero-credit boundary")
    calls = proof["calls"]
    require(isinstance(calls, list) and len(calls) == 2, "Host v4 omitted an original Git call")
    previous = start
    for role, call in zip(("cwd", "workspace"), calls, strict=True):
        require(set(call) == {"role", "arguments", "result", "startedAtNs", "finishedAtNs", "functionRef"}
                and call["role"] == role and call["arguments"] == [mapping[role]]
                and call["result"] is None and proof["results"][role] is call["result"]
                and call["functionRef"] == "original-findGitRoot-export-t",
                "Host v4 Git result differs from its actual original function call")
        entered, returned = tick(call["startedAtNs"]), tick(call["finishedAtNs"])
        require(previous <= entered <= returned <= finish,
                "Host v4 original Git call escaped its actual process interval")
        previous = returned
    permitted = {}
    for package in runtime["packages"]:
        for row in package["files"]:
            absolute = str(Path(package["directory"]) / row["path"])
            require(absolute not in permitted, "Host v4 approved runtime duplicated a source")
            permitted[absolute] = {"package": package["location"], "path": row["path"],
                                   "absolutePath": absolute, "sha256": row["sha256"]}
    loads = proof["loads"]
    require(isinstance(loads, list) and 0 < len(loads) <= 512,
            "Host v4 omitted or exceeded original Git import evidence")
    helper_loaded = False
    for item in loads:
        require(set(item) == {"event", "url", "package", "path", "absolutePath", "sha256"}
                and item["event"] in {"load", "resolve-native"}
                and item["absolutePath"] in permitted,
                "Host v4 original Git imported a foreign source")
        source = {key: item[key] for key in ("package", "path", "absolutePath", "sha256")}
        parsed = urlparse(item["url"])
        require(source == permitted[item["absolutePath"]] and parsed.scheme == "file"
                and parsed.netloc == "" and not parsed.query and not parsed.fragment
                and unquote(parsed.path) == item["absolutePath"]
                and digest(regular(item["absolutePath"])) == item["sha256"],
                "Host v4 original Git transitive source authority changed")
        helper_loaded |= (item["event"] == "load"
                          and item["absolutePath"] == authority["helper"]["absolutePath"])
    require(helper_loaded, "Host v4 original findGitRoot was not actually imported")
    return proof, start, finish


def _native_environment(case, raw, result, capture, *, node, runtime, reference, registered):
    from equivalence.host_turn_barrier_v4_native import (
        ENTRY, LOCAL, PROFILE_KIND, process_timeout, validate_traces,
    )

    context = read_json(capture / "context.json")
    env_path = capture / "host-v4-environment-context.json"
    env = read_json(env_path)
    mapping = validate_mapping(env["mapping"])
    business = business_case(case)
    business_profile = {"kind": "host-turn-barrier-outcomes", "operation": business["operation"],
        "caseId": business["id"], "caseWireSha256": BUSINESS_HASHES[business["id"]],
        "clockNowMs": business["input"]["nowMs"], "nodeRuntime": node, "acceptancePointsAwarded": 0}
    profile = {"kind": PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
        "caseWireSha256": CASE_HASHES[case["id"]],
        "businessCaseWireSha256": BUSINESS_HASHES[business["id"]],
        "environmentContractSha256": CONTRACT_SHA256, "clockNowMs": business["input"]["nowMs"],
        "nodeRuntime": node, "acceptancePointsAwarded": 0}
    require(mapping["engine"] == "native" and mapping["captureRoot"] == str(capture)
            and env["case"] == case and env["registered"] is registered
            and env["contractSha256"] == CONTRACT_SHA256
            and env["caseWireSha256"] == CASE_HASHES[case["id"]]
            and env["runtime"] == context["runtime"] == runtime and env["node"] == node
            and env["referenceRoot"] == str(reference) and env["sourceRoot"] == str(ROOT)
            and env["sourceFiles"] == seal_sources()
            and type(context["schemaVersion"]) is int and context["schemaVersion"] == 1
            and context["kind"] == "release-oracle-execution"
            and context["providerMode"] == "none" and context["fetchPolicy"] == "deny"
            and same(context["hostTurnBarrierProfile"], business_profile)
            and same(context["hostTurnBarrierV4Profile"], profile)
            and env["temporaryRoot"] == environment_contract()["environment"]["temporaryRoot"]
            and context["hostV4EnvironmentContext"] == {"path": str(env_path), "sha256": digest(env_path)}
            and context["approvedNodeRuntime"] == node
            and context["stateDirectory"] == mapping["state"]
            and context["configPath"] == str(Path(mapping["state"]) / "openclaw.json")
            and context["evidenceDirectory"] == str(capture / "evidence")
            and context["traceDirectory"] == str(capture / "traces"),
            "Host v4 Native environment/context is not its exact actual dispatch")
    expected = expected_environment(mapping, source_root=ROOT, executable=node["execPath"],
                                    context_path=capture / "context.json")
    process = read_json(capture / "process.json")
    require(process["environment"] == env["environment"] == expected
            and process["cwd"] == mapping["cwd"] and process["mapping"] == mapping
            and process["argv"] == [node["execPath"], str(ROOT / "equivalence" / ENTRY)]
            and process["actualExitObserved"] is True and process["actualReturnCode"] == 0
            and type(process["actualReturnCode"]) is int and not process.get("timedOut")
            and "pathError" not in process and process["pid"] == raw["pid"]
            and process["coordinatorPid"] == raw["ppid"]
            and process["sourceFilesBefore"] == process["sourceFilesAfter"] == env["sourceFiles"]
            and process["contextSha256"] == digest(capture / "context.json")
            and process["environmentContextSha256"] == digest(env_path)
            and type(process["timeoutSeconds"]) is int
            and process["timeoutSeconds"] == process_timeout(registered),
            "Host v4 Native process/exit/source facts changed")
    require(raw["fixtureBase"] == mapping["state"]
            and raw["config"]["agents"]["defaults"].get("repoRoot") is None,
            "Host v4 Native business ran in another workspace/repository scope")
    validate_path_observation(read_json(capture / "environment-before-launch.json"), mapping, before=True)
    validate_path_observation(process["afterPaths"], mapping, before=False)
    before, after = (read_json(capture / name) for name in
                     ("environment-before-host.json", "environment-after-host.json"))
    git_path = regular(env["gitContext"]["path"])
    require(git_path == capture / "git-context.json" and digest(git_path) == env["gitContext"]["sha256"],
            "Host v4 Native original Git context changed")
    times = []
    for phase, receipt, added in (("before", before, {}), ("after", after, {
            "OPENCLAW_HOME": mapping["state"], "OPENCLAW_STATE_DIR": mapping["state"],
            "OPENCLAW_CONFIG_PATH": context["configPath"], "JITI_FS_CACHE": "false"})):
        proof, entered, returned = git_capture(capture, phase, git_path, mapping, node=node,
            runtime=runtime, reference=reference, parent_pid=raw["pid"])
        require(receipt["pid"] == raw["pid"] and receipt["ppid"] == raw["ppid"]
                and receipt["kind"] == f"host-turn-barrier-v4-native-{phase}-host"
                and type(receipt["version"]) is int and receipt["version"] == 4
                and receipt["contractSha256"] == CONTRACT_SHA256
                and receipt["caseWireSha256"] == CASE_HASHES[case["id"]]
                and receipt["cwd"] == mapping["cwd"] and receipt["environment"] == {**expected, **added}
                and receipt["argv"] == process["argv"] and receipt["execArgv"] == []
                and receipt["actualExecutable"] == node["execPath"]
                and receipt["executableSha256"] == node["sha256"]
                and receipt["source"] == {"path": str(ROOT / "equivalence" / ENTRY),
                                          "sha256": digest(ROOT / "equivalence" / ENTRY)}
                and receipt["originalGitProof"] == proof,
                "Host v4 Native self-observed OS facts differ from its actual process")
        validate_path_observation(receipt["paths"], mapping, before=phase == "before")
        times.append((entered, returned, tick(receipt["atNs"])))
    first, last = raw_interval(raw)
    require(tick(process["startedAtNs"]) <= times[0][0] <= times[0][1] <= times[0][2] < first
            <= last < times[1][0] <= times[1][1] <= times[1][2] <= tick(process["finishedAtNs"]),
            "Host v4 Native environment evidence crosses the original business interval")
    require(context["allowedLocal"] == [{"path": str(ROOT / "equivalence" / name),
             "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
            "Host v4 Native local source authority changed")
    validate_traces(capture / "traces", {**context, "_sha256": digest(capture / "context.json")},
                    runtime, node, process_pid=raw["pid"], parent_pid=raw["ppid"])
    output = read_json(capture / "stdout.json")
    require(output == {"id": case["id"], "ok": True, "result": result},
            "Host v4 Native whole stdout differs from its actual public result")


def _sdk_environment(case, dispatch, result, capture, *, node, runtime, reference, registered):
    context_path = capture / "host-v4-context.json"
    context, git_context = validate_context(context_path, read_json(context_path))
    mapping = validate_mapping(context["mapping"])
    require(context["case"] == case and context["registered"] is registered
            and mapping["captureRoot"] == str(capture)
            and git_context["runtime"] == runtime and git_context["approvedNodeRuntime"] == node
            and git_context["referenceRoot"] == str(reference)
            and context["sourceFiles"] == source_seals(),
            "Host v4 SDK context differs from independently selected authorities")
    envelope = dispatch["hostV4"]
    require(envelope["kind"] == "host-turn-barrier-v4-sdk-dispatch" and envelope["version"] == 4
            and envelope["context"] == seal(context_path) and envelope["mapping"] == mapping
            and envelope["caseId"] == case["id"]
            and envelope["contractSha256"] == CONTRACT_SHA256
            and envelope["caseWireSha256"] == CASE_HASHES[case["id"]]
            and envelope["sourceFilesBefore"] == envelope["sourceFilesAfter"] == context["sourceFiles"]
            and envelope["actualExitObserved"] is True and envelope["actualReturnCode"] == 0
            and not envelope.get("timedOut") and not envelope.get("observationFailure")
            and envelope["environment"] == context["environment"]
            and envelope["initialArgv"] == context["initialArgv"]
            and envelope["execArgv"] == dispatch["argv"] == context["execArgv"]
            and envelope["launchCwd"] == mapping["cwd"] and envelope["timeoutSeconds"] == 120,
            "Host v4 SDK launch/actual exec/exit/source authority changed")
    before = read_json(capture / "environment-before-exec.json")
    after = read_json(capture / "environment-after-exit.json")
    require(envelope["beforeExec"] == seal(capture / "environment-before-exec.json")
            and envelope["afterExit"] == seal(capture / "environment-after-exit.json")
            and before["context"] == seal(context_path)
            and before["pid"] == after["pid"] == dispatch["pid"]
            and before["ppid"] == after["coordinatorPid"] == dispatch["coordinatorPid"]
            and before["kind"] == "host-turn-barrier-v4-sdk-before-exec"
            and before["version"] == 4 and type(before["version"]) is int
            and before["contractSha256"] == CONTRACT_SHA256
            and before["caseWireSha256"] == CASE_HASHES[case["id"]]
            and before["cwd"] == mapping["cwd"] and before["environment"] == context["environment"]
            and before["initialArgv"] == context["initialArgv"]
            and before["execArgv"] == context["execArgv"]
            and before["actualExecutable"] == context["executable"]["realPath"]
            and before["executableSha256"] == context["executable"]["sha256"]
            and before["startupSource"] == {"path": str(ROOT / "equivalence/host_turn_barrier_v4_sdk_start.py"),
                "sha256": digest(ROOT / "equivalence/host_turn_barrier_v4_sdk_start.py"),
                "functionCodeSha256": startup_code_sha256()}
            and before["source"] == {"path": str(ROOT / "equivalence/host_turn_barrier_v4_environment.py"),
                                    "sha256": digest(ROOT / "equivalence/host_turn_barrier_v4_environment.py")}
            and after["actualExitObserved"] is True and after["actualReturnCode"] == 0
            and "pathError" not in after and "gitError" not in after and after["mapping"] == mapping,
            "Host v4 SDK actual same-PID exec/cwd/environment evidence changed")
    validate_path_observation(read_json(capture / "environment-before-launch.json"), mapping, before=True)
    validate_path_observation(before["paths"], mapping, before=True)
    validate_path_observation(after["paths"], mapping, before=False)
    git_path = regular(context["gitContextPath"])
    before_proof, bstart, bend = git_capture(capture, "before", git_path, mapping, node=node,
        runtime=runtime, reference=reference, parent_pid=dispatch["pid"])
    after_proof, astart, aend = git_capture(capture, "after", git_path, mapping, node=node,
        runtime=runtime, reference=reference, parent_pid=dispatch["coordinatorPid"])
    require(before["originalGitProof"] == before_proof,
            "Host v4 SDK pre-exec receipt substituted its original Git result")
    require(after["originalGitProof"] == after_proof
            and after["gitProcess"] == seal(capture / "git-after.process.json")
            and after["gitProof"] == seal(capture / "git-after.proof.json"),
            "Host v4 SDK post-exit receipt substituted its original Git result")
    raw = dispatch["observation"]["raw"]
    require(raw["fixtureBase"] == mapping["state"] and dispatch["request"]["directory"] == mapping["state"],
            "Host v4 SDK ran its original business host in a different state directory")
    first, last = raw_interval(raw)
    require(tick(dispatch["startedAtNs"]) <= bstart <= bend <= tick(before["atNs"]) < first <= last
            < tick(dispatch["finishedAtNs"]) <= astart <= aend <= tick(after["atNs"]),
            "Host v4 SDK exec/Git proof crosses its actual original host interval")
    stdout = regular(capture / "stdout.json").read_bytes()
    stderr = regular(capture / "stderr.log").read_bytes()
    require(stdout.decode("utf-8") == dispatch["stdout"] and stderr.decode("utf-8") == dispatch["stderr"]
            and envelope["stdout"] == seal(capture / "stdout.json")
            and envelope["stderr"] == seal(capture / "stderr.log")
            and strict_json(dispatch["stdout"]) == dispatch["observation"]
            and dispatch["observation"]["result"] == result,
            "Host v4 SDK original streams/carrier/public values were rewritten")


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result, *, native_directory,
                  sdk_directory, approved_node, approved_runtime, approved_reference,
                  approved_source_root, registered=False):
    validate_case(case, registered=registered)
    require(directory(approved_source_root) == ROOT,
            "Host v4 guard must use its independently selected unchanged actor source tree")
    node = (approved_node if isinstance(approved_node, dict)
            else prepare_model_node_authority(Path(approved_node)))
    reference = directory(approved_reference)
    native, sdk = directory(native_directory), directory(sdk_directory)
    require(native != sdk, "Host v4 must retain independent Native and SDK capture directories")
    _native_environment(case, native_raw, native_result, native, node=node, runtime=approved_runtime,
                        reference=reference, registered=registered)
    _sdk_environment(case, sdk_raw, sdk_result, sdk, node=node, runtime=approved_runtime,
                     reference=reference, registered=registered)
    require(validate_business_pair(business_case(case), native_raw, sdk_raw,
                                   native_result, sdk_result) is True,
            "Host v4 lost unchanged original Host v1 business custody")
    return True


def replay_case(case, native_directory, sdk_directory, **authorities):
    native, sdk = directory(native_directory), directory(sdk_directory)
    original = read_json(native / "stdout.json")
    python = read_json(sdk / "sdk-output.json")
    native_rows = read_json(native / "evidence/native-raw.json")
    sdk_rows = read_json(sdk / "python-raw.json")
    require(len(native_rows) == len(sdk_rows) == 1,
            "Host v4 replay requires exactly one actual original packet per engine")
    require(validate_pair(case, native_rows[0], sdk_rows[0], original["result"], python,
                         native_directory=native, sdk_directory=sdk, **authorities) is True,
            "Host v4 whole packet replay did not validate")
    return {"validated": True, "nativeSnapshots": 1, "sdkSnapshots": 1,
            "acceptancePointsAwarded": 0, "nativeResult": original["result"], "sdkResult": python}
