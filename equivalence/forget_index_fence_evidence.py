"""Independent custody for the closed forget/index-fence packet.

This module does not invoke a host, repair an observation, or predict an engine's
policy.  A pair may pass custody and still disagree.  Only independently chosen
source bytes and the approved Node binary may supply replay authority.
"""
from __future__ import annotations

import ast
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from types import CodeType

from equivalence.harness import _same_json


ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1794614400000
NODE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(actual, expected, message):
    require(_same_json(actual, expected), message)


def _finite(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    return value is None or type(value) in (str, int, bool)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(text):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "Evidence JSON contains a duplicate member")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("Evidence JSON contains a nonfinite number: " + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _regular(filename):
    path = Path(filename)
    require(path.is_absolute() and path.resolve(strict=True) == path,
            "Evidence path is relative or contains a symbolic alias")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            "Evidence file is not an independent regular file")
    return path


def _owned(filename, root):
    path, base = _regular(filename), Path(root).resolve(strict=True)
    require(path.is_relative_to(base), "Evidence file escaped its actual owned directory")
    return path


@lru_cache(maxsize=4096)
def _cached_digest(filename, device, inode, size, mtime_ns, ctime_ns):
    return _sha(Path(filename).read_bytes())


def _digest(filename):
    path = _regular(filename)
    info = path.stat()
    return _cached_digest(str(path), info.st_dev, info.st_ino, info.st_size,
                          info.st_mtime_ns, info.st_ctime_ns)


def _read(filename, root=None):
    return _json((_owned(filename, root) if root is not None else _regular(filename)).read_text(encoding="utf8"))


def _relative(value):
    require(isinstance(value, str) and value and "\\" not in value,
            "A source inventory path is not canonical")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == value,
            "A source inventory path escaped its source seal")
    return path


def _sealed_json(row, root=None):
    wire = row["serializedJSON"]
    require(isinstance(wire, str) and row["sha256"] == _sha(wire.encode("utf8")),
            "An original JSON carrier lost its complete byte seal")
    decoded = _json(wire)
    if isinstance(decoded, dict):
        for key, value in decoded.items():
            if key in row:
                _same(row[key], value, "An original JSON carrier disagrees with its captured object")
    if "file" in row:
        require(root is not None, "A serialized carrier has no independently owned transport root")
        require(_owned(row["file"], root).read_text(encoding="utf8") == wire,
                "An original JSON carrier differs from its actual captured file")
    return decoded


def _ns(value):
    require(isinstance(value, str) and value.isdigit(), "An original monotonic clock was removed")
    return int(value)


def _events(rows):
    require(isinstance(rows, list) and rows, "The original lifecycle receipts are missing")
    events = {}
    clocks = {}
    for sequence, row in enumerate(rows, 1):
        require(type(row["sequence"]) is int and row["sequence"] == sequence,
                "Original lifecycle receipts were omitted, duplicated, or reordered")
        key = row.get("pid"), row.get("threadId")
        at = _ns(row.get("atNs", row.get("enteredAtNs")))
        require(at >= clocks.get(key, -1), "Original per-thread chronology was reversed")
        clocks[key] = at
        events[sequence] = row
    return events


def _interval(row, events, entered=None, returned=None):
    start, end = row["enterSeq"], row["returnSeq"]
    require(type(start) is type(end) is int and start < end and start in events and end in events,
            "An original invocation lost its actual entry or settlement")
    if entered is not None:
        require(events[start]["event"] == entered, "An original entry receipt was relabelled")
    if returned is not None:
        require(events[end]["event"] == returned, "An original settlement receipt was relabelled")
    return start, end


def _settlement(value):
    require(isinstance(value, dict) and set(value) == {"status", "isTypedConflict"}
            and value["status"] in {"fulfilled", "rejected"}
            and type(value["isTypedConflict"]) is bool
            and (value["status"] == "rejected" or value["isTypedConflict"] is False),
            "The common client settlement was repaired or relabelled")


def _source_root(recorded, approved):
    root = Path(approved or os.environ.get("MEMORY_FORGET_INDEX_FENCE_SDK_SOURCE_ROOT", ROOT)).resolve(strict=True)
    require(root.is_dir() and (root / "memory_core").is_dir(), "The independently selected SDK source seal is missing")
    original = Path(recorded)
    require(original.is_absolute(), "The original SDK source root was omitted")
    return original, root


def _source_path(filename, recorded_root, approved_root):
    path = Path(filename)
    require(path.is_absolute() and path.is_relative_to(recorded_root),
            "An actual SDK callable borrowed another source tree")
    relative = _relative(path.relative_to(recorded_root).as_posix())
    require(relative.parts[0] == "memory_core", "An SDK production owner came from an observer module")
    return _regular(approved_root / relative)


def _sdk_inventory(identity, approved_root):
    """Authenticate all production bytes, not just the imported subset."""
    recorded_root, source_root = _source_root(identity["root"], approved_root)
    digest, expected = hashlib.sha256(), []
    for path in sorted((source_root / "memory_core").rglob("*.py")):
        _regular(path)
        relative, data = path.relative_to(source_root).as_posix(), path.read_bytes()
        digest.update(relative.encode() + b"\0" + data + b"\0")
        expected.append({"path": relative, "bytes": len(data), "sha256": _sha(data)})
    require(identity["sourceFiles"] == len(expected) and identity["sourceSha256"] == digest.hexdigest(),
            "The complete SDK production source seal changed")
    _same(identity["files"], expected, "The SDK source inventory was truncated or substituted")
    return recorded_root, source_root


