"""Reconstruct each lock observation from the two writers, disk and the shared clock."""

import hashlib
import json
from pathlib import Path
import re

from equivalence.workspace_lock_cases import build_cases
from equivalence.workspace_lock_process import _journals, read_json, retained_leases, write_json


SOURCE_PINS = {
    "extensions/memory-core/src/memory-workspace-lock.ts": "557bf3bdb03a8139af1c3fe40d106b3fb74e8ad20c30969bd888a7bccf25beb2",
    "extensions/memory-core/src/dreaming-state.ts": "b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458",
    "src/plugin-state/plugin-state-store.ts": "361e7571e9c93efde048462fd967e845c6e68a7a9f7a9c6f9a0823b6cad8b530",
    "src/plugin-sdk/process-runtime.ts": "a74d33e18876dc2f5de6d531de08b7cd744e0f727529f918989ef6ea665ac4a8",
}


def source_bindings(checkout):
    from equivalence.harness import _committed_digest
    for name, digest in SOURCE_PINS.items():
        path = checkout / name
        require(path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()
                == _committed_digest(checkout, name) == digest, "The pinned original workspace owner changed")
    return dict(SOURCE_PINS)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _observed_lease(case, raw, role, name):
    side = raw["side"]
    marker = raw["markers"][role][name]
    receipt = raw["receipts"][role]
    pid = receipt["pid"]
    space = "B" if role == "waiter" and case["input"]["workspace"] == "other" else "A"
    lease = marker["lease"]
    require(marker["pid"] == pid and marker["workspace"] == space and
            re.fullmatch(str(pid) + r":[0-9a-f-]+", lease["owner"]), "Lease owner was not this writer")
    rows = [row for row in receipt["receipts"] if row["event"] == name]
    require(len(rows) == 1 and rows[0]["lease"] == lease, "Lease marker did not come from its call")
    if side == "native":
        key = hashlib.sha256(str(Path(raw["root"]) / "workspaces" / space).encode()).hexdigest()
        values = [json.loads(row["value_json"]) for row in marker["physical"]["rows"] if row["entry_key"] == key]
        require(values == [lease] and rows[0]["physical"] == marker["physical"],
                "Original marker does not show the same physical SQLite lease")
    else:
        disk = json.loads(bytes.fromhex(marker["bytes"]))
        require(marker["bytes"] == rows[0]["bytes"] and disk["pid"] == pid
                and lease["owner"] == f"{pid}:{disk['ownerToken']}"
                and disk.get("ownerStartTime") == lease.get("ownerStartTime"),
                "SDK lease was not read from its physical file")
        from memory_core.consolidation._util import parse_ms
        require(parse_ms(disk["createdAt"], -1) == lease["acquiredAt"], "SDK lease epoch changed")
    # The two OS processes have different PIDs, random tokens and Linux start ticks.
    # Compare actor identity rather than a host-generated UUID, after checking the raw evidence.
    return {"owner": role, "workspace": space, "epoch": lease["acquiredAt"]}


def _error(raw, role, holder):
    public = raw["markers"][role]["done"]
    receipt = raw["receipts"][role]
    results = [row for row in receipt["receipts"] if row["event"] in {"done", "lock-return"}]
    require(len(results) == 1 and all(results[0][key] == public[key] for key in ("status", "error")),
            "Public result differs from its actual return")
    if public["error"] is None:
        return {"status": public["status"], "error": None}
    error = public["error"]
    actual = raw["markers"]["holder"]["entered"]["lease"]
    require(error["outcome"]["holder"] == {"owner": actual["owner"], "epoch": actual["acquiredAt"]},
            "Timeout did not identify the observed owner and epoch")
    workspace = Path(raw["root"]) / "workspaces" / "A"
    if raw["side"] == "native":
        reference = "plugin-state:memory-core/short-term-locks/" + hashlib.sha256(str(workspace).encode()).hexdigest()
    else:
        from memory_core.consolidation.store import promotion_lock_path
        reference = str(promotion_lock_path(workspace))
    require(error["message"] == f"Timed out waiting for memory workspace lock at {reference} (held by {actual['owner']})",
            "The actual error message lost its lease reference or holder")
    require(set(error["outcome"]) == {"kind", "holder"}, "Unexpected public lock failure fields")
    return {"status": public["status"], "error": {"code": error["code"], "kind": error["outcome"]["kind"],
            "holder": holder, "message": "Timed out waiting for memory workspace lock at A (held by holder)"}}


