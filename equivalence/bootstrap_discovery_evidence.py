"""Bind the whole bootstrap caller's observed outputs to its literal requests.

These checks select no bootstrap files and implement no setup or privacy policy.
Original callable owners perform those operations; the collector authenticates
their actual imports separately from these transport/retention checks.
"""
import hashlib
import math
from pathlib import Path
import re

from equivalence.bootstrap_discovery_bindings import TEMPLATE_ARTIFACTS
from equivalence.bootstrap_discovery_profile import validate_bootstrap_node_authority
from equivalence.get_contract import map_get_fixture_paths
from equivalence.search_contract import _same_json


def _require(test, message):
    if not test:
        raise ValueError(message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _stable_error(error):
    if isinstance(error, list):
        return [_stable_error(item) for item in error]
    if not isinstance(error, dict):
        return error
    return {key: _stable_error(value) if key == "cause" else value
            for key, value in error.items() if key != "stack"}


def _tree(rows, enumeration):
    _require(isinstance(rows, list), "A complete filesystem observation was dropped")
    paths = set()
    for row in rows:
        relative = row.get("path")
        _require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
                 and ".." not in Path(relative).parts and relative not in paths,
                 "A bootstrap filesystem observation escaped or duplicated an owned path")
        paths.add(relative)
        stat, kind = row.get("stat"), row.get("kind")
        _require(isinstance(stat, dict) and set(stat) == {"dev", "mode", "nlink", "uid", "gid", "rdev", "blksize", "ino", "size", "blocks", "atimeMs", "mtimeMs", "ctimeMs", "birthtimeMs"}
                 and all(type(item) in {int, float} and math.isfinite(item) for item in stat.values())
                 and kind in {"file", "directory", "symlink", "other"}, "Actual filesystem identity/stat fields were dropped")
        expected = {"path", "stat", "kind"}
        if kind == "file":
            expected.add("bytes")
            data = row.get("bytes")
            _require(isinstance(data, dict) and set(data) == {"type", "hex"} and data["type"] == "bytes"
                     and isinstance(data["hex"], str) and re.fullmatch(r"(?:[0-9a-f]{2})*", data["hex"])
                     and len(data["hex"]) // 2 == stat["size"], "A complete bootstrap filesystem byte channel was dropped")
        if kind == "symlink":
            expected.add("target")
            _require(isinstance(row.get("target"), str), "A real symlink target was dropped")
        _require(set(row) == expected, "A filesystem observation changed its complete wire shape")
    _require(isinstance(enumeration, list) and len(enumeration) == len(paths) and set(enumeration) == paths,
             "A filesystem entry was dropped from its independent original recursive enumeration")


def validate_bootstrap_discovery_raw(row, case, diagnostic, evidence_directory, *, runtime_root,
                                    bootstrap, release_by_pid, local_by_pid, process_parents):
    from equivalence.runtime_oracle import ROOT, RuntimeOracleError

    try:
        value = case["input"]
        _require(case["operation"] == "bootstrap-discovery-runtime" and value["kind"] == "workspace-bootstrap"
                 and row.get("ok") is True and isinstance(diagnostic, list) and len(diagnostic) == 1,
                 "Only a complete successful whole bootstrap caller may be compared")
        raw = diagnostic[0]
        _require(set(raw) == {"kind", "input", "fixtureBase", "pid", "ppid", "runtime", "config", "clock",
                 "packagedTemplates", "writes", "calls", "snapshots", "close"}, "A complete bootstrap observation channel was dropped")
        _same(raw["input"], value, "The actual bootstrap caller received different literal inputs")
        _same(raw["kind"], value["kind"], "A different bootstrap caller was observed")
        base = Path(raw["fixtureBase"])
        _require(base.is_absolute() and base.parent == evidence_directory and re.fullmatch(r"native-bootstrap-discovery-[A-Za-z0-9_-]+", base.name),
                 "Bootstrap IO escaped its exact owned fixture directory")
        runtime = validate_bootstrap_node_authority(raw["runtime"])
        pid = raw["pid"]
        _require(type(pid) is int and process_parents.get(pid) == raw["ppid"]
                 and any(item["pid"] == pid and item["isMainThread"] is True for item in bootstrap), "The actual bootstrap producer lost its protected lineage")
        for item in bootstrap:
            _same(item.get("runtime"), runtime, "A bootstrap process or worker used another Node/ICU/Unicode executable")
        _require({str(ROOT / "equivalence" / name) for name in ("release-oracle.mjs", "bootstrap-discovery-runtime.mjs", "get-contract-runtime.mjs")}
                 <= local_by_pid.get(pid, set()) and bool(release_by_pid.get(pid)), "The genuine bootstrap caller or owned-root codec did not execute")
        _same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": value["nowMs"], "dateConstructorReplaced": True,
              "setTimeoutUnchanged": True, "performanceNowUnchanged": True}, "An undeclared scheduler or performance clock was controlled")
        _same(raw["config"], {"logging": {"level": "silent", "consoleLevel": "silent", "file": str(base / "native.log")},
              "session": {"maintenance": {"mode": "warn"}}}, "The actual bootstrap host configuration drifted")
        _require(set(raw["packagedTemplates"]) == set(TEMPLATE_ARTIFACTS), "An original packaged template was dropped")
        for name, expected in TEMPLATE_ARTIFACTS.items():
            template = raw["packagedTemplates"][name]
            _require(set(template) == {"path", "bytes", "sha256", "content"}, "A packaged template observation changed shape")
            content = template["content"].encode("utf-8")
            _same(template["path"], str(Path(runtime_root) / expected["path"]), "A template came from another package owner")
            _same([template["bytes"], template["sha256"]], [len(content), hashlib.sha256(content).hexdigest()], "Original packaged template bytes were lost")
            _same(template["sha256"], expected["sha256"], "The actual packaged template differed from its authenticated artifact")
            _same(template["content"], value["packagedTemplates"][name], "The common host template inputs were replaced")
        _same(raw["close"], {"owner": "closeOpenClawStateDatabaseAsync", "returnedUndefined": True,
              "result": {"type": "undefined"}}, "The actual state owner did not settle its close")
        writes = [{"label": "initial", "path": str(base / "workspace" / relative), "input": text}
                  for relative, text in value.get("files", {}).items()]
        writes.extend({"label": "initial", "operation": "mkdir", "path": str(base / "workspace" / relative)} for relative in value.get("directories", []))
        for key, field in (("fileBytes", "bytes"), ("fileSizes", "shape")):
            writes.extend({"label": "initial", "path": str(base / "workspace" / relative), field: item}
                          for relative, item in value.get(key, {}).items())
        writes.extend({"label": "initial", "path": str(base / "outside" / relative), "input": text}
                      for relative, text in value.get("outsideFiles", {}).items())
        for relative, target in value.get("symlinks", {}).items():
            writes.append({"label": "initial", "operation": "symlink", "path": str(base / "workspace" / relative),
                "target": str(base / target["scope"] / target["path"])})
        writes.extend({"label": "initial", "operation": "hardlink", "path": str(base / "workspace" / relative),
                       "target": str(base / "workspace" / target)} for relative, target in value.get("hardlinks", {}).items())
        for step in value["steps"]:
            writes.extend({"label": step["label"], "path": str(base / "workspace" / relative), "input": text}
                          for relative, text in step.get("writes", {}).items())
            writes.extend({"label": step["label"], "operation": "remove", "path": str(base / "workspace" / relative)} for relative in step.get("removes", []))
        _same(raw["writes"], writes, "An actual literal filesystem request was omitted or replaced")
        calls = iter(raw["calls"])
        expected_steps = []
        workspace = str(base / "workspace")

        def take(label, owner, request):
            call = next(calls)
            _same([call["label"], call["owner"], call["request"]], [label, owner, request], "A whole bootstrap owner received different arguments or ran out of order")
            if "error" in call:
                _require(set(call) == {"label", "owner", "request", "error"} | ({"warnings"} if owner == "resolveBootstrapFilesForRun" else set()), "An original bootstrap error channel was dropped")
            else:
                _require(set(call) == {"label", "owner", "request", "result", "returnedUndefined"} | ({"warnings"} if owner == "resolveBootstrapFilesForRun" else set())
                         and type(call["returnedUndefined"]) is bool
                         and call["returnedUndefined"] is (call["result"] == {"type": "undefined"}), "An original complete bootstrap return was dropped")
            return call

        _require(len(raw["snapshots"]) == len(value["steps"]), "A complete setup/filesystem snapshot was omitted")
        for step, snapshot in zip(value["steps"], raw["snapshots"], strict=True):
            label = step["label"]
            if step.get("setup"):
                take(label, "mergeWorkspaceSetupState", {"dir": workspace, "state": step["setup"]})
            ensure = None
            if "ensure" in step:
                call = take(label, "ensureAgentWorkspace", {**step["ensure"], "dir": workspace})
                ensure = {"error": _stable_error(call["error"])} if "error" in call else {"bootstrapPending": call["result"]["bootstrapPending"]}
            loaded = take(label, "loadWorkspaceBootstrapFiles", {"dir": workspace})
            runs = []
            for run in step.get("runs", []):
                request = {key: item for key, item in run.items() if key != "sessionKind"}
                call = take(label, "resolveBootstrapFilesForRun", {**request, "workspaceDir": workspace})
                runs.append({"request": run, **({"error": _stable_error(call["error"])} if "error" in call else {"files": call["result"]}), "warnings": call["warnings"]})
            state = take(label, "readWorkspaceStateSnapshot", {"dir": workspace})
            status = take(label, "resolveWorkspaceBootstrapStatus", {"dir": workspace})
            completed = take(label, "isWorkspaceSetupCompleted", {"dir": workspace})
            _require(set(snapshot) == {"label", "state", "workspace", "workspaceEntries", "hostState", "hostStateEntries", "outside", "outsideEntries"} and snapshot["label"] == label,
                     "A complete raw filesystem/setup observation was dropped")
            _same(snapshot["state"], {"error": state["error"]} if "error" in state else state["result"], "Original full setup/attestation state was replaced")
            for key in ("workspace", "hostState", "outside"):
                _tree(snapshot[key], snapshot[key + "Entries"])
            expected_steps.append({"label": label, "ensure": ensure,
                **({"loadError": _stable_error(loaded["error"])} if "error" in loaded else {"loaded": loaded["result"]}), "runs": runs,
                "bootstrapStatus": {"error": _stable_error(status["error"])} if "error" in status else status["result"],
                "setupCompleted": {"error": _stable_error(completed["error"])} if "error" in completed else completed["result"]})
        _require(next(calls, None) is None, "The observed bootstrap call batch contained undeclared calls")
        _same(row["result"], map_get_fixture_paths({"provider": "none", "steps": expected_steps}, str(base)),
              "A complete original setup decision, selected file, order, byte or warning was replaced")
    except RuntimeOracleError:
        raise
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError) as error:
        raise RuntimeOracleError("Malformed or unauthenticated complete bootstrap discovery evidence") from error
