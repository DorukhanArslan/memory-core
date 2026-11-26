"""Verify the retained execution packets of three previously mismatched, already registered cases."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from equivalence.bootstrap_discovery_evidence import validate_bootstrap_discovery_raw
from equivalence.harness import _same_json
from equivalence.promotion_ranking_acceptance import PROMOTION_RANKING_PRIMITIVE_CASE_ID
from equivalence.runtime_oracle import MAX_DIAGNOSTIC_BYTES, MAX_SINGLE_TRACE_BYTES


BOOTSTRAP = {"bootstrap-discovery-legacy-state-gate", "bootstrap-discovery-memory-core-layout-extension"}
RANK = PROMOTION_RANKING_PRIMITIVE_CASE_ID
PROTECTED = BOOTSTRAP | {RANK}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_wires(cid, native, sdk, node, *, native_newline=False):
    for packet, side in ((native, "native"), (sdk, "python")):
        require(packet["id"] == cid and packet["side"] == side and len(packet["rawSnapshots"]) == 1,
                "Unexpected historical diagnostic identity or packet count")
    sdk_bytes = (json.dumps(sdk["rawSnapshots"], ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()
    native_bytes = subprocess.run(
        [str(node.resolve()), "-e", "process.stdout.write(JSON.stringify(JSON.parse(require('node:fs').readFileSync(0,'utf8'))))"],
        input=json.dumps(native["rawSnapshots"], ensure_ascii=True, allow_nan=False).encode("ascii"),
        check=True, stdout=subprocess.PIPE, timeout=30,
    ).stdout + (b"\n" if native_newline else b"")
    for packet, wire in ((native, native_bytes), (sdk, sdk_bytes)):
        require(0 < len(wire) <= MAX_DIAGNOSTIC_BYTES and sha(wire) == packet["sha256"],
                "Retained diagnostic does not reproduce its original producer bytes")


def verify_rank_sdk(case, native_result, sdk_result, native_rows, sdk_rows):
    value = case["input"]
    [sdk] = sdk_rows
    for raw, public in ((sdk, sdk_result), (native_rows[0], native_result)):
        require(_same_json(raw["input"], value) and _same_json(raw["output"], public),
                "Historical ranking whole output or input differs from the original process")
    save, phase, *queries = sdk["calls"]
    require(save["operation"] == "write_recall_store" and _same_json(save["arguments"], value["store"])
            and phase["operation"] == "seed_phase_file" and _same_json(phase["arguments"], value["phase"]),
            "Historical ranking store writes differ from the registered input")
    for actual, request, public in zip(queries, value["queries"], sdk_result["queries"], strict=True):
        require(actual["operation"] == "rank_short_term_promotion_candidates" and actual["label"] == request["label"]
                and _same_json(actual["options"], request["options"]) and _same_json(actual["result"], public["candidates"]),
                "Historical ranking candidate list differs from its original query result")
    for snapshot, phase in zip(sdk["snapshots"], ("before", "after"), strict=True):
        require(snapshot["phase"] == phase and _same_json(snapshot["logical"], sdk_result[phase]),
                "Historical ranking store observation differs from the SDK output")
        files = {f["path"]: f for f in snapshot["files"]}
        for name, seeded in (("phase-signals.json", value["phase"]), ("short-term-recall.json", save["postCallArguments"])):
            f = files["workspace/memory/.dreams/" + name]
            raw = bytes.fromhex(f["hex"])
            require(len(raw) == f["stat"]["size"] and _same_json(json.loads(raw), seeded),
                    "A physical SDK ranking file differs from its complete write")


def replay_bootstrap(case, parts, args, runtime, root, profile):
    from equivalence.bootstrap_discovery_bindings import BASELINE_COMPILED_ARTIFACTS
    cid = case["id"]
    native, sdk, trace, pair = (parts[k] for k in ("native", "python", "trace", "pair"))
    verify_wires(cid, native, sdk, args.node, native_newline=True)
    [original], [coordinator] = native["rawSnapshots"], sdk["rawSnapshots"]
    transport = trace["bootstrapDiscoveryTransport"]
    release_root = Path(runtime["runtimeRoot"])
    require(trace["kind"] == "authenticated-process-thread-trace" and trace["id"] == cid
            and trace["provider"] == "none" and trace["networkFetchDenied"] is True
            and transport["kind"] == "actual-bootstrap-discovery-validator-inputs"
            and _same_json(transport["profile"], profile) and transport["adapterRoot"] == str(root)
            and transport["runtimeRoot"] == str(release_root) and _same_json(transport["case"], case),
            "The original bootstrap caller used a different source tree, runtime or case")
    allowed = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    local_paths = {str(root / "equivalence" / name) for name in (
        "release-oracle.mjs", "bootstrap-discovery-runtime.mjs", "get-contract-runtime.mjs", "search-contract-runtime.mjs")}
    preload = sha((root / "equivalence/release-preload.mjs").read_bytes())
    pid, ppid = original["pid"], original["ppid"]
    loaded, locals_loaded, headers, contexts = set(), set(), [], set()
    for carrier in transport["rawProcessWorkerTraces"]:
        wire = carrier["text"].encode()
        require(0 < len(wire) == carrier["bytes"] <= MAX_SINGLE_TRACE_BYTES and wire.endswith(b"\n")
                and sha(wire) == carrier["sha256"], "Bootstrap trace bytes changed")
        header, *events = [json.loads(line) for line in wire.splitlines()]
        thread = header["threadId"]
        require(header["event"] == "bootstrap" and (header["pid"], header["ppid"]) == (pid, ppid)
                and type(thread) is int and thread >= 0 and header["isMainThread"] is (thread == 0)
                and carrier["name"] == f"{pid}-{thread}.jsonl" and header["preloadSha256"] == preload
                and header["fetchDenied"] is True and header["providerMode"] == "none"
                and re.fullmatch(r"[a-f0-9]{64}", header["contextSha256"])
                and {key for key in header if key.endswith("Profile")} == {"bootstrapProfile"}
                and _same_json(header["bootstrapProfile"], profile) and _same_json(header["runtime"], profile["nodeRuntime"]),
                "Bootstrap trace owner or runtime changed")
        contexts.add(header["contextSha256"])
        headers.append({k: header[k] for k in ("pid", "threadId", "isMainThread", "runtime", "bootstrapProfile")})
        for event in events:
            path = event["path"]
            require(event["pid"] == pid and event["threadId"] == thread and event["event"] in {"load", "resolve-native"},
                    "Bootstrap trace escaped its original producer")
            if event["kind"] == "oracle":
                require(thread == 0 and event["event"] == "load" and path in local_paths
                        and sha(Path(path).read_bytes()) == event["sha256"], "Bootstrap loaded a different adapter")
                locals_loaded.add(path)
            else:
                key = (event["package"], path)
                require(event["kind"] == "release" and key in allowed and allowed[key] == event["sha256"],
                        "Bootstrap source is absent from the authenticated release")
                if event["event"] == "load":
                    loaded.add(key)
    native_owners = {path for package, path in loaded if package == "node_modules/openclaw"}
    require(len(contexts) == 1 and len(headers) == len({h["threadId"] for h in headers})
            and sum(h["isMainThread"] for h in headers) == 1
            and trace["protectedWorkerThreads"] == sum(not h["isMainThread"] for h in headers)
            and _same_json(headers, transport["bootstrap"]) and _same_json(headers, trace["threads"])
            and len(loaded) == trace["loadedReleaseFiles"]
            and set(BASELINE_COMPILED_ARTIFACTS) <= native_owners
            and transport["processParents"] == {str(pid): ppid}
            and transport["releaseByPid"] == {str(pid): sorted(native_owners)}
            and transport["localByPid"] == {str(pid): sorted(locals_loaded)},
            "Bootstrap protected process, worker or source inventory differs from its original traces")
    owned_dir = Path(original["fixtureBase"]).parent
    require(owned_dir.name == sha(cid.encode()) and owned_dir.parent.name == "evidence"
            and owned_dir.parent.parent.name.startswith("memory-release-oracle-"), "Unowned bootstrap evidence directory")
    public_row = {"id": cid, "ok": True, "result": pair["openclaw"]}
    require(_same_json(transport["row"], public_row), "Bootstrap trace and whole native output differ")
    validate_bootstrap_discovery_raw(public_row, case, native["rawSnapshots"], owned_dir,
                                     runtime_root=release_root, bootstrap=headers, release_by_pid={pid: native_owners},
                                     local_by_pid={pid: locals_loaded}, process_parents={pid: ppid})
    child = coordinator["child"]
    observation = json.loads(child["stdout"])
    raw = observation["raw"]
    request = {"directory": coordinator["fixtureBase"], "input": case["input"]}
    require(child["exit"] == {"code": 0, "signal": None} and _same_json(child["request"], request)
            and _same_json(json.loads(child["requestJson"]), request) and sha(child["requestJson"].encode()) == child["requestSha256"]
            and _same_json(child["observation"], observation) and _same_json(observation["result"], pair["python"])
            and _same_json(raw["input"], case["input"]) and _same_json(coordinator["input"], raw["input"])
            and raw["fixtureBase"] == coordinator["fixtureBase"] and raw["implementationRoot"] == str(root)
            and (raw["pid"], raw["ppid"]) == (child["pid"], coordinator["coordinatorPid"])
            and child["environmentKeys"] == ["LANG", "PATH", "PYTHONPATH", "TZ"]
            and child["argv"][1:] == ["-m", "equivalence.bootstrap_discovery_sdk", "--phase"],
            "Bootstrap SDK process, input, or whole output changed")

    def inventory(snapshots):
        return [{"label": snap["label"], "workspace": snap["workspaceEntries"], "outside": snap["outsideEntries"],
                 "snapshotSha256": sha(json.dumps(snap, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                                                       allow_nan=False).encode())}
                for snap in snapshots]

    return {"id": cid, "publicMatch": _same_json(pair["openclaw"], pair["python"]), "rawWireHashesReproduced": True,
            "nativeOnDiskRawReopened": False, "sdkRawSha256": sdk["sha256"], "nativeCollectorRawSha256": native["sha256"],
            "sdkChildStdoutSha256": sha(child["stdout"].encode()), "sdkRequestSha256": child["requestSha256"],
            "rawTraceSha256": [c["sha256"] for c in transport["rawProcessWorkerTraces"]],
            "protectedWorkerThreads": trace["protectedWorkerThreads"], "compiledOwners": len(native_owners),
            "nativePhases": inventory(original["snapshots"]), "sdkPhases": inventory(raw["snapshots"])}