def observe_drive(case, raw, *, replay_disk=False):
    require(case in build_cases() and raw["case"] == case, "Foreign independent writer case")
    side = raw["side"]
    require(side in {"sdk", "native"}, "Unknown writer runtime")
    root = Path(raw["root"])
    if replay_disk:
        require(read_json(root / "case.json") == case and raw["caseSha256"] ==
                hashlib.sha256((root / "case.json").read_bytes()).hexdigest(), "Changed writer inputs")
        require(_journals(root) == raw["observations"][-1]["journals"]
                and retained_leases(root, side) == raw["finalLeases"], "Durable final state changed")
    holder, waiter = (raw["receipts"][role]["pid"] for role in ("holder", "waiter"))
    require(len({holder, waiter, raw["coordinatorPid"]}) == 3, "The two writers must be independent children")
    for role, receipt in raw["receipts"].items():
        rows = receipt["receipts"]
        require(rows and all(row["pid"] == receipt["pid"] and row["ppid"] == raw["coordinatorPid"]
                             for row in rows), "Receipts were not written by the launched applications")
        if replay_disk:
            require([json.loads(line) for line in (root / role / "receipts.jsonl").read_bytes().splitlines()] == rows,
                    "Raw writer receipts changed")
            require(all(read_json(root / role / (name + ".json")) == data
                        for name, data in raw["markers"][role].items()), "Raw writer marker changed")
            if side == "native":
                for trace in receipt["trace"]["traces"]:
                    path = Path(trace["path"])
                    require(path.parent == root / role / "traces" and hashlib.sha256(path.read_bytes()).hexdigest()
                            == trace["sha256"], "Original worker trace changed")
    payload = case["input"]
    if payload["holder"] == "replace-start-time":
        events = raw["receipts"]["holder"]["receipts"]
        tag = "replaced" if side == "native" else "replace-start-time"
        changes = [event for event in events if event["event"] == tag]
        require(len(changes) == 1 and changes[0]["priorPid"] == raw["coordinatorPid"],
                "The recycled PID fixture did not use the prior process")
        old, new = ((changes[0]["original"], changes[0]["replacement"]) if side == "native"
                    else (changes[0]["before"], changes[0]["after"]))
        require(new == {**old, "ownerStartTime": new["ownerStartTime"]}
                and 0 < new["ownerStartTime"] < old["ownerStartTime"],
                "The fixture changed more than process start identity")
    if "observed_twice" in raw["markers"]["waiter"]:
        events = raw["receipts"]["waiter"]["receipts"]
        current = raw["markers"]["holder"]["entered"]["lease"]
        if side == "native":
            seen = [event["returned"]["value"] for event in events if event["event"] == "store-return"
                    and event["origin"] == "lease" and event["method"] == "observe"
                    and event["returned"].get("value") == current]
        else:
            seen = [event for event in events if event["event"] == "observed"
                    and json.loads(bytes.fromhex(event["bytes"]))["ownerToken"] == current["owner"].split(":", 1)[1]]
        require(len(seen) >= 2, "The contender never actually observed the same live lease twice")
    holder_lease = _observed_lease(case, raw, "holder", "entered")
    waiter_marks = raw["markers"]["waiter"]
    waiter_lease = _observed_lease(case, raw, "waiter", "entered") if "entered" in waiter_marks else None
    if waiter_lease:
        require(_observed_lease(case, raw, "waiter", "before-release") == waiter_lease
                and waiter_marks["entered"]["lease"] == waiter_marks["before-release"]["lease"],
                "A late owner released a different writer's lease")
    wait_result = _error(raw, "waiter", holder_lease)
    killed = raw["receipts"]["holder"]["returncode"] == -9
    require(killed is (payload["holder"] == "kill") and raw["receipts"]["waiter"]["returncode"] == 0,
            "Missing original owner death or unsettled writer")
    if killed:
        require("done" not in raw["markers"]["holder"], "A killed holder returned")
    holder_result = {"status": "killed"} if killed else _error(raw, "holder", holder_lease)

    # The retained physical stores are allowed to differ, but any surviving lease is visible.
    public = {"holder": holder_result, "holderLease": holder_lease, "waiter": wait_result,
              "waiterLease": waiter_lease, "observationCountReached": "observed_twice" in waiter_marks,
              "sequence": raw["observations"], "finalLeases": raw["finalLeases"]}
    if side == "native":
        first, second = (line.encode().hex() for line in payload["lines"])
        drive = payload["drive"]
        journals = {"A": first if drive in {"timeout", "independent"} else first + second,
                    "B": second if drive == "independent" else None}
        require(raw["observations"][0]["journals"] == {"A": None, "B": None}
                and raw["observations"][-1]["journals"] == journals and not public["finalLeases"],
                "The original two writers did not exercise the final publication and release")
        require(wait_result["status"] == ("held" if drive == "timeout" else "acquired")
                and public["observationCountReached"] is (drive in {"wait", "timeout", "at-threshold"}),
                "The original did not exercise the declared exclusion/reclaim boundary")
        require(holder_lease["epoch"] == payload["epochMs"]
                and (waiter_lease is None or waiter_lease["epoch"] == payload["epochMs"] + payload["ageMs"]
                     + (1 if drive == "at-threshold" else 0)), "The original writers used a different lease age")
    return public


def run_sdk_case(case):
    from equivalence.workspace_lock_process import run_drive
    directory = Path(case["_diagnosticDirectory"])
    directory.mkdir(parents=True, exist_ok=True)
    definition = {key: val for key, val in case.items() if key != "_diagnosticDirectory"}
    raw = run_drive(definition, directory / "actors")
    write_json(directory / "python-raw.json", [raw])
    return observe_drive(definition, raw, replay_disk=True)


def run_native_case(case, directory, node, runtime):
    from equivalence.workspace_lock_process import run_drive
    raw = run_drive(case, directory / "actors", node=node, runtime=runtime)
    path = directory / "native-raw.json"
    write_json(path, [raw])
    public = observe_drive(case, raw, replay_disk=True)
    loaded = {}
    for actor in raw["receipts"].values():
        for item in actor["trace"]["loaded"]:
            loaded[item["package"], item["path"]] = item
    return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": public}], "releaseSources": list(loaded.values()),
            "releaseTrace": {"kind": "two-protected-workspace-writers", "provider": "none", "networkFetchDenied": True,
                             "actors": [a["trace"]["bootstraps"] for a in raw["receipts"].values()]},
            "runtimeDiagnostics": [{"id": case["id"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                    "rawSnapshots": [raw], "validationStatus": "verified", "rawPath": str(path)}]}