@lru_cache(maxsize=1024)
def _definitions(filename, digest):
    definitions = {}
    def visit(node, parent=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = parent + child.name
                definitions[name] = min([child.lineno, *(item.lineno for item in child.decorator_list)])
                visit(child, name + ("." if isinstance(child, ast.ClassDef) else ".<locals>."))
            else:
                visit(child, parent)
    visit(ast.parse(Path(filename).read_text(encoding="utf8")))
    return definitions


@lru_cache(maxsize=1024)
def _bytecodes(filename, digest):
    result = {}
    def visit(code):
        result[code.co_qualname, code.co_firstlineno] = _sha(code.co_code)
        for item in code.co_consts:
            if isinstance(item, CodeType):
                visit(item)
    visit(compile(Path(filename).read_text(encoding="utf8"), filename, "exec", dont_inherit=True))
    return result


def _sdk_code_owner(row, recorded_root, approved_root):
    source = _source_path(row["file"], recorded_root, approved_root)
    digest = _digest(source)
    require(row["sourceSha256"] == digest
            and (row["qualname"], row["firstLine"]) in _bytecodes(str(source), digest),
            "An actual SDK callable lost its original source/code identity")
    require(row["bytecodeSha256"] == _bytecodes(str(source), digest).get((row["qualname"], row["firstLine"])),
            "The actual SDK callable code differs from independently compiled original source")
    return source


def _observer_exception(error, recorded_root):
    trace = error.get("traceback", "")
    require(isinstance(trace, str), "An actual SDK exception traceback was removed")
    frames = re.findall(r'^\s*File "([^"]+)", line \d+', trace, flags=re.MULTILINE)
    require(frames and not Path(frames[-1]).is_relative_to(recorded_root / "equivalence"),
            "An observer-origin exception contaminated the original operation")


FORGET_FIELDS = {"agentId", "dryRun", "sessionIds", "participantMatches", "sessionResolutions",
                 "entryKeys", "mixedLineageEntryKeys", "untargetableEntryKeys", "curatedWrites",
                 "artifacts", "refusals"}
CALL_KINDS = {"original-sync": "sync", "start-sync": "sync",
              "public-memory-search": "search", "start-public-memory-search": "search",
              "original-forget": "forget", "start-forget": "forget",
              "original-promotion": "promotion", "start-promotion": "promotion",
              "original-record-short-term-recalls": "recall"}
SNAPSHOT_FIELDS = {"documents", "origins", "tombstones", "recall", "phaseSignals",
                   "ingestion", "preimages", "sessions", "index", "concurrency", "events"}


def _case(case):
    from equivalence.forget_index_fence import validate_case
    validate_case(case)
    return case["input"]


def _expected_calls(value):
    calls = {}
    steps = []
    for step in value["steps"]:
        steps.extend(value["seedActions"] if step["operation"] == "execute-seed-actions" else [step])
    for step in steps:
        if step["operation"] in CALL_KINDS:
            kind = CALL_KINDS[step["operation"]]
            key = kind + ":" + step["label"]
            require(key not in calls, "The frozen schedule aliases two public calls")
            calls[key] = kind, step["label"], step["actor"]
    return calls


def validate_result(case, result):
    value = _case(case)
    require(isinstance(result, dict) and set(result) == {"provider", "calls", "snapshots"}
            and result["provider"] == "none" and isinstance(result["calls"], dict)
            and isinstance(result["snapshots"], dict) and _finite(result),
            "The complete forget/index-fence common wire changed")
    expected = _expected_calls(value)
    require(set(result["calls"]) == set(expected), "An original public call was omitted or added")
    for key, (kind, label, _) in expected.items():
        call = result["calls"][key]
        require(isinstance(call, dict) and set(call) == {"operation", "label", "outcome"}
                and call["operation"] == kind and call["label"] == label,
                "A complete original public call lost its operation or label")
        outcome = call["outcome"]
        if kind == "sync":
            _settlement(outcome)
        elif kind == "recall" and outcome == {"status": "fulfilled"}:
            pass
        else:
            require(isinstance(outcome, dict) and outcome.get("status") in {"fulfilled", "rejected", "terminated"},
                    "The actual original public settlement was removed")
            if outcome["status"] == "terminated":
                require(kind == "forget" and set(outcome) == {"status", "signal"} and outcome["signal"] == "SIGKILL",
                        "A killed original call was replaced with an invented return")
            elif outcome["status"] == "rejected":
                require(set(outcome) == {"status", "error"} and isinstance(outcome["error"], dict)
                        and isinstance(outcome["error"].get("message"), str),
                        "The whole actual accessible public error was removed")
            else:
                require(set(outcome) == {"status", "result"}, "A public result was truncated or repaired")
                if kind == "forget":
                    _forget_report(outcome["result"])
                elif kind == "search":
                    require(isinstance(outcome["result"], dict), "The complete actual public search details are absent")
    stages = [step["label"] for step in value["steps"] if step["operation"] == "capture-physical-state"]
    require(set(result["snapshots"]) == set(stages) and len(stages) == len(set(stages)),
            "A declared actual physical stage was omitted or added")
    for snapshot in result["snapshots"].values():
        require(isinstance(snapshot, dict) and set(snapshot) == SNAPSHOT_FIELDS
                and isinstance(snapshot["documents"], list) and isinstance(snapshot["origins"], list)
                and isinstance(snapshot["tombstones"], list), "A complete logical/physical snapshot was truncated")
        for tombstone in snapshot["tombstones"]:
            require(isinstance(tombstone, dict) and "createdAt" in tombstone,
                    "An original logical tombstone timestamp was stripped")
        paths = []
        for document in snapshot["documents"]:
            require(isinstance(document, dict) and set(document) == {"path", "exists", "bytes", "sha256"}
                    and type(document["exists"]) is bool, "A complete common source record changed")
            _relative(document["path"])
            paths.append(document["path"])
            if document["exists"]:
                require(isinstance(document["bytes"], str) and bytes.fromhex(document["bytes"]).hex() == document["bytes"]
                        and _sha(bytes.fromhex(document["bytes"])) == document["sha256"],
                        "A common source record lost its complete original bytes")
            else:
                require(document["bytes"] is document["sha256"] is None, "An absent original source acquired bytes")
        require(len(paths) == len(set(paths)), "A common original source was duplicated")
        require(isinstance(snapshot["index"], list) and all(isinstance(row, dict)
                    and set(row) == {"path", "source", "startLine", "endLine", "text"} for row in snapshot["index"]),
                "The whole canonical index contains a truncated or added member")
        require(isinstance(snapshot["sessions"], dict) and set(snapshot["sessions"]) == {"facts", "admission"}
                and isinstance(snapshot["sessions"]["facts"], list) and isinstance(snapshot["sessions"]["admission"], list),
                "Complete original session facts or admission observations were removed")
        concurrency = snapshot["concurrency"]
        require(isinstance(concurrency, dict) and set(concurrency) == {"markerVisible", "forgetSettled", "oldBuildSettled"}
                and all(item is None or type(item) is bool for item in concurrency.values()),
                "Actual process/database concurrency observations were repaired")
    return True


def _forget_report(report):
    require(isinstance(report, dict) and set(report) == FORGET_FIELDS
            and type(report["dryRun"]) is bool and isinstance(report["agentId"], str)
            and isinstance(report["artifacts"], dict)
            and all(type(count) is int and count >= 0 for count in report["artifacts"].values())
            and all(isinstance(report[field], list) for field in FORGET_FIELDS - {"agentId", "dryRun", "artifacts"})
            and _finite(report), "The complete original public forget report was truncated or repaired")


def _search_envelope(envelope):
    require(isinstance(envelope, dict) and isinstance(envelope.get("details"), dict)
            and isinstance(envelope.get("content"), list) and _finite(envelope),
            "The complete original search envelope/details are absent")
    carriers = [row["text"] for row in envelope["content"]
                if isinstance(row, dict) and row.get("type") == "text" and isinstance(row.get("text"), str)]
    require(carriers, "The actual public search text carrier was removed")
    # The original tool decides its public error/warning/actions. A complete
    # actual carrier, rather than a reconstructed subset, authenticates them.
    require(any(_same_json(_json(text), envelope["details"]) for text in carriers),
            "Public search details differ from the original complete text carrier")


def _source_entry(row, root):
    require(isinstance(row, dict) and isinstance(row["path"], str),
            "An original source observation is incomplete")
    path = Path(row["path"])
    require(path.is_absolute() and path.is_relative_to(Path(root)) and path == path.absolute(),
            "An original source observation escaped its fixture")
    kind = row["kind"]
    require(kind in {"file", "missing", "symlink", "directory"}, "An original source kind changed")
    if kind == "file":
        data = bytes.fromhex(row["hex"])
        require(data.hex() == row["hex"] and row["text"] == data.decode("utf8", "replace"),
                "Original source bytes and decoded text were detached")
        if "sha256" in row:
            require(row["sha256"] == _sha(data), "Original source bytes lost their digest")
        require("mtimeNs" in row or "mtimeMs" in row or "mtime_ns" in row,
                "Original source metadata timestamps were stripped")
        for field in ("mtimeNs", "mtime_ns"):
            if field in row:
                require((isinstance(row[field], str) and row[field].isdigit()) or type(row[field]) is int,
                        "An original source timestamp changed type")
    elif kind == "symlink":
        require(isinstance(row["target"], str), "An original source symlink lost its actual target")


def _physical_database(row, root):
    """Check complete actual schema/table carriers without inventing DB parity."""
    payload = _sealed_json(row, root)
    require(isinstance(payload, dict), "The actual physical SQL snapshot is not an object")
    path = Path(payload["dbPath"])
    require(path.is_absolute() and path.is_relative_to(Path(root)),
            "A physical SQL snapshot borrowed another fixture database")
    require(payload.get("readOnly") is True, "A physical observer was allowed to write")
    schema, tables = payload["schema"], payload["tables"]
    require(isinstance(schema, list) and isinstance(tables, dict)
            and len({(item["type"], item["name"]) for item in schema}) == len(schema),
            "The original physical SQL schema was truncated or duplicated")
    available = {item["name"] for item in schema if item["type"] == "table"}
    selected = payload.get("selectedTables", list(available))
    require(isinstance(selected, list) and len(set(selected)) == len(selected)
            and set(selected) <= available and set(tables) == set(selected),
            "A real selected physical table was omitted or added")
    for name, table in tables.items():
        require(isinstance(table, dict) and isinstance(table["columns"], list)
                and isinstance(table["rows"], list) and table["rowCount"] == len(table["rows"])
                and type(table["rowCount"]) is int and table["rowCount"] >= 0,
                "Actual physical SQL rows or column metadata were truncated")
        require(all(isinstance(item, dict) and set(item) == set(table["columns"]) for item in table["rows"]),
                "Actual SQL row members differ from the original complete columns")
    require(_finite(payload), "Physical SQL evidence contains a nonfinite JSON number")
    return payload


@lru_cache(maxsize=256)
def _archive_inventory(filename, device, inode, size, mtime_ns, ctime_ns, package_json):
    from equivalence.release_runtime import _archive_files
    files = _archive_files(Path(filename).read_bytes(), _json(package_json))
    return {name: _sha(data) for name, data in files.items()}


def _release_inventory(runtime, trusted_archive=None):
    from equivalence.release_runtime import _manifest, MANIFEST_SHA256, REFERENCE_COMMIT, VERSION
    manifest, digest = _manifest()
    require(digest == MANIFEST_SHA256 and runtime["manifestSha256"] == digest
            and runtime["reference"] == {"tag": "v" + VERSION, "commit": REFERENCE_COMMIT},
            "Original Native release authority changed")
    root = Path(runtime["runtimeRoot"]).parent.parent
    pinned = {row["location"]: row for row in manifest["packages"]}
    # The selected original native binary is an additional integrity-pinned
    # release package; its location and integrity must come from the manifest.
    from equivalence.dependencies import _target
    native = dict(manifest["nativeTargets"][_target()])
    native.update(location="node_modules/" + native["name"], pin="upstream-pnpm-lock")
    pinned[native["location"]] = native
    inventories = {}
    for package in runtime["packages"]:
        declaration = pinned.get(package["location"])
        require(declaration is not None and all(package[key] == declaration[key]
                    for key in ("name", "version", "integrity", "pin")),
                "A captured Native package has no independently pinned archive authority")
        name = package["name"].replace("/", "-").lstrip("@") + "-" + package["version"] + ".tgz"
        archive = root / "archives" / name
        if trusted_archive is not None and package["name"] == "openclaw":
            chosen = Path(trusted_archive).resolve(strict=True)
            archive = chosen / name if chosen.is_dir() else chosen
        archive = _regular(archive)
        info = archive.stat()
        inventory = _archive_inventory(str(archive), info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, json.dumps(declaration, sort_keys=True))
        recorded = {row["path"]: row["sha256"] for row in package["files"]}
        require(len(recorded) == len(package["files"]) and recorded == inventory,
                "Captured complete Native release inventory differs from pinned archive bytes")
        inventories[package["location"]] = inventory
    require(set(pinned) == set(inventories) and "node_modules/openclaw" in inventories,
            "The actual Native release package inventory is missing")
    return root, inventories


def _native_authority(case, raw, directory, approved_node, trusted_archive, approved_reference):
    directory = Path(directory).resolve(strict=True)
    context_path, process_path = directory / "context.json", directory / "process.json"
    context, process = _read(context_path, directory), _read(process_path, directory)
    require(process["pid"] == raw["pid"] and process["parentPid"] == raw["ppid"]
            and process["returncode"] == 0 and process["contextPath"] == str(context_path)
            and process["contextSha256"] == _digest(context_path)
            and process["protectedBytesUnchanged"] is True and process["retryAllowed"] is False
            and not process.get("observationFailure") and not process.get("timedOut"),
            "The actual Native process lost its PID or approved context identity")
    request_path = _owned(process["requestPath"], directory)
    require(process["requestSha256"] == _digest(request_path), "Native actual input request bytes changed")
    _same(_read(request_path), {key: case[key] for key in ("id", "operation", "input")},
          "Native actual request borrowed another frozen input")
    authority = context["approvedNodeRuntime"]
    selected = approved_node or os.environ.get("MEMORY_EQ_NODE") or ROOT / "work/node-v24.16.0-linux-x64/bin/node"
    binary = _regular(Path(selected).resolve(strict=True))
    require(str(binary) == authority["execPath"] and _digest(binary) == authority["sha256"] == NODE_SHA256
            and authority["nodeVersion"] == "v24.16.0" and authority["icuVersion"] == "78.3"
            and authority["unicodeVersion"] == "17.0" and process["argv"][0] == str(binary),
            "Native original executable differs from the independently approved Node")
    require(context["providerMode"] == "none" and context["fetchPolicy"] == "deny"
            and context["stateDirectory"] == raw["fixtureBase"] == str(directory / "state"),
            "Native original process borrowed ambient provider or fixture state")
    profile = context["forgetIndexFenceProfile"]
    require(profile["kind"] == "forget-index-fence" and profile["operation"] == case["operation"]
            and profile["caseId"] == case["id"] and profile["acceptancePointsAwarded"] == 0
            and profile["caseWireSha256"] == _digest(request_path),
            "Native original process used an undeclared execution profile")
    _same(profile["gates"], case["input"]["gates"], "Native actual gate declarations differ from frozen input")
    _same(profile["actorClocks"], {"coordinator": case["input"]["clock"]["nowMs"],
          "observer": case["input"]["clock"]["nowMs"], **dict.fromkeys(case["input"]["actors"], case["input"]["clock"]["nowMs"])},
          "Native process wall-clock capabilities were silently equalized")
    program_root = Path(process["cwd"])
    allowed = {row["path"]: row["sha256"] for row in context["allowedLocal"]}
    require(len(allowed) == 3 and set(allowed) == {str(program_root / "equivalence" / f"forget-index-fence-{name}.mjs")
                for name in ("entry", "runtime", "preload")}, "Native execution allowed an undeclared local program")
    for filename, digest in allowed.items():
        require(_digest(filename) == digest, "An actual Native observer/actor program changed after execution")
    environment = process["environment"]
    require(set(environment) == {"PATH", "LANG", "TZ", "NODE_OPTIONS", "MEMORY_EQ_RELEASE_CONTEXT",
                "MEMORY_EQ_FIF_ACTOR", "OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"}
            and environment["MEMORY_EQ_RELEASE_CONTEXT"] == str(context_path)
            and environment["MEMORY_EQ_FIF_ACTOR"] == "coordinator"
            and environment["OPENCLAW_STATE_DIR"] == raw["fixtureBase"]
            and environment["OPENCLAW_CONFIG_PATH"] == context["configPath"]
            and environment["NODE_OPTIONS"] == f'--import={program_root / "equivalence/forget-index-fence-preload.mjs"}',
            "Native actual process environment borrowed another actor, config, or preload")
    _native_declarations(process, context, directory, approved_reference)
    package_root, inventories = _release_inventory(context["runtime"], trusted_archive)
    by_pid, passive = {}, {}
    for path in sorted(_owned_trace_directory(context["traceDirectory"], directory).glob("*.jsonl")):
        rows = [_json(line) for line in _owned(path, directory).read_text().splitlines()]
        require(rows and rows[0]["event"] == "bootstrap", "An original Native import trace lost its bootstrap")
        boot = rows[0]
        pid, thread = boot["pid"], boot["threadId"]
        require(path.name == f"{pid}-{thread}.jsonl" and boot["fetchDenied"] is True
                and boot["contextSha256"] == process["contextSha256"]
                and boot["isMainThread"] is (thread == 0), "Native imported worker identity was substituted")
        _same(boot["runtime"], authority, "An actual Native worker used another executable")
        require((pid, thread) not in by_pid, "A Native worker import trace was duplicated")
        loaded, clock, gates = set(), [], []
        for row in rows[1:]:
            require(row["pid"] == pid and row["threadId"] == thread,
                    "An original Native import trace changed process or worker")
            if row["event"] == "forget-index-fence-bootstrap":
                clock.append(row)
                continue
            if row["event"] == "fence-gate-enter":
                gates.append(row)
                continue
            require(row["event"] in {"load", "resolve-native"}, "An unknown Native import operation was accepted")
            if row.get("kind") == "oracle":
                require(allowed.get(row["path"]) == row["sha256"], "An unapproved Native local program executed")
            else:
                package, relative = row["package"], _relative(row["path"])
                require(row.get("kind") == "release" and inventories[package].get(str(relative)) == row["sha256"]
                        and _digest(package_root / _relative(package) / relative) == row["sha256"],
                        "Actually imported Native source differs from the pinned original archive")
                loaded.add(row["path"])
        require(len(clock) == 1 and clock[0]["clock"]["apis"] == ["Date"]
                and clock[0]["clock"]["setTimeoutUnchanged"] is True
                and clock[0]["clock"]["performanceNowUnchanged"] is True,
                "Native original monotonic clocks or timers were replaced")
        by_pid[pid, thread] = {"bootstrap": boot, "loaded": loaded, "clock": clock[0]["clock"], "gates": gates}
    require((raw["pid"], 0) in by_pid, "Native actual coordinator never imported the authenticated actor")
    for path in sorted((directory / "evidence").glob("*-events.jsonl")):
        rows = [_json(line) for line in _owned(path, directory).read_text().splitlines()]
        if rows:
            pid, thread = rows[0]["pid"], rows[0]["threadId"]
            require((pid, thread) in by_pid and path.name == f"{pid}-{thread}-events.jsonl",
                    "A Native passive receipt borrowed an unauthenticated worker")
            require(all(row["pid"] == pid and row["threadId"] == thread for row in rows),
                    "Native original passive receipts changed worker identity")
            passive[pid, thread] = rows
    for key, loaded in by_pid.items():
        rows = [*passive.get(key, []), *loaded["gates"]]
        if rows:
            rows.sort(key=lambda row: row["sequence"])
            _events(rows)
            passive[key] = rows
    return context, process, authority, by_pid, passive


def _native_declarations(process, context, directory, approved_reference):
    from equivalence.forget_index_fence_bindings import (
        SOURCE_HASHES, SOURCE_ANCHORS, COMPILED_HASHES, COMPILED_ANCHORS, REFERENCE_COMMIT,
    )
    source = Path(approved_reference or os.environ.get("MEMORY_EQ_REFERENCE_CHECKOUT", ROOT / "work/openclaw-v2026.9.9")).resolve(strict=True)
    require(process["sourceCheckout"] == str(source), "Native original source checkout differs from independent source authority")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, timeout=10, check=False)
    require(head.returncode == 0 and head.stdout.strip() == REFERENCE_COMMIT,
            "Native original TypeScript source checkout lost its pinned commit")
    bindings = _read(Path(directory) / "declaration-bindings.json", directory)
    require(bindings["kind"] == process["declarationAuthorityKind"] == "official-release-forget-index-fence-owners"
            and bindings["referenceCommit"] == REFERENCE_COMMIT and bindings["sourceBuildReproduced"] is False
            and bindings["sourceFallbackAllowed"] is False and bindings["constructorSkipped"] is False,
            "Native source/release declarations lost their original authority")
    for name, root, hashes, anchors in (("sourceBindings", source, SOURCE_HASHES, SOURCE_ANCHORS),
            ("compiledBindings", Path(context["runtime"]["runtimeRoot"]), COMPILED_HASHES, COMPILED_ANCHORS)):
        rows = bindings[name]
        require(len(rows) == len(hashes) and {row["path"] for row in rows} == set(hashes),
                "A Native original source/compiled owner declaration was omitted")
        for row in rows:
            path = _regular(root / _relative(row["path"]))
            require(row["sha256"] == hashes[row["path"]] == _digest(path),
                    "A Native original source/compiled owner differs from independently pinned bytes")
            text = _compiled_text(str(path), _digest(path))
            expected = []
            for anchor in anchors[row["path"]]:
                require(text.count(anchor) == 1, "An original Native source owner linkage is not unique")
                expected.append({"anchor": anchor.rstrip("\n"), "line": text[:text.index(anchor)].count("\n") + 1})
            _same(row["anchors"], expected, "A Native original source owner anchor was relabelled")


