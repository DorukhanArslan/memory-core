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
        result.setdefault((code.co_qualname, code.co_firstlineno), set()).add(_sha(code.co_code))
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
    require(row["bytecodeSha256"] in _bytecodes(str(source), digest).get((row["qualname"], row["firstLine"]), set()),
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
    if isinstance(case, dict) and case.get("operation") == "forget-index-fence-v2-runtime":
        from equivalence.forget_index_fence_v2 import validate_case
    else:
        from equivalence.forget_index_fence import validate_case
    validate_case(case)
    return case["input"]


def _v2(case):
    return case["operation"] == "forget-index-fence-v2-runtime"


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
    profile = context["forgetIndexFenceV2Profile" if _v2(case) else "forgetIndexFenceProfile"]
    require(profile["kind"] == case["input"]["kind"] and profile["operation"] == case["operation"]
            and profile["caseId"] == case["id"] and profile["acceptancePointsAwarded"] == 0
            and profile["caseWireSha256"] == _digest(request_path),
            "Native original process used an undeclared execution profile")
    _same(profile["gates"], case["input"]["gates"], "Native actual gate declarations differ from frozen input")
    _same(profile["actorClocks"], {"coordinator": case["input"]["clock"]["nowMs"],
          "observer": case["input"]["clock"]["nowMs"], **dict.fromkeys(case["input"]["actors"], case["input"]["clock"]["nowMs"])},
          "Native process wall-clock capabilities were silently equalized")
    program_root = Path(process["cwd"])
    allowed = {row["path"]: row["sha256"] for row in context["allowedLocal"]}
    local_names = ("entry", "runtime", "preload", "source-clock") if _v2(case) else ("entry", "runtime", "preload")
    require(len(allowed) == len(local_names) and set(allowed) == {str(program_root / "equivalence" / f"forget-index-fence-{name}.mjs")
                for name in local_names}, "Native execution allowed an undeclared local program")
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
        loaded, release_imports, clock, gates = set(), [], [], []
        for row in rows[1:]:
            require(row["pid"] == pid and row["threadId"] == thread,
                    "An original Native import trace changed process or worker")
            if row["event"] == ("forget-index-fence-v2-bootstrap" if _v2(case) else "forget-index-fence-bootstrap"):
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
                release_imports.append({"package": package, "path": row["path"], "sha256": row["sha256"]})
                if package == "node_modules/openclaw":
                    loaded.add(row["path"])
        require(len(clock) == 1 and clock[0]["clock"]["apis"] == ["Date"]
                and clock[0]["clock"]["setTimeoutUnchanged"] is True
                and clock[0]["clock"]["performanceNowUnchanged"] is True,
                "Native original monotonic clocks or timers were replaced")
        _same(clock[0]["profile"], profile, "An original Native worker used another complete execution capability")
        by_pid[pid, thread] = {"bootstrap": boot, "loaded": loaded, "releaseImports": release_imports,
                              "clock": clock[0]["clock"], "gates": gates}
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
    _native_process_graph(case, raw, context, process, authority, by_pid, passive, approved_node or binary)
    if _v2(case):
        _native_ram_channels(directory, process, by_pid, passive)
    return context, process, authority, by_pid, passive


def _native_process_graph(case, raw, context, process, authority, imports, passive, approved_node):
    """Every original helper needs its actual source-owned launch and OS close."""
    graph = {raw["pid"]: {"ppid": raw["ppid"], "actor": "coordinator", "instance": 0,
                          "clock": case["input"]["clock"]["nowMs"]}}
    for child in raw["children"]:
        require(child["pid"] not in graph, "An actual Native process PID was duplicated")
        clock = case["input"]["clock"]["nowMs"]
        for step in raw["steps"]:
            if "wallClockNowMs" in step["step"] and _ns(step["startedAtNs"]) <= _ns(child["startedAtNs"]):
                clock = step["step"]["wallClockNowMs"]
        graph[child["pid"]] = {"ppid": raw["pid"], "actor": child["actor"], "instance": child["instance"], "clock": clock}
    allowed = {(package["location"], row["path"]): row["sha256"]
               for package in context["runtime"]["packages"] for row in package["files"]}
    package_root = Path(context["runtime"]["runtimeRoot"]).parent.parent
    def source(record, owner_key):
        require(isinstance(record, dict) and record["kind"] == "release"
                and allowed.get((record["package"], record["path"])) == record["sha256"],
                "An original Native helper used an unapproved source caller or entrypoint")
        filename = package_root / _relative(record["package"]) / _relative(record["path"])
        require(record["absolutePath"] == str(filename) and _digest(filename) == record["sha256"],
                "An actual Native helper source path differs from pinned original release bytes")
        require(any(row["package"] == record["package"] and row["path"] == record["path"]
                    and row["sha256"] == record["sha256"] for row in imports[owner_key]["releaseImports"]),
                "An actual Native helper source was not imported by its producing process/worker")
        return filename
    launches, lifecycle, messages = {}, {}, {}
    for key, rows in passive.items():
        for row in rows:
            if row["event"] == "original-child-spawn":
                require(row["launchId"] not in launches, "An actual original child launch was duplicated")
                launches[row["launchId"]] = key, row
            elif row["event"] in {"original-child-os-exit", "original-child-exit", "original-child-error"}:
                lifecycle.setdefault(row["launchId"], []).append((key, row))
            elif row["event"] == "original-child-message":
                messages.setdefault(row["launchId"], []).append((key, row))
    require(set(lifecycle) <= set(launches) and set(messages) <= set(launches),
            "An original helper return, error, or IPC message has no actual source launch")
    unresolved = dict(launches)
    while unresolved:
        progressed = False
        for launch_id, (key, row) in list(unresolved.items()):
            if row["pid"] not in graph:
                continue
            parent = graph[row["pid"]]
            require(key in imports and row["method"] in {"fork", "spawn"} and row["returnedChildRef"]
                    and row["ppid"] == parent["ppid"] and row["actor"] == parent["actor"]
                    and row["instance"] == parent["instance"] and isinstance(row["originalStack"], str),
                    "An actual original helper launch borrowed another process/worker/source frame")
            caller = source(row["sourceCaller"], key)
            require(row["method"] == "fork" and row["sourceCaller"]["package"] == "node_modules/openclaw"
                    and row["sourceCaller"]["path"] == "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs"
                    and row["sourceEntrypoint"]["package"] == "node_modules/openclaw"
                    and row["sourceEntrypoint"]["path"] == "dist/infra/sqlite-integrity.worker.js",
                    "An original Native helper did not use the source-declared integrity route")
            require(str(caller) in row["originalStack"] or caller.as_uri() in row["originalStack"],
                    "An actual original helper launch lost its source-owned call stack")
            paths = "|".join(re.escape(value) for value in (str(caller), caller.as_uri()))
            frame = re.search(r"at assertSqliteIntegrityWithProcess \((?:" + paths + r"):(\d+):\d+\)", row["originalStack"])
            source_lines = _compiled_text(str(caller), _digest(caller)).splitlines()
            require(frame is not None and 0 < int(frame[1]) <= len(source_lines)
                    and "fork(entry, [], {" in source_lines[int(frame[1]) - 1],
                    "An original integrity launch did not come from its actual pinned fork call site")
            require(row["executable"] == authority["execPath"] and row["argv"]
                    and row["argv"][0] == authority["execPath"] and Path(row["cwd"]).is_absolute(),
                    "An original Native helper executed a different binary or working directory")
            environment = row["environment"]
            require(environment["MEMORY_EQ_RELEASE_CONTEXT"] == process["contextPath"]
                    and environment["MEMORY_EQ_FIF_ACTOR"] == parent["actor"]
                    and environment["MEMORY_EQ_FIF_INSTANCE"] == str(parent["instance"])
                    and environment["OPENCLAW_STATE_DIR"] == raw["fixtureBase"]
                    and environment["OPENCLAW_CONFIG_PATH"] == context["configPath"]
                    and environment["NODE_OPTIONS"] == process["environment"]["NODE_OPTIONS"]
                    and environment["HOME"] == environment["OPENCLAW_HOME"] == raw["fixtureBase"]
                    and environment["MEMORY_EQ_FIF_CLOCK_NOW_MS"] == str(row["wallClockNowMs"]),
                    "An original Native helper borrowed ambient state, actor identity, clock, or preload authority")
            permitted_clocks = {case["input"]["clock"]["nowMs"], case["input"]["clock"].get("recoveryNowMs")}
            require(type(row["wallClockNowMs"]) is int and row["wallClockNowMs"] in permitted_clocks,
                    "An original Native helper used an undeclared wall-clock phase")
            _native_child_arguments(row, authority, approved_node)
            ends = lifecycle.get(launch_id, [])
            require(all(owner == key and item["childPid"] == row["childPid"]
                        and item["sequence"] > row["sequence"] for owner, item in ends),
                    "An original helper lifecycle receipt borrowed another actual child object")
            closes = [item for _, item in ends if item["event"] == "original-child-exit"]
            exits = [item for _, item in ends if item["event"] == "original-child-os-exit"]
            errors = [item for _, item in ends if item["event"] == "original-child-error"]
            require(len(closes) == 1 and closes[0]["spawnSequence"] == row["sequence"]
                    and (closes[0]["code"] is None or type(closes[0]["code"]) is int)
                    and (closes[0]["signal"] is None or isinstance(closes[0]["signal"], str)),
                    "An original Native helper has no actual OS close settlement")
            child_pid = row["childPid"]
            if child_pid is None:
                require(errors and not exits, "An unspawned original helper lacks its actual source-owned launch error")
                for error in errors:
                    decoded = _native_value(error["error"], authority, approved_node)
                    require(decoded["privateType"] == "Error" and decoded["message"] == error["message"],
                            "An original helper launch error lost its actual exception carrier")
            else:
                require(type(child_pid) is int and child_pid > 0 and child_pid not in graph
                        and (child_pid, 0) in imports and len(exits) == 1
                        and row["sequence"] < exits[0]["sequence"] < closes[0]["sequence"]
                        and exits[0]["spawnSequence"] == row["sequence"]
                        and exits[0]["code"] == closes[0]["code"] and exits[0]["signal"] == closes[0]["signal"],
                        "An original helper PID was substituted or its actual OS exit/close was omitted")
                entrypoint = source(row["sourceEntrypoint"], (child_pid, 0))
                require(row["modulePath"] == str(entrypoint) and str(entrypoint) in row["argv"],
                        "An original Native helper executed another actual release entrypoint")
                graph[child_pid] = {"ppid": row["pid"], "actor": parent["actor"],
                                    "instance": parent["instance"], "clock": row["wallClockNowMs"]}
            for owner, message in messages.get(launch_id, []):
                require(owner == key and message["childPid"] == child_pid
                        and message["direction"] in {"parent-to-child", "child-to-parent"}
                        and row["sequence"] < message["sequence"] < closes[0]["sequence"],
                        "An actual original helper IPC message lost its producing launch/object/lifetime")
                _same(_native_value(message["message"], authority, approved_node), message["messageJSON"],
                      "An actual original helper IPC payload was rewritten or truncated")
            _native_integrity_messages([message for _, message in messages.get(launch_id, [])], raw["fixtureBase"])
            for error in errors:
                decoded = _native_value(error["error"], authority, approved_node)
                require(decoded["privateType"] == "Error" and decoded["message"] == error["message"],
                        "An original helper error differs from its complete actual V8 exception")
            del unresolved[launch_id]
            progressed = True
        require(progressed, "An original helper process has no authenticated parent launch chain")
    mains = {pid for pid, thread in imports if thread == 0}
    require(mains == set(graph), "An actual Native process bootstrap has no genuine original spawn receipt")
    for (pid, thread), item in imports.items():
        require(pid in graph, "An original Native worker borrowed an unknown process")
        identity, boot = graph[pid], item["bootstrap"]
        require(boot["ppid"] == identity["ppid"] and boot["actor"] == identity["actor"]
                and boot["instance"] == identity["instance"],
                "An original Native main/worker bootstrap lost its actual process lineage")
        if thread == 0:
            require(item["clock"]["nowMs"] == identity["clock"],
                    "An original Native process bootstrap changed its actual source-owned wall-clock phase")
        else:
            dispatches = [row for (parent_pid, _), rows in passive.items() if parent_pid == pid
                          for row in rows if row["event"] == "original-worker-first-dispatch"
                          and row["workerThreadId"] == thread]
            require(len(dispatches) == 1 and dispatches[0]["wallClockNowMs"] == item["clock"]["nowMs"],
                    "An original Native worker has no actual dispatch/clock receipt from its producing process")


def _native_child_arguments(spawn, authority, approved_node):
    """Bind V8's host-class loss to the independently observed fork target.

    V8 preserves the complete original bytes but serializes URL and AbortSignal
    host objects as empty objects. Only those exact original fork parameters
    have additional typed observations; ordinary arguments remain exact.
    """
    request = spawn["request"]
    original = _native_value(request["originalArgs"], authority, approved_node)
    options = _native_value(request["options"], authority, approved_node)
    observed_options = request["optionsJSON"]
    require(isinstance(observed_options, dict), "Original helper options lost their actual complete object")
    require({"execArgv", "serialization", "stdio", "timeout", "killSignal"} <= set(observed_options)
            and set(observed_options) <= {"execArgv", "serialization", "stdio", "timeout", "killSignal", "signal"}
            and observed_options["execArgv"] == spawn["execArgv"] == []
            and observed_options["serialization"] == "advanced"
            and observed_options["stdio"] == ["ignore", "ignore", "ignore", "ipc"]
            and observed_options["killSignal"] == "SIGKILL",
            "An original Native integrity fork changed its actual source-declared options")
    expected_options = dict(observed_options)
    if "signal" in expected_options:
        signal_ = expected_options["signal"]
        require(isinstance(signal_, dict) and set(signal_) == {"privateType", "aborted", "reason", "ref"}
                and signal_["privateType"] == "AbortSignal" and type(signal_["aborted"]) is bool
                and isinstance(signal_["ref"], str) and signal_["ref"],
                "An original fork signal lost its actual host-class/state/ref observation")
        expected_options["signal"] = {}
    _same(options, expected_options, "Original helper options differ from their complete V8 fields and typed signal witness")
    observed = request["argumentsJSON"]
    if spawn["method"] == "fork" and isinstance(observed, list) and observed:
        target = observed[0]
        if isinstance(target, dict) and target.get("privateType") == "URL":
            require(set(target) == {"privateType", "href"}
                    and target["href"] == Path(spawn["modulePath"]).as_uri()
                    and spawn["modulePath"] in spawn["argv"]
                    and spawn["sourceEntrypoint"]["absolutePath"] == spawn["modulePath"],
                    "An original fork URL lost its actual argv/approved-entrypoint relationship")
            require(len(observed) == 3 and _same_json(observed[2], observed_options),
                    "An original fork argument list omitted its actual options object")
            _same(original, [{}, observed[1], expected_options],
                  "The complete original fork V8 arguments differ outside their declared host-class fields")
            return
    _same(original, observed, "An original Native helper launch lost its complete actual argument carrier")


def _native_integrity_messages(rows, fixture):
    active, phases, previous, closed, checks = None, [], None, False, 0
    for receipt in rows:
        message = receipt["messageJSON"]
        if receipt["direction"] == "parent-to-child":
            if _same_json(message, {"type": "close"}):
                require(active is None and previous is not None and previous[0].get("reuse") is True
                        and previous[1]["ok"] is True and not closed,
                        "An original integrity close has no actual completed reusable request")
                closed = True
                continue
            require(active is None and not closed and isinstance(message, dict)
                    and {"pathname", "databaseLabel", "identity", "busyTimeoutMs", "tables"} <= set(message)
                    and set(message) <= {"pathname", "databaseLabel", "identity", "busyTimeoutMs", "tables", "reuse"},
                    "An original integrity request overlaps another request or lost actual source fields")
            path = Path(message["pathname"])
            require(path.is_absolute() and ".." not in path.parts and path.is_relative_to(Path(fixture))
                    and isinstance(message["databaseLabel"], str) and type(message["busyTimeoutMs"]) is int
                    and message["busyTimeoutMs"] >= 0 and ("reuse" not in message or message["reuse"] is True),
                    "An original integrity request borrowed an unowned actual database or changed source options")
            identity = message["identity"]
            require(isinstance(identity, dict) and set(identity) == {"dev", "ino", "size"}
                    and all(isinstance(value, dict) and set(value) == {"privateType", "value"}
                            and value["privateType"] == "bigint" and isinstance(value["value"], str)
                            and value["value"].isdigit() for value in identity.values()),
                    "An original integrity request lost its complete native file identity")
            tables = message["tables"]
            require(tables == {"privateType": "undefined"} or isinstance(tables, list)
                    and all(isinstance(table, dict) and set(table) == {"table", "check"}
                            and isinstance(table["table"], str) and table["check"] in {"quick_check", "integrity_check"}
                            for table in tables), "An original integrity request rewrote its actual table checks")
            active, phases = message, []
        else:
            require(active is not None and not closed and isinstance(message, dict),
                    "An original integrity reply has no actual outstanding request")
            if message.get("type") == "phase":
                phases.append(message["phase"])
                require(set(message) == {"type", "phase"} and phases in (
                    ["opening"], ["opening", "checking"], ["opening", "closing"], ["opening", "checking", "closing"]),
                    "Original integrity worker phases were omitted, duplicated, or reordered")
                continue
            require(type(message.get("ok")) is bool and set(message) <= {"ok", "checkElapsedMs", "tables", "error"}
                    and phases and (message["ok"] is False or phases == ["opening", "checking", "closing"])
                    and (message["ok"] is False or "error" not in message),
                    "An original integrity worker result lost its actual complete outcome/lifetime")
            if "checkElapsedMs" in message:
                require(type(message["checkElapsedMs"]) in (int, float) and math.isfinite(message["checkElapsedMs"])
                        and message["checkElapsedMs"] >= 0, "An original integrity timing number was stripped or rewritten")
            if message["ok"] is False:
                error = message["error"]
                require(isinstance(error, dict) and {"name", "message", "code", "errcode"} <= set(error)
                        and isinstance(error["name"], str) and isinstance(error["message"], str),
                        "An original integrity error lost its actual message/code fields")
            if "tables" in message:
                require(isinstance(message["tables"], list) and all(isinstance(table, dict)
                        and set(table) == {"table", "check", "elapsedMs"} and isinstance(table["table"], str)
                        and table["check"] in {"quick_check", "integrity_check"}
                        and type(table["elapsedMs"]) in (int, float) and math.isfinite(table["elapsedMs"])
                        and table["elapsedMs"] >= 0 for table in message["tables"]),
                        "Original integrity per-table timing/error numbers were removed or rewritten")
            previous, active, phases, checks = (active, message), None, [], checks + 1
    require(active is None and checks and (previous[0].get("reuse") is not True or previous[1]["ok"] is False or closed),
            "An original integrity process did not settle its actual checks and close protocol")


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
    require(error["publicFields"]["message"] == error["message"]
            and ("code" in error) is ("code" in error["publicFields"]),
            "An SDK public error fabricated or dropped an actual accessible error code")
    if "code" in error:
        _same(error["code"], error["publicFields"]["code"], "An SDK public error rewrote the actual accessible error code")
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


def _clock_stat(row, *, native):
    names = ({"dev": "dev", "ino": "ino", "mode": "mode", "nlink": "nlink", "size": "size",
              "mtimeNs": "mtimeNs", "ctimeNs": "ctimeNs", "atimeNs": "atimeNs"} if native else
             {"dev": "st_dev", "ino": "st_ino", "mode": "st_mode", "nlink": "st_nlink", "size": "st_size",
              "mtimeNs": "st_mtime_ns", "ctimeNs": "st_ctime_ns", "atimeNs": "st_atime_ns"})
    require(isinstance(row, dict) and set(names.values()) <= set(row), "A complete source-clock stat witness was stripped")
    result = {}
    for name, field in names.items():
        value = row[field]
        require(isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value) is not None,
                "An original source-clock stat field lost its exact integer carrier")
        result[name] = int(value)
    require(stat.S_ISREG(result["mode"]) and result["nlink"] == 1 and result["size"] >= 0,
            "A source-clock operation did not retain an owned single-link regular inode")
    return result


