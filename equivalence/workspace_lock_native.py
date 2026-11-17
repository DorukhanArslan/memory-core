"""Protected independent OpenClaw lease actors, their SQLite rows, and process/worker evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from contextlib import closing

from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.promotion_apply_bindings import PROMOTION_WORKER_ROUTE
from equivalence.workspace_lock_cases import build_cases, validate_registration

HERE = Path(__file__).resolve().parent
PRELOAD = HERE / "release-preload.mjs"
WRITER = HERE / "workspace-lock-writer.mjs"
OWNERS = {
    "dist/dreaming-dreams-file-BJzlZFlf.mjs": ("g", "withMemoryWorkspaceLock", "4c2e28a389583f35c3cea6414e1a1532fec0e774d2ec554b30eb2cbad4853294"),
    "dist/dreaming-state-VYUvbU-n.mjs": ("p", "configureMemoryCoreDreamingState", "7c97cd878aa65b0ee17367683050f50530df0656d54ab52e3e6f0c2d92e279cc"),
    "dist/plugin-sdk/plugin-state-store-runtime.js": ("createPluginStateKeyedStore", "createPluginStateKeyedStore", "3c4f0e6163afd4d4f9462fe11b1c18410332764b5ea591361ed6c66034d0c203"),
    "dist/plugin-state-store-BPUaLoVD.mjs": ("u", "closePluginStateDatabaseAsync", "c648b6b2311377ff1d43593a21ce37b67b4d8b9bce744aae495049043b99da92"),
    "dist/pid-alive-BYw_9KTp.mjs": ("n", "getFileLockProcessStartTime", "a986cff7b7cee2c1c185d89c9a09587e29fb7c976303699e45149ee529412429"),
}


def _require(value, message):
    if not value:
        raise ValueError(message)


def _read(path):
    return json.loads(path.read_bytes())


def _write(path, value):
    path.write_text(json.dumps(value, separators=(",", ":"), allow_nan=False))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(root, role, case, node, runtime):
    validate_registration(build_cases())
    _require(case in build_cases() and role in {"holder", "waiter"}, "Unknown lock actor or drive")
    directory = root / role
    _require(directory.is_dir() and directory.resolve() == directory and (root / "workspaces").is_dir(),
             "Actor requires its owned fixture directory")
    return {
        "schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": prepare_model_node_authority(node),
        "allowedLocal": [{"path": str(p), "sha256": _sha(p)} for p in (PRELOAD, WRITER)],
        "traceDirectory": str(directory / "traces"), "evidenceDirectory": str(directory),
        "stateDirectory": str(root / "state"), "configPath": str(root / "openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": [],
        "workspaceLockActor": {"role": role, "root": str(root), "definition": case},
    }


def start_actor(root: Path, role: str, case: dict, node: Path, runtime: dict) -> subprocess.Popen:
    root, node = Path(root).resolve(), Path(node).resolve()
    directory = root / role
    context = _context(root, role, case, node, runtime)
    (directory / "traces").mkdir()
    context_path = directory / "context.json"
    _write(context_path, context)
    config = root / "openclaw.json"
    if role == "holder" and not config.exists():
        _write(config, {"logging": {"level": "silent", "consoleLevel": "silent", "file": str(root / "native.log")}})
    environment = {
        "PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
        "NODE_OPTIONS": "--import=" + str(PRELOAD), "MEMORY_EQ_RELEASE_CONTEXT": str(context_path),
        "OPENCLAW_STATE_DIR": context["stateDirectory"], "OPENCLAW_CONFIG_PATH": str(config),
    }
    args = [str(node), str(WRITER)]
    with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen(args, cwd=HERE.parent, stdout=stdout, stderr=stderr, env=environment,
                                   start_new_session=True)
    _write(directory / "launch.json", {"pid": process.pid, "ppid": os.getpid(), "args": args,
                                       "environment": environment, "contextSha256": _sha(context_path)})
    return process


def _traces(directory, context, launch):
    expected = {(package["location"], item["path"]): item["sha256"]
                for package in context["runtime"]["packages"] for item in package["files"]}
    local = {entry["path"]: entry["sha256"] for entry in context["allowedLocal"]}
    bootstraps, loaded, workers, traces, main = [], {}, {}, [], set()
    for path in sorted((directory / "traces").iterdir()):
        _require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
                 and path.stat().st_size < 8 * 1024 * 1024, "Unowned native actor trace")
        content = path.read_bytes()
        _require(content.endswith(b"\n"), "Partial protected worker trace")
        items = [json.loads(line) for line in content.splitlines()]
        first = items[0]
        thread = first["threadId"]
        _require(first["event"] == "bootstrap" and path.name == f'{launch["pid"]}-{thread}.jsonl'
                 and first["pid"] == launch["pid"] and first["ppid"] == launch["ppid"]
                 and first["isMainThread"] is (thread == 0)
                 and first.get("runtime") == context["approvedNodeRuntime"]
                 and first["contextSha256"] == launch["contextSha256"]
                 and first["preloadSha256"] == local[str(PRELOAD)]
                 and first["fetchDenied"] is True and first["providerMode"] == "none",
                 "Unauthenticated lock process or worker bootstrap")
        bootstraps.append(first)
        seen = main if thread == 0 else workers.setdefault(thread, set())
        for row in items[1:]:
            _require(row["event"] in {"load", "resolve-native"} and row["pid"] == launch["pid"]
                     and row["threadId"] == thread, "Unexpected protected native import event")
            if row["kind"] == "release":
                key = row["package"], row["path"]
                _require(expected.get(key) == row["sha256"], "Unpinned native lock import")
                loaded[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                seen.add(key)
            else:
                _require(row["kind"] == "oracle" and local.get(row["path"]) == row["sha256"],
                         "Unpinned native lock adapter import")
                seen.add(("oracle", row["path"]))
        traces.append({"path": str(path), "sha256": _sha(path)})
    package = "node_modules/openclaw"
    _require(sum(row["threadId"] == 0 for row in bootstraps) == 1
             and ("oracle", str(WRITER)) in main and all((package, name) in main for name in OWNERS)
             and any(all((package, name) in seen for name in PROMOTION_WORKER_ROUTE) for seen in workers.values()),
             "Missing original lock owner, store or SQLite worker execution")
    return {"bootstraps": bootstraps, "loaded": list(loaded.values()), "traces": traces}


def _physical(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        _require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "Native lock SQLite is inconsistent")
        rows = db.execute("SELECT entry_key,value_json FROM plugin_state_entries WHERE plugin_id=? AND namespace=? "
                          "ORDER BY entry_key", ("memory-core", "short-term-locks")).fetchall()
    return {"database": str(database), "rows": [{"entry_key": key, "value_json": val} for key, val in rows]}


def _lease_evidence(root, key, pid, role, case, rows, calls, answers, markers):
    by_kind = {}
    for row in rows:
        by_kind.setdefault(row["event"], []).append(row)
    updates = [(calls[row["call"]], row["returned"]) for row in answers if row["method"] == "compareAndApply"]
    observed = [row for row in answers if row["method"] == "observe"]
    _require(observed and len({row["call"] for row in answers}) == len(calls), "Missing real store return")
    lease_sets = [call for call, result in updates if call["origin"] == "lease" and call["args"][2]["action"] == "set"
                  and result["status"] == "applied"]
    original_entry = bool(lease_sets)
    timeout = role == "waiter" and case["input"]["drive"] == "timeout"
    _require(len(lease_sets) == int(not timeout) and ("entered" in markers) == original_entry,
             "Native lease acquisition did not match the original CAS result")
    if "observed_twice" in markers:
        holder = markers["observed_twice"]["lease"]
        foreign = [row for row in observed if row["origin"] == "lease" and row["returned"]["value"] == holder]
        _require(len(foreign) >= 2 and not holder["owner"].startswith(str(pid) + ":"),
                 "Original store never independently observed the foreign holder twice")
    if timeout:
        outcome = markers["done"]["error"]
        holder = markers["observed_twice"]["lease"]
        _require(not updates and not by_kind.get("write") and outcome["code"] == "MEMORY_WORKSPACE_LOCK_HELD"
                 and outcome["outcome"] == {"kind": "held", "holder": {"owner": holder["owner"], "epoch": holder["acquiredAt"]}},
                 "Missing original held-owner timeout")
        return
    acquired = lease_sets[0]["args"][2]["value"]
    start = int(rows[0]["processStart"].rsplit(")", 1)[1].split()[19])
    _require(re.fullmatch(fr"{pid}:[0-9a-f-]{{36}}", acquired["owner"]) and acquired["ownerStartTime"] == start
             and acquired["acquiredAt"] == lease_sets[0]["nowMs"], "Lease is not owned by the observed OS process")
    for name, marker_name in (("entered", "entered"), ("before-release", "before-release")):
        if marker_name not in markers:
            continue
        marker = markers[marker_name]
        point = by_kind[name][0]
        _require(point["lease"] == marker["lease"] and point["physical"] == marker["physical"]
                 and marker["physical"]["database"] == str(root / "state/state/openclaw.sqlite"),
                 "Native lease marker does not match its physical SQLite capture")
        durable = {item["entry_key"]: json.loads(item["value_json"]) for item in marker["physical"]["rows"]}
        _require(durable.get(key) == marker["lease"], "Native actor did not own its claimed physical row")
    replaced = role == "holder" and case["input"]["holder"] == "replace-start-time"
    if replaced:
        change = by_kind["replaced"][0]
        _require(change["original"] == acquired and change["replacement"] == markers["entered"]["lease"]
                 and change["priorPid"] == rows[0]["ppid"] and change["olderStartTime"] < start
                 and change["replacement"] == {**acquired, "ownerStartTime": change["olderStartTime"]},
                 "Missing real process start-identity replacement")
        intent, result = updates[-1]
        _require(any(call["origin"] == "replace-start-time" and returned["status"] == "applied" and
                     call["args"][2]["value"] == change["replacement"] for call, returned in updates)
                 and intent["args"][2] == {"operation": "delete", "action": "keep"}
                 and result["status"] == "unchanged", "Previous holder did not preserve the replacement lease")
    else:
        _require(markers["entered"]["lease"] == acquired, "Native actor lost its acquired lease")
    writes = by_kind["write"]
    _require(len(writes) == 1 and writes[0]["path"] == str(root / "workspaces" / markers["entered"]["workspace"] / "journal.txt")
             and writes[0]["line"] == case["input"]["lines"][int(role == "waiter")], "Wrong native journal operation")
    if role == "waiter":
        nested = by_kind["nested-call"][0]["sequence"] < writes[0]["sequence"] < by_kind["nested-return"][0]["sequence"]
        _require(nested and markers["before-release"]["lease"] == acquired, "Native public nested lease lost ownership")


def finish_actor(root: Path, role: str, case: dict, node: Path, runtime: dict, pid: int, returncode: int):
    root, node = Path(root).resolve(), Path(node).resolve()
    directory = root / role
    context = _context(root, role, case, node, runtime)
    context_path = directory / "context.json"
    _require(_read(context_path) == context, "Native actor context changed")
    launch = _read(directory / "launch.json")
    _require(launch["pid"] == pid and launch["contextSha256"] == _sha(context_path)
             and launch["args"] == [str(node), str(WRITER)], "Native launch identity changed")
    trace = _traces(directory, context, launch)
    raw_path = directory / "receipts.jsonl"
    content = raw_path.read_bytes()
    _require(content.endswith(b"\n") and len(content) < 8 * 1024 * 1024, "Incomplete native lease receipts")
    rows = [json.loads(line) for line in content.splitlines()]
    workspace = "B" if role == "waiter" and case["input"]["workspace"] == "other" else "A"
    key = hashlib.sha256(str(root / "workspaces" / workspace).encode()).hexdigest()
    _require(all(row["sequence"] == i and row["pid"] == pid and row["ppid"] == launch["ppid"]
                 and row["workspace"] == workspace for i, row in enumerate(rows, 1)),
             "Misbound lock operation identity")
    def one(event):
        return [row for row in rows if row["event"] == event]
    artifact = {item["path"]: item["sha256"] for item in trace["loaded"] if item["package"] == "node_modules/openclaw"}
    owners = [{"relative": name, "alias": alias, "name": fn, "sourceSha256": sha, "artifactSha256": artifact[name]}
              for name, (alias, fn, sha) in OWNERS.items()]
    _require([{k: row[k] for k in owners[0]} for row in one("owner")] == owners,
             "Wrong native lease or store function identity")
    _require(rows[0]["event"] == "startup" and rows[0]["timersUnchanged"] is True
             and rows[0]["workspaceKey"] == key and rows[0]["definition"] == case
             and len(one("factory")) == len(one("lock-call")) == 1 and not one("unexpected")
             and one("factory")[0]["options"] == {"namespace": "short-term-locks", "maxEntries": 4096},
             "Native workspace lease setup failed")
    calls = {row["call"]: row for row in one("store-call")}
    answers = one("store-return")
    _require(len(calls) == len(answers) and not one("store-error")
             and all(row["call"] in calls and calls[row["call"]]["method"] == row["method"] and
                     calls[row["call"]]["args"][0] == key and row["sequence"] > row["call"] for row in answers),
             "Missing or incorrectly bound store observations or CAS results")
    killed = role == "holder" and case["input"]["holder"] == "kill"
    _require(returncode == (-9 if killed else 0), "Unexpected native actor exit")
    markers = {name: _read(directory / (name + ".json")) for name in
               ("entered", "observed_twice", "before-release", "done") if (directory / (name + ".json")).exists()}
    for name, value in markers.items():
        _require(value["pid"] == pid and value["ppid"] == launch["ppid"] and value["workspace"] == workspace,
                 "Native condition came from a foreign writer")
    if killed:
        _require(rows[-1]["event"] == "entered" and "done" not in markers, "Killed native owner continued executing")
    else:
        _require(rows[-1]["event"] == "closed" and one("closed")[0]["timersUnchanged"] is True
                 and len(one("lock-return")) == 1 and "done" in markers, "Native lease did not settle")
        outcome = one("lock-return")[0]
        _require(all(outcome[k] == markers["done"][k] for k in ("status", "error")), "Native lease output mismatch")
    _lease_evidence(root, key, pid, role, case, rows, calls, answers, markers)
    return {"pid": pid, "ppid": launch["ppid"], "returncode": returncode, "role": role, "workspace": workspace,
            "launch": launch, "authority": context["approvedNodeRuntime"], "trace": trace,
            "receipts": rows, "markers": markers, "physical": _physical(root / "state/state/openclaw.sqlite")}