def _owned_trace_directory(filename, directory):
    path = Path(filename)
    require(path == Path(directory) / "traces" and path.resolve(strict=True) == path and path.is_dir(),
            "Native trace directory escaped its actual packet")
    return path


def _document_rows(value, rows):
    records = {}
    for row in rows:
        name = row["path"]
        _relative(name)
        require(name not in records, "An original physical source observation was duplicated")
        records[name] = row
        if row["kind"] == "file":
            data = bytes.fromhex(row["hex"])
            require(data.hex() == row["hex"] and data.decode("utf8", "replace") == row["text"]
                    and row["sha256"] == _sha(data) and isinstance(row["mtimeNs"], str)
                    and row["mtimeNs"].isdigit(), "Actual source bytes/stat/digest were dropped or substituted")
            if "rawStat" in row:
                info = row["rawStat"]
                require({"dev", "ino", "mode", "nlink", "size", "mtimeNs", "ctimeNs"} <= set(info)
                        and str(info["mtimeNs"]) == row["mtimeNs"] and int(info["size"]) == len(data),
                        "Native complete original source stat fingerprints were stripped")
            else:
                info, after = row["stat"], row["statAfter"]
                require({"st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"} <= set(info)
                        and set(info) == set(after) and info["st_mtime_ns"] == row["mtimeNs"]
                        and int(info["st_size"]) == len(data)
                        and all(info[key] == after[key] for key in ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")),
                        "SDK complete original source stat fingerprints changed during the actual source read")
    names = {name for name, row in records.items() if row["kind"] == "file" and name.lower().endswith((".md", ".txt"))}
    names |= {name for name in value["initialFiles"] if name.lower().endswith((".md", ".txt"))}
    result = []
    for name in sorted(names):
        row = records.get(name)
        exists = row is not None and row["kind"] == "file"
        require(row is None or row["kind"] in {"file", "missing"},
                "An observed original source cannot be projected as an ordinary file")
        result.append({"path": name, "exists": exists, "bytes": row["hex"] if exists else None,
                       "sha256": row["sha256"] if exists else None})
    return result


def _canonical_index(database, native):
    name = "memory_index_chunks" if native else "chunks"
    result = [{"path": row["path"], "source": row["source"], "startLine": row["start_line"],
               "endLine": row["end_line"], "text": row["text"]}
              for row in database["tables"].get(name, {}).get("rows", [])]
    return sorted(result, key=lambda row: (row["path"], row["source"], row["startLine"], row["endLine"], row["text"]))


def _logical_origins(rows):
    return [{"entryKey": row["entry_key"], "agentId": row["agent_id"], "sessionId": row["session_id"],
             "sessionKey": row["session_key"], "originClass": row["origin_class"], "observedAt": row["observed_at"]}
            for row in rows]


def _logical_tombstones(rows):
    return [{"sessionId": row["session_id"], "agentId": row["agent_id"], "reason": row["reason"],
             "createdAt": row["created_at"]} for row in rows]


def _workspace_path(value, workspace):
    require(isinstance(value, str), "An actual promotion memoryPath changed type")
    path, base = Path(value), Path(workspace)
    require(path.is_absolute() and path.is_relative_to(base)
            and path.resolve() == path and path != base,
            "An actual promotion memoryPath escaped its owned original workspace")
    return "$WORKSPACE/" + path.relative_to(base).as_posix()


def _promotion_result(value, workspace):
    require(isinstance(value, dict) and "memoryPath" in value,
            "The complete original promotion result was removed")
    return {**value, "memoryPath": _workspace_path(value["memoryPath"], workspace)}


def _public_error(error):
    result = {"message": error["message"]}
    if "code" in error:
        result["code"] = error["code"]
    return result


def _session_shape(value, sessions):
    require(isinstance(sessions, dict) and set(sessions) == {"facts", "admission"},
            "Original persisted session facts or producer admission were omitted")
    expected = [(row["agentId"], row["sessionId"], row["sessionKey"]) for row in value["sessionFacts"]["sessions"]]
    require([(row["agentId"], row["sessionId"], row["sessionKey"]) for row in sessions["facts"]] == expected,
            "Original session facts were duplicated, omitted, reordered, or reassigned")
    require([(row["agentId"], row["sessionId"]) for row in sessions["admission"]]
            == [(agent, session) for agent, session, _ in expected]
            and all(set(row) == {"agentId", "sessionId", "admitted"} and type(row["admitted"]) is bool
                    for row in sessions["admission"]), "Original session producer membership was repaired")
    for row in sessions["facts"]:
        require(set(row) == {"agentId", "sessionId", "sessionKey", "entry", "events"},
                "An original session metadata/event field was removed")


def _sdk_error(error, recorded_root, approved_root):
    _observer_exception(error, recorded_root)
    kind, typed = error["exceptionType"], error["typedConflictClass"]
    require(kind["module"] == error["module"] and kind["name"] == error["name"]
            and typed["module"] == "memory_core.consolidation.origins"
            and typed["name"] == "MemoryIndexRevisionConflictError",
            "An original SDK exception class or typed-conflict authority was relabelled")
    for identity in (kind, typed):
        require(identity["mro"] and identity["mro"][0]["module"] == identity["module"]
                and identity["mro"][0]["name"] == identity["name"], "An original SDK exception MRO was truncated")
        for row in identity["mro"]:
            if row["module"].startswith("memory_core"):
                source = _source_path(row["sourceFile"], recorded_root, approved_root)
                require(_digest(source) == row["sourceSha256"] and row["name"] in _definitions(str(source), _digest(source)),
                        "An original SDK exception class lost its independently selected source seal")
    actual = any(row["module"] == typed["module"] and row["name"] == typed["name"] for row in kind["mro"])
    require(error["isTypedConflict"] is actual, "The original SDK typed-conflict predicate was substituted")
    return actual


def _source_snapshot_common(value, snapshot, *, native, database, origins_database):
    rows = snapshot["documents" if native else "files"]
    documents = _document_rows(value, rows)
    if native:
        public, stores = snapshot["publicState"], snapshot["stores"]
        origins, tombstones = public["origins"], public["tombstones"]
        sessions = {"facts": snapshot["sessions"], "admission": snapshot["common"]["sessions"]["admission"]}
        logical_stores = {"recall": stores["recall"], "phaseSignals": stores["phase"],
                          "ingestion": stores["ingestion"], "preimages": stores["preimages"]}
    else:
        origins, tombstones = _logical_origins(snapshot["logicalOrigins"]), _logical_tombstones(snapshot["tombstones"])
        sessions, logical_stores = snapshot["logicalSessions"], snapshot["logicalStores"]
    table_origins = origins_database["tables"].get("memory_entry_origins", {}).get("rows", [])
    table_tombstones = origins_database["tables"].get("memory_session_tombstones", {}).get("rows", [])
    # SQL captures and original logical readers have the same source ordering
    # on these keys. Compare complete records, including all timestamps.
    ordered_origins = sorted(table_origins, key=lambda row: (row["entry_key"], row["session_id"]))
    ordered_tombstones = sorted(table_tombstones, key=lambda row: row["session_id"])
    _same(origins, _logical_origins(ordered_origins), "Original logical origins differ from complete real SQL rows")
    _same(tombstones, _logical_tombstones(ordered_tombstones), "Original logical tombstones differ from real SQL timestamps/rows")
    _session_shape(value, sessions)
    return {"documents": documents, **logical_stores, "origins": origins, "tombstones": tombstones,
            "sessions": sessions, "index": _canonical_index(database, native)}


def _native_value(row, authority, approved_node):
    return _decode_v8(authority, [row["v8Hex"]], approved_node)[0]


@lru_cache(maxsize=4096)
def _compiled_text(filename, digest):
    return Path(filename).read_text(encoding="utf8")


def _native_code_owners(actor, loaded, context):
    names = {}
    root = Path(context["runtime"]["runtimeRoot"])
    texts = [_compiled_text(str(_regular(root / _relative(name))), _digest(root / _relative(name)))
             for name in loaded if name.endswith((".js", ".mjs", ".cjs"))]
    for row in actor["codeOwners"]:
        text = row["functionSource"]
        require(row["modulePath"] in loaded and isinstance(text, str) and "[native code]" not in text
                and row["functionSourceSha256"] == _sha(text.encode()) and any(text in source for source in texts)
                and isinstance(row["functionRef"], str) and row["functionRef"].startswith(str(actor["pid"]) + ":"),
                "An actual Native callable lost its original compiled source/function identity")
        if row["name"] in names:
            _same(row, names[row["name"]], "One Native callable name was rebound during the original lifetime")
        names[row["name"]] = row
    require({"MemoryIndexManager.get", "runMemoryForget", "recordShortTermRecalls",
             "rankShortTermPromotionCandidates", "applyShortTermPromotions", "createMemorySearchTool"} <= set(names),
            "An original Native public owner callable was omitted")
    for get in actor["getCalls"]:
        require(get["originalFunctionRef"] == names["MemoryIndexManager.get"]["functionRef"]
                and get["returnedPromiseRef"] and get["args"] and get["ownerRef"],
                "An actual Native getter borrowed a different function/promise/owner")
        for args in get["args"]:
            require(args["agentId"] == actor["request"]["input"]["identity"]["agentId"]
                    and args["purpose"] in {"cli", "tool", "status", "default"},
                    "An original Native getter used another agent or purpose")
            _same(args["cfg"], actor["config"], "An original Native owner acquired another configuration")
        require(any(owner["ownerRef"] == get["ownerRef"] for owner in actor["ownerBindings"]),
                "An actual Native get return has no original receiver binding")
    for owner in actor["ownerBindings"]:
        require(owner["classRef"] and owner["prototypeRef"] and owner["databaseRef"]
                and owner["nativeConnectionRef"] and Path(owner["dbPath"]).is_relative_to(Path(actor["request"]["fixtureBase"])),
                "An actual Native manager/database receiver lost its identity")
        for method in owner["methods"]:
            require(method["functionRef"] and any(method["functionSourceSha256"] == row["functionSourceSha256"]
                        for row in actor["codeOwners"] if row["functionRef"] == method["functionRef"])
                    if method["name"] == "sync" else bool(method["functionRef"]),
                    "An actual Native bound owner method was replaced")
    typed = actor["typedConflictClass"]
    require(typed["module"] == "dist/manager-db-kernel-DyJADqYu.mjs" and typed["export"] == "t"
            and typed["classRef"] and typed["prototypeRef"] and typed["module"] in loaded
            and typed["compiledSha256"] == _digest(root / typed["module"]),
            "The Native original typed-conflict constructor lost its compiled authority")


def _native_error(actor, entry, authority, approved_node):
    typed, witness, error = actor["typedConflictClass"], entry["errorType"], entry["error"]
    actual = typed["prototypeRef"] in witness["prototypeChainRefs"]
    require(witness["originalTypedClassRef"] == typed["classRef"]
            and witness["originalTypedPrototypeRef"] == typed["prototypeRef"]
            and witness["isTypedConflict"] is actual and witness["isError"] is True
            and witness["errorRef"] and len(witness["prototypeChainRefs"]) == len(witness["prototypeChain"]),
            "The original Native error/prototype typed-conflict predicate was relabelled")
    decoded = _native_value(entry["privateError"], authority, approved_node)
    require(decoded["privateType"] == "Error" and decoded["message"] == error["message"]
            and decoded["stack"] == error["stack"], "A complete original Native error lost its actual V8 carrier")
    frames = error["stack"].splitlines()[1:]
    require(frames and "equivalence/forget-index-fence-" not in frames[0],
            "An observer-origin Native exception contaminated an original public operation")
    properties = {}
    for row in entry["errorOwnProperties"]:
        require(isinstance(row["enumerable"], bool) and isinstance(row["configurable"], bool),
                "An original Native error property descriptor changed")
        if isinstance(row["key"], str) and "value" in row:
            require(row["key"] not in properties, "An original Native error property was duplicated")
            properties[row["key"]] = _native_value(row["value"], authority, approved_node)
    require(properties.get("message", error["message"]) == error["message"]
            and properties.get("stack", error["stack"]) == error["stack"],
            "A complete Native error property differs from the original error carrier")
    public = {"message": error["message"]}
    if "code" in properties:
        public["code"] = properties["code"]
    return actual, public


def _native_public(case, child, actor, command, entry, authority, approved_node):
    value = case["input"]
    kind = CALL_KINDS[command["operation"]]
    label = command["label"]
    require(entry["operation"] == command["operation"] and entry["label"] == label
            and _ns(command["startedAtNs"]) <= _ns(entry["startedAtNs"]),
            "An original Native public call borrowed another command or label")
    if "settlement" not in command:
        require(kind == "forget" and "settledAtNs" not in entry and child["exit"] == {"code": None, "signal": "SIGKILL"}
                and child["kill"]["signal"] == "SIGKILL" and child["reapedAtNs"],
                "A missing original Native return lacks its genuine OS kill/reap")
        return {"operation": kind, "label": label, "outcome": {"status": "terminated", "signal": "SIGKILL"}}
    settlement = command["settlement"]
    require(settlement["pid"] == actor["pid"] and settlement["id"] == command["id"]
            and settlement["actor"] == actor["actor"] and settlement["instance"] == actor["instance"]
            and _ns(entry["startedAtNs"]) < _ns(entry["settledAtNs"]) <= _ns(command["settledAtNs"]),
            "An original Native settlement lost its exact producing process/command lifetime")
    _same(settlement["error"], entry.get("error"), "Native IPC dropped or altered the whole original error")
    if "error" in entry:
        typed, public = _native_error(actor, entry, authority, approved_node)
        outcome = {"status": "rejected", "isTypedConflict": typed} if kind == "sync" else {"status": "rejected", "error": public}
    else:
        _same(settlement["privateReturn"], entry["privateReturn"], "Native IPC replaced the complete original return carrier")
        actual = _native_value(entry["privateReturn"], authority, approved_node)
        if kind == "sync":
            require(entry["returnedUndefined"] is True and actual == {"privateType": "undefined"},
                    "The actual Native sync void return was replaced with an SDK count")
            outcome = {"status": "fulfilled", "isTypedConflict": False}
        elif kind == "recall":
            require(entry["returnedUndefined"] is True and actual == {"privateType": "undefined"},
                    "The actual Native recall void return was manufactured")
            outcome = {"status": "fulfilled"}
        elif kind == "search":
            tool = entry["publicTool"]
            _search_envelope(tool["envelope"])
            _same(_sealed_json(tool), tool["envelope"], "Original search envelope JSON bytes changed")
            _same(actual, tool["envelope"], "Original public search result differs from its actual V8 return")
            _same(tool["details"], tool["envelope"]["details"], "Whole public search details were replaced")
            require(tool["carrierJSON"] == tool["envelope"]["content"][0]["text"], "Original search text carrier was rewritten")
            _same(entry["originalArguments"], value["queries"][label], "Original Native public search arguments changed")
            outcome = {"status": "fulfilled", "result": tool["details"]}
        elif kind == "forget":
            write = entry["actualWriteJson"]
            report = _native_value(write["privateReturnValue"], authority, approved_node)
            _same(report, write["value"], "Original CLI forget report differs from its actual emitted V8 value")
            _same(_json(write["serializedJSON"]), report, "Original whole CLI forget report JSON changed")
            _forget_report(report)
            stream = entry["actualCliStdout"]
            data = bytes.fromhex(stream["hex"])
            require(data.decode("utf8") == stream["text"] and _sha(data) == stream["sha256"],
                    "The complete original CLI stdout bytes were changed")
            _same(_json(stream["text"]), report, "The actual original CLI stdout differs from its emitted whole report")
            outcome = {"status": "fulfilled", "result": report}
        else:
            _same(actual, entry["publicPromotionResult"], "The whole Native promotion result lost its original V8 return")
            outcome = {"status": "fulfilled", "result": _promotion_result(actual, Path(actor["request"]["fixtureBase"]) / "workspace")}
    expected = {"operation": kind, "label": label, "outcome": outcome}
    _same(settlement["publicCall"], expected, "The Native IPC public outcome was truncated or repaired")
    return expected


def _native_gates(case, raw, actors, passive, authority, approved_node, directory):
    specifications = {row["name"]: row for row in case["input"]["gates"]}
    require(len(raw["gates"]) == len(specifications), "An original Native functional gate was omitted or added")
    for gate in raw["gates"]:
        spec, receipt = specifications[gate["name"]], gate["receipt"]
        _same({key: gate[key] for key in spec}, spec, "A Native functional control declaration changed")
        require(receipt["actor"] == spec["actor"] and receipt["boundary"] == spec["boundary"]
                and receipt["callLabel"] == spec["callLabel"] and receipt["pid"] in actors,
                "An original Native gate borrowed another actor/call/boundary")
        path = Path(directory) / "gates" / (gate["name"] + ".hit.json")
        _same(_read(path, directory), receipt, "The original Native gate receipt differs from its actual file")
        events = passive[receipt["pid"], receipt["threadId"]]
        actual = next((row for row in events if row["sequence"] == receipt["sequence"]), None)
        require(actual is not None and actual["event"] == "fence-gate-enter", "A Native gate has no actual original worker receipt")
        _same({key: actual[key] for key in receipt}, receipt, "A Native gate receipt was relabelled after its original worker entry")
        hit = _ns(receipt["enteredAtNs"])
        require(_ns(gate["armedAtNs"]) < hit and isinstance(receipt["originalStack"], str),
                "A Native functional gate fired before arming or lacks its original source frame")
        if spec.get("pause") is not False:
            if gate.get("killWhileHeld"):
                child = actors[receipt["pid"]][0]
                require(child["exit"] == {"code": None, "signal": "SIGKILL"}
                        and hit < _ns(child["kill"]["atNs"]) <= _ns(child["finishedAtNs"])
                        and "releasedAtNs" not in gate, "An alleged marker kill did not kill the actual held original process")
            else:
                require(hit < _ns(gate["releasedAtNs"]), "A Native gate released before the actual original boundary")
                release = next((row for row in events if row["event"] == "fence-gate-release"
                                and row["gate"] == gate["name"]), None)
                require(release is not None and _ns(release["atNs"]) >= _ns(gate["releasedAtNs"]),
                        "The held Native original frame never consumed its actual release")
        boundary = spec["boundary"]
        if boundary == "rebuild.revision-captured-before-publication":
            read = receipt["originalCapturedRevisionRead"]
            require(read is not None and "runInPlaceReindex" in read["originalStack"]
                    and read["dbPath"] == receipt["publishedDbPath"]
                    and receipt["shadowDbPath"] and receipt["shadowDbPath"] != receipt["publishedDbPath"]
                    and read["sql"] == "SELECT revision FROM memory_index_state WHERE id = ?",
                    "The Native builder gate lacks its actual producer-captured fence/shadow frame")
            decoded = _native_value(read["result"], authority, approved_node)
            require(decoded["revision"] == read["value"], "The original Native expected fence differs from its actual SQLite read")
            commands = [row for (pid, _), rows in passive.items() if pid == receipt["pid"]
                        for row in rows if row["event"] == "original-database-publication-command"
                        and row.get("callLabel") == spec["callLabel"]]
            if commands:
                command = _native_value(commands[-1]["command"], authority, approved_node)
                require(command["type"] == "database.publish" and command["input"]["expectedRevision"] == read["value"]
                        == commands[-1]["expectedRevision"], "The actual Native publisher refreshed or replaced its captured expected fence")
        elif boundary == "publication.fence-checked-before-table-writes":
            read = receipt["lastRevisionRead"]
            require(receipt["transactionActive"] is True and read["dbPath"] == receipt["dbPath"]
                    and read["databaseRef"] == receipt["databaseRef"]
                    and "publishMemoryDatabaseTables" in read["originalStack"],
                    "The Native postcheck gate lacks its actual owned transaction/live SQL fence check")
            require(_native_value(read["result"], authority, approved_node)["revision"] == read["value"],
                    "The Native postcheck live fence differs from its actual SQL return")
        elif boundary == "forget.marker-committed-before-purge":
            require(receipt["commitReturned"] is True and receipt["wasTransaction"] is True
                    and receipt["transactionActive"] is False and receipt["sql"].strip().upper() in {"COMMIT", "COMMIT;"}
                    and "forgetWorkspaceMemory" in receipt["originalStack"],
                    "The killed Native forget had no actual committed marker before purge")
        elif boundary == "forget.marker-commit-or-original-workspace-or-writer-wait":
            observation = receipt["observation"]
            require(observation in spec["observationAlternatives"], "Native forget progress was inferred from elapsed time")
            if observation == "actual-marker-COMMIT-returned":
                require(receipt["commitReturned"] is True and receipt["wasTransaction"] is True,
                        "Native forget marker progress lacks the real original COMMIT return")
            elif observation == "actual-original-workspace-lock-wait":
                require("acquireMemoryWorkspaceLock" in receipt["originalStack"] and receipt["delayMs"] == 40
                        and receipt["asyncId"] and receipt["triggerAsyncId"] is not None,
                        "Native workspace wait was not an actual source-owned pending sleep")
        elif boundary == "search.keyword-result-before-enrichment":
            request, reply = _native_value(receipt["request"], authority, approved_node), _native_value(receipt["reply"], authority, approved_node)
            require(request["taskId"] == reply["taskId"] == receipt["taskId"] and reply["status"] == "ok"
                    and reply["value"]["kind"] == request["input"]["kind"] == "keyword"
                    and receipt["replyV8Sha256"] == _sha(bytes.fromhex(receipt["reply"]["v8Hex"])),
                    "The Native in-flight public search lost its actual complete keyword worker reply")
        elif boundary == "promotion.model-planning-before-final-lock":
            require(receipt["sourceOwner"] == "consolidateMemory.actual-subagent-complete-await"
                    and isinstance(receipt["request"], dict), "The Native model gate did not hold the actual original planning request")
        else:
            require(receipt["sourceOwner"] == "resolveMemoryPromotionLockTarget.actual-realpath-return"
                    and "resolveMemoryPromotionLockTarget" in receipt["originalStack"]
                    and _native_value(receipt["result"], authority, approved_node) == str(Path(raw["fixtureBase"]) / "workspace"),
                    "The Native direct promotion gate replaced the original source/lock planning frame")


def _sdk_observation(observation, process, value, approved_root):
    recorded, trusted = _sdk_inventory(observation["sourceProvenanceBefore"], approved_root)
    _same(observation["sourceProvenanceBefore"], observation["sourceProvenanceAfter"],
          "Original SDK production bytes changed during an actor lifetime")
    require(observation["pid"] == process["pid"] and observation["actor"] == process["actor"]
            and observation["process"]["cwd"] == str(recorded)
            and observation["process"]["executable"] == process["argv"][0],
            "Original SDK observation borrowed another process, actor, executable, or imported tree")
    argv = bytes.fromhex(observation["process"]["cmdlineHex"]).split(b"\0")
    require([item.decode() for item in argv if item] == process["argv"],
            "The actual SDK process command line differs from its recorded dispatch")
    for module in observation["loadedSdk"]:
        source = _source_path(module["path"], recorded, trusted)
        require(_digest(source) == module["sha256"], "An actually imported SDK module differs from the trusted source seal")
    codes = {}
    for row in observation["codeOwners"]:
        _sdk_code_owner(row["code"], recorded, trusted)
        require(row["name"] not in codes, "An SDK original callable was omitted or given two identities")
        codes[row["name"]] = row
    for owner in observation["ownerBindings"]:
        require(owner["actor"] == observation["actor"] and owner["pid"] == observation["pid"]
                and owner["memoryPublication"] == "on-search" and owner["catalogTombstoneMirror"] is False,
                "The actual SDK constructor/profile or catalog ownership changed")
        fenced = value["storageProfile"]["sdk"]["revisionFence"] == "actual-ledger-revision-fence"
        shared = value["storageProfile"]["sdk"]["indexAndOrigins"] == "same-database-file"
        require(owner["explicitFence"] is fenced and owner["forgottenCallback"] is fenced
                and owner["storage"]["fenced"] is fenced and owner["storage"]["shared"] is shared
                and owner["storage"]["catalog"] != owner["storage"]["index"]
                and (owner["storage"]["origins"] == owner["storage"]["index"]) is shared,
                "An SDK fence/callback/catalog profile was silently strengthened or weakened")
        _sdk_code_owner(owner["constructorCode"], recorded, trusted)
        require(owner["classMro"][0]["module"] == "memory_core.host.managed_index"
                and owner["classMro"][0]["name"] == "ManagedSQLiteMemoryStore",
                "The actual SDK owner is not the original managed store")
        for cls in owner["classMro"]:
            if cls["module"].startswith("memory_core"):
                source = _source_path(cls["sourceFile"], recorded, trusted)
                require(_digest(source) == cls["sourceSha256"], "An original SDK receiver class lost its source bytes")
    events = _events(observation["originalCalls"])
    returns = {}
    for row in events.values():
        require(row["pid"] == observation["pid"], "An SDK original event borrowed another process")
        if row["event"] == "original-call":
            _same(row["code"], codes[row["name"]]["code"], "An actual SDK invocation borrowed another callable/code object")
            require(row["exactReceiver"] is (codes[row["name"]]["receiver"] is not None),
                    "An SDK original method lost its exact bound receiver")
        elif row["event"] == "original-return":
            call = events[row["callSequence"]]
            require(call["event"] == "original-call" and call["sequence"] < row["sequence"]
                    and call["name"] == row["name"] and call["threadId"] == row["threadId"]
                    and call["callLabel"] == row["callLabel"] and row["callSequence"] not in returns,
                    "An SDK original return was omitted, duplicated, or reassigned")
            returns[row["callSequence"]] = row
    if process["exit"]["code"] != -9:
        require(all(row["sequence"] in returns for row in events.values() if row["event"] == "original-call"),
                "An SDK original frame remained pending without an actual killed process")
    for row in observation["sqlStatements"]:
        _same(row, events[row["sequence"]], "An actual SDK SQL statement lost its original source/connection receipt")
        require(row["event"] == "original-sql" and isinstance(row["connectionId"], str),
                "An SDK SQL statement was generated without its original connection")
        if "executionSequence" in row:
            execution = events[row["executionSequence"]]
            require(execution["event"] == "original-sql-c-call" and execution["connectionId"] == row["connectionId"]
                    and execution["sequence"] < row["sequence"], "An original SDK SQL trace borrowed another C execution")
    for row in observation["sqlExecutions"]:
        _same(row, events[row["sequence"]], "An SDK C execution receipt was detached from the original event stream")
        _sdk_code_owner(row["parentCode"], recorded, trusted)
        if "finishedSequence" in row:
            end = events[row["finishedSequence"]]
            require(end["executionSequence"] == row["sequence"] and end["connectionId"] == row["connectionId"]
                    and end["event"] in {"original-sql-c-return", "original-sql-c-exception"},
                    "An original SDK C execution lost its actual return or exception")
    return recorded, trusted, events, returns


def _sdk_public(case, call, observation, process, events, returns, recorded, trusted):
    kind, label, value = call["kind"], call["label"], case["input"]
    require(call["pid"] == process["pid"] and call["actor"] == process["actor"],
            "An SDK public call borrowed another actual child")
    args = value[{"search": "queries", "sync": "syncs", "forget": "forgetCalls",
                  "promotion": "promotions", "recall": "recallCalls"}[kind]][label]
    _same(call["arguments"], args, "An actual SDK public call received different frozen arguments")
    start = events[call["enterSeq"]]
    require(start["event"] == "public-call-enter" and start["label"] == label and start["kind"] == kind,
            "An SDK public call lost its actual original entry")
    owners = [owner for owner in observation["ownerBindings"] if owner["storeObjectId"] == call["storeObjectId"]]
    require(len(owners) == 1, "An SDK public call used another store receiver")
    if "returnSeq" not in call:
        require(kind == "forget" and process["exit"]["code"] == -9 and process["kill"]["signal"] == "SIGKILL"
                and process["kill"]["pid"] == process["pid"] and process["reapedAtNs"],
                "An absent SDK original return lacks actual OS kill/reap custody")
        return {"operation": kind, "label": label, "outcome": {"status": "terminated", "signal": "SIGKILL"}}
    end = events[call["returnSeq"]]
    require(end["event"] == "public-call-return" and call["enterSeq"] < call["returnSeq"]
            and end["label"] == label and end["kind"] == kind,
            "An SDK public call lost its actual settlement")
    primary = {"search": "MemorySearchTool.execute", "sync": "ManagedSQLiteMemoryStore.reindex",
               "forget": "forget_memory_entries", "promotion": "run_short_term_promotion",
               "recall": "record_short_term_recalls"}[kind]
    calls = [row for row in events.values() if row["event"] == "original-call" and row["name"] == primary
             and row["callLabel"] == label and call["enterSeq"] < row["sequence"] < call["returnSeq"]]
    require(len(calls) == 1, "An SDK public result has no unique actual original API invocation")
    original = calls[0]
    if kind != "recall":
        expected_receiver = owners[0]["storeObjectId"] if kind != "search" else original["receiverObjectId"]
        require(original["exactReceiver"] is True and original["receiverObjectId"] == expected_receiver,
                "An SDK public method borrowed another original receiver")
    if "error" in call:
        typed = _sdk_error(call["error"], recorded, trusted)
        require(any(row["callLabel"] == label and row["error"]["module"] == call["error"]["module"]
                    and row["error"]["name"] == call["error"]["name"]
                    and row["error"]["message"] == call["error"]["message"]
                    for row in observation["originalExceptions"]),
                "An SDK public error has no original exception-frame witness")
        outcome = {"status": "rejected", "isTypedConflict": typed} if kind == "sync" else {"status": "rejected", "error": _public_error(call["error"])}
    else:
        returned = returns[original["sequence"]]
        if kind == "sync":
            require(type(call["returned"]) is int and call["returned"] >= 0
                    and call["returnType"] == {"module": "builtins", "name": "int"},
                    "The actual SDK sync integer return was dropped or manufactured")
            _same(returned["returned"], call["returned"], "SDK sync result lost its actual original return")
            outcome = {"status": "fulfilled", "isTypedConflict": False}
        elif kind == "recall":
            require(type(call["returned"]) is int and call["returned"] >= 0
                    and call["returnType"] == {"module": "builtins", "name": "int"},
                    "The full actual SDK recall integer return was dropped")
            _same(returned["returned"], call["returned"], "SDK recall count differs from its actual source-owned return")
            outcome = {"status": "fulfilled"}
        elif kind == "search":
            _search_envelope(call["envelope"])
            _same(returned["returned"], call["envelope"], "Original SDK search envelope differs from its actual original return")
            _same(call["returned"], call["envelope"], "Complete SDK search return was truncated")
            _same(call["details"], call["envelope"]["details"], "SDK public search warning/error/actions were rewritten")
            outcome = {"status": "fulfilled", "result": call["details"]}
        elif kind == "forget":
            _forget_report(call["report"])
            _same(call["returned"], call["report"], "SDK whole forget report differs from its actual public return")
            # The profile retains the original dataclass before the API's
            # to_json conversion. Match every source-declared report field.
            mapping = {"agent_id": "agentId", "dry_run": "dryRun", "session_ids": "sessionIds",
                       "participant_matches": "participantMatches", "session_resolutions": "sessionResolutions",
                       "entry_keys": "entryKeys", "mixed_lineage_entry_keys": "mixedLineageEntryKeys",
                       "untargetable_entry_keys": "untargetableEntryKeys", "curated_writes": "curatedWrites",
                       "artifacts": "artifacts", "refusals": "refusals"}
            _same({mapping[key]: item for key, item in returned["returned"].items()}, call["report"],
                  "The SDK original report dataclass lost fields in public JSON conversion")
            outcome = {"status": "fulfilled", "result": call["report"]}
        else:
            _same(returned["returned"], call["promotion"], "The SDK full promotion result differs from its actual original return")
            _same(_sdk_promotion_public(call["promotion"], Path(process["request"]["directory"]) / "workspace"),
                  call["publicPromotion"], "The SDK whole public promotion result was truncated or repaired")
            outcome = {"status": "fulfilled", "result": _promotion_result(call["publicPromotion"], Path(process["request"]["directory"]) / "workspace")}
    if kind == "sync":
        _same(call["outcome"], outcome, "The SDK common sync settlement was relabelled")
    return {"operation": kind, "label": label, "outcome": outcome}


def _sdk_candidate(row):
    fields = {"key": "key", "path": "path", "start_line": "startLine", "end_line": "endLine",
              "snippet": "snippet", "recall_count": "recallCount", "daily_count": "dailyCount",
              "grounded_count": "groundedCount", "signal_count": "signalCount", "avg_score": "avgScore",
              "max_score": "maxScore", "unique_queries": "uniqueQueries", "first_recalled_at": "firstRecalledAt",
              "last_recalled_at": "lastRecalledAt", "age_days": "ageDays", "score": "score",
              "recall_days": "recallDays", "concept_tags": "conceptTags", "components": "components"}
    result = {output: row[key] for key, output in fields.items()}
    result["source"] = "memory"
    for key, output in (("claim_hash", "claimHash"), ("project_key", "projectKey"), ("promoted_at", "promotedAt")):
        if row[key]:
            result[output] = row[key]
    if row["provenance"] is not None:
        result["provenance"] = row["provenance"]
    return result


def _sdk_promotion_public(row, workspace):
    return {"memoryPath": str(Path(workspace) / row["target"]), "applied": len(row["applied_candidates"]),
            "appended": row["appended"], "reconciledExisting": row["reconciled_existing"],
            "appliedCandidates": [_sdk_candidate(item) for item in row["applied_candidates"]],
            "rejectedCandidates": [{"candidate": _sdk_candidate(item["candidate"]), "reason": item["reason"],
                                    "category": item["category"]} for item in row["rejected_candidates"]],
            "compactedSections": len(row["compacted_dates"]), "compactedDates": row["compacted_dates"]}


def _common_events(rows, workspace):
    result = []
    for row in rows:
        if row["type"].startswith("memory.recall.") or row["type"] == "memory.promotion.applied":
            if row["type"] == "memory.promotion.applied" and "memoryPath" in row:
                result.append({**row, "memoryPath": _workspace_path(row["memoryPath"], workspace)})
            else:
                result.append(row)
    return result


def _native_capture(case, raw, result, directory, approved_node, trusted_archive, approved_reference):
    require(raw["kind"] == "forget-index-fence-native-capture" and raw["schemaVersion"] == 1
            and raw["engine"] == "native" and raw["caseId"] == case["id"]
            and raw["completed"] is raw["allChildrenReaped"] is True
            and not any(raw.get(name) for name in ("error", "teardownError", "observationErrors")),
            "The original Native packet is incomplete or contaminated")
    _same(raw["input"], case["input"], "The original Native received another frozen input")
    _same(raw["result"], result, "Native raw capture lost its whole public result")
    directory = Path(directory or Path(raw["fixtureBase"]).parent).resolve(strict=True)
    context, process, authority, imports, passive = _native_authority(case, raw, directory, approved_node, trusted_archive, approved_reference)
    approved_node = authority["execPath"]
    returned = _read(process["stdoutPath"], directory)
    require(returned["id"] == case["id"] and returned["ok"] is True, "The actual Native coordinator did not return its complete result")
    _same(returned["result"], result, "Native actual stdout differs from the public result")
    require(len(raw["steps"]) == len(case["input"]["steps"]), "An original Native schedule step was omitted")
    previous = _ns(process["startedAtNs"])
    for observed, expected in zip(raw["steps"], case["input"]["steps"], strict=True):
        _same(observed["step"], expected, "The actual Native schedule changed its original operation order")
        require(previous <= _ns(observed["startedAtNs"]) < _ns(observed["finishedAtNs"]),
                "An original Native schedule step lost its actual monotonic lifetime")
        previous = _ns(observed["finishedAtNs"])
    actors, commands, reconstructed = {}, {}, {}
    require(len({child["pid"] for child in raw["children"]}) == len(raw["children"]), "A Native child PID was reused as a fresh process")
    generations = {}
    for child in raw["children"]:
        require(child["ppid"] == raw["pid"] and child["pid"] != raw["pid"]
                and _ns(process["startedAtNs"]) < _ns(child["startedAtNs"]) < _ns(child["finishedAtNs"])
                <= _ns(child["reapedAtNs"]) < _ns(process["finishedAtNs"])
                and child["exit"] in ({"code": 0, "signal": None}, {"code": None, "signal": "SIGKILL"})
                and "fatal" not in child, "An original Native child failed, was not reaped, or borrowed another process lifetime")
        previous_child = generations.get(child["actor"])
        require(child["instance"] == (previous_child["instance"] + 1 if previous_child else 1)
                and (previous_child is None or _ns(previous_child["reapedAtNs"]) < _ns(child["startedAtNs"])),
                "A Native reopened owner was substituted for a genuinely fresh child process")
        generations[child["actor"]] = child
        _same(_sealed_json(child["requestSeal"]), child["request"], "Native original child request bytes changed")
        _same(child["request"]["input"], case["input"], "A Native original child borrowed another input")
        require(child["request"]["fixtureBase"] == raw["fixtureBase"]
                and child["request"]["actor"] == child["actor"] and child["request"]["instance"] == child["instance"]
                and child["argv"] == [authority["execPath"], str(Path(process["cwd"]) / "equivalence/forget-index-fence-entry.mjs")],
                "A Native original child executed another program, actor, or fixture")
        actor_path = directory / "evidence" / f'{child["actor"]}-{child["instance"]}-raw.json'
        actor = _read(actor_path, directory)
        require(actor["kind"] == "forget-index-fence-actor" and actor["pid"] == child["pid"]
                and actor["ppid"] == child["ppid"] and actor["actor"] == child["actor"]
                and actor["instance"] == child["instance"] and (child["pid"], 0) in imports,
                "A Native original actor capture borrowed another PID or imported program")
        _same(actor["request"], child["request"], "A Native actor changed its actual initialization request")
        _native_code_owners(actor, imports[child["pid"], 0]["loaded"], context)
        actors[child["pid"]] = child, actor
        if child["exit"]["code"] == 0:
            require(actor["closed"] is True, "An original Native owner did not actually close before graceful exit")
        entries = {row["id"]: row for row in actor["calls"]}
        require(len(entries) == len(actor["calls"]) == len(child["commands"]),
                "An actual Native child invocation was omitted or duplicated")
        for command in child["commands"]:
            require(command["id"] not in commands, "A Native original command identity was duplicated")
            commands[command["id"]] = child, actor, command, entries[command["id"]]
            entry = entries[command["id"]]
            _same(_sealed_json(command["requestSeal"]), command["request"], "A Native command request carrier was rewritten")
            _same({key: entry[key] for key in command["request"]}, command["request"], "An actual Native actor received different command arguments")
            if command["operation"] in CALL_KINDS:
                kind, label = CALL_KINDS[command["operation"]], command["label"]
                key = kind + ":" + label
                require(key not in reconstructed, "An original Native labelled API call was duplicated")
                entered = entry["originalEntered"]
                require(entered["pid"] == child["pid"] and entered["id"] == command["id"]
                        and entered["actor"] == child["actor"] and entered["instance"] == child["instance"],
                        "An actual Native public entry borrowed another live original call frame")
                own_events = _events(passive[child["pid"], 0])
                live_entry = own_events[entered["sequence"]]
                require(live_entry["event"] == "original-public-owner-enter"
                        and live_entry["callLabel"] == label and live_entry["atNs"] == entered["atNs"],
                        "An actual Native public entry lost its source-owned observer receipt")
                reconstructed[key] = _native_public(case, child, actor, command, entry, authority, approved_node)
        emitted = "".join(row["actualCliStdout"]["text"] for row in actor["calls"] if "actualCliStdout" in row)
        require(emitted == child["stdout"], "The actual Native child stdout omitted an original CLI report or added unrelated output")
        for owner in actor["ownerBindings"]:
            status = owner["providerIdentity"]
            _same(_native_value(status["privateReturn"], authority, approved_node), status["result"],
                  "The Native selected provider status differs from its actual original return")
            require(status["result"]["provider"] == result["provider"], "Native provider-none result was predicted instead of observed")
    require(set(reconstructed) == set(_expected_calls(case["input"])), "Native actual calls differ from the complete frozen schedule")
    _same(reconstructed, result["calls"], "Native common calls dropped or repaired original public outcomes")
    _native_gates(case, raw, actors, passive, authority, approved_node, directory)
    snapshots = {}
    for snapshot in raw["snapshots"]:
        label = snapshot["label"]
        require(label not in snapshots and snapshot["pid"] in actors, "An original Native physical stage was duplicated or reassigned")
        child, actor = actors[snapshot["pid"]]
        actual = [row for row in actor["snapshots"] if row["label"] == label]
        require(len(actual) == 1, "A Native physical stage has no unique producing observer")
        _same(actual[0], snapshot, "Native original observer snapshot differs from coordinator IPC")
        events = _events(passive[snapshot["pid"], 0])
        _interval(snapshot, events, "physical-snapshot-enter", "physical-snapshot-return")
        database = _physical_database(snapshot["physical"], raw["fixtureBase"])
        _native_plugin_state(snapshot, actor, events, raw["fixtureBase"], authority, approved_node)
        require(set(database["selectedTables"]) == {row["name"] for row in database["schema"]
                    if row["type"] == "table" and row["name"].startswith(("memory_", "session_"))},
                "A source-selected Native physical table was dropped")
        common = _source_snapshot_common(case["input"], snapshot, native=True, database=database, origins_database=database)
        for name, raw_value in (("origins", snapshot["publicState"]["origins"]),
                                ("tombstones", snapshot["publicState"]["tombstones"]), ("stores", snapshot["stores"]),
                                ("sessions", snapshot["sessions"])):
            _same(_native_value(snapshot["publicReadReturns"][name], authority, approved_node), raw_value,
                  "An original Native logical reader lost its complete V8 return")
        membership = snapshot["originalCorpusMembership"]
        _same(_sealed_json(membership), membership["entries"], "The Native actual session admission source carrier changed")
        admission = [{"agentId": row["agentId"], "sessionId": row["sessionId"],
                      "admitted": any(item["agentId"] == row["agentId"] and item["sessionId"] == row["sessionId"]
                                      for item in membership["entries"])} for row in case["input"]["sessionFacts"]["sessions"]]
        _same(common["sessions"]["admission"], admission, "Native session admission was invented from expected tombstone policy")
        common["events"] = _common_events(snapshot["stores"]["events"], Path(raw["fixtureBase"]) / "workspace")
        common["concurrency"] = _native_concurrency(case, snapshot, commands)
        _same(_sealed_json(snapshot["commonSeal"]), snapshot["common"], "Native common snapshot JSON bytes changed")
        _same(common, snapshot["common"], "Native common state lost complete actual source/SQL/public reader custody")
        snapshots[label] = common
    _same(snapshots, result["snapshots"], "Native common snapshot stages were omitted or repaired")
    return True


def _native_plugin_state(snapshot, actor, events, fixture, authority, approved_node):
    binding = actor["pluginStatePathBinding"]
    require(binding["module"] == "dist/openclaw-state-db.paths-rJI64Ab5.mjs" and binding["export"] == "s"
            and binding["result"] == str(Path(fixture) / "state/openclaw.sqlite")
            and binding["arguments"]["env"]["OPENCLAW_STATE_DIR"] == fixture,
            "Native plugin-state physical capture borrowed another original path owner or state root")
    require(any(owner["name"] == "resolveOpenClawStateSqlitePath" and owner["functionRef"] == binding["functionRef"]
                for owner in actor["codeOwners"]), "Native plugin-state path lost its actual original callable identity")
    _same(_native_value(binding["privateReturn"], authority, approved_node), binding["result"],
          "The Native plugin-state path differs from its actual original return")
    capture = snapshot["pluginStateCapture"]
    _interval(capture, events, "physical-plugin-state-read-enter", "physical-plugin-state-read-return")
    require(snapshot["enterSeq"] < capture["enterSeq"] < capture["returnSeq"] < snapshot["returnSeq"]
            and capture["pathBindingRef"] == binding["functionRef"],
            "Native plugin-state SQL observation lost its source-qualified physical capture interval")
    database = _physical_database(snapshot["pluginStatePhysical"], fixture)
    require(database["dbPath"] == binding["result"]
            and set(database["tables"]) == {row["name"] for row in database["schema"] if row["type"] == "table"},
            "A Native physical plugin-state table was omitted or added")
    if database["exists"] is False:
        require(capture["fileIdentity"] is None and database["missingError"]["code"] == "ENOENT"
                and not database["schema"] and not database["tables"],
                "Absent Native plugin-state SQL lacks its actual original missing-file proof")
        return
    require(capture["fileIdentity"] is not None and int(capture["fileIdentity"]["nlink"]) == 1,
            "Native plugin-state SQL lost its actual independent physical file identity")


def _native_concurrency(case, snapshot, commands):
    def settled(role):
        reference = snapshot["coordinatedCalls"][role]
        if reference is None or reference["entered"] is None:
            return None
        child, _, command, entry = commands[reference["commandId"]]
        require(child["pid"] == reference["pid"], "Native concurrency borrowed another original process")
        _same(reference["entered"], command["originalEntered"], "Native concurrency fabricated an original API entry")
        _same(entry["originalEntered"], reference["entered"], "Native API entry lost its actual live-frame observer")
        if reference["settlement"] is not None:
            _same(reference["settlement"], command["settlement"], "Native concurrency fabricated an original API settlement")
            return True
        return False
    return {"markerVisible": any(row["sessionId"] == case["input"]["forgetCalls"]["selected"]["sessionIds"][0]
                                 for row in snapshot["publicState"]["tombstones"]),
            "forgetSettled": settled("forget"), "oldBuildSettled": settled("builder")}


def _sdk_capture(case, dispatch, result, directory, approved_root):
    value = case["input"]
    require(dispatch["kind"] == "forget-index-fence-sdk-dispatch" and dispatch["exit"] == {"code": 0}
            and not any(dispatch.get(key) for key in ("timeout", "stdoutParseError", "error")),
            "The original SDK outer process failed or its stdout was replaced")
    _same(dispatch["input"], value, "The actual SDK dispatch received another frozen input")
    _same(_json(dispatch["requestJson"]), dispatch["request"], "The actual SDK request JSON bytes changed")
    require(dispatch["requestSha256"] == _sha(dispatch["requestJson"].encode())
            and set(dispatch["request"]) == {"input", "directory"}
            and dispatch["argv"][1:] == ["-m", "equivalence.forget_index_fence_sdk_cli"]
            and dispatch["environmentKeys"] == ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"]
            and dispatch["pid"] != dispatch["coordinatorPid"],
            "The actual SDK outer request, executable arguments, environment, or PID changed")
    _same(dispatch["request"]["input"], value, "Actual SDK outer input bytes differ from the frozen literal")
    raw = _json(dispatch["stdout"])
    _same(raw, dispatch["observation"], "SDK stdout lost the complete actual observation")
    require(raw["kind"] == "forget-index-fence-sdk-host" and raw["complete"] is True
            and raw["pid"] == dispatch["pid"] and raw["fixtureRoot"] == dispatch["request"]["directory"]
            and not raw.get("error"), "The original SDK host borrowed another PID or fixture root")
    _same(raw["input"], value, "The original SDK host received another input")
    _same(raw["result"], result, "SDK actual stdout lost the complete common result")
    recorded_root, trusted_root = _sdk_inventory(raw["sourceProvenanceBefore"], approved_root)
    for identity in (raw["sourceProvenanceAfter"], dispatch["sourceProvenanceBefore"], dispatch["sourceProvenanceAfter"]):
        _same(identity, raw["sourceProvenanceBefore"], "SDK production bytes changed across the complete process dispatch")
    fixture = Path(raw["fixtureRoot"])
    require(fixture.is_absolute() and fixture.resolve(strict=True) == fixture,
            "The actual SDK fixture root was aliased or relative")
    if directory is not None:
        require(fixture.is_relative_to(Path(directory).resolve(strict=True)),
                "The SDK fixture root escaped the independently selected SDK transport directory")
    processes, observations, reconstructed = {}, {}, {}
    for process in raw["processes"]:
        require(process["pid"] not in processes and process["pid"] != raw["pid"]
                and process["exit"] in ({"code": 0}, {"code": -9})
                and not process.get("cleanupError") and not process.get("reapError")
                and _ns(process["startedAtNs"]) < _ns(process["reapedAtNs"]),
                "An original SDK child was duplicated, failed, or was not actually reaped")
        require(process["argv"] == dispatch["argv"] and process["request"]["directory"] == raw["fixtureRoot"]
                and process["request"]["actor"] == process["actor"] and process["request"]["mode"] == "actor"
                and process["requestSha256"] == _sha(process["requestJson"].encode()),
                "An original SDK actor changed its executable/fixture/input request")
        _same(_json(process["requestJson"]), process["request"], "Original SDK actor input JSON carrier changed")
        _same(process["request"]["input"], value, "An original SDK child received another frozen input")
        require(len(process["stdoutResponses"]) == len(process["stdoutLines"])
                == len(process["stdinCommands"]), "An original SDK command or complete response was omitted")
        for number, (command, wire, response) in enumerate(zip(process["stdinCommands"], process["stdoutLines"], process["stdoutResponses"], strict=True), 1):
            require(command["id"] == response["id"] == number and response["ok"] is True,
                    "An actual SDK child command/response was duplicated or reassigned")
            _same(_json(wire), response, "SDK actual response stdout bytes changed")
            require(response["observation"]["pid"] == process["pid"]
                    and response["observation"]["ppid"] == raw["pid"], "An SDK original response borrowed another child/parent PID")
        observation = process["observation"]
        _same(observation, process["stdoutResponses"][-1]["observation"], "SDK final process observation lost its actual last response")
        recorded, trusted, events, returns = _sdk_observation(observation, process, value, trusted_root)
        require(recorded == recorded_root and trusted == trusted_root, "An SDK child imported another source namespace")
        if observation["ownerBindings"]:
            require(observation["providerIdentity"] is None and result["provider"] == "none",
                    "SDK provider-none was predicted instead of using its actual original provider identity")
        processes[process["pid"]] = process
        observations[process["pid"]] = observation, events, returns
        for key, call in observation["publicCalls"].items():
            require(key == call["kind"] + ":" + call["label"] and key not in reconstructed,
                    "An original SDK labelled API call was omitted, duplicated, or reassigned")
            reconstructed[key] = _sdk_public(case, call, observation, process, events, returns, recorded, trusted)
    _same(reconstructed, result["calls"], "SDK common outcomes dropped, predicted, or repaired original public calls")
    _sdk_gates(case, raw, processes, observations, recorded_root, trusted_root)
    require(len(raw["steps"]) == len(value["steps"]), "The original SDK schedule omitted a declared step")
    snapshots = {}
    previous = -1
    for number, (step, specification) in enumerate(zip(raw["steps"], value["steps"], strict=True)):
        _same(step["specification"], specification, "The original SDK schedule changed its operation order")
        require(step["number"] == number and step["status"] == "settled"
                and previous <= _ns(step["enteredAtNs"]) < _ns(step["settledAtNs"]),
                "An SDK schedule step lost its actual monotonic lifetime")
        previous = _ns(step["settledAtNs"])
        if specification["operation"] != "capture-physical-state":
            continue
        label = specification["label"]
        snapshot = raw["physicalSnapshots"][label]
        _same(step["returned"], snapshot, "SDK physical stage differs from its actual command return")
        _same(_sealed_json(snapshot), {key: snapshot[key] for key in _json(snapshot["serializedJSON"])},
              "SDK full original snapshot carrier changed")
        capture = step["physicalCapture"]
        capture_path = _owned(capture["path"], fixture)
        require(capture_path == fixture / "captures" / f"{label}-sdk.json"
                and capture["bytes"] == capture_path.stat().st_size and capture["sha256"] == _digest(capture_path),
                "An SDK physical stage lost its separately persisted original file seal")
        _same(_read(capture_path), snapshot, "SDK physical stage file borrowed another observation")
        database = _physical_database(snapshot["indexSql"], fixture)
        origins = _physical_database(snapshot["originsSql"], fixture)
        catalog = _physical_database(snapshot["catalogSql"], fixture)
        _physical_database(snapshot["provenanceSql"], fixture)
        require(catalog["dbPath"] != database["dbPath"] and catalog["dbPath"] != origins["dbPath"],
                "SDK catalog tombstones were mirrored or conflated with the original ledger")
        catalog_tombstones = catalog["tables"].get("memory_session_tombstones", {}).get("rows", [])
        _same(sorted(row["session_id"] for row in catalog_tombstones), snapshot["catalogForgotten"],
              "SDK original catalog forgotten view differs from its actual separate physical table")
        common = _source_snapshot_common(value, snapshot, native=False, database=database, origins_database=origins)
        _sdk_sessions(snapshot, catalog, common["sessions"])
        stages = step["observationsAtCapture"]
        for observation in stages:
            pid = observation["pid"]
            require(pid in processes and any(_same_json(observation, response["observation"])
                    for response in processes[pid]["stdoutResponses"]),
                    "An SDK stage borrowed final/fabricated actor observations")
        receipts = [receipt for observation in stages for receipt in observation["hostEventReceipts"]]
        receipts.sort(key=lambda receipt: _ns(receipt["atNs"]))
        for receipt in receipts:
            require(receipt["pid"] in processes and receipt["callScope"] is not None
                    and receipt["callScope"]["kind"] in {"recall", "promotion", "search"},
                    "An SDK effect event has no actual declared original call scope")
        common["events"] = _common_events([receipt["event"] for receipt in receipts], fixture / "workspace")
        common["concurrency"] = _sdk_concurrency(case, snapshot, stages)
        snapshots[label] = common
    _same(snapshots, result["snapshots"], "SDK common state dropped or repaired complete actual source/SQL/public-reader observations")
    return True


def _sdk_sessions(snapshot, catalog, common):
    tables = catalog["tables"]
    nodes, records = tables.get("memory_session_nodes", {}).get("rows", []), tables.get("memory_session_events", {}).get("rows", [])
    for row in common["facts"]:
        node = [item for item in nodes if item["agent"] == row["agentId"] and item["session_key"] == row["sessionKey"]]
        require(len(node) == 1, "A logical SDK session lost its actual persisted catalog metadata")
        _same(_json(node[0]["entry_json"]), row["entry"], "A logical SDK session entry differs from its complete actual catalog row")
        events = sorted((item for item in records if item["agent"] == row["agentId"] and item["session_id"] == row["sessionId"]), key=lambda item: item["seq"])
        _same([_json(item["event_json"]) for item in events], row["events"], "SDK whole session history differs from actual persisted event rows")
    sources = {row["rel_path"] for row in snapshot["actualAdmittedSourceFiles"]}
    expected = [{"agentId": row["agentId"], "sessionId": row["sessionId"],
                 "admitted": f'sessions/{row["agentId"]}/{row["sessionId"]}.jsonl' in sources} for row in common["facts"]]
    _same(expected, common["admission"], "SDK session admission was invented from tombstone expectations")


def _sdk_concurrency(case, snapshot, observations):
    controlled = {gate["callLabel"] for gate in case["input"]["gates"]
                  if gate["boundary"] in {"rebuild.revision-captured-before-publication", "publication.fence-checked-before-table-writes"}}
    calls = [call for observation in observations for call in observation["publicCalls"].values()]
    def settled(kind):
        selected = [call for call in calls if call["kind"] == kind and "apiEntry" in call
                    and (kind != "sync" or call["label"] in controlled)]
        if not selected:
            return None
        selected.sort(key=lambda call: _ns(call["apiEntry"]["atNs"]))
        return "returnSeq" in selected[-1]
    return {"markerVisible": any(row["session_id"] == case["input"]["forgetCalls"]["selected"]["sessionIds"][0]
                                 for row in snapshot["tombstones"]), "forgetSettled": settled("forget"), "oldBuildSettled": settled("sync")}


def _sdk_gates(case, raw, processes, observations, recorded, trusted):
    for spec in case["input"]["gates"]:
        matches = [(pid, observation["functionalGates"][spec["name"]])
                   for pid, (observation, _, _) in observations.items()
                   if spec["name"] in observation["functionalGates"] and observation["functionalGates"][spec["name"]]["armed"]]
        require(len(matches) == 1, "An SDK functional control was omitted or armed in two original lifetimes")
        pid, gate = matches[0]
        _same(gate["specification"], spec, "An SDK functional gate changed its source declaration")
        require(gate["reached"] is True and len(gate["hits"]) == 1,
                "An SDK gate was not reached by an actual eligible original frame")
        receipt = gate["hits"][0]
        observation, events, returns = observations[pid]
        require(receipt["pid"] == pid and receipt["actor"] == spec["actor"]
                and receipt["callLabel"] == spec["callLabel"] and receipt["boundary"] == spec["boundary"],
                "An actual SDK control borrowed another original actor/call/frame")
        trigger = events[receipt["triggerSequence"]]
        require(trigger.get("callLabel", trigger.get("label")) == spec["callLabel"]
                and trigger["threadId"] == receipt["threadId"],
                "An SDK control was detached from its original source-thread trigger")
        if spec.get("pause") is not False:
            killed = any(step["operation"] == "stop-original-process" and step.get("atGate") == spec["name"]
                         and step["mode"] == "SIGKILL" for step in case["input"]["steps"])
            require(gate["released"] is (not killed) and (not killed or processes[pid]["exit"]["code"] == -9),
                    "An SDK original frame was released early or its alleged marker kill was not genuine")
        if receipt["originalFrame"] is not None:
            _sdk_code_owner(receipt["originalFrame"], recorded, trusted)
            _same(receipt["originalFrame"], trigger.get("code", receipt["originalFrame"]),
                  "An SDK functional gate borrowed another original code object")
        for parent in receipt["originalParentFrames"]:
            _sdk_code_owner(parent["code"], recorded, trusted)
            require(any(owner["storeObjectId"] == parent["exactStoreObjectId"] for owner in observation["ownerBindings"]),
                    "An SDK producer frame borrowed another store receiver")
        boundary = spec["boundary"]
        if boundary == "rebuild.revision-captured-before-publication":
            require(trigger["event"] == "original-call" and trigger["name"] == "SQLiteMemoryStore.publish_prepared_index"
                    and "prepared" in receipt["originalArguments"] and "expected_revision" in receipt["originalArguments"]
                    and receipt["originalParentFrames"], "The SDK old builder lacks its actual live prepared producer frame")
            expected = receipt["originalArguments"]["expected_fence_revision"]
            frames = [parent for parent in receipt["originalParentFrames"] if "expected_fence" in parent["locals"]]
            require(frames and any(parent["locals"]["expected_fence"] == expected for parent in frames),
                    "The SDK producer refreshed its captured expected fence before publication")
        elif boundary == "publication.fence-checked-before-table-writes":
            require(trigger["event"] == "original-call" and trigger["name"] == "write_prepared_index",
                    "The SDK postcheck control did not hold the actual original table writer")
            checks = [row for row in events.values() if row["event"] == "original-call"
                      and row["name"] in {"IndexRevisionFence.assert_unchanged", "IndexRevisionFence.assert_unchanged_in"}
                      and row["callLabel"] == spec["callLabel"] and row["sequence"] < trigger["sequence"]]
            if case["input"]["storageProfile"]["sdk"]["revisionFence"] == "actual-ledger-revision-fence":
                require(checks and checks[-1]["sequence"] in returns,
                        "The SDK postcheck gate bypassed its original live fence check")
                check = returns[checks[-1]["sequence"]]
                scalars = check["frameScalars"]
                require("live" in scalars and "expected" in scalars and scalars["live"] == scalars["expected"],
                        "The SDK postcheck gate lost its actual source-frame expected/live fence values")
        elif boundary == "forget.marker-committed-before-purge":
            require(trigger["event"] == "original-call" and trigger["name"] == "purge_memory_index",
                    "SDK forget was killed outside the original marker-before-purge frame")
            markers = [row for row in events.values() if row["event"] == "original-call"
                       and row["name"] == "MemoryEntryOriginLedger.record_session_tombstones_if_lineage_current"
                       and row["callLabel"] == spec["callLabel"] and row["sequence"] < trigger["sequence"]]
            require(markers and returns[markers[-1]["sequence"]]["returned"] is True,
                    "The SDK killed forget lacks the actual committed guarded marker return")
            require(any(row["statement"].strip().upper() == "COMMIT" and row["sequence"] < trigger["sequence"]
                        for row in observation["sqlStatements"]), "The SDK marker-before-purge gate has no genuine original COMMIT receipt")
        elif boundary == "forget.marker-commit-or-original-workspace-or-writer-wait":
            if receipt["progressKind"] == "actual-marker-COMMIT-returned":
                require(trigger["event"] == "original-return" and trigger["returned"] is True,
                        "SDK forget progress fabricated an original guarded marker return")
            else:
                require(receipt["progressKind"] == "actual-original-SQLite-writer-attempt"
                        and trigger["event"] in {"original-sql", "original-sql-c-call"},
                        "SDK forget progress was guessed from elapsed time")
                execution = events[receipt["sqlExecutionSequence"]]
                stage = next(step for step in raw["steps"] if step["specification"]["operation"] == "await-gate"
                             and step["specification"]["gate"] == spec["name"])
                observed = stage["returned"]["hits"][0]
                _same(observed, receipt, "The actual SDK writer progress receipt changed after its admission")
                require(execution["sequence"] <= trigger["sequence"] and execution["source"] in {
                    "SQLiteMemoryStore.connect", "MemoryEntryOriginLedger._open_write"},
                    "SDK pending writer progress did not reach an actual owned original SQLite call")
        elif boundary == "search.keyword-result-before-enrichment":
            require(trigger["event"] == "original-return" and trigger["name"] == "SQLiteMemoryStore._search_keyword_with_fallback"
                    and isinstance(trigger["returned"], list), "SDK in-flight search gate lacks its actual complete original keyword return")
        elif boundary == "promotion.source-planned-before-final-lock":
            require(trigger["event"] == "original-call" and trigger["name"] == "acquire_short_term_promotion_lock"
                    and receipt["originalParentFrames"], "The SDK direct promotion gate lacks its actual original source-planning frame")
        else:
            require(trigger["event"] == "declared-model-promise" and spec["callLabel"] in {
                call["label"] for call in observation["publicCalls"].values() if call.get("modelRequests")},
                "The SDK model planning gate did not hold its actual original completion request")


def validate_capture(case, capture, result, *, native, approved_node=None, approved_sdk_root=None,
                     trusted_archive=None, directory=None, approved_reference=None):
    """Authenticate one actual engine independently; no policy match is required."""
    try:
        validate_result(case, result)
        return (_native_capture(case, capture, result, directory, approved_node, trusted_archive, approved_reference)
                if native else _sdk_capture(case, capture, result, directory, approved_sdk_root))
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, OSError, UnicodeError,
            json.JSONDecodeError) as error:
        raise ValueError(("Native" if native else "SDK") + " forget/index-fence custody is structurally incomplete: " + str(error)) from error


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result, *, approved_node=None,
                  approved_sdk_root=None, trusted_archive=None, native_directory=None, sdk_directory=None,
                  approved_reference=None):
    """Custody precedes parity; genuine original differences remain differences."""
    validate_capture(case, native_raw, native_result, native=True, approved_node=approved_node,
                     trusted_archive=trusted_archive, directory=native_directory, approved_reference=approved_reference)
    validate_capture(case, sdk_raw, sdk_result, native=False, approved_sdk_root=approved_sdk_root,
                     directory=sdk_directory)
    return True