def _clock_path(filename, workspace, *, source=True):
    path, base = Path(filename), Path(workspace)
    require(path.is_absolute() and ".." not in path.parts and path.is_relative_to(base) and path != base
            and (not source or path.suffix.lower() in {".md", ".txt"}),
            "A source clock borrowed an unowned source, private state, or staged path")
    return path


def _native_clock_state(state):
    data = bytes.fromhex(state["bytesHex"])
    require(data.hex() == state["bytesHex"] and _sha(data) == state["sha256"],
            "Native clock byte verification lost its complete original bytes or digest")
    stats = [_clock_stat(state[key], native=True) for key in ("fdStat", "pathStat", "readerStat", "afterReadStat")]
    fields = ("dev", "ino", "nlink", "size", "mtimeNs", "ctimeNs")
    require(all(all(row[key] == stats[0][key] for key in fields) for row in stats)
            and stats[0]["size"] == len(data),
            "Native clock descriptor/path/reader observations borrowed another inode or changed bytes during inspection")
    return stats[0]


def _native_clock_owner(owner, stack, context, imports, pid):
    require(isinstance(owner, dict) and owner["kind"] == "release", "A Native clock writer has no actual original source owner")
    package_root = Path(context["runtime"]["runtimeRoot"]).parent.parent
    path = package_root / _relative(owner["package"]) / _relative(owner["path"])
    require(owner["absolutePath"] == str(path) and _digest(path) == owner["sha256"]
            and isinstance(stack, str) and (str(path) in stack or path.as_uri() in stack)
            and any(row["package"] == owner["package"] and row["path"] == owner["path"]
                    and row["sha256"] == owner["sha256"] for (process_pid, _), loaded in imports.items()
                    if process_pid == pid for row in loaded["releaseImports"]),
            "A Native source clock borrowed another loaded writer, source bytes, or call stack")


