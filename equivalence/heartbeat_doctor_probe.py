"""First zero-credit whole-Doctor observations, before any Doctor SDK fixes.

Run each phase in fresh protected native and SDK processes. The adapter supplies
literal config/files and calls real public APIs. It does not resolve heartbeat
owners, implement preview/migration decisions, replace workers or repair text.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

from equivalence.heartbeat_doctor_authority import prepare_doctor_authority
from equivalence.heartbeat_doctor_bindings import MANIFEST_SHA256, prepare_doctor_bindings
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.release_runtime import prepare_release_runtime

ROOT = Path(__file__).resolve().parents[1]
CODEC_SHA256 = "86671a5b11a40cfcd5299c5a867a7c8f27898112055bdaa7c3bbc2eeccd54a38"
NOW = 2_000_000_000_000
ADAPTERS = ("equivalence/heartbeat-doctor-preload.mjs", "equivalence/heartbeat-doctor-runtime.mjs",
            "equivalence/heartbeat_doctor_probe.py", "equivalence/heartbeat_doctor_authority.py",
            "equivalence/heartbeat_doctor_bindings.py", "equivalence/heartbeat_dependency.py")
SDK_FILES = ("memory_core/heartbeat_migration.py", "memory_core/automation.py", "memory_core/heartbeat_ownership.py",
             "memory_core/heartbeat_scratch.py", "memory_core/_heartbeat_constants.py", "memory_core/bootstrap/_js.py",
             "memory_core/bootstrap/tools_md.py")
STORE_ISOLATION_FILES = ("equivalence/heartbeat_node_authority.py", "equivalence/heartbeat-preload.mjs",
                         "equivalence/heartbeat-runtime.mjs")


def phase(*operations, agents=None, host=None, custom=False):
    return {"nowMs": NOW, "agents": agents or [{"id": "main", "every": "30m"}],
            "host": host or {"agentIds": ["main"], "retainSource": False},
            "customStore": custom, "ops": [{"op": item} if isinstance(item, str) else item for item in operations]}


def build_doctor_cases():
    cases = []
    def add(name, files, phases=None, **extra):
        selected = deepcopy(phases or [phase("findings", "preview", "repair", "findings"), phase("findings", "repair")])
        for index, item in enumerate(selected):
            item["nowMs"] = NOW + index * 1000
        cases.append({"id": "doctor-" + name, "requirement": "heartbeat.scratch", "covers": [],
                      "files": files, "phases": selected, **extra})
    for name, content in [("ordinary", "- Check the release board\n"), ("empty", ""),
                          ("crlf", "- Check the board\r\n- Keep CRLF\r\n"), ("bom", "\ufeff- Checklist\n")]:
        add(name, {"HEARTBEAT.md": {"text": content}})
    add("no-file", {})
    add("operator-scratch", {"HEARTBEAT.md": {"text": "- Legacy source\n"}},
        [phase({"op": "seedScratch", "agentId": "main", "content": "- Operator instructions\n"}, "findings", "repair"), phase("findings", "repair")])
    add("explicit-unset", {"HEARTBEAT.md": {"text": "- Legacy source\n"}},
        [phase({"op": "seedScratch", "agentId": "main", "content": "present"},
               {"op": "seedScratch", "agentId": "main", "content": None}, "repair"), phase("findings", "repair")])
    agents = [{"id": "main", "every": "30m"}, {"id": "ops", "every": "30m"}]
    add("shared-enabled", {"HEARTBEAT.md": {"text": "- Shared checklist\n"}},
        [phase("findings", "repair", agents=agents, host={"agentIds": ["main", "ops"], "retainSource": False}),
         phase("findings", "repair", agents=agents, host={"agentIds": ["main", "ops"], "retainSource": False})])
    disabled = [{"id": "main", "every": "30m"}, {"id": "ops", "every": "0m"}]
    add("disabled-shared-retention", {"HEARTBEAT.md": {"text": "- Shared retained checklist\n"}},
        [phase("findings", "repair", "findings", agents=disabled, host={"agentIds": ["main"], "retainSource": True}),
         phase("findings", "repair", agents=agents, host={"agentIds": ["main", "ops"], "retainSource": False})])
    add("custom-store", {"HEARTBEAT.md": {"text": "- Custom partition\n"}},
        [phase("findings", "repair", custom=True), phase("findings", "repair", custom=True)])
    add("invalid-utf8", {"HEARTBEAT.md": {"bytes": [255, 254, 32, 98, 97, 100]}})
    add("too-large", {"HEARTBEAT.md": {"text": "a" * 262145}})
    add("contained-symlink", {"HEARTBEAT.md": {"symlink": "notes/checks.md"}, "notes/checks.md": {"text": "- Linked source\n"}})
    add("escaping-symlink", {"HEARTBEAT.md": {"symlink": "$outside"}})
    add("hard-link", {"HEARTBEAT.md": {"hardlink": "copy.md"}, "copy.md": {"text": "- Shared inode\n"}})
    add("directory", {"HEARTBEAT.md": {"directory": True}})
    add("unreadable-file", {"HEARTBEAT.md": {"text": "- Preserve unreadable bytes\n", "mode": 0}})
    for role in ("dead", "live", "zombie"):
        add(role + "-claim", {}, claim=role)
    add("orphan-claim", {"HEARTBEAT.md": {"text": "- Recreated source\n"}}, claim="dead")
    add("multiple-claims", {}, claim="multiple")
    return cases


def _error_attribute(value, seen, location):
    if isinstance(value, bytes):
        return {"type": "bytes", "base64": base64.b64encode(value).decode()}
    if isinstance(value, BaseException):
        return _error(value, seen, location)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if id(value) in seen:
        return {"type": "reference", "target": seen[id(value)], "constructorName": type(value).__name__}
    seen[id(value)] = location
    if isinstance(value, (tuple, list)):
        return [_error_attribute(item, seen, f"{location}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _error_attribute(item, seen, f"{location}.{key}") for key, item in value.items()}
    return {"type": type(value).__name__, "repr": repr(value)}


def _error(error, seen=None, location="$"):
    seen = {} if seen is None else seen
    if id(error) in seen:
        return {"type": "reference", "target": seen[id(error)], "constructorName": type(error).__name__}
    seen[id(error)] = location
    value = {"name": type(error).__name__, "message": str(error), "constructorName": type(error).__name__,
             "ownProperties": {**_error_attribute(vars(error), seen, location + ".ownProperties"),
                               "args": _error_attribute(error.args, seen, location + ".ownProperties.args"),
                               "stack": "".join(traceback.format_exception(error))}}
    for key in ("errno", "filename", "filename2"):
        if getattr(error, key, None) is not None:
            value["ownProperties"][key] = _error_attribute(getattr(error, key), seen, location + ".ownProperties." + key)
    if error.__cause__ is not None:
        value["cause"] = _error(error.__cause__, seen, location + ".cause")
    if error.__context__ is not None:
        value["context"] = _error(error.__context__, seen, location + ".context")
    value["suppressContext"] = error.__suppress_context__
    return value


def _capture_process(arguments, phase_directory, side, **options):
    # Own only this direct child. A forced stop is diagnostic failure handling,
    # never an inferred original canonical-close/state observation.
    timeout = options.pop("timeout", None)
    child = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except BaseException as error:
        receipt = {"pid": child.pid, "arguments": arguments, "reason": type(error).__name__,
                   "pollBeforeStop": child.poll(), "forcedStopRequested": False}
        cleanup_errors = []
        if receipt["pollBeforeStop"] is None:
            receipt["forcedStopRequested"] = True
            try:
                child.kill()
                receipt["killReturned"] = True
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        stdout, stderr = getattr(error, "output", None), getattr(error, "stderr", None)
        try:
            stdout, stderr = child.communicate(timeout=5)
            receipt["drained"] = True
        except BaseException as cleanup_error:
            cleanup_errors.append(cleanup_error)
            stdout = getattr(cleanup_error, "output", None) if getattr(cleanup_error, "output", None) is not None else stdout
            stderr = getattr(cleanup_error, "stderr", None) if getattr(cleanup_error, "stderr", None) is not None else stderr
            receipt["drained"] = False
        receipt["returncodeAfterDrain"] = child.poll()
        for stream, value in (("stdout.json", stdout), ("stderr.log", stderr)):
            if value is not None:
                (phase_directory / (side + "." + stream)).write_bytes(value)
        receipt["error"] = _error(error)
        receipt["cleanupErrors"] = [_error(item) for item in cleanup_errors]
        (phase_directory / (side + ".forced-stop.json")).write_text(json.dumps(receipt, ensure_ascii=True))
        raise
    (phase_directory / (side + ".stdout.json")).write_bytes(stdout)
    (phase_directory / (side + ".stderr.log")).write_bytes(stderr)
    process = subprocess.CompletedProcess(arguments, child.returncode, stdout, stderr)
    process.check_returncode()
    return process


def _tree(directory):
    directory = Path(directory)
    rows = []
    def entry(current, name):
        try:
            info = current.lstat()
        except OSError as error:
            rows.append({"path": name, "error": _error(error)})
            return
        kind = "symlink" if stat.S_ISLNK(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
        row = {"path": name, "mode": stat.S_IMODE(info.st_mode), "kind": kind,
               "physical": {"dev": info.st_dev, "ino": info.st_ino, "nlink": info.st_nlink, "size": info.st_size,
                            "mtimeMs": info.st_mtime_ns / 1_000_000, "ctimeMs": info.st_ctime_ns / 1_000_000}}
        rows.append(row)
        try:
            if kind == "file":
                row["bytes"] = {"type": "bytes", "base64": base64.b64encode(current.read_bytes()).decode()}
            elif kind == "symlink":
                row["target"] = os.readlink(current)
        except OSError as error:
            row["error"] = _error(error)
        if kind == "directory":
            try:
                children = sorted(current.iterdir())
            except OSError as error:
                rows.append({"path": name, "error": _error(error)})
                return
            for child in children:
                entry(child, child.relative_to(directory).as_posix())
    if not directory.exists() and not directory.is_symlink():
        return [{"path": ".", "kind": "absent"}]
    entry(directory, ".")
    return rows


def sdk_doctor_phase(request):
    import memory_core
    from memory_core.automation import FileAutomationStore
    from memory_core.heartbeat_migration import (
        migrate_heartbeat_md, heartbeat_md_migration_findings, heartbeat_migration_archive_dir,
    )
    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise ValueError("Doctor baseline imported a different SDK source tree")
    root, input_value = Path(request["fixtureDirectory"]), request["input"]
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    store = FileAutomationStore(workspace)
    raw = {"fixtureDirectory": str(root), "hostMapping": input_value["host"], "calls": [], "snapshots": [],
           "pid": os.getpid(), "sourceBuildReproduced": False,
           "clock": {"owner": "unittest.mock", "target": "memory_core.heartbeat_migration.time.time", "nowMs": input_value["nowMs"]}}
    def snapshot():
        monitors = {agent["id"]: value.to_json() if (value := store.read_heartbeat_monitor_scratch(agent["id"])) is not None
                    else {"type": "undefined"} for agent in input_value["agents"]}
        return {"monitors": monitors, "sourceTree": _tree(workspace), "archiveTree": _tree(heartbeat_migration_archive_dir(workspace))}
    with patch("memory_core.heartbeat_migration.time.time", return_value=input_value["nowMs"] / 1000):
        raw["snapshots"].append(snapshot())
        for operation in input_value["ops"]:
            call = {"operation": operation, "clockMs": int(time.time() * 1000)}
            raw["calls"].append(call)
            try:
                if operation["op"] == "findings":
                    call["request"] = {"root": str(workspace), "agentIds": input_value["host"]["agentIds"],
                                       "retain_source": input_value["host"]["retainSource"]}
                    call["result"] = [finding.to_json() for agent in input_value["host"]["agentIds"]
                        for finding in heartbeat_md_migration_findings(workspace, agent_id=agent,
                            retain_source=input_value["host"]["retainSource"])]
                elif operation["op"] in {"preview", "repair"}:
                    arguments = {"agent_ids": input_value["host"]["agentIds"],
                                 "retain_source": input_value["host"]["retainSource"], "now_ms": input_value["nowMs"]}
                    if operation["op"] == "preview":
                        # Actual unsupported public input, not an invented local preview.
                        arguments["should_repair"] = False
                    call["request"] = {"root": str(workspace), **arguments}
                    returned = migrate_heartbeat_md(workspace, store, **arguments)
                    call["result"] = {"changes": list(returned.changes), "warnings": list(returned.warnings)}
                else:
                    owner = store.enroll_heartbeat_monitor(operation["agentId"])
                    call["preparation"] = asdict(owner)
                    call["request"] = {"agentId": operation["agentId"], "jobId": owner.job_id,
                                       "content": operation["content"], "nowMs": input_value["nowMs"]}
                    call["result"] = store.write_job_scratch(operation["agentId"], owner.job_id, operation["content"],
                                                             now_ms=input_value["nowMs"]).to_json()
            except Exception as error:
                call["error"] = _error(error)
            call["stateAtReturn"] = {"storePath": str(store.path),
                "bytes": {"type": "bytes", "base64": base64.b64encode(store.path.read_bytes()).decode()} if store.path.exists() else None}
            raw["snapshots"].append(snapshot())
    raw["fixtureTreeAfterClose"] = _tree(root)
    result = {"operations": [{"error": call["error"]} if "error" in call else call["result"] for call in raw["calls"]],
              "snapshots": raw["snapshots"]}
    return {"kind": "heartbeat-doctor-observation", "covers": [], "result": result, "raw": raw}


def _documents():
    values = {}
    for name, expected in [("heartbeat-doctor-bindings.proposal.json", MANIFEST_SHA256),
                           ("heartbeat-doctor-codec.proposal.json", CODEC_SHA256),
                           ("heartbeat-doctor-codec.proposal.initial.json", "284a9059aa04e09ab53e7b91a0dc806ff4b1f4def9aebb39028eb4f8c1352e52"),
                           ("heartbeat-doctor-bindings.proposal.initial.json", "1f572b21305684bae8b684d510f3cd9666f83f16e920262591f828ec71b6f29a")]:
        raw = (ROOT / "equivalence" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("A separately approved Doctor declaration/codec document changed")
        values[name] = {"sha256": expected, "bytes": len(raw), "document": json.loads(raw)}
    return values


def _identity(names):
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def _runtime(checkout, cache):
    value = prepare_release_runtime(checkout, cache)
    extra = prepare_heartbeat_dependency(checkout, cache, ROOT / ".reference/heartbeat-dependencies/archives/croner-10.0.1.tgz")
    if len(value["packages"]) != 83 or extra["archiveSha256"] != "d6d93c286125fed567b986a576ff1daa74e72d56bb63fe28248ca17cfcb00cee" or extra["filesSha256"] != "dbf132f1899f1bbb92ec5f8fcc8519a7569337139c0004292862eeab87ce38e1":
        raise ValueError("Doctor private84 installation changed its complete authenticated package set")
    return {**value, "packages": [*value["packages"], extra]}


def _root_comparison(value, root):
    if isinstance(value, dict):
        if value.get("type") in {"bytes", "Buffer", "Uint8Array", "ArrayBuffer"} and "base64" in value:
            return deepcopy(value)
        return {key: _root_comparison(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_root_comparison(item, root) for item in value]
    if isinstance(value, str):
        return re.sub(r"(^|[\s'\"`\[(:=])" + re.escape(str(root)) + r"(?=/|$)",
                      lambda match: match.group(1) + "<FIXTURE>", value)
    return value


def _fixture(root, files, claim_pids):
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (root / "outside.md").write_bytes(b"- Outside target preserved\n")
    for name, item in files.items():
        target = workspace / name
        if target.is_absolute() and not target.is_relative_to(workspace) or ".." in Path(name).parts:
            raise ValueError("Doctor source fixture escapes its owned workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        if "hardlink" in item:
            continue
        if "directory" in item:
            target.mkdir(exist_ok=True)
        elif "symlink" in item:
            target.symlink_to(root / "outside.md" if item["symlink"] == "$outside" else item["symlink"])
        else:
            target.write_bytes(bytes(item["bytes"]) if "bytes" in item else item["text"].encode("utf-8"))
            if "mode" in item:
                target.chmod(item["mode"])
                if item["mode"] == 0 and os.access(target, os.R_OK):
                    raise ValueError("The declared chmod fixture is readable under this actual process identity")
    for name, item in files.items():
        if "hardlink" in item:
            os.link(workspace / item["hardlink"], workspace / name)
    content = b"- Interrupted source claim\n"
    for ordinal, pid in enumerate(claim_pids):
        suffix = hashlib.sha256(content + (str(ordinal).encode() if ordinal else b"")).hexdigest()[:12]
        (workspace / f"HEARTBEAT.md.doctor-importing-{pid}-{suffix}").write_bytes(content)


def _claims(role):
    if role is None:
        return [], [], lambda: None
    if role == "live":
        process = subprocess.Popen([sys.executable, "-c", "import sys;sys.stdin.readline()"], stdin=subprocess.PIPE,
                                   env={"PATH": os.defpath, "LANG": "C.UTF-8", "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": ""})
        return [process.pid], [], lambda: (process.terminate(), process.wait(timeout=10))
    if role == "zombie":
        if sys.platform != "linux":
            raise ValueError("The declared Doctor zombie fixture requires real Linux process state")
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = Path(f"/proc/{pid}/status").read_text()
            if re.search(r"^State:\s+Z", status, re.M) and re.search(r"^Threads:\s+1$", status, re.M):
                return [pid], [], lambda: os.waitpid(pid, 0)
            time.sleep(0.01)
        os.waitpid(pid, 0)
        raise ValueError("The fixture did not establish an actual single-thread zombie")
    count = 2 if role == "multiple" else 1
    pids = []
    for _ in range(count):
        process = subprocess.Popen([sys.executable, "-c", "pass"], env={"PATH": os.defpath, "LANG": "C.UTF-8"})
        process.wait(timeout=10)
        if Path(f"/proc/{process.pid}").exists():
            raise ValueError("The exited fixture PID was reused before claim setup")
        pids.append(process.pid)
    return pids, [], lambda: None


def _pid_status(pids):
    values = []
    for pid in pids:
        path = Path(f"/proc/{pid}/status")
        try:
            values.append({"pid": pid, "status": path.read_text()})
        except FileNotFoundError:
            values.append({"pid": pid, "status": "absent"})
    return values


def _require_claim_role(role, observed):
    for item in observed:
        status = item["status"]
        if role in {"dead", "multiple"} and status != "absent":
            raise ValueError("The declared dead claim PID was reused")
        if role == "live" and (status == "absent" or re.search(r"^State:\s+Z", status, re.M)):
            raise ValueError("The declared live claim owner is no longer live")
        if role == "zombie" and (not re.search(r"^State:\s+Z", status, re.M) or not re.search(r"^Threads:\s+1$", status, re.M)):
            raise ValueError("The declared claim owner no longer has actual single-thread zombie state")


def _validate_public_observation(observation, input_value):
    if (set(observation) != {"kind", "covers", "result", "raw"} or
            observation["kind"] != "heartbeat-doctor-observation" or observation["covers"] != [] or
            set(observation["result"]) != {"operations", "snapshots"}):
        raise ValueError("Doctor changed its exact public observation envelope")
    raw = observation["raw"]
    if ([call["operation"] for call in raw["calls"]] != input_value["ops"] or
            len(raw["snapshots"]) != len(input_value["ops"]) + 1 or
            any(("error" in call) == ("result" in call) for call in raw["calls"]) or
            observation["result"]["operations"] != [{"error": call["error"]} if "error" in call else call["result"] for call in raw["calls"]] or
            observation["result"]["snapshots"] != raw["snapshots"]):
        raise ValueError("Doctor omitted or changed a complete actual input/result/snapshot observation")


def _validate_decoded_events(trace_events, decoded_rows):
    expected = {}
    metadata = {"trace", "line", "event", "messageType", "targetThreadId", "field", "bytes"}
    for filename, events in trace_events.items():
        for number, event in enumerate(events, 1):
            if event["event"] not in {"worker-send", "worker-reply"}:
                continue
            message = event["message"]
            if (event["event"] == "worker-send" and message.get("type") == "execute" and
                    (not isinstance(message.get("input"), dict) or not isinstance(message["input"].get("base64"), str))):
                raise ValueError("A real Doctor execute command lacks its complete encoded input")
            for field in ("input", "value", "preparation"):
                encoded = message.get(field)
                if isinstance(encoded, dict) and isinstance(encoded.get("base64"), str):
                    expected[(filename, number, field)] = {
                        "trace": filename, "line": number, "event": event["event"],
                        "messageType": message.get("type", {"type": "undefined"}),
                        "targetThreadId": event["targetThreadId"], "field": field, "bytes": encoded,
                    }
    seen = set()
    for decoded in decoded_rows:
        if (not isinstance(decoded, dict) or type(decoded.get("line")) is not int or
                not isinstance(decoded.get("trace"), str) or not isinstance(decoded.get("field"), str) or
                set(decoded) not in (metadata | {"value"}, metadata | {"error"})):
            raise ValueError("Doctor supplied an incomplete or extra decoded-event envelope")
        key = (decoded["trace"], decoded["line"], decoded["field"])
        if key in seen or key not in expected:
            raise ValueError("Doctor duplicated or added a decoded transport event")
        seen.add(key)
        if any(decoded[name] != value for name, value in expected[key].items()):
            raise ValueError("Doctor decoded bytes are not bound to their actual original transport event")
    if seen != set(expected):
        raise ValueError("Doctor omitted an actual encoded transport event from decoding")


def validate_execution(phase_directory, context, native):
    request = json.loads(Path(context["requestPath"]).read_text())
    input_value = request["input"]
    _validate_public_observation(native, input_value)
    if (native["raw"]["sourceBuildReproduced"] is not False or native["raw"]["gatewayMutationContextInstalled"] is not False or
            native["raw"]["nowMs"] != input_value["nowMs"]):
        raise ValueError("Doctor omitted or changed a complete actual input/result observation")
    for call in native["raw"]["calls"]:
        op = call["operation"]["op"]
        if call["clockMs"] != input_value["nowMs"]:
            raise ValueError("Doctor per-call clock changed")
        actual_request = call["request"]
        if actual_request["cfg"] != native["raw"]["cfg"]:
            raise ValueError("Doctor did not retain its literal complete pre-call config")
        if op in {"repair", "preview"} and (set(actual_request) != {"cfg", "env", "shouldRepair"} or
                actual_request["shouldRepair"] != (op == "repair") or actual_request["env"] != native["raw"]["env"]):
            raise ValueError("Doctor did not execute the declared whole original repair-state arguments")
        if "stateAtReturn" not in call:
            raise ValueError("Doctor lacks its immediate synchronous return-cut state")
    for observed in [native["raw"]["stateBeforeCalls"], *[call["stateAtReturn"] for call in native["raw"]["calls"]],
                     native["raw"]["stateAfterCanonicalClose"]]:
        for record in observed:
            if "error" in record or "closeError" in record or any("error" in table for table in record.get("tables", [])):
                raise ValueError("Doctor readonly state observation failed to retain complete actual rows/bytes")
            if "schema" in record and (record.get("queryOnly") != {"query_only": 1} or record.get("closed") is not True):
                raise ValueError("Doctor state observer was not a completed actual readonly connection")
    allowed = {(package["location"], file["path"]): file["sha256"] for package in context["runtime"]["packages"] for file in package["files"]}
    locals_map = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    digest = hashlib.sha256((phase_directory / "context.json").read_bytes()).hexdigest()
    all_events, threads, trace_events = [], {}, {}
    for file in sorted((phase_directory / "traces").glob("*.jsonl")):
        data = file.read_bytes()
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("A Doctor thread trace exceeded its bound")
        events = [json.loads(line) for line in data.splitlines()]
        trace_events[file.name] = events
        if not events or events[0]["event"] != "bootstrap" or sum(event["event"] == "bootstrap" for event in events) != 1:
            raise ValueError("Every actual Doctor thread needs one authenticated bootstrap")
        boot = events[0]
        if (boot["node"] != context["capability"]["node"] or boot["contextSha256"] != digest or
                boot["requestSha256"] != context["requestSha256"] or boot["profile"] != "heartbeat-scratch-doctor" or
                boot["preloadSha256"] != locals_map[str(ROOT / ADAPTERS[0])] or
                boot["clock"] != {"owner": "node:test", "apis": ["Date"], "nowMs": native["raw"]["nowMs"],
                    "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "setIntervalUnchanged": True,
                    "performanceNowUnchanged": True}):
            raise ValueError("Doctor thread changed Node, context, request or Date-only clock")
        expected_entry = ROOT / ADAPTERS[1] if boot["isMainThread"] else Path(context["runtime"]["runtimeRoot"]) / "dist/infra/sqlite-store.worker.js"
        if (boot["entry"] != str(expected_entry) or boot["pid"] != native["raw"]["pid"] or
                (boot["isMainThread"] != (boot["threadId"] == 0)) or
                (not boot["isMainThread"] and boot["execArgv"] != []) or
                boot["processEnv"].get("MEMORY_EQ_DOCTOR_CONTEXT") != str(phase_directory / "context.json") or
                boot["processEnv"].get("NODE_OPTIONS") != "--import=" + (ROOT / ADAPTERS[0]).as_uri() or
                boot["processEnv"].get("OPENAI_API_KEY") != "" or boot["processEnv"].get("OPENROUTER_API_KEY") != "" or
                boot["processEnv"].get("MEMORY_EQ_HEARTBEAT_CONTEXT") or boot["processEnv"].get("MEMORY_EQ_RELEASE_CONTEXT")):
            raise ValueError("Doctor carrier entry or actual inherited process environment changed")
        threads[boot["threadId"]] = events
        for event in events[1:]:
            if event["event"] in {"network-denied", "rejected"}:
                raise ValueError("Doctor trace contains a rejected authority or network attempt")
            if event["event"] in {"load", "native-load"}:
                if event.get("kind") == "official-release":
                    if allowed.get((event["package"], event["path"])) != event["sha256"]:
                        raise ValueError("A Doctor loaded artifact differs from authenticated package bytes")
                elif locals_map.get(event.get("path")) != event.get("sha256"):
                    raise ValueError("A Doctor adapter changed during import")
            elif event["event"] not in {"worker-send", "worker-reply", "worker-exit", "worker-send-return", "worker-send-error",
                                        "worker-emit-return", "port-send", "port-send-return", "port-send-error",
                                        "worker-terminate", "worker-terminate-return", "worker-terminate-error"}:
                raise ValueError("Doctor trace contains an undeclared observer event")
        all_events.extend(events)
    if 0 not in threads or len(threads) > 2:
        raise ValueError("Doctor permits exactly its main thread and at most one direct carrier")
    main_loaded = {event.get("path") for event in threads[0] if event["event"] == "load"}
    if not {"dist/doctor-heartbeat-scratch-migration-DZDMSbFc.mjs", "dist/doctor-heartbeat-cadence-migration-B8HOzYOl.mjs",
            "dist/service-u8zoxec7.mjs", "dist/scratch-store-BsjpiVxl.mjs"} <= main_loaded:
        raise ValueError("Doctor did not import its required unchanged whole caller owners")
    requested = any(call["operation"]["op"] in {"repair", "seedScratch"} for call in native["raw"]["calls"])
    workers = set(threads) - {0}
    if bool(workers) != requested:
        raise ValueError("Doctor preview/findings must have no worker; repair must use the actual original carrier")
    for worker in workers:
        loaded = {event.get("path") for event in threads[worker] if event["event"] == "load"}
        if not {"dist/infra/sqlite-store.worker.js", "dist/state/openclaw-state.worker.js",
                "dist/openclaw-state-worker-runtime-DsFyroJI.mjs", "dist/runtime-maintenance.worker-obG_otbc.mjs"} <= loaded:
            raise ValueError("The real Doctor carrier did not load its required original backend owners")
        if not any(event["event"] == "worker-send" and event["targetThreadId"] == worker for event in threads[0]):
            raise ValueError("The actual Doctor parent did not dispatch to its observed carrier")
        exits = [event for event in threads[0] if event["event"] == "worker-exit" and event["targetThreadId"] == worker]
        terminations = [event for event in threads[0] if event["event"] == "worker-terminate-return" and event["targetThreadId"] == worker]
        if (len(exits) != 1 or len(terminations) != 1 or exits[0]["code"] != terminations[0]["code"] or
                not any(event["event"] == "worker-terminate" and event["targetThreadId"] == worker for event in threads[0])):
            raise ValueError("The actual Doctor carrier lacks matching original terminate/exit receipts")
    requests, replies = {}, {}
    for event in threads[0]:
        if event["event"] not in {"worker-send", "worker-reply"}:
            continue
        message = event["message"]
        if event["event"] == "worker-reply" and message.get("status") == "memory":
            continue
        identity = (event["targetThreadId"], message.get("id"))
        if type(identity[1]) is not int or identity[1] < 0 or identity[0] not in workers:
            raise ValueError("Doctor worker RPC has no literal owned thread/request identity")
        bucket = requests if event["event"] == "worker-send" else replies
        if identity in bucket:
            raise ValueError("Doctor worker RPC identity was reused or staged without a reviewed bounded input")
        bucket[identity] = message
        if event["event"] == "worker-send":
            if message["type"] not in {"open", "execute", "close"}:
                raise ValueError("The first literal Doctor packet requires ordinary unchunked original RPC")
            if message["type"] == "open":
                expected_backend = (Path(context["runtime"]["runtimeRoot"]) / "dist/state/openclaw-state.worker.js").as_uri()
                if message.get("moduleUrl") != expected_backend:
                    raise ValueError("Doctor carrier opened a different backend module")
    if set(requests) != set(replies):
        raise ValueError("Doctor left an actual worker request/reply unmatched")
    for identity, request_message in requests.items():
        reply = replies[identity]
        if type(reply.get("ok")) is not bool:
            raise ValueError("Doctor worker returned no actual success/refusal result")
        if request_message["type"] == "close" and reply["ok"] is not True:
            raise ValueError("Doctor original backend close was actually refused")
    if requested and not any(message["type"] == "close" for message in requests.values()):
        raise ValueError("Doctor did not send the original owned actor close")
    _validate_decoded_events(trace_events, native["raw"]["workerDecoded"])
    commands = []
    for event in native["raw"]["workerDecoded"]:
        if event["event"] == "worker-send" and event["field"] == "input" and event["messageType"] == "execute":
            if "error" in event or not isinstance(event.get("value"), dict) or "type" not in event["value"]:
                raise ValueError("A real Doctor command could not be completely decoded")
            commands.append(event["value"]["type"])
    if any(command not in {"cron.loadMutable", "cron.scheduleUnowned", "cron.saveChanges"} for command in commands):
        raise ValueError("Doctor executed an unapproved actor command")
    if requested and not {"cron.loadMutable", "cron.scheduleUnowned"} <= set(commands):
        raise ValueError("Doctor bypassed its original CronService list/maintenance path")
    if requested and request["phase"] == 0 and "cron.saveChanges" not in commands:
        raise ValueError("A fresh Doctor monitor was not persisted through the actual original async save path")
    if requested:
        settlements = [event for event in all_events if event["event"] == "port-send" and isinstance(event["message"], dict) and
                       event["message"].get("kind") == "native-settlement"]
        if not settlements or any(event["message"]["settlement"]["kind"] != "completed" for event in settlements):
            raise ValueError("Doctor lacks actual completed private-port native settlement receipts")
        if request["phase"] == 0 and not any(event["event"] == "port-send" and isinstance(event["message"], dict) and
                event["message"].get("kind") == "native-commit" for event in all_events):
            raise ValueError("Doctor async native save lacks its actual private-port commit receipt")
    if "error" in native["raw"]["close"] or native["raw"]["close"]["export"] != "closeOpenClawStateDatabaseAsync":
        raise ValueError("Doctor canonical owned database cleanup did not complete")
    return {"threads": sorted(threads), "events": len(all_events), "commands": commands}


def run(checkout, cache, node, output, selected=None):
    output.mkdir(parents=True, exist_ok=False)
    documents = _documents()
    runtime = _runtime(checkout, cache)
    capability = prepare_doctor_authority(node)
    bindings = prepare_doctor_bindings(checkout, Path(runtime["runtimeRoot"]))
    identities = _identity((*ADAPTERS, *SDK_FILES, *STORE_ISOLATION_FILES))
    before = {"runtime": runtime, "capability": capability, "bindings": bindings, "documents": documents, "ownedFiles": identities}
    (output / "authentication-before.json").write_text(json.dumps(before))
    cases = [case for case in build_doctor_cases() if selected is None or case["id"] in selected]
    if not cases:
        raise ValueError("No literal Doctor case was selected")
    (output / "cases.json").write_text(json.dumps(cases, ensure_ascii=True, indent=2))
    rows = []
    try:
        for case in cases:
            directory = output / case["id"]; directory.mkdir()
            pids, _unused, cleanup = _claims(case.get("claim"))
            try:
                for side in ("native", "sdk"):
                    _fixture(directory / (side + "-fixture"), case["files"], pids)
                phase_rows = []
                for ordinal, input_value in enumerate(case["phases"]):
                    phase_directory = directory / str(ordinal); phase_directory.mkdir(); (phase_directory / "traces").mkdir()
                    observed_pids = _pid_status(pids)
                    _require_claim_role(case.get("claim"), observed_pids)
                    (phase_directory / "claim-processes-before.json").write_text(json.dumps(observed_pids))
                    request = {"kind": "heartbeat-doctor-sequence", "phase": ordinal, "input": input_value,
                               "fixtureDirectory": str(directory / "native-fixture")}
                    request_path = phase_directory / "native-input.json"; request_path.write_text(json.dumps(request, ensure_ascii=True))
                    context = {"kind": "heartbeat-doctor-execution", "providerMode": "none", "fetchPolicy": "deny", "capability": capability,
                        "runtime": runtime, "requestPath": str(request_path), "requestSha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                        "traceDirectory": str(phase_directory / "traces"), "bindingsSha256": MANIFEST_SHA256, "codecSha256": CODEC_SHA256,
                        "allowedLocal": [{"path": str(ROOT / name), "sha256": identities[name]} for name in ADAPTERS[:2]]}
                    context_path = phase_directory / "context.json"; context_path.write_text(json.dumps(context))
                    environment = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
                                   "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": "", "MEMORY_EQ_DOCTOR_CONTEXT": str(context_path),
                                   "NODE_OPTIONS": "--import=" + (ROOT / ADAPTERS[0]).as_uri()}
                    native_process = _capture_process([str(node), str(ROOT / ADAPTERS[1]), str(request_path)], phase_directory, "native",
                                                      cwd=ROOT, timeout=60, env=environment)
                    native = json.loads(native_process.stdout)
                    execution = validate_execution(phase_directory, context, native)
                    sdk_request = {**request, "fixtureDirectory": str(directory / "sdk-fixture")}
                    sdk_path = phase_directory / "sdk-input.json"; sdk_path.write_text(json.dumps(sdk_request, ensure_ascii=True))
                    sdk_process = _capture_process([sys.executable, "-m", "equivalence.heartbeat_doctor_probe", "--sdk-phase", str(sdk_path)],
                        phase_directory, "sdk", cwd=ROOT, timeout=60,
                        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "PYTHONPATH": str(ROOT), "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": ""})
                    sdk = json.loads(sdk_process.stdout)
                    _validate_public_observation(sdk, input_value)
                    observed_pids = _pid_status(pids)
                    _require_claim_role(case.get("claim"), observed_pids)
                    (phase_directory / "claim-processes-after.json").write_text(json.dumps(observed_pids))
                    native_compared = _root_comparison(native["result"], directory / "native-fixture")
                    sdk_compared = _root_comparison(sdk["result"], directory / "sdk-fixture")
                    phase_rows.append({"phase": ordinal, "matches": native_compared == sdk_compared, "execution": execution,
                                       "native": native_compared, "sdk": sdk_compared, "nativePid": native["raw"]["pid"], "sdkPid": sdk["raw"]["pid"]})
                if (len({item["nativePid"] for item in phase_rows}) != len(phase_rows) or
                        len({item["sdkPid"] for item in phase_rows}) != len(phase_rows)):
                    raise ValueError("Doctor reconstruction phases must use fresh actual native and SDK processes")
                rows.append({"id": case["id"], "covers": [], "matches": all(item["matches"] for item in phase_rows), "phases": phase_rows})
            finally:
                cleanup()
                permission_receipts = []
                for side in ("native", "sdk"):
                    for name, specification in case["files"].items():
                        if specification.get("mode") != 0:
                            continue
                        file = directory / (side + "-fixture") / "workspace" / name
                        if file.exists() and file.is_file() and not file.is_symlink():
                            original_mode = stat.S_IMODE(file.stat().st_mode)
                            file.chmod(0o600)
                            permission_receipts.append({"side": side, "path": str(file), "modeBeforeCleanup": original_mode,
                                "modeAfterCleanup": stat.S_IMODE(file.stat().st_mode),
                                "actualBytesAfterModeRestoration": {"type": "bytes", "base64": base64.b64encode(file.read_bytes()).decode()}})
                if permission_receipts:
                    (directory / "permission-fixture-cleanup.json").write_text(json.dumps(permission_receipts))
    except BaseException as error:
        (output / "capture-rejection.json").write_text(json.dumps({"covers": [], "acceptancePointsAwarded": 0,
            "validationStatus": "rejected", "completedCases": [row["id"] for row in rows], "error": _error(error)}, ensure_ascii=True, indent=2))
        raise
    finally:
        after = {"runtime": _runtime(checkout, cache), "capability": prepare_doctor_authority(node),
                 "bindings": prepare_doctor_bindings(checkout, Path(runtime["runtimeRoot"])), "documents": _documents(),
                 "ownedFiles": _identity((*ADAPTERS, *SDK_FILES, *STORE_ISOLATION_FILES))}
        (output / "authentication-after.json").write_text(json.dumps(after))
        if before != after:
            raise ValueError("Doctor source, package, capability, codec or adapter bytes changed during capture")
    report = {"kind": "heartbeat-doctor-first-baseline", "covers": [], "acceptancePointsAwarded": 0,
              "sourceBuildReproduced": False, "observations": rows}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2))
    return {"cases": len(rows), "matches": sum(row["matches"] for row in rows), "acceptancePointsAwarded": 0}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--sdk-phase":
        print(json.dumps(sdk_doctor_phase(json.loads(Path(sys.argv[2]).read_text())), ensure_ascii=True)); return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkout", "runtime-cache", "node", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    print(json.dumps(run(args.checkout.resolve(), args.runtime_cache.resolve(), args.node.resolve(), args.output.resolve(), args.case)))


if __name__ == "__main__":
    main()
