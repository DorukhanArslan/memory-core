"""Closed multi-process original caller for the frozen forget/index-fence inputs.

The launcher authenticates custody and process/module authority. Independent
capture validation owns race semantics; this transport awards no acceptance.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time

from equivalence.forget_index_fence_bindings import (
    REQUIRED_MAIN_ARTIFACTS_BY_ROUTE,
    REQUIRED_WORKER_ARTIFACTS_BY_ROUTE,
    prepare_forget_index_fence_bindings,
)
from equivalence.host_restart_native import digest, write_json
from equivalence.model_runtime_authority import (
    prepare_model_node_authority,
    validate_model_node_authority,
)
from equivalence.release_runtime import validate_release_sources

ROOT = Path(__file__).resolve().parents[1]
PROFILE_KEY = "forgetIndexFenceProfile"
BOOTSTRAP_EVENT = "forget-index-fence-bootstrap"
PROFILE_KIND = "forget-index-fence"
NATIVE_KIND = "official-release-forget-index-fence"
ENTRY = "forget-index-fence-entry.mjs"
PRELOAD = "forget-index-fence-preload.mjs"
ACTOR = "forget-index-fence-runtime.mjs"
LOCAL = (ENTRY, PRELOAD, ACTOR)
_CONTEXT_KEYS = frozenset({
    "schemaVersion", "kind", "runtime", "providerMode", "fetchPolicy", "approvedNodeRuntime",
    PROFILE_KEY, "allowedLocal", "traceDirectory", "evidenceDirectory", "stateDirectory",
    "configPath", "gateDirectory", "approvedReferenceSources", "fixtureSourceCaptures",
})
_ALWAYS_MAIN_ARTIFACTS = (
    "dist/extensions/memory-core/manager-runtime.js", "dist/extensions/memory-core/runtime-api.js",
    "dist/plugin-sdk/config-runtime.js", "dist/runtime-snapshot-BFi3jxlO.mjs",
    "dist/plugin-sdk/plugin-state-store-runtime.js", "dist/plugin-sdk/session-store-runtime.js",
    "dist/plugin-sdk/session-transcript-runtime.js", "dist/session-accessor-CiKKTlbe.mjs",
    "dist/short-term-promotion-Cy0NJmOU.mjs", "dist/memory-entry-origins-BCQSIB3X.mjs",
    "dist/cli.runtime-CVRN4xUp.mjs", "dist/runtime-BC29JSZp.mjs", "dist/tools-DotaQGXh.mjs",
)


def _contract():
    # The root integrates the independently frozen input module. Importing this
    # transport alone neither loads that manifest nor launches either engine.
    return import_module("equivalence.forget_index_fence")


def _validated_case(case):
    contract = _contract()
    value = contract.validate_case(case)
    # Recheck the complete sealed manifest before admitting any single member.
    frozen = {item["id"]: item for item in contract.build_cases()}
    if case.get("id") not in frozen or value != frozen[case["id"]]:
        raise ValueError("Forget/index-fence requires its closed independently frozen family")
    wire = contract.case_wire(value)
    if hashlib.sha256(wire).hexdigest() != contract.CASE_HASHES[value["id"]]:
        raise ValueError("Forget/index-fence input wire differs from its frozen hash")
    return value, wire


def prepare_profile(case, authority):
    case, wire = _validated_case(case)
    authority = validate_model_node_authority(authority)
    base = case["input"]["clock"]["nowMs"]
    actors = case["input"]["actors"]
    if (type(base) is not int or not isinstance(actors, dict) or not actors
            or len(actors) > 10 or {"coordinator", "observer"} & set(actors)
            or any(not isinstance(actor, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", actor)
                   for actor in actors)):
        raise ValueError("Forget/index-fence requires declared actor clocks and identities")
    profile = {
        "kind": PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
        "caseWireSha256": hashlib.sha256(wire).hexdigest(),
        "actorClocks": {"coordinator": base, "observer": base, **dict.fromkeys(actors, base)},
        "gates": deepcopy(case["input"]["gates"]), "nodeRuntime": authority,
        "acceptancePointsAwarded": 0,
    }
    if "recoveryNowMs" in case["input"]["clock"]:
        recovery = case["input"]["clock"]["recoveryNowMs"]
        if type(recovery) is not int:
            raise ValueError("Forget/index-fence recovery wall phase must be an exact integer")
        profile["recoveryNowMs"] = recovery
    return profile


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("Forget/index-fence requires its exact closed profile")
    cases = {case["id"]: case for case in _contract().build_cases()}
    if profile.get("caseId") not in cases:
        raise ValueError("Forget/index-fence profile names an unapproved frozen case")
    expected = prepare_profile(cases[profile["caseId"]], profile.get("nodeRuntime"))
    if profile != expected or type(profile.get("acceptancePointsAwarded")) is not int:
        raise ValueError("Forget/index-fence profile differs from its exact frozen capability")
    return deepcopy(profile)


def _regular(path):
    path = Path(path)
    info = path.lstat()
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink() and path.resolve() == path)


def _read_json(path, *, limit=64 * 1024 * 1024):
    path = Path(path)
    if not _regular(path) or path.stat().st_size > limit:
        raise ValueError("Forget/index-fence custody file is aliased or excessive")
    return json.loads(path.read_text(encoding="utf8"))


def _local_authority():
    result = []
    for name in LOCAL:
        path = ROOT / "equivalence" / name
        if not _regular(path):
            raise ValueError("Forget/index-fence local module is not an independent regular file")
        result.append({"path": str(path), "sha256": digest(path)})
    return result


def _verify_unchanged(local, node, authority):
    for item in local:
        if not _regular(item["path"]) or digest(item["path"]) != item["sha256"]:
            raise ValueError("A protected forget/index-fence local module changed during execution")
    if prepare_model_node_authority(node) != authority:
        raise ValueError("The actual forget/index-fence executable changed during execution")


def _seal(value, expected):
    if (not isinstance(value, dict) or set(value) != {"serializedJSON", "sha256"}
            or not isinstance(value["serializedJSON"], str)
            or hashlib.sha256(value["serializedJSON"].encode()).hexdigest() != value["sha256"]
            or json.loads(value["serializedJSON"]) != expected):
        raise ValueError("Forget/index-fence child request lost its original byte seal")


def _positive_integer(value):
    return type(value) is int and value > 0


def _monotonic(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]+", value) is not None


def _process_graph(raw, context, *, process_pid, parent_pid):
    if (raw.get("pid") != process_pid or raw.get("ppid") != parent_pid
            or raw.get("fixtureBase") != context["stateDirectory"]
            or not isinstance(raw.get("children"), list) or not 1 <= len(raw["children"]) <= 64):
        raise ValueError("Forget/index-fence coordinator or child custody is detached")
    profile = context[PROFILE_KEY]
    graph = {process_pid: {"actor": "coordinator", "ppid": parent_pid, "instance": 0,
                           "clock": profile["actorClocks"]["coordinator"]}}
    generations, command_ids = {}, set()
    for child in raw["children"]:
        actor, instance, pid = child.get("actor"), child.get("instance"), child.get("pid")
        if (actor not in profile["actorClocks"] or actor == "coordinator"
                or not _positive_integer(pid) or pid in graph or child.get("ppid") != process_pid
                or type(instance) is not int or instance != generations.get(actor, 0) + 1
                or child.get("argv") != [profile["nodeRuntime"]["execPath"], str(ROOT / "equivalence" / ENTRY)]
                or not _monotonic(child.get("startedAtNs")) or not _monotonic(child.get("finishedAtNs"))
                or not _monotonic(child.get("reapedAtNs"))
                or int(child["startedAtNs"]) > int(child["finishedAtNs"])
                or int(child["finishedAtNs"]) > int(child["reapedAtNs"])
                or not isinstance(child.get("exit"), dict)
                or set(child["exit"]) != {"code", "signal"}
                or not isinstance(child.get("commands"), list)
                or not isinstance(child.get("stdout"), str) or not isinstance(child.get("stderr"), str)
                or child.get("fatal")):
            raise ValueError("Forget/index-fence child identity, ancestry, reap or settlement changed")
        generations[actor] = instance
        if child.get("ready") != {"type": "ready", "actor": actor, "pid": pid,
                                  "ppid": process_pid, "instance": instance}:
            raise ValueError("Forget/index-fence child never acknowledged its exact original request")
        for command in child["commands"]:
            request = command.get("request")
            command_id = command.get("id")
            if (not _positive_integer(command_id) or command_id in command_ids
                    or not isinstance(request, dict) or request.get("id") != command_id
                    or request.get("operation") != command.get("operation")
                    or request.get("label") != command.get("label")
                    or request.get("wallClockNowMs") not in {
                        profile["actorClocks"][actor], profile.get("recoveryNowMs")}
                    or not _monotonic(command.get("startedAtNs"))):
                raise ValueError("Forget/index-fence original child command identity or wall phase changed")
            command_ids.add(command_id)
            _seal(command.get("requestSeal"), request)
        request = {
            "kind": "forget-index-fence-child", "actor": actor, "instance": instance,
            "caseId": profile["caseId"], "input": raw["input"],
            "runtimeRoot": context["runtime"]["runtimeRoot"], "fixtureBase": context["stateDirectory"],
            "configPath": context["configPath"], "evidenceDirectory": context["evidenceDirectory"],
        }
        if child.get("request") != request:
            raise ValueError("Forget/index-fence child received undeclared source inputs")
        _seal(child.get("requestSeal"), request)
        clock = profile["actorClocks"][actor]
        located = False
        for observed in raw["steps"]:
            step = observed["step"]
            if step["operation"] in {"release-gate", "start-fresh-original-process"} and "wallClockNowMs" in step:
                clock = step["wallClockNowMs"]
            if int(observed["startedAtNs"]) <= int(child["startedAtNs"]) <= int(observed["finishedAtNs"]):
                located = True
                break
        if not located or clock not in {profile["actorClocks"][actor], profile.get("recoveryNowMs")}:
            raise ValueError("Forget/index-fence child was started outside its declared wall phase")
        graph[pid] = {"actor": actor, "ppid": process_pid, "instance": instance,
                      "clock": clock, "child": child}
    return graph


def _required_routes(child):
    operations = {command["operation"] for command in child["commands"]}
    main, workers = set(), set()
    if operations & {"acquire-original-owner", "original-sync", "public-memory-search", "public-memory-get"}:
        main.add("manager")
    if "prepare-real-host-inputs" in operations:
        main.add("producer")
    if "original-forget" in operations:
        main.add("forget")
    if "original-promotion" in operations:
        main.add("promotion")
    if operations & {"public-memory-search", "public-memory-get"}:
        main.add("tools")
    if "process-exit" in operations:
        main.add("state")
    if child["instance"] > 1 and "acquire-original-owner" in operations:
        main.add("reopen")
    if "original-sync" in operations:
        workers.update(("preparation", "publication"))
    if "public-memory-search" in operations:
        workers.add("retrieval")
    if operations & {"original-sync", "original-forget", "original-promotion",
                     "original-record-short-term-recalls", "capture-physical-state"}:
        workers.add("state")
    return main, workers


def validate_traces(directory, context, runtime, authority, *, process_pid, parent_pid, raw):
    """Authenticate each actual child/worker import and its unchanged executable."""
    validate_profile(context[PROFILE_KEY])
    if (set(context) != _CONTEXT_KEYS | {"_sha256"}
            or context["runtime"] != runtime or context["approvedNodeRuntime"] != authority
            or context[PROFILE_KEY]["nodeRuntime"] != authority
            or context["allowedLocal"] != _local_authority()):
        raise ValueError("Forget/index-fence traces require the exact independent context authority")
    originals = {(package["location"], file["path"]): file["sha256"]
                 for package in runtime["packages"] for file in package["files"]}
    local = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    graph = _process_graph(raw, context, process_pid=process_pid, parent_pid=parent_pid)
    files = sorted(Path(directory).iterdir())
    if not files or len(files) > 1024:
        raise ValueError("Missing or excessive actual forget/index-fence traces")
    total, seen, bootstraps, main_loads, worker_loads, local_loads = 0, {}, [], {}, {}, {}
    gate_rows = []
    for filename in files:
        if not _regular(filename) or not re.fullmatch(r"[1-9][0-9]*-[0-9]+\.jsonl", filename.name):
            raise ValueError("Aliased or unknown forget/index-fence trace")
        data = filename.read_bytes()
        total += len(data)
        if not data or not data.endswith(b"\n") or len(data) > 16 * 1024 * 1024 or total > 256 * 1024 * 1024:
            raise ValueError("Incomplete or excessive forget/index-fence trace bytes")
        rows = [json.loads(line) for line in data.splitlines()]
        first = rows[0]
        identity = graph.get(first.get("pid"))
        if (not identity or first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("ppid") != identity["ppid"] or first.get("actor") != identity["actor"]
                or type(first.get("instance")) is not int or first["instance"] != identity["instance"]
                or first.get("fetchDenied") is not True or first.get("providerMode") != "none"
                or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != local[str(ROOT / "equivalence" / PRELOAD)]
                or type(first.get("threadId")) is not int or first["threadId"] < 0
                or first.get("isMainThread") is not (first["threadId"] == 0)
                or filename.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Wrong forget/index-fence process, worker, context or executable")
        bootstraps.append(first)
        own = [row for row in rows if row.get("event") == BOOTSTRAP_EVENT]
        clock = own[0].get("clock") if len(own) == 1 else None
        bootstrap_now = clock.get("nowMs") if isinstance(clock, dict) else None
        allowed_worker_clocks = {context[PROFILE_KEY]["actorClocks"][identity["actor"]]}
        if "recoveryNowMs" in context[PROFILE_KEY]:
            allowed_worker_clocks.add(context[PROFILE_KEY]["recoveryNowMs"])
        # Main startup is bound to the actual child creation step. A later
        # original worker inherits its parent's declared current wall phase;
        # dispatch/event custody binds that exact phase in the independent guard.
        allowed_clock = (bootstrap_now == identity["clock"] if first["isMainThread"]
                         else bootstrap_now in allowed_worker_clocks)
        if (len(own) != 1 or own[0].get("profile") != context[PROFILE_KEY]
                or type(bootstrap_now) is not int or not allowed_clock
                or clock != {
                    "owner": "node:test", "apis": ["Date"], "nowMs": bootstrap_now,
                    "dateConstructorReplaced": True, "setTimeoutUnchanged": True,
                    "performanceNowUnchanged": True,
                }):
            raise ValueError("Forget/index-fence worker lost its declared Date-only capability")
        for row in rows[1:]:
            if (row.get("event") not in {"load", "resolve-native", BOOTSTRAP_EVENT, "fence-gate-enter"}
                    or row.get("pid") != first["pid"] or row.get("ppid") != first["ppid"]
                    or row.get("threadId") != first["threadId"] or row.get("actor") != first["actor"]
                    or type(row.get("instance")) is not int or row["instance"] != identity["instance"]):
                raise ValueError("Unknown, rejected or reassigned forget/index-fence trace event")
            if row["event"] == BOOTSTRAP_EVENT:
                continue
            if row["event"] == "fence-gate-enter":
                gate_rows.append(row)
                continue
            if row.get("kind") == "release":
                key = row.get("package"), row.get("path")
                if originals.get(key) != row.get("sha256"):
                    raise ValueError("An actual forget/index-fence release import changed")
                seen[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                target = main_loads if first["isMainThread"] else worker_loads
                target.setdefault(first["pid"] if first["isMainThread"] else (first["pid"], first["threadId"]), set()).add(row["path"])
            elif row.get("kind") == "oracle" and local.get(row.get("path")) == row.get("sha256"):
                if first["isMainThread"]:
                    local_loads.setdefault(first["pid"], set()).add(row["path"])
            else:
                raise ValueError("Forget/index-fence imported an undeclared local or source substitution")
    mains = [row for row in bootstraps if row["isMainThread"]]
    if len(mains) != len(graph) or {row["pid"] for row in mains} != set(graph):
        raise ValueError("Forget/index-fence omitted or duplicated an actual process bootstrap")
    for pid, identity in graph.items():
        if not {str(ROOT / "equivalence" / name) for name in (ENTRY, ACTOR)} <= local_loads.get(pid, set()):
            raise ValueError("An actual forget/index-fence process omitted its protected local caller")
        if pid == process_pid:
            continue
        main_routes, worker_routes = _required_routes(identity["child"])
        required = {*_ALWAYS_MAIN_ARTIFACTS,
                    *(path for route in main_routes for path in REQUIRED_MAIN_ARTIFACTS_BY_ROUTE[route])}
        missing = sorted(required - main_loads.get(pid, set()))
        if missing:
            raise ValueError(f"Actual forget/index-fence actor omitted required original main owners: {missing}")
        for route in worker_routes:
            if not any(worker_pid == pid and set(REQUIRED_WORKER_ARTIFACTS_BY_ROUTE[route]) <= paths
                       for (worker_pid, _), paths in worker_loads.items()):
                raise ValueError(f"Actual forget/index-fence actor omitted original worker route: {route}")
    receipts = {gate["name"]: gate["receipt"] for gate in raw["gates"] if "receipt" in gate}
    if len(gate_rows) != len(receipts):
        raise ValueError("Forget/index-fence gate trace is detached from its actual receipt")
    for row in gate_rows:
        receipt = receipts.get(row.get("name"))
        if receipt is None or {key: value for key, value in row.items() if key != "event"} != receipt:
            raise ValueError("Forget/index-fence gate trace differs from its actual held boundary")
    validate_release_sources(runtime, list(seen.values()))
    return {"bootstraps": bootstraps, "loaded": list(seen.values()), "gates": gate_rows,
            "traces": [{"name": filename.name, "sha256": digest(filename), "text": filename.read_text()}
                       for filename in files]}


def validate_raw(raw, case, result, context, *, process_pid, parent_pid):
    if (not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict)
            or raw[0].get("schemaVersion") != 1 or raw[0].get("kind") != "forget-index-fence-native-capture"
            or raw[0].get("engine") != "native" or raw[0].get("caseId") != case["id"]
            or raw[0].get("input") != case["input"] or raw[0].get("result") != result
            or raw[0].get("completed") is not True or raw[0].get("allChildrenReaped") is not True
            or raw[0].get("pid") != process_pid or raw[0].get("ppid") != parent_pid
            or raw[0].get("fixtureBase") != context["stateDirectory"]
            or not isinstance(raw[0].get("gates"), list) or not isinstance(raw[0].get("snapshots"), list)
            or not isinstance(raw[0].get("steps"), list)
            or [observed.get("step") for observed in raw[0]["steps"]] != case["input"]["steps"]):
        raise ValueError("Forget/index-fence custody is detached from its actual process, source or result")
    for observed in raw[0]["steps"]:
        if (not _monotonic(observed.get("startedAtNs")) or not _monotonic(observed.get("finishedAtNs"))
                or int(observed["startedAtNs"]) > int(observed["finishedAtNs"])):
            raise ValueError("Forget/index-fence schedule lacks actual monotonic step custody")
    _process_graph(raw[0], context, process_pid=process_pid, parent_pid=parent_pid)
    return raw[0]


def run_native_case(case, node, runtime, directory, *, timeout=180, checkout=None):
    """One immutable original attempt; retain failures and never retry a case."""
    case, wire = _validated_case(case)
    node = Path(node).resolve(strict=True)
    authority = prepare_model_node_authority(node)
    profile = prepare_profile(case, authority)
    source = Path(checkout or os.environ.get("MEMORY_EQ_REFERENCE_CHECKOUT", ROOT / "work/openclaw-v2026.9.9")).resolve(strict=True)
    bindings = prepare_forget_index_fence_bindings(source, Path(runtime["runtimeRoot"]))
    local = _local_authority()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    traces, evidence, state, gates = (directory / name for name in ("traces", "evidence", "state", "gates"))
    for folder in (traces, evidence, state, gates):
        folder.mkdir()
    context = {
        "schemaVersion": 1, "kind": "release-oracle-execution", "runtime": deepcopy(runtime),
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
        PROFILE_KEY: profile, "allowedLocal": local, "traceDirectory": str(traces),
        "evidenceDirectory": str(evidence), "stateDirectory": str(state),
        "configPath": str(state / "openclaw.json"), "gateDirectory": str(gates),
        "approvedReferenceSources": [], "fixtureSourceCaptures": [],
    }
    if set(context) != _CONTEXT_KEYS:
        raise ValueError("Forget/index-fence launcher constructed an unreviewed context capability")
    context_path, request_path = directory / "context.json", directory / "request.json"
    write_json(context_path, context)
    request_path.write_bytes(wire)
    env = {
        "PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
        "NODE_OPTIONS": f'--import={ROOT / "equivalence" / PRELOAD}',
        "MEMORY_EQ_RELEASE_CONTEXT": str(context_path), "MEMORY_EQ_FIF_ACTOR": "coordinator",
        "OPENCLAW_STATE_DIR": str(state), "OPENCLAW_CONFIG_PATH": context["configPath"],
    }
    argv = [str(node), str(ROOT / "equivalence" / ENTRY)]
    process_record = {
        "argv": argv, "cwd": str(ROOT), "environment": env,
        "requestPath": str(request_path), "requestSha256": digest(request_path),
        "contextPath": str(context_path), "contextSha256": digest(context_path),
        "parentPid": os.getpid(), "startedAtNs": str(time.monotonic_ns()),
        "sourceCheckout": str(source), "declarationAuthorityKind": bindings["kind"],
        "retryAllowed": False,
    }
    write_json(directory / "declaration-bindings.json", bindings)
    process = None
    try:
        with (directory / "stdout.json").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            try:
                process = subprocess.Popen(argv, env=env, cwd=ROOT, stdin=subprocess.PIPE,
                                           stdout=stdout, stderr=stderr, start_new_session=os.name == "posix")
                process_record["pid"] = process.pid
                process.communicate(wire, timeout=timeout)
            except subprocess.TimeoutExpired:
                process_record["timedOut"] = True
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.communicate()
                raise ValueError("Actual forget/index-fence caller timed out; complete streams retained without retry") from None
            finally:
                process_record.update(
                    returncode=process.returncode if process is not None else None,
                    finishedAtNs=str(time.monotonic_ns()),
                    stdoutPath=str(directory / "stdout.json"), stderrPath=str(directory / "stderr.log"),
                )
                write_json(directory / "process.json", process_record)
        stdout_path = directory / "stdout.json"
        returned = _read_json(stdout_path, limit=64 * 1024 * 1024)
        if (process.returncode or not isinstance(returned, dict) or set(returned) != {"id", "ok", "result"}
                or returned.get("id") != case["id"] or returned.get("ok") is not True):
            raise ValueError("Original forget/index-fence observation failed; complete streams retained without retry")
        raw = _read_json(evidence / "native-raw.json", limit=128 * 1024 * 1024)
        capture = validate_raw(raw, case, returned["result"], context,
                               process_pid=process.pid, parent_pid=os.getpid())
        trace = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority,
                                process_pid=process.pid, parent_pid=os.getpid(), raw=capture)
    except BaseException as error:
        process_record["observationFailure"] = {"name": type(error).__name__, "message": str(error)}
        raise
    finally:
        # Both success and failure reauthenticate all protected local modules and
        # the exact executable. This does not turn a failed run into a retry.
        try:
            _verify_unchanged(local, node, authority)
            if digest(context_path) != process_record["contextSha256"] or digest(request_path) != process_record["requestSha256"]:
                raise ValueError("Forget/index-fence immutable context or request changed during execution")
            process_record["protectedBytesUnchanged"] = True
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            process_record["protectedBytesUnchanged"] = False
            process_record["integrityError"] = {"name": type(error).__name__, "message": str(error)}
            raise
        finally:
            write_json(directory / "process.json", process_record)
    return {
        "kind": NATIVE_KIND, "results": [returned], "releaseSources": trace["loaded"],
        "releaseTrace": trace, "runtimeDiagnostics": raw, "evidenceDirectory": str(directory),
        "declarationBindings": bindings, "acceptancePointsAwarded": 0,
        "process": {
            **process_record, "stdoutSha256": digest(directory / "stdout.json"),
            "stderrSha256": digest(directory / "stderr.log"),
            "stdout": (directory / "stdout.json").read_text(),
            "stderr": (directory / "stderr.log").read_text(),
        },
    }