def _native_clock_control_v2(case, control, *, actor, child, context, imports, passive, authority, approved_node):
    policy = case["input"]["clock"]["sourceWriteClock"]
    tick = policy["ticksByCall"][control["callKey"]]
    _same(control["tick"], tick, "Native source clock replaced its independently frozen literal tick")
    require(control["actor"] == tick["actor"] == actor["actor"] == child["actor"]
            and type(control["ordinal"]) is int and control["ordinal"] == tick["ordinal"]
            and control["status"] == "clocked" and "controlError" not in control,
            "A Native source control changed actor/ordinal or failed its actual timestamp operation")
    workspace = Path(actor["request"]["fixtureBase"]) / "workspace"
    target = _clock_path(control["path"], workspace)
    frame = control["causalFrame"]
    entries = [entry for entry in actor["calls"] if entry["id"] == frame["commandId"]]
    require(len(entries) == 1, "A Native clock has no actual originating public command")
    entry = entries[0]
    require(entry["operation"] in CALL_KINDS
            and CALL_KINDS[entry["operation"]] + ":" + entry["label"] == control["callKey"],
            "A Native source clock guessed or refreshed the original causal API entry")
    _same(frame, {"commandId": entry["id"], "actor": actor["actor"], "instance": actor["instance"],
                  "pid": actor["pid"], "wallClockNowMs": tick["wallClockNowMs"], "enteredAtNs": entry["startedAtNs"]},
          "A Native source clock changed its actual causal public-entry frame")
    matching = [(key, row) for key, rows in passive.items() for row in rows
                if row["event"] == "source-clock-control" and row["controlId"] == control["controlId"]]
    require(len(matching) == 1, "Native source control lost its actual independently retained passive receipt")
    key, original = matching[0]
    require(key[0] == child["pid"] and original["actor"] == child["actor"]
            and original["instance"] == child["instance"] and control["handleRef"]
            and type(control["fd"]) is int and control["fd"] >= 0,
            "A Native clock control borrowed another process/worker/file handle")
    metadata = {"sequence", "pid", "ppid", "threadId", "instance", "atNs", "callLabel"}
    for name, value in original.items():
        if name not in metadata:
            _same(control[name], value, "A Native clock receipt changed after its actual controlled syscall")
    _native_clock_owner(control["sourceOwner"], control["originalStack"], context, imports, child["pid"])
    opened = control["open"]
    _native_clock_owner(opened["sourceOwner"], opened["originalStack"], context, imports, child["pid"])
    require(_ns(entry["startedAtNs"]) <= _ns(opened["atNs"]) < _ns(control["startedAtNs"]),
            "A Native clock handle was opened outside its actual original call lineage")
    require(control["writes"], "A Native source clock lacks its actual completed original write")
    for write in control["writes"]:
        require(write["status"] == "fulfilled" and _ns(opened["atNs"]) <= _ns(write["startedAtNs"])
                < _ns(write["finishedAtNs"]) <= _ns(control["startedAtNs"]),
                "A Native clock preceded the final actual successful original write completion")
        arguments = _native_value(write["arguments"], authority, approved_node)
        returned = _native_value(write["return"], authority, approved_node)
        require(write["method"] in {"fs.promises.writeFile", "writeFile", "write"},
                "A Native clock invented another original source-write operation")
        if write["method"] in {"fs.promises.writeFile", "writeFile"}:
            require(returned == {"privateType": "undefined"}, "An original Native writeFile lost its actual void return")
        else:
            require(isinstance(arguments, list) and isinstance(returned, dict)
                    and set(returned) == {"bytesWritten", "buffer"} and type(returned["bytesWritten"]) is int
                    and returned["bytesWritten"] >= 0,
                    "An original Native FileHandle.write lost its actual typed result")
    for sync in control["syncs"]:
        require(sync["method"] == "sync" and sync["status"] in {"fulfilled", "rejected"}
                and _ns(sync["startedAtNs"]) < _ns(sync["finishedAtNs"]) <= _ns(control["startedAtNs"]),
                "A Native clock omitted or preceded the actual original fsync settlement")
        if sync["status"] == "fulfilled":
            require(_native_value(sync["return"], authority, approved_node) == {"privateType": "undefined"},
                    "An original Native FileHandle.sync lost its actual void return")
        else:
            require(_native_value(sync["privateError"], authority, approved_node)["message"] == sync["error"]["message"],
                    "A Native original fsync error was fabricated or dropped")
    before, after = _native_clock_state(control["before"]), _native_clock_state(control["after"])
    require(all(before[name] == after[name] for name in ("dev", "ino", "nlink", "size"))
            and control["before"]["bytesHex"] == control["after"]["bytesHex"]
            and control["before"]["sha256"] == control["after"]["sha256"],
            "A Native clock changed the genuine staged/descriptor bytes or inode")
    stamp = control["utimes"]
    _same(stamp["arguments"], [tick["atimeMs"] / 1000, tick["mtimeMs"] / 1000],
          "Native source clock did not request both literal atime and mtime through the real handle")
    require(_ns(control["startedAtNs"]) <= _ns(stamp["startedAtNs"]) < _ns(stamp["finishedAtNs"])
            <= _ns(control["finishedAtNs"]) and "error" not in stamp
            and _native_value(stamp["return"], authority, approved_node) == {"privateType": "undefined"}
            and after["mtimeNs"] == tick["mtimeMs"] * 1_000_000,
            "Native source clock lacks its actual successful utimes return or exact target mtime")
    continuations = [row for row in passive[key] if row["event"] == "source-clock-continuation"
                     and row["controlId"] == control["controlId"]]
    require(len(continuations) == 1 and continuations[0]["sequence"] > original["sequence"],
            "Native source clock has no unique actual original continuation")
    continuation = continuations[0]
    if control["operation"] == "atomic":
        stage = _clock_path(control["stagePath"], workspace, source=False)
        require(stage != target and opened["path"] == str(stage)
                and opened["sourceOwner"].get("publicationRole") == "stage",
                "A Native atomic clock did not control the original owned staged inode")
        rename = control["rename"]
        _same(continuation["rename"], rename, "Native clock original rename differs from its actual passive continuation")
        _same(_native_value(rename["arguments"], authority, approved_node), [str(stage), str(target)],
              "A Native clocked stage was renamed to another original target")
        require(_ns(control["finishedAtNs"]) < _ns(rename["returnedAtNs"]),
                "Native clock ran after the original atomic rename made its source visible")
        if "error" in rename:
            require(not control.get("committed") and not control.get("published")
                    and _native_value(rename["privateError"], authority, approved_node)["message"] == rename["error"]["message"],
                    "An original failed Native rename acquired a fabricated successful publication")
            return None
        require(_native_value(rename["return"], authority, approved_node) == {"privateType": "undefined"}
                and control["committed"] is continuation["committed"] is True,
                "A Native atomic publication lost its actual original rename result")
        _same(control["published"], continuation["published"], "Native published inode differs from its actual rename continuation")
        published = _native_clock_state(control["published"])
        require(all(after[name] == published[name] for name in ("dev", "ino", "nlink", "size", "mtimeNs"))
                and control["published"]["bytesHex"] == control["after"]["bytesHex"],
                "The original Native rename did not publish the clocked same inode and bytes")
        committed_at = rename["returnedAtNs"]
    else:
        require(control["operation"] == "inPlace" and control["stagePath"] is None
                and opened["path"] == str(target) and opened["sourceOwner"].get("publicationRole") == "inPlace"
                and control["committed"] is True,
                "A Native in-place clock borrowed a staged or unowned original descriptor")
        close = control["close"]
        _same(close, continuation["close"], "Native original close differs from its actual passive continuation")
        require(_ns(control["finishedAtNs"]) <= _ns(close["startedAtNs"]) < _ns(close["finishedAtNs"]),
                "The Native source descriptor closed before its completed real clock operation")
        if "error" in close:
            require(_native_value(close["privateError"], authority, approved_node)["message"] == close["error"]["message"],
                    "A Native source close error lost its actual private exception")
        else:
            require(_native_value(close["return"], authority, approved_node) == {"privateType": "undefined"},
                    "An original Native FileHandle.close lost its actual void return")
        committed_at = control["finishedAtNs"]
    require(_ns(committed_at) < _ns(child["finishedAtNs"]), "Native source commit occurred outside its actual producer process lifetime")
    return {"path": str(target), "sha256": control["after"]["sha256"], "bytes": control["after"]["bytesHex"],
            "mtimeNs": after["mtimeNs"], "atNs": committed_at, "callKey": control["callKey"], "pid": child["pid"],
            "operation": control["operation"], "writeStartedAtNs": min(write["startedAtNs"] for write in control["writes"]),
            "clockFinishedAtNs": control["finishedAtNs"]}