def replay_case(case, native_directory, sdk_directory=None, *, approved_node=None,
                approved_sdk_root=None, trusted_archive=None, approved_reference=None):
    """Replay explicit retained transports; the SDK directory contains its raw file.

    A full-pair transport is a mapping with exactly ``nativeDirectory`` and
    ``sdkDirectory``. No previous packet, development root, or sibling capture
    is selected implicitly.
    """
    if isinstance(native_directory, dict):
        require(sdk_directory is None and set(native_directory) == {"nativeDirectory", "sdkDirectory"},
                "An explicit pair transport must name both actual engine directories")
        sdk_directory = native_directory["sdkDirectory"]
        native_directory = native_directory["nativeDirectory"]
    require(sdk_directory is not None, "Replay requires the explicitly selected separate SDK raw directory")
    native_directory, sdk_directory = Path(native_directory).resolve(strict=True), Path(sdk_directory).resolve(strict=True)
    native_values = _read(native_directory / "evidence/native-raw.json", native_directory)
    sdk_values = _read(sdk_directory / "python-raw.json", sdk_directory)
    require(isinstance(native_values, list) and isinstance(sdk_values, list)
            and len(native_values) == len(sdk_values) == 1,
            "Replay requires exactly one genuine new capture per engine")
    returned = _read(native_directory / "stdout.json", native_directory)
    require(returned["ok"] is True and returned["id"] == case["id"], "The original Native public stdout failed")
    native_result, sdk_result = returned["result"], sdk_values[0]["observation"]["result"]
    validate_pair(case, native_values[0], sdk_values[0], native_result, sdk_result,
                  approved_node=approved_node, approved_sdk_root=approved_sdk_root,
                  trusted_archive=trusted_archive, native_directory=native_directory, sdk_directory=sdk_directory,
                  approved_reference=approved_reference)
    return {"validated": True, "publicMatch": _same_json(native_result, sdk_result),
            "nativeSnapshots": len(native_result["snapshots"]), "sdkSnapshots": len(sdk_result["snapshots"]),
            "acceptancePointsAwarded": 0}


