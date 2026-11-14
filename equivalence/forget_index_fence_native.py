"""Closed multi-process original caller for the frozen forget/index-fence inputs.

The launcher authenticates custody and process/module authority. Independent
capture validation owns race semantics; this transport awards no acceptance.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import hashlib
from importlib import import_module
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time
import zlib

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
PROFILE_KEY = "forgetIndexFenceV2Profile"
BOOTSTRAP_EVENT = "forget-index-fence-v2-bootstrap"
PROFILE_KIND = "forget-index-fence-v2"
NATIVE_KIND = "official-release-forget-index-fence-v2"
ENTRY = "forget-index-fence-entry.mjs"
PRELOAD = "forget-index-fence-preload.mjs"
ACTOR = "forget-index-fence-runtime.mjs"
SOURCE_CLOCK = "forget-index-fence-source-clock.mjs"
LOCAL = (ENTRY, PRELOAD, ACTOR, SOURCE_CLOCK)
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
    return import_module("equivalence.forget_index_fence_v2")


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
    source_clock = case["input"]["clock"].get("sourceWriteClock")
    actors = case["input"]["actors"]
    if (type(base) is not int or not isinstance(source_clock, dict)
            or source_clock.get("protocol") != "owned-source-write-clock-v2"
            or not isinstance(source_clock.get("ticksByCall"), dict)
            or not isinstance(actors, dict) or not actors
            or len(actors) > 10 or {"coordinator", "observer"} & set(actors)
            or any(not isinstance(actor, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", actor)
                   for actor in actors)):
        raise ValueError("Forget/index-fence requires declared actor clocks and identities")
    profile = {
        "kind": PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
        "caseWireSha256": hashlib.sha256(wire).hexdigest(),
        "actorClocks": {"coordinator": base, "observer": base, **dict.fromkeys(actors, base)},
        "gates": deepcopy(case["input"]["gates"]), "nodeRuntime": authority,
        "sourceWriteClock": deepcopy(source_clock),
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
    try:
        exact = json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("Forget/index-fence profile is not an exact JSON capability") from error
    if (exact != json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False)
            or type(profile.get("acceptancePointsAwarded")) is not int):
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


# Installed source facts: these hashes identify the original helper route, not
# a fixture child or an authority inferred from a reported parent PID.
_INTEGRITY_CALLER = "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs"
_INTEGRITY_ENTRY = "dist/infra/sqlite-integrity.worker.js"
_INTEGRITY_ARTIFACT_HASHES = {
    _INTEGRITY_CALLER: "8a582f38f3e2ccbca248409dccf1507009d256843f2b684d7f59b6cbeb7eb09b",
    _INTEGRITY_ENTRY: "b884b1033d414cea5187d24ee066bce1eddfde6ed3096fadd15e79637f6279df",
    "dist/node-sqlite-DRQTiYwd.mjs": "5008332cd5a0ba99eae3194a790bff4979b5b05f99c2c8c69312d7471f200504",
    "dist/sqlite-busy-timeout-DYrW2wFu.mjs": "0fdc74e60a91cbc82e2505e455794bf2c4c211befdbbf38b3714ecce969e1243",
    "dist/sqlite-file-generation-Z_oSlnyK.mjs": "47fd0d5b69868fb71239992947a1d85f562f107415b75ca2588eb8f6541c5be5",
    "dist/sqlite-integrity-CkZDPF4-.mjs": "00d460b423d51eb3f0221712d8846199d0e149593aa76b96613be94d7ab265f1",
    "dist/sqlite-maintenance-cache-AYpxl8JZ.mjs": "ace110d1b2c93624554cedbdaeab1736275f0a933414ca79b520114816b23199",
    "dist/error-coercion-1P2One0X.mjs": "dc084c616cc292128c5ff39fc77cf2a5cf9487bd0e8339bb0a8aa215110646b6",
}
_INTEGRITY_CHILD_ARTIFACTS = tuple(path for path in _INTEGRITY_ARTIFACT_HASHES if path != _INTEGRITY_CALLER)
_CHILD_EVENTS = {"original-child-spawn", "original-child-message", "original-child-exit",
                 "original-child-os-exit", "original-child-error"}
_UNDEFINED = {"privateType": "undefined"}


def _same_protocol(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_protocol(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_protocol(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _v8_receipt(value):
    if (not isinstance(value, dict) or set(value) != {"v8Hex"}
            or not isinstance(value["v8Hex"], str) or not 2 <= len(value["v8Hex"]) <= 32 * 1024 * 1024
            or len(value["v8Hex"]) % 2 or re.fullmatch(r"[0-9a-f]+", value["v8Hex"]) is None):
        raise ValueError("Original integrity process lost its complete V8 carrier")


def _source_child_record(relative, context):
    return {"kind": "release", "package": "node_modules/openclaw", "path": relative,
            "sha256": _INTEGRITY_ARTIFACT_HASHES[relative],
            "absolutePath": str(Path(context["runtime"]["runtimeRoot"]) / relative)}


def _integrity_request(message, context):
    required = {"pathname", "databaseLabel", "identity", "busyTimeoutMs", "tables"}
    if (not isinstance(message, dict) or not required <= set(message)
            or set(message) - required not in (set(), {"reuse"})
            or not isinstance(message["pathname"], str) or not Path(message["pathname"]).is_absolute()
            or str(Path(message["pathname"])) != message["pathname"]
            or ".." in Path(message["pathname"]).parts
            or not Path(message["pathname"]).is_relative_to(Path(context["stateDirectory"]))
            or not isinstance(message["databaseLabel"], str) or not message["databaseLabel"]
            or type(message["busyTimeoutMs"]) is not int or message["busyTimeoutMs"] < 0
            or ("reuse" in message and message["reuse"] is not True)
            or not isinstance(message["identity"], dict) or set(message["identity"]) != {"dev", "ino", "size"}):
        raise ValueError("Original integrity request differs from its source-owned input schema")
    for value in message["identity"].values():
        if (not isinstance(value, dict) or set(value) != {"privateType", "value"}
                or value["privateType"] != "bigint" or not isinstance(value["value"], str)
                or re.fullmatch(r"0|[1-9][0-9]*", value["value"]) is None):
            raise ValueError("Original integrity request lost its native file identity")
    tables = message["tables"]
    if not _same_protocol(tables, _UNDEFINED):
        if not isinstance(tables, list) or any(
                not isinstance(row, dict) or set(row) != {"table", "check"}
                or not isinstance(row["table"], str) or not row["table"]
                or row["check"] not in {"integrity_check", "quick_check"} for row in tables):
            raise ValueError("Original integrity request changed its source-owned table checks")


def _integrity_result(message):
    if (not isinstance(message, dict) or type(message.get("ok")) is not bool
            or set(message) - {"ok", "checkElapsedMs", "tables", "error"}
            or (message["ok"] is True and "error" in message)):
        raise ValueError("Original integrity result differs from its source-owned result schema")
    if "checkElapsedMs" in message and (type(message["checkElapsedMs"]) not in (int, float)
            or not math.isfinite(message["checkElapsedMs"]) or message["checkElapsedMs"] < 0):
        raise ValueError("Original integrity timing is not a retained finite native duration")
    if message["ok"] is False:
        error = message.get("error")
        if (not isinstance(error, dict) or not {"name", "message", "code", "errcode"} <= set(error)
                or set(error) - {"name", "message", "code", "errcode", "cause"}
                or not isinstance(error["name"], str) or not isinstance(error["message"], str)):
            raise ValueError("Original integrity failure lost its native error fields")
    if "tables" in message:
        tables = message["tables"]
        if not isinstance(tables, list) or any(
                not isinstance(row, dict) or set(row) != {"table", "check", "elapsedMs"}
                or not isinstance(row["table"], str) or row["check"] not in {"integrity_check", "quick_check"}
                or type(row["elapsedMs"]) not in (int, float) or not math.isfinite(row["elapsedMs"])
                or row["elapsedMs"] < 0 for row in tables):
            raise ValueError("Original integrity result lost its per-table timing schema")


def _integrity_message_source(row, context, *, closing):
    caller = Path(context["runtime"]["runtimeRoot"]) / _INTEGRITY_CALLER
    paths = "|".join(re.escape(value) for value in (str(caller), caller.as_uri()))
    frame = r"(?:" + paths + r"):" + ("73" if closing else "293") + r":[1-9][0-9]*"
    if not isinstance(row.get("originalStack"), str) or re.search(frame, row["originalStack"]) is None:
        raise ValueError("Original integrity request has no pinned source send/close call site")


def _integrity_messages(rows, context):
    checks, active, phases, closed, previous = [], None, [], False, None
    for row in rows:
        _v8_receipt(row.get("message"))
        message = row.get("messageJSON")
        if row.get("direction") == "parent-to-child":
            if _same_protocol(message, {"type": "close"}):
                _integrity_message_source(row, context, closing=True)
                if active is not None or not checks or closed or not previous["request"].get("reuse") or previous["result"]["ok"] is not True:
                    raise ValueError("Original integrity close request has no completed reusable check")
                closed = True
                continue
            if active is not None or closed or (previous is not None and (
                    previous["request"].get("reuse") is not True or previous["result"]["ok"] is not True)):
                raise ValueError("Original integrity requests overlap or reuse an unretained process")
            _integrity_message_source(row, context, closing=False)
            _integrity_request(message, context)
            active, phases = {"request": message, "send": row}, []
        elif row.get("direction") == "child-to-parent":
            if active is None or closed:
                raise ValueError("Original integrity reply has no actual outstanding request")
            if isinstance(message, dict) and message.get("type") == "phase":
                if (set(message) != {"type", "phase"} or message["phase"] not in {"opening", "checking", "closing"}
                        or (phases + [message["phase"]]) not in (
                            ["opening"], ["opening", "checking"], ["opening", "closing"],
                            ["opening", "checking", "closing"])):
                    raise ValueError("Original integrity native phases changed order or repeated")
                phases.append(message["phase"])
            else:
                _integrity_result(message)
                if (not phases or (message["ok"] is True and phases != ["opening", "checking", "closing"])):
                    raise ValueError("Original integrity result arrived before its native check/close phases")
                active.update(result=message, receive=row, phases=list(phases))
                checks.append(active)
                previous, active, phases = active, None, []
        else:
            raise ValueError("Original integrity message has an unowned direction")
    if active is not None or not checks or (previous["request"].get("reuse") is True
                                          and previous["result"]["ok"] is True and not closed):
        raise ValueError("Original integrity process did not finish its actual request and close protocol")
    return checks


def _qualify_integrity_spawn(spawn, context, originals, graph):
    pid, thread, child_pid = spawn.get("pid"), spawn.get("threadId"), spawn.get("childPid")
    creator = graph.get(pid)
    profile = context[PROFILE_KEY]
    allowed_clocks = {profile["actorClocks"].get(spawn.get("actor"))}
    if "recoveryNowMs" in profile:
        allowed_clocks.add(profile["recoveryNowMs"])
    caller, entry = _source_child_record(_INTEGRITY_CALLER, context), _source_child_record(_INTEGRITY_ENTRY, context)
    frame_paths = (caller["absolutePath"], Path(caller["absolutePath"]).as_uri())
    frame = r"at assertSqliteIntegrityWithProcess \((?:" + "|".join(re.escape(value) for value in frame_paths) + r"):172:[1-9][0-9]*\)"
    if (not creator or "child" not in creator or type(thread) is not int or thread < 0
            or not _positive_integer(child_pid) or child_pid in graph
            or spawn.get("actor") != creator["actor"] or spawn.get("instance") != creator["instance"]
            or spawn.get("method") != "fork" or spawn.get("modulePath") != entry["absolutePath"]
            or spawn.get("sourceCaller") != caller or spawn.get("sourceEntrypoint") != entry
            or not isinstance(spawn.get("originalStack"), str) or re.search(frame, spawn["originalStack"]) is None
            or spawn.get("executable") != profile["nodeRuntime"]["execPath"]
            or spawn.get("argv") != [profile["nodeRuntime"]["execPath"], entry["absolutePath"]]
            or spawn.get("execArgv") != [] or spawn.get("cwd") != str(ROOT)
            or type(spawn.get("wallClockNowMs")) is not int or spawn["wallClockNowMs"] not in allowed_clocks
            or not isinstance(spawn.get("returnedChildRef"), str) or not spawn["returnedChildRef"]):
        raise ValueError("Unapproved original OS child: canonical integrity launch provenance is required")
    for path, expected in _INTEGRITY_ARTIFACT_HASHES.items():
        if originals.get(("node_modules/openclaw", path)) != expected:
            raise ValueError("Original integrity child source graph differs from pinned release bytes")
    environment = {
        "MEMORY_EQ_RELEASE_CONTEXT": str(Path(context["traceDirectory"]).parent / "context.json"),
        "MEMORY_EQ_FIF_ACTOR": creator["actor"], "MEMORY_EQ_FIF_INSTANCE": str(creator["instance"]),
        "MEMORY_EQ_FIF_CLOCK_NOW_MS": str(spawn["wallClockNowMs"]),
        "NODE_OPTIONS": f'--import={ROOT / "equivalence" / PRELOAD}',
        "OPENCLAW_STATE_DIR": context["stateDirectory"], "OPENCLAW_CONFIG_PATH": context["configPath"],
        "HOME": context["stateDirectory"], "OPENCLAW_HOME": context["stateDirectory"],
    }
    if not _same_protocol(spawn.get("environment"), environment):
        raise ValueError("Original integrity child did not inherit the closed actor capability")
    request = spawn.get("request")
    if not isinstance(request, dict) or set(request) != {"originalArgs", "argumentsJSON", "options", "optionsJSON"}:
        raise ValueError("Original integrity fork lost its complete source call arguments")
    _v8_receipt(request["originalArgs"])
    _v8_receipt(request["options"])
    options = request["optionsJSON"]
    required = {"execArgv", "serialization", "stdio", "timeout", "killSignal"}
    if (not isinstance(options, dict) or not required <= set(options)
            or set(options) - required not in (set(), {"signal"})
            or options["execArgv"] != [] or options["serialization"] != "advanced"
            or options["stdio"] != ["ignore", "ignore", "ignore", "ipc"] or options["killSignal"] != "SIGKILL"
            or (not _same_protocol(options["timeout"], _UNDEFINED)
                and (type(options["timeout"]) is not int or options["timeout"] <= 0))
            or not _same_protocol(request["argumentsJSON"], [
                {"privateType": "URL", "href": Path(entry["absolutePath"]).as_uri()}, [], options])):
        raise ValueError("Original integrity fork options differ from the pinned original call site")
    if "signal" in options:
        signal_ = options["signal"]
        if (not isinstance(signal_, dict) or set(signal_) != {"privateType", "aborted", "reason", "ref"}
                or signal_["privateType"] != "AbortSignal" or signal_["aborted"] is not False
                or not _same_protocol(signal_["reason"], _UNDEFINED) or not isinstance(signal_["ref"], str)):
            raise ValueError("Original integrity fork lost its actual caller signal state")
    return {"actor": creator["actor"], "ppid": pid, "instance": creator["instance"],
            "clock": spawn["wallClockNowMs"], "role": "sqlite-integrity", "creatorThreadId": thread,
            "launch": spawn}


def _child_receipt_json(line):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Original child receipt JSON contains duplicate members")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Original child receipt JSON contains a nonfinite number")

    return json.loads(line, object_pairs_hook=pairs, parse_constant=constant)


PASSIVE_EVENT_CODEC = "deflate-raw-native-event-v1"
PASSIVE_RAW_RECORD_LIMIT = 64 * 1024 * 1024
PASSIVE_RAW_TOTAL_LIMIT = 1024 * 1024 * 1024


def decode_passive_event(line, *, allow_legacy_plain=False, max_raw_bytes=PASSIVE_RAW_RECORD_LIMIT):
    """Decode storage only; plain events are an explicit diagnostic capability."""
    frame = _child_receipt_json(line)
    if not isinstance(frame, dict) or frame.get("codec") != PASSIVE_EVENT_CODEC:
        if allow_legacy_plain and isinstance(frame, dict) and "codec" not in frame:
            raw = line.encode("utf8") if isinstance(line, str) else line
            if len(raw) > max_raw_bytes:
                raise ValueError("Diagnostic passive event exceeds its decoded record bound")
            return frame, len(raw)
        raise ValueError("Native passive event requires its lossless storage codec")
    if (set(frame) != {"codec", "rawBytes", "rawSha256", "dataBase64"}
            or type(frame.get("rawBytes")) is not int
            or not 0 < frame["rawBytes"] <= min(PASSIVE_RAW_RECORD_LIMIT, max_raw_bytes)
            or not isinstance(frame.get("rawSha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", frame["rawSha256"]) is None
            or not isinstance(frame.get("dataBase64"), str)):
        raise ValueError("Native passive event codec envelope is malformed or excessive")
    try:
        compressed = base64.b64decode(frame["dataBase64"], validate=True)
        if base64.b64encode(compressed).decode("ascii") != frame["dataBase64"]:
            raise ValueError("Native passive event base64 is not canonical")
        inflater = zlib.decompressobj(wbits=-15)
        raw = inflater.decompress(compressed, frame["rawBytes"] + 1)
    except (binascii.Error, UnicodeError, zlib.error) as error:
        raise ValueError("Native passive event storage payload is corrupt") from error
    if (not inflater.eof or inflater.unused_data or inflater.unconsumed_tail
            or len(raw) != frame["rawBytes"]
            or hashlib.sha256(raw).hexdigest() != frame["rawSha256"]):
        raise ValueError("Native passive event storage payload lost its exact bytes")
    try:
        result = _child_receipt_json(raw.decode("utf8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Native passive event original JSON bytes are invalid") from error
    if not isinstance(result, dict):
        raise ValueError("Native passive event original record is not an object")
    return result, len(raw)


def _original_children(context, originals, graph):
    files, groups, all_event_files, total, decoded_total = [], {}, [], 0, 0
    for filename in sorted(Path(context["evidenceDirectory"]).glob("*-events.jsonl")):
        if not _regular(filename) or re.fullmatch(r"[1-9][0-9]*-[0-9]+-events\.jsonl", filename.name) is None:
            raise ValueError("Original child receipts used an unowned passive event file")
        wire = filename.read_bytes()
        total += len(wire)
        if (not wire or not wire.endswith(b"\n") or len(wire) > 64 * 1024 * 1024
                or total > 256 * 1024 * 1024 or len(all_event_files) >= 1024):
            raise ValueError("Original child receipts are incomplete or excessive")
        identity = None
        has_child, last_sequence, last_time = False, 0, -1
        for line in wire.splitlines():
            row, decoded_bytes = decode_passive_event(line, max_raw_bytes=PASSIVE_RAW_TOTAL_LIMIT - decoded_total)
            decoded_total += decoded_bytes
            if (not isinstance(row, dict) or not _positive_integer(row.get("pid"))
                    or type(row.get("threadId")) is not int or row["threadId"] < 0
                    or filename.name != f'{row["pid"]}-{row["threadId"]}-events.jsonl'
                    or not _positive_integer(row.get("sequence")) or row["sequence"] <= last_sequence
                    or not _monotonic(row.get("atNs")) or int(row["atNs"]) < last_time):
                raise ValueError("Original child passive receipts lost their actual process/order")
            actual_identity = {key: row.get(key) for key in ("pid", "ppid", "threadId", "actor", "instance")}
            if identity is not None and not _same_protocol(actual_identity, identity):
                raise ValueError("A passive event file mixed its actual process identity")
            identity = actual_identity
            last_sequence, last_time = row["sequence"], int(row["atNs"])
            if str(row.get("event", "")).startswith("original-child-"):
                if row["event"] not in _CHILD_EVENTS or row["event"] == "original-child-error":
                    raise ValueError("Unknown or failed original OS child lifecycle")
                creator = graph.get(row["pid"])
                if (not creator or "child" not in creator or row.get("ppid") != creator["ppid"]
                        or row.get("actor") != creator["actor"] or type(row.get("instance")) is not int
                        or row["instance"] != creator["instance"]
                        or not int(creator["child"]["startedAtNs"]) <= int(row["atNs"]) <= int(creator["child"]["finishedAtNs"])):
                    raise ValueError("Original child receipt borrowed an unowned creator process")
                if not isinstance(row.get("launchId"), str) or not row["launchId"]:
                    raise ValueError("Original child receipt lost its actual launch object")
                has_child = True
                key = row["pid"], row["threadId"], row["launchId"]
                if row["event"] == "original-child-spawn":
                    if key in groups:
                        raise ValueError("Original child launch receipt was duplicated")
                    groups[key] = {"spawn": row, "messages": [], "exits": [], "osExits": []}
                else:
                    if key not in groups:
                        raise ValueError("Original child message/close has no actual source launch")
                    group = groups[key]
                    if row.get("childPid") != group["spawn"].get("childPid"):
                        raise ValueError("Original child lifecycle changed its actual OS process")
                    group[{"original-child-message": "messages", "original-child-exit": "exits",
                           "original-child-os-exit": "osExits"}[row["event"]]].append(row)
        all_event_files.append(identity)
        if has_child:
            files.append({"name": filename.name, "sha256": hashlib.sha256(wire).hexdigest(), "text": wire.decode("utf8")})
    incidental, processes = {}, []
    for group in groups.values():
        spawn = group["spawn"]
        identity = _qualify_integrity_spawn(spawn, context, originals, graph)
        child_pid = spawn["childPid"]
        if child_pid in incidental or len(group["exits"]) != 1 or len(group["osExits"]) > 1:
            raise ValueError("Original integrity child was duplicated or never actually closed")
        close = group["exits"][0]
        for finished in [close, *group["osExits"]]:
            if (finished.get("code") != 0 or type(finished.get("code")) is not int
                    or finished.get("signal") is not None or type(finished.get("spawnSequence")) is not int
                    or finished["spawnSequence"] != spawn["sequence"]
                    or finished["sequence"] <= spawn["sequence"]
                    or int(finished["atNs"]) < int(spawn["atNs"])):
                raise ValueError("Original integrity child lacked an actual clean source-owned close")
        if group["osExits"] and group["osExits"][0]["sequence"] >= close["sequence"]:
            raise ValueError("Original integrity OS exit did not precede its actual close")
        if any(row["sequence"] >= close["sequence"] for row in group["messages"]):
            raise ValueError("Original integrity message arrived after actual child close")
        checks = _integrity_messages(group["messages"], context)
        incidental[child_pid] = identity
        processes.append({**group, "checks": checks})
    for row in all_event_files:
        identity = graph.get(row["pid"]) or incidental.get(row["pid"])
        if (not identity or row.get("actor") != identity["actor"]
                or row.get("ppid") != identity["ppid"] or type(row.get("instance")) is not int
                or row["instance"] != identity["instance"]):
            raise ValueError("A passive receipt is detached from the qualified original process graph")
    return incidental, {"processes": processes, "receiptFiles": files}


def validate_traces(directory, context, runtime, authority, *, process_pid, parent_pid, raw):
    """Authenticate each actual child/worker import and its unchanged executable."""
    validate_profile(context.get(PROFILE_KEY))
    if (set(context) != _CONTEXT_KEYS | {"_sha256"}
            or context["runtime"] != runtime or context["approvedNodeRuntime"] != authority
            or context[PROFILE_KEY]["nodeRuntime"] != authority
            or context["allowedLocal"] != _local_authority()):
        raise ValueError("Forget/index-fence traces require the exact independent context authority")
    originals = {(package["location"], file["path"]): file["sha256"]
                 for package in runtime["packages"] for file in package["files"]}
    local = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    graph = _process_graph(raw, context, process_pid=process_pid, parent_pid=parent_pid)
    incidental, original_children = _original_children(context, originals, graph)
    graph.update(incidental)
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
        if identity.get("role") == "sqlite-integrity" and first["threadId"] != 0:
            raise ValueError("Original integrity entry cannot borrow an unqualified worker route")
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
                if row["event"] == "load":
                    local_loads.setdefault((first["pid"], first["threadId"]), set()).add(row["path"])
            else:
                raise ValueError("Forget/index-fence imported an undeclared local or source substitution")
    mains = [row for row in bootstraps if row["isMainThread"]]
    if len(mains) != len(graph) or {row["pid"] for row in mains} != set(graph):
        raise ValueError("Forget/index-fence omitted or duplicated an actual process bootstrap")
    source_clock_path = str(ROOT / "equivalence" / SOURCE_CLOCK)
    for row in bootstraps:
        if source_clock_path not in local_loads.get((row["pid"], row["threadId"]), set()):
            raise ValueError("An actual forget/index-fence v2 bootstrap omitted its protected source clock module")
    for pid, identity in graph.items():
        if identity.get("role") == "sqlite-integrity":
            if (local_loads.get((pid, 0), set()) != {source_clock_path}
                    or not set(_INTEGRITY_CHILD_ARTIFACTS) <= main_loads.get(pid, set())):
                raise ValueError("Original integrity child omitted its pinned native check/close module graph")
            creator_thread = identity["creatorThreadId"]
            creator_imports = (main_loads.get(identity["ppid"], set()) if creator_thread == 0
                               else worker_loads.get((identity["ppid"], creator_thread), set()))
            if _INTEGRITY_CALLER not in creator_imports:
                raise ValueError("Original integrity child has no loaded canonical caller in its actual creator thread")
            continue
        if not {str(ROOT / "equivalence" / name) for name in (ENTRY, ACTOR)} <= local_loads.get((pid, 0), set()):
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
            "originalChildren": original_children,
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