def _native_source_clock_v2(case, raw, actors, imports, passive, context, authority, approved_node):
    policy = case["input"]["clock"]["sourceWriteClock"]
    _same(context["forgetIndexFenceV2Profile"]["sourceWriteClock"], policy,
          "Native clock capability differs from the independently frozen source-write policy")
    commits, reads, boundaries, control_ids = [], [], [], set()
    all_clock_events = [row for rows in passive.values() for row in rows if row["event"].startswith("source-clock-")]
    require(not raw.get("sourceClockFailures") and not any(row["event"] == "source-clock-failure" for row in all_clock_events),
            "A Native functional source clock failed while original results were retained")
    for pid, (child, actor) in actors.items():
        clock = actor["sourceClock"]
        require(clock["protocol"] == policy["protocol"] and clock["blocked"] is False and clock["failures"] == [],
                "Native source-clock control was missing, blocked, or retrospectively cleared")
        rows = clock["receipts"]
        actor_events = [row for row in all_clock_events if row["pid"] == pid]
        selected = [row for row in actor_events if row["event"] in {
            "source-clock-control", "source-clock-call-boundary", "source-clock-read", "source-clock-deletion"}]
        require(len(rows) == len(selected), "Native source-clock receipts omitted or duplicated actual passive events")
        claimed = set()
        for receipt in rows:
            event = receipt["event"]
            identity = ("controlId",) if event == "source-clock-control" else (("atNs",) if "atNs" in receipt
                         else ("startedAtNs", "finishedAtNs", "path", "method"))
            candidates = [row for row in selected if row["event"] == event
                          and all(row.get(name) == receipt.get(name) for name in identity)]
            require(len(candidates) == 1 and (candidates[0]["threadId"], candidates[0]["sequence"]) not in claimed,
                    "Native source-clock receipts are not one-to-one with actual passive source events")
            claimed.add((candidates[0]["threadId"], candidates[0]["sequence"]))
            if event == "source-clock-control":
                require(receipt["controlId"] not in control_ids, "A Native clocked source publication was duplicated")
                control_ids.add(receipt["controlId"])
                commit = _native_clock_control_v2(case, receipt, actor=actor, child=child, context=context,
                    imports=imports, passive=passive, authority=authority, approved_node=approved_node)
                if commit is not None:
                    commits.append(commit)
                continue
            require(event in {"source-clock-call-boundary", "source-clock-read", "source-clock-deletion"},
                    "An unknown Native clock receipt acquired custody")
            identity = ("atNs",) if "atNs" in receipt else ("startedAtNs", "finishedAtNs", "path", "method")
            matching = [row for row in actor_events if row["event"] == event
                        and all(row.get(name) == receipt.get(name) for name in identity)]
            require(len(matching) == 1, "A Native clock receipt lost its unique actual passive source observation")
            for name, value in receipt.items():
                _same(matching[0][name], value, "A Native clock observation changed after its actual original event")
            if event == "source-clock-call-boundary":
                _same(receipt["tick"], policy["ticksByCall"][receipt["callKey"]], "A Native call boundary changed its literal source tick")
                require(receipt["tick"]["actor"] == child["actor"], "A Native source boundary borrowed another actor's call")
                boundaries.append(receipt)
            else:
                _native_clock_owner(receipt["sourceOwner"], receipt["originalStack"], context, imports, pid)
                _clock_path(receipt["path"], Path(raw["fixtureBase"]) / "workspace")
                value = _native_value(receipt["return"], authority, approved_node)
                if event == "source-clock-read":
                    require(_ns(receipt["startedAtNs"]) < _ns(receipt["finishedAtNs"]), "A Native source reader lost its actual IO lifetime")
                    read = {"path": receipt["path"], "method": receipt["method"], "enteredAtNs": receipt["startedAtNs"],
                            "finishedAtNs": receipt["finishedAtNs"], "pid": pid}
                    if receipt["method"] in {"stat", "lstat"}:
                        require(isinstance(value, dict) and "mtimeMs" in value, "Native original source stat lost its actual mtime")
                        read["mtimeMs"] = value["mtimeMs"]
                    elif isinstance(value, str):
                        read.update(bytes=value.encode("utf8").hex(), sha256=_sha(value.encode("utf8")))
                    elif isinstance(value, dict) and "hex" in value:
                        read.update(bytes=value["hex"], sha256=_sha(bytes.fromhex(value["hex"])))
                    reads.append(read)
        require(claimed == {(row["threadId"], row["sequence"]) for row in selected},
                "A Native actual source event was omitted from its original actor's raw record")
    versions = {}
    for commit in commits:
        key = commit["callKey"], commit["path"]
        require(key not in versions or versions[key] == commit["sha256"],
                "One Native public call committed unsupported distinct byte revisions under one source tick")
        versions[key] = commit["sha256"]
    return {"commits": commits, "reads": reads, "boundaries": boundaries}


def _native_json(row, authority, approved_node):
    """Use the original actor's declared JSON/plain codec at that boundary."""
    view = _decode_v8_views(authority, [row["v8Hex"]], approved_node)[0]["json"]
    require(view["status"] == "serialized", "An original public JSON carrier is not JSON serializable")
    return _json(view["text"])


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
                    and args["purpose"] in {"cli", "tool", "status", "default", "maintenance"},
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
            _same(_native_json(entry["privateReturn"], authority, approved_node), tool["envelope"],
                  "Original public search result differs from its actual V8 JSON view")
            _same(tool["details"], tool["envelope"]["details"], "Whole public search details were replaced")
            require(tool["carrierJSON"] == tool["envelope"]["content"][0]["text"], "Original search text carrier was rewritten")
            _same(entry["originalArguments"], value["queries"][label], "Original Native public search arguments changed")
            outcome = {"status": "fulfilled", "result": tool["details"]}
        elif kind == "forget":
            write = entry["actualWriteJson"]
            report = _native_json(write["privateReturnValue"], authority, approved_node)
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
            actual_json = _native_json(entry["privateReturn"], authority, approved_node)
            _same(actual_json, entry["publicPromotionResult"], "The whole Native promotion result lost its original V8 JSON view")
            outcome = {"status": "fulfilled", "result": _promotion_result(actual_json, Path(actor["request"]["fixtureBase"]) / "workspace")}
    expected = {"operation": kind, "label": label, "outcome": outcome}
    _same(settlement["publicCall"], expected, "The Native IPC public outcome was truncated or repaired")
    return expected


def _native_gate_release(gate, raw, events, directory):
    """Authenticate consumption against the real release write interval."""
    steps = [row for row in raw["steps"] if row["step"]["operation"] == "release-gate"
             and row["step"]["gate"] == gate["name"]]
    require(len(steps) == 1, "A held Native gate has no unique actual release operation")
    step = steps[0]
    _same(_read(Path(directory) / "gates" / (gate["name"] + ".release"), directory), step["step"],
          "The Native original gate consumed a release file from another actual schedule step")
    require(_ns(gate["receipt"]["enteredAtNs"]) < _ns(step["startedAtNs"])
            <= _ns(gate["releasedAtNs"]) <= _ns(step["finishedAtNs"]),
            "Native release timestamps lost the original pre-write/post-write operation bracket")
    releases = [row for row in events if row["event"] == "fence-gate-release" and row["gate"] == gate["name"]]
    require(len(releases) == 1 and _ns(releases[0]["atNs"]) >= _ns(step["startedAtNs"]),
            "The held Native original frame never consumed its actual release")
    return releases[0], step


def _native_observed_value(row, authority, approved_node, *, opaque=False):
    if set(row) == {"v8Hex"}:
        return _native_value(row, authority, approved_node)
    require(opaque and set(row) in ({"serializationError"}, {"unserializable"}),
            "An actual Native private carrier was replaced or its V8 bytes were dropped")
    error = row.get("serializationError", row.get("unserializable"))
    require(isinstance(error, dict) and isinstance(error["name"], str) and isinstance(error["message"], str),
            "An original Native host serialization failure was stripped")
    return None


def _native_ram_channels(directory, process, imports, passive):
    protocol, token = "shared-original-event-jsonl-v1", process["contextSha256"]
    files, claimed = {}, {}
    for key in imports:
        pid, thread = key
        filename = _owned(Path(directory) / "evidence" / f"{pid}-{thread}-events.jsonl", directory)
        data = filename.read_bytes()
        require(data.endswith(b"\n"), "Native passive RAM log lost a complete immutable JSONL prefix")
        files[key] = data
        registered = [row for row in passive[key] if row["event"] == "passive-channel-register"]
        require(len(registered) == 1 and registered[0]["protocol"] == protocol
                and registered[0]["token"] == token and registered[0]["channelIndex"] == thread
                and registered[0]["initialBytes"] == 64 * 1024 and registered[0]["maxBytes"] == 64 * 1024 * 1024
                and registered[0]["slotCount"] == 128,
                "A Native actual thread lost its independently owned passive RAM channel")
    def channel(row, owner_pid):
        key = row["pid"], row["threadId"]
        require(key in files and row["pid"] == owner_pid and row["protocol"] == protocol and row["token"] == token
                and row["channelIndex"] == row["threadId"] and row["failureCode"] == 0,
                "A Native RAM seal borrowed another process/thread/context or hid a buffer failure")
        names = ("publishedBytes", "persistedBytes", "capacityBytes", "maxBytes", "failureCode", "channelIndex")
        require(all(type(row[name]) is int for name in names)
                and 0 <= row["publishedBytes"] <= row["persistedBytes"] <= len(files[key])
                and row["publishedBytes"] <= row["capacityBytes"] <= row["maxBytes"] == 64 * 1024 * 1024,
                "Native passive channel lost its actual atomic published/persisted prefix bounds")
        prefix = files[key][:row["publishedBytes"]]
        require((not prefix or prefix.endswith(b"\n")) and _sha(prefix) == row["sha256"],
                "Native passive prefix differs from its actual RAM byte seal")
        claimed[key] = max(claimed.get(key, 0), row["publishedBytes"])
    seals = list((Path(directory) / "evidence").glob("*-passive-seal.json"))
    require(seals, "Native selected SQL/transport RAM channels have no actual lifecycle checkpoint seal")
    for filename in seals:
        seal = _read(filename, directory)
        require(seal["protocol"] == protocol and seal["token"] == token and seal["failures"] == []
                and (seal["pid"], seal["flushingThreadId"]) in imports
                and filename.name == f'{seal["pid"]}-{seal["flushingThreadId"]}-passive-seal.json',
                "Native passive checkpoint seal lost its actual flushing thread/source context")
        _ns(seal["atNs"])
        require(len({row["threadId"] for row in seal["channels"]}) == len(seal["channels"]),
                "A Native passive checkpoint duplicated an actual thread channel")
        for row in seal["channels"]:
            channel(row, seal["pid"])
    require(set(claimed) == set(files) and all(claimed[key] == len(data) for key, data in files.items()),
            "A Native original thread lost an unflushed tail or supplied unsealed passive event bytes")


def _native_terminated_threads(context, imports, passive, authority, approved_node):
    workers, exited = {}, {}
    for (pid, _), rows in passive.items():
        for row in rows:
            if row["event"] == "original-worker-command-call" and row["workerThreadId"] > 0:
                key = pid, row["workerRef"]
                require(key not in workers or workers[key] == row["workerThreadId"],
                        "An original Native Worker object changed its actual thread identity")
                workers[key] = row["workerThreadId"]
    for (pid, thread), rows in passive.items():
        for row in rows:
            if row["event"] != "original-worker-lifecycle-event" or row["eventName"] != "exit":
                continue
            actual_thread = workers.get((pid, row["workerRef"]))
            key = pid, actual_thread
            require(key in imports and key not in exited, "A Native original Worker exit lost its actual object/thread ownership")
            _native_clock_owner(row["sourceCaller"], row["originalStack"], context, imports, pid)
            arguments = _native_transport_value(row["arguments"], authority, approved_node, pid=pid, thread=thread)
            require(isinstance(arguments, list) and arguments and type(arguments[0]) is int,
                    "An actual Native Worker exit lost its original numeric exit code")
            exited[key] = _ns(row["atNs"])
    return exited