# V8 is used strictly as a decoder. No program, module, or executable selected by
# captured metadata is evaluated by replay.
V8_DECODER = r'''
import {deserialize} from 'node:v8';
import fs from 'node:fs';
function carrier(value, seen=new WeakSet()) {
  if(value===undefined)return {privateType:'undefined'};
  if(typeof value==='bigint')return {privateType:'bigint',value:value.toString()};
  if(typeof value==='number'&&!Number.isFinite(value))return {privateType:'number',value:String(value)};
  if(value===null||typeof value!=='object')return value;
  if(value instanceof Error)return {privateType:'Error',name:value.name,message:value.message,stack:value.stack??null,
    ...(value.cause===undefined?{}:{cause:carrier(value.cause,seen)})};
  if(ArrayBuffer.isView(value))return {privateType:value.constructor.name,byteLength:value.byteLength,hex:Buffer.from(value.buffer,value.byteOffset,value.byteLength).toString('hex')};
  if(value instanceof ArrayBuffer)return {privateType:'ArrayBuffer',byteLength:value.byteLength,hex:Buffer.from(value).toString('hex')};
  if(seen.has(value))throw Error('Unreviewed repeated/cyclic V8 value');
  seen.add(value);
  if(value instanceof Map)return {privateType:'Map',entries:[...value].map(([k,v])=>[carrier(k,seen),carrier(v,seen)])};
  if(value instanceof Set)return {privateType:'Set',values:[...value].map(v=>carrier(v,seen))};
  if(Array.isArray(value))return value.map(v=>carrier(v,seen));
  return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,carrier(v,seen)]));
}
const input=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(input.map(hex=>carrier(deserialize(Buffer.from(hex,'hex'))))));
'''
_V8_CACHE = {}


