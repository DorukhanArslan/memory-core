"""Ordinary zero-credit paired observations for fixed contract heartbeat.scratch.

Every phase executes in a fresh real Node process and a fresh SDK process. The
native side invokes exact authenticated compiled exports; the SDK side invokes
its actual public API, retaining missing APIs as actual Python exceptions.
Neither adapter supplies an upstream scratch rule or expected output snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from equivalence.heartbeat_node_authority import prepare_heartbeat_node_authority
from equivalence.heartbeat_runtime_bindings import prepare_heartbeat_runtime_bindings
from equivalence.release_runtime import prepare_release_runtime

ROOT = Path(__file__).resolve().parents[1]
LOCAL_FILES = ("equivalence/heartbeat-preload.mjs", "equivalence/heartbeat-runtime.mjs",
               "equivalence/heartbeat_scratch_probe.py", "equivalence/heartbeat_node_authority.py",
               "equivalence/heartbeat_runtime_bindings.py")
SDK_FILES = ("memory_core/heartbeat_scratch.py", "memory_core/automation.py", "memory_core/_heartbeat_constants.py",
             "memory_core/bootstrap/_js.py", "memory_core/heartbeat_ownership.py",
             "memory_core/host/kit.py", "memory_core/host/heartbeat_run.py")
NOW = 2_000_000_000_000
OWNER = {"agentId": "main", "jobId": "owner-main", "partition": "main"}


def _case(identifier, steps, *, owners=None, later=()):
    phases = [{"nowMs": NOW, "initialize": owners is not None, "owners": owners or [], "steps": steps}]
    phases.extend({"nowMs": NOW + index + 1, "initialize": False, "owners": owners or [], "steps": follow}
                  for index, follow in enumerate(later))
    return {"id": identifier, "requirement": "heartbeat.scratch", "covers": [], "kind": "store", "phases": phases}


def build_cases():
    cases = []
    for name, content in [
        ("empty", ""), ("ascii-cap", {"unit": "a", "count": 262144}),
        ("ascii-over", {"unit": "a", "count": 262145}),
        ("multibyte-cap", {"unit": "é", "count": 131072}),
        ("multibyte-over", {"unit": "é", "count": 131072, "suffix": "a"}),
        ("astral-cap", {"unit": "😀", "count": 65536}),
        ("astral-over", {"unit": "😀", "count": 65536, "suffix": "a"}),
        ("surrogate-under", {"unit": "\ud800", "count": 87381}),
        ("surrogate-over", {"unit": "\ud800", "count": 87382}),
    ]:
        cases.append(_case("scratch-cap-" + name, [{"op": "cap", "content": content}]))
    cases.append(_case("scratch-source-hashes", [{"op": "hash", "content": value}
                      for value in ("", "- Check status\n", "é😀", "\ud800", "a\ud83d\ude00b")]))
    cases.append(_case("scratch-store-transitions", [
        {"op": "read"}, {"op": "write", "content": None}, {"op": "write", "content": "", "nowMs": 10},
        {"op": "read"}, {"op": "write", "content": "first", "nowMs": 20},
        {"op": "write", "content": "stale", "expectedRevision": 0, "nowMs": 25},
        {"op": "write", "content": "second", "expectedRevision": 2, "sourceSha256": "  abc  ", "nowMs": 30},
        {"op": "read"}, {"op": "write", "content": "third", "nowMs": 35},
        {"op": "write", "content": None, "expectedRevision": 4, "nowMs": 40}, {"op": "read"},
        {"op": "write", "content": "stale resurrection", "expectedRevision": 4, "nowMs": 50},
        {"op": "write", "content": "recreated", "expectedRevision": 5, "sourceSha256": "   ", "nowMs": 60},
        {"op": "write", "content": None, "sourceSha256": "abc", "nowMs": 61},
        {"op": "write", "content": "back", "sourceSha256": "def", "nowMs": 62},
        {"op": "delete", "expectedRevision": 5}, {"op": "delete", "expectedRevision": 8}, {"op": "read"},
        {"op": "delete", "expectedRevision": 0}, {"op": "delete"},
        {"op": "write", "content": {"unit": "a", "count": 262145}, "expectedRevision": 9},
        {"op": "write", "content": "a\ud800b", "sourceSha256": "abc", "nowMs": 80}, {"op": "read"},
    ], owners=[OWNER], later=([
        {"op": "read"}, {"op": "write", "content": None, "expectedRevision": 1, "nowMs": 90}, {"op": "read"},
    ], [{"op": "read"}, {"op": "write", "content": "after reopen", "expectedRevision": 2, "nowMs": 100}, {"op": "read"}])))
    cases.append(_case("scratch-no-monitor", [{"op": "readMonitorReadOnly"}, {"op": "read"},
        {"op": "write", "content": "late", "expectedRevision": 0}, {"op": "readMonitor"}, {"op": "read"}],
        later=([{ "op": "read"}, {"op": "write", "content": None}],)))
    cases.append(_case("scratch-present-monitor", [{"op": "readMonitorReadOnly"}, {"op": "readMonitor"},
        {"op": "write", "content": "", "nowMs": 10}, {"op": "readMonitorReadOnly"},
        {"op": "write", "content": None, "nowMs": 20}, {"op": "readMonitor"}], owners=[OWNER],
        later=([{ "op": "readMonitorReadOnly"}],)))
    for name, content in [("content", "retained"), ("tombstone", None)]:
        cases.append(_case("scratch-deleted-owner-" + name, [
            {"op": "write", "content": "initial", "nowMs": 10}, {"op": "write", "content": content, "nowMs": 20},
            {"op": "removeOwner"}, {"op": "read"}, {"op": "readMonitor"},
            {"op": "write", "content": "late", "expectedRevision": 2, "nowMs": 30}, {"op": "read"},
        ], owners=[OWNER], later=([{ "op": "read"}, {"op": "write", "content": None, "expectedRevision": 2}, {"op": "read"}],)))
    cases.append(_case("scratch-deleted-owner-cleanup", [{"op": "write", "content": "initial"},
        {"op": "removeOwner", "cleanupScratch": True}, {"op": "read"},
        {"op": "write", "content": "late", "expectedRevision": 0}, {"op": "read"}], owners=[OWNER],
        later=([{ "op": "read"}],)))
    other = {"agentId": "main", "jobId": "owner-main", "partition": "other"}
    ops = {"agentId": "ops", "jobId": "owner-ops", "partition": "main"}
    cases.append(_case("scratch-partition-and-job-isolation", [
        {"op": "write", "content": "primary", "nowMs": 10},
        {"op": "write", "partition": "other", "content": "other", "nowMs": 20},
        {"op": "write", "agentId": "ops", "jobId": "owner-ops", "content": "ops", "nowMs": 30},
        {"op": "read"}, {"op": "read", "partition": "other"}, {"op": "read", "agentId": "ops", "jobId": "owner-ops"},
    ], owners=[OWNER, other, ops], later=([{ "op": "read"}, {"op": "read", "partition": "other"},
        {"op": "read", "agentId": "ops", "jobId": "owner-ops"}],)))
    return cases


def _text(value):
    return value if isinstance(value, str) else value.get("unit", "") * value.get("count", 0) + value.get("suffix", "")


def _error(exc):
    import traceback
    out = {"name": type(exc).__name__, "message": str(exc), "attributes": dict(vars(exc)),
           "stack": "".join(traceback.format_exception(exc))}
    if exc.__cause__ is not None:
        out["cause"] = _error(exc.__cause__)
    return out


def sdk_phase(request):
    import memory_core
    from memory_core.automation import FileAutomationStore
    from memory_core.heartbeat_scratch import (
        HeartbeatScratchTooLargeError, assert_heartbeat_scratch_content, hash_heartbeat_scratch_source,
        CRON_JOB_SCRATCH_MAX_BYTES,
    )
    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise ValueError("The heartbeat probe imported another SDK tree")
    directory = Path(request["fixtureDirectory"])
    directory.mkdir(parents=True, exist_ok=True)
    input_value = request["input"]
    stores = {}

    def store(partition):
        if partition not in stores:
            stores[partition] = FileAutomationStore(directory / "partitions" / partition, require_monitor_owner=True)
        return stores[partition]

    raw, values = {"calls": [], "snapshots": [], "initialization": []}, []
    if input_value["initialize"]:
        from dataclasses import asdict
        for owner in input_value["owners"]:
            result = store(owner.get("partition", "main")).enroll_heartbeat_monitor(owner["agentId"], owner["jobId"])
            raw["initialization"].append({"api": "enroll_heartbeat_monitor", "input": owner, "result": asdict(result)})
    for step in input_value["steps"]:
        owner = store(step.get("partition", "main"))
        agent_id, job_id = step.get("agentId", "main"), step.get("jobId", "owner-main")
        record = {"step": step}
        raw["calls"].append(record)
        try:
            if step["op"] == "cap":
                assert_heartbeat_scratch_content(_text(step["content"]))
                value = {"ok": True, "maxBytes": CRON_JOB_SCRATCH_MAX_BYTES}
            elif step["op"] == "hash":
                value = hash_heartbeat_scratch_source(_text(step["content"]))
            elif step["op"] == "read":
                value = owner.read_job_scratch(agent_id, job_id).to_json()
            elif step["op"] in {"readMonitor", "readMonitorReadOnly"}:
                result = owner.read_heartbeat_monitor_scratch(agent_id)
                value = result.to_json() if result is not None else {"absent": True}
            elif step["op"] == "write":
                value = owner.write_job_scratch(agent_id, job_id, None if step["content"] is None else _text(step["content"]),
                    expected_revision=step.get("expectedRevision"), source_sha256=step.get("sourceSha256"),
                    now_ms=step.get("nowMs", input_value["nowMs"])).to_json()
            elif step["op"] == "delete":
                value = owner.delete_job_scratch(agent_id, job_id, expected_revision=step.get("expectedRevision"))
            elif step["op"] == "removeOwner":
                record["fixtureMutationResult"] = owner.remove_heartbeat_monitor(agent_id, job_id=job_id,
                    cleanup_scratch=step.get("cleanupScratch", False))
                value = None  # The native owner-row fixture mutation also returns no public scratch result.
            else:
                raise ValueError("Undeclared heartbeat SDK operation")
            record["result"] = value
        except Exception as exc:
            record["error"] = _error(exc)
            # This one declared cross-language exception type is the full codec.
            # Unknown exceptions retain their actual name and message.
            value = {"error": {"name": "Error" if isinstance(exc, HeartbeatScratchTooLargeError) else type(exc).__name__,
                               "message": str(exc), **dict(vars(exc))}}
        values.append(value)
    for name, instance in stores.items():
        raw["snapshots"].append({"partition": name, "path": str(instance.path),
            "bytes": list(instance.path.read_bytes()) if instance.path.exists() else None})
    return {"kind": "heartbeat-scratch-store", "covers": [], "result": values, "raw": raw,
            "process": {"pid": os.getpid(), "executable": sys.executable}}


def _hash_files(names):
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def _same_json_wire(left, right):
    """Compare the exact JSON UTF-16 code units, including escaped surrogates.

    Python may represent an escaped pair as two surrogate code points before
    transport; JSON.parse represents those same code units as one scalar. This
    comparison changes neither a lone surrogate nor any normalization form.
    """
    return json.dumps(left, ensure_ascii=True, sort_keys=True, allow_nan=False) == json.dumps(
        right, ensure_ascii=True, sort_keys=True, allow_nan=False)


def _validate_trace(directory, context, runtime, capability):
    allowed = {(item["location"], file["path"]): file["sha256"]
               for item in runtime["packages"] for file in item["files"]}
    local = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    digest = hashlib.sha256((directory / "context.json").read_bytes()).hexdigest()
    events = []
    for trace in sorted((directory / "traces").glob("*.jsonl")):
        raw = trace.read_bytes()
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("A heartbeat process trace exceeded its bound")
        thread = [json.loads(line) for line in raw.splitlines()]
        if not thread or thread[0]["event"] != "bootstrap" or sum(item["event"] == "bootstrap" for item in thread) != 1:
            raise ValueError("Every heartbeat process/thread requires one actual bootstrap")
        boot = thread[0]
        if (boot["node"] != capability["node"] or boot["profile"] != capability["profile"]
                or boot.get("isMainThread") is not True or boot.get("threadId") != 0
                or boot["contextSha256"] != digest or boot["requestSha256"] != context["requestSha256"]
                or boot["preloadSha256"] != local[str(ROOT / "equivalence/heartbeat-preload.mjs")]):
            raise ValueError("A heartbeat process or worker changed its authority")
        for item in thread[1:]:
            if item["event"] in {"rejected", "network-denied"}:
                raise ValueError("Heartbeat evidence contains a rejected import or network attempt")
            if item["event"] not in {"load", "native-load"}:
                raise ValueError("Undeclared heartbeat evidence event")
            if item.get("kind") == "official-release":
                if allowed.get((item["package"], item["path"])) != item["sha256"]:
                    raise ValueError("A heartbeat import has unauthenticated release bytes")
            elif local.get(item.get("path")) != item.get("sha256"):
                raise ValueError("A heartbeat adapter import changed its reviewed bytes")
        events.extend(thread)
    if len(list((directory / "traces").glob("*.jsonl"))) != 1:
        raise ValueError("The synchronous heartbeat store profile admits no workers or child processes")
    if not events or not any(item.get("path") == "dist/scratch-store-BsjpiVxl.mjs" for item in events):
        raise ValueError("The original heartbeat scratch owner did not execute")
    return events


def run(checkout, runtime_cache, node, output):
    output.mkdir(parents=True, exist_ok=False)
    capability = prepare_heartbeat_node_authority(node, "heartbeat-scratch-store")
    runtime = prepare_release_runtime(checkout, runtime_cache)
    bindings = prepare_heartbeat_runtime_bindings(checkout, Path(runtime["runtimeRoot"]))
    identities = _hash_files((*LOCAL_FILES, *SDK_FILES))
    before = {"runtime": runtime, "bindings": bindings, "capability": capability, "ownedFiles": identities}
    (output / "authentication-before.json").write_text(json.dumps(before))
    cases = build_cases()
    (output / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=True))
    observations = []
    for case in cases:
        directory = output / case["id"]
        directory.mkdir()
        phases = []
        for index, input_value in enumerate(case["phases"]):
            phase = directory / str(index)
            phase.mkdir()
            (phase / "traces").mkdir()
            request = {"kind": case["kind"], "phase": index, "input": input_value,
                       "fixtureDirectory": str(directory / "native-fixture")}
            request_path = phase / "native-input.json"
            request_path.write_text(json.dumps(request, ensure_ascii=True))
            context = {"kind": "heartbeat-scratch-execution", "capability": capability,
                "providerMode": "none", "fetchPolicy": "deny", "runtime": runtime,
                "requestPath": str(request_path), "requestSha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                "traceDirectory": str(phase / "traces"), "allowedLocal": [
                    {"path": str(ROOT / name), "sha256": identities[name]} for name in LOCAL_FILES[:2]]}
            context_path = phase / "context.json"
            context_path.write_text(json.dumps(context))
            environment = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
                           "MEMORY_EQ_HEARTBEAT_CONTEXT": str(context_path)}
            native_process = subprocess.run([str(node), "--import", str(ROOT / LOCAL_FILES[0]),
                str(ROOT / LOCAL_FILES[1]), str(request_path)], capture_output=True, text=True, timeout=60,
                cwd=ROOT, env=environment)
            (phase / "native.stdout.json").write_text(native_process.stdout)
            (phase / "native.stderr.log").write_text(native_process.stderr)
            native_process.check_returncode()
            native = json.loads(native_process.stdout)
            trace = _validate_trace(phase, context, runtime, capability)
            if (native.get("covers") != [] or native["raw"]["clock"] != {
                    "owner": "node:test", "apis": ["Date"], "nowMs": input_value["nowMs"],
                    "dateConstructorReplaced": True, "setTimeoutUnchanged": True}
                    or not _same_json_wire(native["raw"]["observations"], [dict(step=step, value=value)
                        for step, value in zip(input_value["steps"], native["result"], strict=True)])):
                raise ValueError("Heartbeat observations changed their complete input/result or clock binding")
            sdk_request = {**request, "fixtureDirectory": str(directory / "sdk-fixture")}
            sdk_path = phase / "sdk-input.json"
            sdk_path.write_text(json.dumps(sdk_request, ensure_ascii=True))
            sdk_process = subprocess.run([sys.executable, "-m", "equivalence.heartbeat_scratch_probe", "--sdk-phase", str(sdk_path)],
                capture_output=True, text=True, timeout=60, cwd=ROOT,
                env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "PYTHONPATH": str(ROOT)})
            (phase / "sdk.stdout.json").write_text(sdk_process.stdout)
            (phase / "sdk.stderr.log").write_text(sdk_process.stderr)
            sdk_process.check_returncode()
            sdk = json.loads(sdk_process.stdout)
            phases.append({"phase": index, "matches": native["result"] == sdk["result"],
                           "native": native["result"], "sdk": sdk["result"],
                           "nativePid": native["raw"]["process"]["pid"], "sdkPid": sdk["process"]["pid"],
                           "traceEvents": len(trace)})
        if len({item["nativePid"] for item in phases}) != len(phases) or len({item["sdkPid"] for item in phases}) != len(phases):
            raise ValueError("Heartbeat reconstruction phases require fresh real processes")
        observations.append({"id": case["id"], "covers": [], "matches": all(item["matches"] for item in phases), "phases": phases})
    after = {"runtime": prepare_release_runtime(checkout, runtime_cache),
             "bindings": prepare_heartbeat_runtime_bindings(checkout, Path(runtime["runtimeRoot"])),
             "capability": prepare_heartbeat_node_authority(node, "heartbeat-scratch-store"),
             "ownedFiles": _hash_files((*LOCAL_FILES, *SDK_FILES))}
    (output / "authentication-after.json").write_text(json.dumps(after))
    if before != after:
        raise ValueError("A heartbeat source, adapter, SDK or runtime artifact changed during capture")
    report = {"kind": "heartbeat-scratch-ordinary-diagnostic", "covers": [], "acceptancePointsAwarded": 0,
              "sourceBuildReproduced": False, "observations": observations}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True))
    return {"cases": len(cases), "matches": sum(item["matches"] for item in observations), "acceptancePointsAwarded": 0}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--sdk-phase":
        print(json.dumps(sdk_phase(json.loads(Path(sys.argv[2]).read_text())), ensure_ascii=True))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkout", "runtime-cache", "node", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.checkout.resolve(), args.runtime_cache.resolve(), args.node.resolve(), args.output.resolve())))


if __name__ == "__main__":
    main()