def _native_sql_custody(raw, context, imports, passive, authority, approved_node):
    """Authenticate actual selected native SQL without replaying a query."""
    fixture = Path(raw["fixtureBase"])
    exited = _native_terminated_threads(context, imports, passive, authority, approved_node)
    operations = {"prepare", "exec", "get", "all", "run", "iterate", "columns", "setAllowBareNamedParameters",
                  "setAllowUnknownNamedParameters", "setReadBigInts", "setReturnArrays", "iterate.next", "iterate.return", "iterate.throw"}
    for key, rows in passive.items():
        pid, thread = key
        prefix = f"{pid}:{thread}:process-ref-"
        def valid_ref(value):
            return isinstance(value, str) and value.startswith(prefix) and value[len(prefix):].isdigit()
        installed = [row for row in rows if row["event"] == "original-sql-observer-installed"]
        require(len(installed) == 1 and installed[0]["storage"] == "shared-per-thread-immutable-jsonl"
                and installed[0]["statementMethods"] == ["get", "all", "run", "iterate", "columns", "setAllowBareNamedParameters",
                    "setAllowUnknownNamedParameters", "setReadBigInts", "setReturnArrays"]
                and installed[0]["iteratorMethods"] == ["next", "return", "throw"]
                and all(valid_ref(installed[0][name]) for name in ("databaseClassRef", "databasePrototypeRef", "prepareOriginalRef", "execOriginalRef")),
                "The actual Native thread never armed the complete source-owned SQL observation surface")
        bindings, calls, settled, statements = {}, {}, set(), {}
        for row in rows:
            event = row["event"]
            if event == "original-sql-method-binding":
                require(valid_ref(row["functionRef"]) and row["functionRef"] not in bindings
                        and row["functionSourceSha256"] == _sha(row["functionSource"].encode())
                        and "[native code]" in row["functionSource"]
                        and all(valid_ref(row[name]) for name in ("databaseClassRef", "databasePrototypeRef",
                                                                  "receiverPrototypeRef", "receiverConstructorRef")),
                        "An actual Native SQL callable lost its native function/class/prototype identity")
                bindings[row["functionRef"]] = row
                require(row["databaseClassRef"] == installed[0]["databaseClassRef"]
                        and row["databasePrototypeRef"] == installed[0]["databasePrototypeRef"],
                        "A Native selected SQL binding borrowed another installed database class")
                continue
            if event not in {"original-selected-sql-call", "original-selected-sql-return", "original-selected-sql-throw"}:
                continue
            require(row["operation"] in operations and valid_ref(row["databaseRef"])
                    and isinstance(row["sql"], str) and row["originalMethodRef"] in bindings
                    and bindings[row["originalMethodRef"]]["functionName"] == row["originalMethodName"]
                    == row["operation"].split(".")[-1],
                    "A selected Native SQL operation borrowed another database/method binding")
            require(row["transactionActive"] is None or type(row["transactionActive"]) is bool,
                    "Native SQL transaction state lost its actual type")
            path = row["dbPath"]
            require(path in (None, "", ":memory:") or (Path(path).is_absolute()
                    and Path(path).is_relative_to(fixture) and ".." not in Path(path).parts),
                    "An original Native selected SQL operation escaped its owned database fixture")
            if event == "original-selected-sql-call":
                require(row["callId"] not in calls, "An actual Native SQL invocation was duplicated")
                arguments = _native_observed_value(row["arguments"], authority, approved_node)
                require(isinstance(arguments, list), "Native original SQL lost its complete actual argument array")
                if row["operation"] in {"prepare", "exec"}:
                    _native_clock_owner(row["sourceCaller"], row["originalStack"], context, imports, pid)
                    require(row["statementRef"] is None and arguments and arguments[0] == row["sql"],
                            "Native SQL text differs from its actual original prepare/exec argument")
                    require(row["originalMethodRef"] == installed[0][row["operation"] + "OriginalRef"],
                            "A Native prepare/exec call bypassed its actually installed original native method")
                else:
                    statement = statements.get(row["statementRef"])
                    require(statement is not None and statement["databaseRef"] == row["databaseRef"]
                            and statement["sql"] == row["sql"],
                            "An actual Native statement operation lost its original prepare receiver/SQL")
                    _same(statement["sourceCaller"], row["sourceCaller"],
                          "A Native cached statement changed its original preparation owner")
                    package_root = Path(context["runtime"]["runtimeRoot"]).parent.parent
                    require(isinstance(row["originalStack"], str) and any(
                        str(package_root / _relative(owner["package"]) / _relative(owner["path"])) in row["originalStack"]
                        for (process_pid, _), loaded in imports.items() if process_pid == pid
                        for owner in loaded["releaseImports"]),
                        "A Native cached SQL statement was invoked outside an actual original source frame")
                calls[row["callId"]] = row
                continue
            require(row["callId"] in calls and row["callId"] not in settled,
                    "An original Native SQL settlement was duplicated or has no actual invocation")
            call = calls[row["callId"]]
            _same({name: row[name] for name in ("operation", "statementRef", "sql", "sourceCaller", "originalStack",
                   "originalMethodRef", "originalMethodName", "databaseRef")},
                  {name: call[name] for name in ("operation", "statementRef", "sql", "sourceCaller", "originalStack",
                   "originalMethodRef", "originalMethodName", "databaseRef")},
                  "A Native SQL result/error was reassigned to another original call")
            require(call["sequence"] < row["sequence"], "A Native SQL settlement preceded its actual invocation")
            settled.add(row["callId"])
            if event == "original-selected-sql-return":
                result = _native_observed_value(row["result"], authority, approved_node,
                                                opaque=row["operation"] in {"prepare", "iterate"})
                require(row["resultType"] in {"undefined", "object", "number", "bigint", "boolean", "string"},
                        "Native SQL lost its original returned type")
                if row["resultRef"] is not None:
                    require(valid_ref(row["resultRef"]) and type(row["resultPrototypeIsNull"]) is bool
                            and ((row["resultPrototypeIsNull"] is True and row["resultPrototypeRef"] is None)
                                 or (row["resultPrototypeIsNull"] is False and valid_ref(row["resultPrototypeRef"]))),
                            "Native SQL lost its actual returned object/prototype identity")
                if row["operation"] == "prepare":
                    require(valid_ref(row["resultRef"]) and row["resultRef"] not in statements,
                            "Native SQL prepare lost or reused its actual StatementSync object")
                    statements[row["resultRef"]] = call
                elif row["operation"] == "exec":
                    require(result == {"privateType": "undefined"} and row["resultType"] == "undefined",
                            "Original Native DatabaseSync.exec lost its actual void return")
            else:
                error = _native_observed_value(row["privateError"], authority, approved_node)
                require(error["privateType"] == "Error" and error["name"] == row["name"]
                        and error["message"] == row["message"] and error["stack"] == row["stack"]
                        and all(valid_ref(row[name]) for name in ("errorRef", "errorPrototypeRef", "errorConstructorRef")),
                        "An original Native SQLite exception lost its complete actual typed carrier")
                for field in row["ownProperties"]:
                    if "value" in field:
                        value = _native_observed_value(field["value"], authority, approved_node, opaque=True)
                        if field["key"] in {"message", "stack"}:
                            _same(value, row[field["key"]], "A Native SQL exception descriptor changed its actual error field")
        # Any retained unreturned call is an actual partial frame. It is never
        # converted into a void result or an inferred exception here.
        for call_id in set(calls) - settled:
            require((key in exited and _ns(calls[call_id]["atNs"]) < exited[key]) or any(
                    child["pid"] == pid and child["exit"] == {"code": None, "signal": "SIGKILL"} for child in raw["children"]),
                    "A live original Native SQL invocation lost its actual return/error receipt")


def _native_transport_value(payload, authority, approved_node, *, pid, thread):
    require(set(payload) == {"value", "privateJSON", "valueRef"}, "A Native transport payload lost its whole original carrier")
    prefix = f"{pid}:{thread}:process-ref-"
    def ref(value):
        require(isinstance(value, str) and value.startswith(prefix) and value[len(prefix):].isdigit(),
                "A Native transport host value borrowed another actual object identity")
    def projection(value):
        if isinstance(value, list):
            return [projection(item) for item in value]
        if not isinstance(value, dict):
            return value
        kind = value.get("privateType")
        if kind in {"SharedArrayBuffer", "ArrayBuffer"}:
            require(set(value) == {"privateType", "byteLength", "hex", "ref"} and type(value["byteLength"]) is int
                    and value["byteLength"] >= 0 and bytes.fromhex(value["hex"]).hex() == value["hex"]
                    and len(bytes.fromhex(value["hex"])) == value["byteLength"],
                    "A Native original transport buffer lost its complete actual bytes or size")
            ref(value["ref"])
            return value if kind == "SharedArrayBuffer" else {name: value[name] for name in ("privateType", "byteLength", "hex")}
        if kind in {"MessagePort", "function"}:
            require(set(value) == ({"privateType", "ref"} if kind == "MessagePort" else {"privateType", "name", "ref"}),
                    "A Native opaque transport value lost its actual host type/ref descriptor")
            ref(value["ref"])
            return value
        if kind == "reference":
            ref(value["ref"])
            return value
        if kind in {"URL", "AbortSignal"}:
            if kind == "AbortSignal":
                ref(value["ref"])
            return {}
        if kind == "Error":
            ref(value["ref"])
            require(isinstance(value["ownProperties"], list), "Native transport exception descriptors were dropped")
            if value["constructorName"] == "DOMException":
                return {}
            result = {"privateType": "Error", "name": value["name"], "message": value["message"], "stack": value.get("stack")}
            causes = [row for row in value["ownProperties"] if row["key"] == "cause" and "value" in row]
            require(len(causes) <= 1, "A Native transport exception cause was duplicated")
            if causes:
                result["cause"] = projection(causes[0]["value"])
            return result
        return {name: projection(item) for name, item in value.items()}
    def has_opaque(value):
        if isinstance(value, list):
            return any(has_opaque(item) for item in value)
        return isinstance(value, dict) and (value.get("privateType") in {"SharedArrayBuffer", "MessagePort", "function"}
                or any(has_opaque(item) for item in value.values()))
    observed = payload["privateJSON"]
    if payload["valueRef"] is not None:
        ref(payload["valueRef"])
    if isinstance(observed, dict) and "ref" in observed and observed.get("privateType") != "reference":
        require(observed["ref"] == payload["valueRef"], "A Native transport's original root host-object ref changed")
    expected = projection(observed)
    if set(payload["value"]) == {"v8Hex"}:
        _same(_native_value(payload["value"], authority, approved_node), expected,
              "A Native transport JSON/typed side observation differs from its complete actual V8 value")
    else:
        _native_observed_value(payload["value"], authority, approved_node, opaque=True)
        require(has_opaque(observed), "A Native transport V8 failure has no retained actual nonserializable host value")
    return observed