def _decode_v8(authority, wires, approved_node):
    require(approved_node is not None, "Replay requires an independently selected approved Node binary")
    binary = _regular(Path(approved_node).resolve(strict=True))
    digest = _digest(binary)
    require(str(binary) == authority["execPath"] and digest == authority["sha256"] == NODE_SHA256,
            "Captured Node authority differs from the independently approved decoder")
    for wire in wires:
        require(isinstance(wire, str) and len(wire) % 2 == 0 and re.fullmatch(r"[0-9a-f]*", wire) is not None,
                "An original V8 carrier is not complete hexadecimal bytes")
    decoder = _sha(V8_DECODER.encode())
    missing = list(dict.fromkeys(wire for wire in wires if (digest, decoder, wire) not in _V8_CACHE))
    if missing:
        finished = subprocess.run([str(binary), "--input-type=module", "-e", V8_DECODER],
            input=json.dumps(missing), capture_output=True, text=True, timeout=30,
            cwd="/tmp", env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
        require(finished.returncode == 0 and not finished.stderr, "Independent approved V8 decoding failed")
        values = _json(finished.stdout)
        require(isinstance(values, list) and len(values) == len(missing), "V8 replay dropped an original carrier")
        for wire, value in zip(missing, values, strict=True):
            _V8_CACHE[digest, decoder, wire] = value
    return [_V8_CACHE[digest, decoder, wire] for wire in wires]