def _native_transport_custody(raw, context, imports, passive, authority, approved_node):
    families = {"original-worker-command": ("originalPostRef", "postMessage"),
                "original-worker-reply": ("originalEmitRef", "emit"),
                "original-message-port": ("originalPostRef", "postMessage")}
    exited = _native_terminated_threads(context, imports, passive, authority, approved_node)
    for (pid, thread), rows in passive.items():
        bindings, calls, settled, received = {}, {}, set(), {}
        known_workers = {row["workerRef"]: row["workerThreadId"] for row in rows
                         if row["event"] == "original-worker-command-call" and row["workerThreadId"] > 0}
        installed = [row for row in rows if row["event"] == "original-transport-observer-installed"]
        require(len(installed) == 1 and installed[0]["storage"] == "shared-per-thread-immutable-jsonl"
                and all(isinstance(installed[0][name], str) for name in ("workerClassRef", "workerPrototypeRef", "workerPostOriginalRef",
                    "workerEmitOriginalRef", "portClassRef", "portPrototypeRef", "portPostOriginalRef")),
                "The actual Native thread never armed its complete original Worker/MessagePort observation surface")
        for row in rows:
            event = row["event"]
            if event == "original-transport-method-binding":
                require(row["functionRef"] not in bindings and row["functionName"] in {"postMessage", "emit"}
                        and row["functionSourceSha256"] == _sha(row["functionSource"].encode())
                        and isinstance(row["sourceClassRef"], str) and isinstance(row["sourcePrototypeRef"], str),
                        "An original Native transport callable lost its source/class/function binding")
                bindings[row["functionRef"]] = row
                continue
            if event == "original-worker-reply-received":
                require(row["callId"] not in received, "An original Native worker notification was duplicated")
                received[row["callId"]] = row
            family = next((name for name in families if event in {name + "-call", name + "-return", name + "-throw"}), None)
            if family is None:
                continue
            function_ref, function_name = families[family]
            require(row[function_ref] in bindings and bindings[row[function_ref]]["functionName"] == function_name,
                    "An actual Native transport invocation borrowed a different original method")
            method = "portPostOriginalRef" if family == "original-message-port" else (
                "workerEmitOriginalRef" if family == "original-worker-reply" else "workerPostOriginalRef")
            owner = "port" if family == "original-message-port" else "worker"
            require(row[function_ref] == installed[0][method]
                    and bindings[row[function_ref]]["sourceClassRef"] == installed[0][owner + "ClassRef"]
                    and bindings[row[function_ref]]["sourcePrototypeRef"] == installed[0][owner + "PrototypeRef"],
                    "A Native transport bypassed the actually installed original class/prototype/method")
            _native_clock_owner(row["sourceCaller"], row["originalStack"], context, imports, pid)
            if event.endswith("-call"):
                require(row["callId"] not in calls, "A Native transport original invocation was duplicated")
                _native_transport_value(row["message"], authority, approved_node, pid=pid, thread=thread)
                _native_transport_value(row["arguments"], authority, approved_node, pid=pid, thread=thread)
                if family != "original-message-port":
                    actual_thread = row["workerThreadId"] if row["workerThreadId"] > 0 else known_workers.get(row["workerRef"])
                    require((pid, actual_thread) in imports and actual_thread != 0,
                            "An original Native transport borrowed a Worker outside its actual imported process graph")
                if family == "original-worker-reply":
                    require(row["callId"] in received and received[row["callId"]]["sequence"] < row["sequence"],
                            "An actual original worker reply was delivered without its actual incoming notification")
                    for name in ("workerRef", "sourceCaller", "originalStack", "message", "arguments", "requestId", "taskId"):
                        _same(row[name], received[row["callId"]][name], "A Native original worker reply changed between receipt and delivery")
                calls[row["callId"]] = family, row
                continue
            require(row["callId"] in calls and row["callId"] not in settled,
                    "A Native original transport result/error was duplicated or has no actual invocation")
            original_family, call = calls[row["callId"]]
            require(original_family == family and call["sequence"] < row["sequence"],
                    "Native transport completion belongs to another actual call or precedes it")
            for name in (function_ref, "sourceCaller", "originalStack", "message", "arguments"):
                _same(call[name], row[name], "An original Native transport completion changed its actual call carrier or callable")
            settled.add(row["callId"])
            if event.endswith("-return"):
                value = row.get("actualReturn", row.get("result"))
                returned = _native_observed_value(value, authority, approved_node)
                require((function_name == "postMessage" and returned == {"privateType": "undefined"})
                        or (function_name == "emit" and type(returned) is bool),
                        "A Native original transport lost its actual void/boolean return type")
            else:
                error = _native_observed_value(row["privateError"], authority, approved_node)
                require(error["privateType"] == "Error" and error["name"] == row["error"]["name"]
                        and error["message"] == row["error"]["message"] and isinstance(row["error"]["ownProperties"], list),
                        "A Native original transport exception lost its complete actual typed error carrier")
        require(set(received) <= set(calls), "An incoming original Native worker reply was never delivered to the original listener")
        for call_id in set(calls) - settled:
            require(((pid, thread) in exited and _ns(calls[call_id][1]["atNs"]) < exited[pid, thread]) or any(
                    child["pid"] == pid and child["exit"] == {"code": None, "signal": "SIGKILL"} for child in raw["children"]),
                    "A live Native original transport call lost its actual return/error")


def _native_keyword_delivery(receipt, gate, raw, actors, passive, authority, approved_node, context, imports, directory):
    require(receipt["mode"] == "deferred-original-worker-reply" and receipt["threadId"] == 0
            and receipt["sourceOwner"] == "WorkerTaskPool.original-keyword-reply" and receipt["eventName"] == "message",
            "The Native keyword fixture froze a thread instead of holding only the original reply delivery")
    caller = receipt["requestSourceCaller"]
    require(caller["package"] == "node_modules/openclaw" and caller["path"] == "dist/worker-task-pool-BQlnRNqZ.mjs",
            "The held Native keyword task was dispatched by another original owner")
    _native_clock_owner(caller, receipt["requestOriginalStack"], context, imports, receipt["pid"])
    require((receipt["pid"], receipt["workerThreadId"]) in imports and receipt["workerThreadId"] != 0,
            "The Native held keyword reply has no actual authenticated original Worker")
    refs = [receipt[name] for name in ("workerRef", "emitRef", "messageRef", "requestRef", "nativeSectionsRef")]
    require(len(set(refs)) == len(refs) and all(isinstance(value, str)
            and re.fullmatch(rf'{receipt["pid"]}:0:process-ref-[0-9]+', value) for value in refs),
            "The Native keyword hold replaced or conflated its original Worker/message/emitter/request identities")
    request, reply = _native_value(receipt["requestInput"], authority, approved_node), _native_value(receipt["reply"], authority, approved_node)
    header = receipt["requestHeader"]
    require(set(header) == {"taskId", "interactive", "sampleMemory", "nativeSections"}
            and type(header["taskId"]) is int and header["taskId"] == receipt["taskId"] == reply["taskId"]
            and type(header["interactive"]) is bool and header["sampleMemory"] is True
            and request["kind"] == reply["value"]["kind"] == "keyword" and reply["status"] == "ok"
            and receipt["replyV8Sha256"] == _sha(bytes.fromhex(receipt["reply"]["v8Hex"])),
            "The held Native keyword notification lost its complete actual task input/header/reply")
    native = header["nativeSections"]
    require(set(native) == {"constructorName", "byteLength", "bytesHex"} and native["constructorName"] == "SharedArrayBuffer"
            and type(native["byteLength"]) is int and native["byteLength"] >= 0
            and bytes.fromhex(native["bytesHex"]).hex() == native["bytesHex"]
            and len(bytes.fromhex(native["bytesHex"])) == native["byteLength"],
            "The original Native task's shared native-section carrier was stripped or reconstructed")
    # V8 deliberately cannot clone the original SharedArrayBuffer. Preserve
    # that actual failure alongside the separately witnessed same object.
    require(set(receipt["request"]) == {"unserializable"}
            and receipt["request"]["unserializable"]["name"] == "Error"
            and "SharedArrayBuffer" in receipt["request"]["unserializable"]["message"],
            "The Native original task serialization failure was replaced by a reconstructed request")
    arguments = _native_value(receipt["eventArguments"], authority, approved_node)
    require(isinstance(arguments, list) and len(arguments) == len(receipt["eventArgumentRefs"]),
            "Native original keyword delivery lost actual extra emitter arguments")
    events = passive[receipt["pid"], 0]
    facts = ("sourceOwner", "taskId", "workerThreadId", "workerRef", "emitRef", "messageRef", "requestRef", "request",
             "requestInput", "nativeSectionsRef", "requestSourceCaller", "requestOriginalStack", "reply", "replyV8Sha256",
             "eventName", "eventArguments", "eventArgumentRefs", "callLabel", "requestHeader")
    selected = {}
    for name in ("held", "delivery-enter", "delivery-return"):
        rows = [row for row in events if row["event"] == "keyword-reply-" + name
                and row.get("messageRef") == receipt["messageRef"]]
        require(len(rows) == 1, "The Native held notification was omitted, duplicated, or delivered more than once")
        selected[name] = rows[0]
        _same({key: rows[0][key] for key in facts}, {key: receipt[key] for key in facts},
              "Native deferred delivery changed its actual original receiver/task/message/arguments")
    held, enter, returned = (selected[name] for name in ("held", "delivery-enter", "delivery-return"))
    release, release_step = _native_gate_release(gate, raw, events, directory)
    require(held["sequence"] < receipt["sequence"] < release["sequence"]
            < enter["sequence"] < returned["sequence"]
            and _ns(release_step["startedAtNs"]) <= _ns(release["atNs"]) <= _ns(enter["enteredAtNs"])
            < _ns(returned["returnedAtNs"]) and returned["actualReturnType"] == "boolean"
            and type(_native_value(returned["actualReturn"], authority, approved_node)) is bool
            and "actualReturn" not in held and "actualReturn" not in enter,
            "Native keyword delivery claimed an original emit return before the real release or invocation")
    _same(enter["message"], receipt["reply"], "The actual Native original emit received another keyword message")
    _same(enter["arguments"], receipt["eventArguments"], "The actual Native original emit received changed extra arguments")
    progress = [row for row in events if row["event"] == "async-gate-mainloop-progress" and row["gate"] == gate["name"]]
    require(len(progress) == 2 and {row["kind"] for row in progress} == {"setImmediate", "setTimeout"}
            and all(row["gateEnterAtNs"] == receipt["enteredAtNs"] and row["callLabel"] == receipt["callLabel"]
                    and receipt["sequence"] < row["sequence"] < release["sequence"] for row in progress),
            "The Native keyword hold has no genuine independent main-loop progress while delivery is pending")
    forgets = [entry for _, actor in actors.values() for entry in actor["calls"]
               if entry["operation"] == "original-forget" and entry.get("label") == "selected"]
    require(len(forgets) == 1 and _ns(receipt["enteredAtNs"]) < _ns(forgets[0]["startedAtNs"])
            < _ns(forgets[0]["settledAtNs"]) < _ns(release_step["startedAtNs"]),
            "The Native keyword fixture did not permit the actual independent original forget to settle while held")


def _native_held_publication_terminal(gate, passive, context, imports, authority, approved_node):
    receipt = gate["receipt"]
    key = receipt["pid"], receipt["threadId"]
    rows = passive[key]
    terminal = [row for row in rows if row["event"] == "held-publication-worker-terminal-reply"
                and row["gate"] == gate["name"] and row["gateEnterSequence"] == receipt["sequence"]]
    require(len(terminal) == 1, "The actual held Native publication lost its source-owned original terminal reply checkpoint")
    terminal = terminal[0]
    require(terminal["sourceOwner"] == "SqliteStoreWorker.receive.original-terminal-reply"
            and terminal["sourceCaller"]["package"] == "node_modules/openclaw"
            and terminal["sourceCaller"]["path"] == "dist/infra/sqlite-store.worker.js",
            "A held Native publication terminal reply came from another original source owner")
    _native_clock_owner(terminal["sourceCaller"], terminal["originalStack"], context, imports, key[0])
    request = _native_value(terminal["request"], authority, approved_node)
    command = _native_value(terminal["requestInput"], authority, approved_node)
    reply = _native_value(terminal["reply"], authority, approved_node)
    arguments = _native_value(terminal["postArguments"], authority, approved_node)
    require(terminal["requestType"] == request["type"] == "execute" and type(request["id"]) is int
            and request["id"] == terminal["brokerRequestId"] == reply["id"]
            and command["type"] == "database.publish" and type(reply["ok"]) is bool
            and isinstance(arguments, list) and arguments,
            "The held Native terminal reply lost its actual original broker request/command/result envelope")
    _same(_native_value({"v8Hex": request["input"]["hex"]}, authority, approved_node), command,
          "The held Native publication command differs from its complete actual received broker bytes")
    _same(arguments[0], reply, "The actual Native terminal post received another original reply object")
    publication = [row for (pid, _), records in passive.items() if pid == key[0] for row in records
                   if row["event"] == "original-database-publication-command" and row["brokerRequestId"] == request["id"]]
    require(len(publication) == 1, "The held Native reply has no unique actual parent publication dispatch")
    _same(_native_value(publication[0]["command"], authority, approved_node), command,
          "The original Native worker published a command different from its actual parent dispatch")
    require(receipt["sequence"] < terminal["sequence"] and command["input"]["expectedRevision"] == receipt["lastRevisionRead"]["value"],
            "The held Native publication refreshed its original captured expected fence or replied before the held frame")


def _native_gates(case, raw, actors, passive, authority, approved_node, directory, *, context=None, imports=None):
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
                _native_gate_release(gate, raw, events, directory)
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
            _native_held_publication_terminal(gate, passive, context, imports, authority, approved_node)
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
            _native_keyword_delivery(receipt, gate, raw, actors, passive, authority, approved_node, context, imports, directory)
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
    def code_key(name, code):
        return name, code["file"], code["qualname"], code["firstLine"], code["bytecodeSha256"]
    for row in observation["codeOwners"]:
        _sdk_code_owner(row["code"], recorded, trusted)
        key = code_key(row["name"], row["code"])
        require(key not in codes, "An SDK original callable/code identity was duplicated")
        codes[key] = row
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
            owner = codes[code_key(row["name"], row["code"])]
            _same(row["code"], owner["code"], "An actual SDK invocation borrowed another callable/code object")
            require(row["exactReceiver"] is (owner["receiver"] is not None),
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
            nested = [row for row in events.values() if row["event"] == "original-call"
                      and row["name"] in {"SQLiteMemoryStore.reindex", "SQLiteMemoryStore._reindex_locked"}
                      and row["callLabel"] == label and call["enterSeq"] < row["sequence"] < call["returnSeq"]
                      and row["sequence"] in returns and type(returns[row["sequence"]]["returned"]) is int]
            require(nested, "The SDK sync integer has no actual nested original producer return")
            for source_call in nested:
                _same(returns[source_call["sequence"]]["returned"], call["returned"],
                      "The SDK private sync count differs from another actual original producer-frame return")
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


def _native_transcript_exports(case, actor, snapshot, events, authority, approved_node):
    """Bind observation facts to the supported original read-only export call."""
    method = "readTranscriptExportSnapshotReadOnlySync"
    owners = [row for row in actor["codeOwners"] if row["name"] == method]
    require(len(owners) == 1 and owners[0]["modulePath"] == "dist/session-accessor-CiKKTlbe.mjs",
            "The Native observation lost its original read-only transcript export callable")
    rows = snapshot["sessionTranscriptExportReads"]
    require(len(rows) == len(case["input"]["sessionFacts"]["sessions"]) == len(snapshot["sessions"]),
            "A Native transcript observation omitted or duplicated an actual export")
    observed = [row for row in actor["sessionTranscriptExportReads"]
                if snapshot["enterSeq"] < row["enterSeq"] < row["returnSeq"] < snapshot["returnSeq"]]
    _same(rows, observed, "A Native snapshot replaced its actual cumulative transcript export receipts")
    fixture = Path(actor["request"]["fixtureBase"])
    for receipt, session in zip(rows, snapshot["sessions"], strict=True):
        start, end = _interval(receipt, events, "original-transcript-export-read-enter", "original-transcript-export-read-return")
        entered, returned = events[start], events[end]
        require(receipt["method"] == entered["method"] == returned["method"] == method
                and receipt["methodRef"] == entered["methodRef"] == returned["methodRef"] == owners[0]["functionRef"]
                and receipt["ownerRef"] == entered["ownerRef"] and receipt["ownerRef"].startswith(str(actor["pid"]) + ":")
                and returned["enteredSeq"] == start and returned["threw"] is False
                and receipt["returnedUndefined"] is returned["returnedUndefined"] is False
                and "error" not in receipt and receipt["startedAtNs"] == entered["atNs"]
                and receipt["finishedAtNs"] == returned["atNs"] and _ns(receipt["startedAtNs"]) < _ns(receipt["finishedAtNs"]),
                "A Native export borrowed another original receiver, call frame, or settlement")
        scope = receipt["scope"]
        require(set(scope) == {"agentId", "sessionId", "sessionKey", "storePath"}
                and all(scope[name] == session[name] for name in ("agentId", "sessionId", "sessionKey"))
                and Path(scope["storePath"]).is_absolute() and Path(scope["storePath"]).is_relative_to(fixture)
                and ".." not in Path(scope["storePath"]).parts,
                "A Native export observed another session identity or unowned producer database")
        _same(_native_json(receipt["privateReturn"], authority, approved_node), receipt["result"],
              "The Native read-only export lost its whole original typed return")
        require(isinstance(receipt["result"], dict) and isinstance(receipt["result"]["events"], list),
                "An undefined Native transcript export was replaced with an empty event history")
        _same(receipt["result"]["events"], session["events"],
              "Native observed session events differ from the full actual original read-only export")


def _native_capture(case, raw, result, directory, approved_node, trusted_archive, approved_reference):
    require(raw["kind"] == "forget-index-fence-native-capture" and raw["schemaVersion"] == 1
            and raw["engine"] == "native" and raw["caseId"] == case["id"]
            and raw["completed"] is raw["allChildrenReaped"] is True
            and not any(raw.get(name) for name in ("error", "teardownError", "observationErrors", "controlFailures")),
            "The original Native packet is incomplete or contaminated")
    _same(raw["input"], case["input"], "The original Native received another frozen input")
    _same(raw["result"], result, "Native raw capture lost its whole public result")
    directory = Path(directory or Path(raw["fixtureBase"]).parent).resolve(strict=True)
    context, process, authority, imports, passive = _native_authority(case, raw, directory, approved_node, trusted_archive, approved_reference)
    require(not any(row["event"] == "fixture-control-failure" for rows in passive.values() for row in rows),
            "An actual Native functional fixture failure was omitted from its outer control status")
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
        if _v2(case):
            require(actor["controlFailures"] == [], "A Native deferred fixture control failed outside the original public outcome")
        _native_code_owners(actor, imports[child["pid"], 0]["loaded"], context)
        _native_producers(case, actor, authority, approved_node)
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
            _same(_native_json(status["privateReturn"], authority, approved_node), status["result"],
                  "The Native selected provider status differs from its actual original return")
            require(status["result"]["provider"] == result["provider"], "Native provider-none result was predicted instead of observed")
    require(set(reconstructed) == set(_expected_calls(case["input"])), "Native actual calls differ from the complete frozen schedule")
    _same(reconstructed, result["calls"], "Native common calls dropped or repaired original public outcomes")
    if _v2(case):
        wires = []
        def collect_carriers(value):
            if isinstance(value, dict):
                if "v8Hex" in value:
                    wires.append(value["v8Hex"])
                for item in value.values():
                    collect_carriers(item)
            elif isinstance(value, list):
                for item in value:
                    collect_carriers(item)
        collect_carriers(list(passive.values()))
        _decode_v8_views(authority, wires, approved_node)
        _native_sql_custody(raw, context, imports, passive, authority, approved_node)
        _native_transport_custody(raw, context, imports, passive, authority, approved_node)
        _native_source_clock_v2(case, raw, actors, imports, passive, context, authority, approved_node)
        for pid, (_, actor) in actors.items():
            entries = [row["sequence"] for row in passive[pid, 0] if row["event"] == "original-transcript-export-read-enter"]
            require([row["enterSeq"] for row in actor["sessionTranscriptExportReads"]] == entries,
                    "Native transcript exports were omitted, duplicated, or reordered after actual invocation")
    _native_gates(case, raw, actors, passive, authority, approved_node, directory, context=context, imports=imports)
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
        if _v2(case):
            _native_transcript_exports(case, actor, snapshot, events, authority, approved_node)
        database = _physical_database(snapshot["physical"], raw["fixtureBase"])
        _native_plugin_state(snapshot, actor, events, raw["fixtureBase"], authority, approved_node)
        require(set(database["selectedTables"]) == {row["name"] for row in database["schema"]
                    if row["type"] == "table" and row["name"].startswith(("memory_", "session_"))},
                "A source-selected Native physical table was dropped")
        common = _source_snapshot_common(case["input"], snapshot, native=True, database=database, origins_database=database)
        for name, raw_value in (("origins", snapshot["publicState"]["origins"]),
                                ("tombstones", snapshot["publicState"]["tombstones"]), ("stores", snapshot["stores"]),
                                ("sessions", snapshot["sessions"])):
            _same(_native_json(snapshot["publicReadReturns"][name], authority, approved_node), raw_value,
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


def _native_producers(case, actor, authority, approved_node):
    preparation = [row for row in actor["calls"] if row["operation"] == "prepare-real-host-inputs"]
    if not preparation:
        require(not actor["producerReceipts"], "A Native actor invented an undeclared session producer")
        return
    require(len(preparation) == 1, "An original Native host-input producer was duplicated")
    value, fixture = case["input"], Path(actor["request"]["fixtureBase"])
    file_receipts = actor["inputFileReceipts"]
    require([row["path"] for row in file_receipts] == list(actor["request"]["input"]["initialFiles"])
            and len(file_receipts) == len(value["initialFiles"])
            and {row["path"] for row in file_receipts} == set(value["initialFiles"]),
            "The Native original input source creation omitted or duplicated a declared file")
    prepared = {row["path"]: row for row in actor["preparedSourceDocuments"]}
    for row in file_receipts:
        path, text = row["path"], value["initialFiles"][row["path"]]
        filename = fixture / "workspace" / _relative(path)
        require(row["absolutePath"] == str(filename) and row["flags"] == "wx"
                and row["bytes"] == text.encode("utf8").hex(),
                "A Native initial source file borrowed another actual path, bytes, or creation mode")
        _same(row["utimesArguments"], [str(filename), value["clock"]["initialSourceMtimeMs"] / 1000,
              value["clock"]["initialSourceMtimeMs"] / 1000], "The Native initial source clock arguments changed")
        for name in ("writeReturn", "utimesReturn"):
            require(_native_value(row[name], authority, approved_node) == {"privateType": "undefined"},
                    "A Native initial source syscall lost its actual original void return")
        observed = prepared[path]
        require(observed["kind"] == "file" and observed["hex"] == row["bytes"]
                and int(observed["mtimeNs"]) == value["clock"]["initialSourceMtimeMs"] * 1_000_000,
                "A Native prepared source differs from its actual initial bytes or filesystem-clock input")
    facts = value["sessionFacts"]["sessions"]
    require(len(actor["producerReceipts"]) == len(facts), "An actual Native session producer was omitted or added")
    names = {row["name"] for row in actor["codeOwners"]}
    if _v2(case):
        require({"upsertSessionEntry", "replaceTranscriptEventsSync"} <= names,
                "The original Native session counterpart producer lost its actual callable source owners")
    for receipt, fact in zip(actor["producerReceipts"], facts, strict=True):
        scope = receipt["scope"]
        require(scope["agentId"] == fact["agentId"] and scope["sessionKey"] == fact["sessionKey"]
                and scope["sessionId"] == fact["sessionId"] and Path(scope["storePath"]).is_absolute()
                and Path(scope["storePath"]).is_relative_to(fixture),
                "A Native persisted session producer borrowed another declared identity or state root")
        _same(receipt["upsertRequest"], {**scope, "entry": fact["entry"]},
              "The Native original upsert received nonliteral metadata or another producer's output")
        _native_value(receipt["upsertReturn"], authority, approved_node)
        if _v2(case) or "transcriptReplacement" in receipt:
            replacement = receipt["transcriptReplacement"]
            require(replacement["method"] == "replaceTranscriptEventsSync"
                    and type(replacement["result"]) is bool and replacement["privateReturn"]["type"] == "boolean",
                    "The actual Native literal-event replacement lost its original boolean return")
            _same(replacement["request"], {"scope": scope, "events": fact["events"]},
                  "The original Native event replacement received altered literals or SDK-derived state")
            _same(_native_value(replacement["privateReturn"], authority, approved_node), replacement["result"],
                  "The original Native event replacement result differs from its actual V8 boolean")
            require(isinstance(replacement["beforeEvents"], list)
                    and isinstance(replacement["eventsArgumentAfter"], list) and isinstance(receipt["events"], list),
                    "The original Native event replacement lost its actual before/argument-after/readback records")
        else:
            require(len(receipt["messages"]) == len(fact["events"]),
                    "The legacy Native diagnostic omitted an actual original append")
            for message, event in zip(receipt["messages"], fact["events"], strict=True):
                require(message["params"]["message"] == event["message"]
                        and message["params"]["eventId"] == event["id"],
                        "The legacy Native original append received another literal event")


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


def _sdk_snapshot_receiver(specification, step, snapshot, processes, stages):
    selection = step["snapshotReceiver"]
    require(set(selection) == {"requestedActor", "preferredActor", "selectedActor", "pid", "reason", "candidates"},
            "SDK snapshot receiver custody fields were removed or replaced")
    requested = specification.get("actor")
    preferred = requested if requested is not None else "foreground"
    require(selection["requestedActor"] == requested and selection["preferredActor"] == preferred,
            "SDK observation receiver selection changed the frozen explicit actor request")
    # Reassignment of an existing actor preserves its original insertion order.
    current = {}
    for process in processes.values():
        if _ns(process["startedAtNs"]) < _ns(step["enteredAtNs"]):
            current[process["actor"]] = process
    candidates = selection["candidates"]
    require([row["actor"] for row in candidates] == list(current),
            "SDK snapshot selection omitted, duplicated, or invented an existing actor")
    observations = {row["pid"]: row for row in stages}
    require(len(observations) == len(stages), "SDK snapshot receiver lifecycle observations were duplicated")
    require(all(_ns(event["atNs"]) < _ns(step["settledAtNs"]) for observation in stages
                for event in observation["originalCalls"]),
            "SDK snapshot receiver substituted an original response from a future schedule step")
    available = {}
    for row in candidates:
        process = current[row["actor"]]
        require(set(row) == {"actor", "pid", "poll", "acquired"} and row["pid"] == process["pid"]
                and type(row["acquired"]) is bool and row["acquired"] is bool(observations.get(row["pid"], {}).get("ownerBindings")),
                "SDK snapshot candidate did not retain its actual latest PID and acquired original owner")
        require(row["poll"] is None or (type(row["poll"]) is int and row["poll"] == process["exit"]["code"]),
                "SDK snapshot candidate changed its actual OS process status")
        if _ns(process["reapedAtNs"]) < _ns(step["enteredAtNs"]):
            require(row["poll"] == process["exit"]["code"], "An already reaped SDK process was admitted as a live snapshot receiver")
        if row["poll"] is None and row["acquired"]:
            available[row["actor"]] = row
    if preferred in available:
        selected = preferred
        reason = "explicit-live-acquired-actor" if requested is not None else "implicit-foreground-live-acquired"
    else:
        require(requested is None and available, "An explicit SDK snapshot receiver was silently replaced or reacquired")
        selected, reason = next(iter(available)), "implicit-live-acquired-fallback"
    require(selection["selectedActor"] == snapshot["actor"] == selected
            and selection["pid"] == snapshot["pid"] == available[selected]["pid"] and selection["reason"] == reason,
            "SDK physical observation was reassigned using an output-dependent receiver choice")
    process = processes[selection["pid"]]
    require(_ns(process["startedAtNs"]) < _ns(step["enteredAtNs"]) < _ns(step["settledAtNs"]) < _ns(process["reapedAtNs"]),
            "SDK snapshot result came from a process outside its actual live lifetime")
    matches = [(command, response) for command, response in zip(process["stdinCommands"], process["stdoutResponses"], strict=True)
               if command["operation"] == "snapshot" and command["label"] == specification["label"]]
    require(len(matches) == 1, "SDK observation has no unique actual snapshot command/response")
    command, response = matches[0]
    require(any(item["operation"] == "acquire" and item["id"] < command["id"] for item in process["stdinCommands"]),
            "SDK snapshot receiver was not actually acquired before the original snapshot command")
    _same(response["result"], snapshot, "SDK snapshot receiver's actual stdout returned another physical observation")
    _same(response["observation"], observations[selection["pid"]],
          "SDK snapshot receiver substituted an earlier or future observation for its actual snapshot response")


def _sdk_capture(case, dispatch, result, directory, approved_root):
    value = case["input"]
    prefix = "forget-index-fence-v2" if _v2(case) else "forget-index-fence"
    require(dispatch["kind"] == prefix + "-sdk-dispatch" and dispatch["exit"] == {"code": 0}
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
    require(raw["kind"] == prefix + "-sdk-host" and raw["complete"] is True
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
    if _v2(case):
        require(raw["observationInvalid"] == [], "SDK clock custody was invalidated outside the original public outcomes")
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
        if _v2(case):
            from equivalence.forget_index_fence_sdk_clock_evidence import validate_sdk_clock_v2
            validate_sdk_clock_v2(case, observation, process, events, returns, recorded_root=recorded,
                                  approved_sdk_root=trusted, fixture_root=fixture)
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
        if _v2(case):
            _sdk_snapshot_receiver(specification, step, snapshot, processes, stages)
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
                    "SQLiteMemoryStore.connect", "MemoryEntryOriginLedger._open_write",
                    "MemoryEntryOriginLedger.record_session_tombstones_if_lineage_current"}
                        and execution["parentCode"]["qualname"] == execution["source"]
                        and execution["event"] == "original-sql-c-call" and execution["method"] in {"execute", "executescript"}
                        and execution["connectionId"] == trigger["connectionId"]
                        and (trigger["event"] != "original-sql" or (trigger["executionSequence"] == execution["sequence"]
                             and trigger["statement"] in execution["statements"])),
                    "SDK pending writer progress did not reach an actual owned original SQLite call")
                require(_ns(execution["atNs"]) < _ns(stage["settledAtNs"])
                        and ("finishedAtNs" not in execution or _ns(stage["settledAtNs"]) < _ns(execution["finishedAtNs"])),
                        "SDK writer-wait progress was already settled when the actual gate was observed")
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
process.stdout.write(JSON.stringify(input.map(hex=>{
  const value=deserialize(Buffer.from(hex,'hex'));
  let json;
  try {
    const text=JSON.stringify(value);
    json=text===undefined?{status:'undefined'}:{status:'serialized',text};
  } catch(error) {
    json={status:'rejected',error:{name:error.name,message:error.message}};
  }
  return {carrier:carrier(value),json};
})));
'''
_V8_CACHE = {}


def _decode_v8_views(authority, wires, approved_node):
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


def _decode_v8(authority, wires, approved_node):
    return [view["carrier"] for view in _decode_v8_views(authority, wires, approved_node)]
