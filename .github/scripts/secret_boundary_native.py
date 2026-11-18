"""Reopen the four synthetic boundary callers and independently authenticate each original result."""
from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import Path
import re

from equivalence.harness import ROOT, _adapter_identity, _committed_digest, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.model_runtime_evidence import validate_model_session_raw
from equivalence.model_tool_error_evidence import validate_model_tool_error_raw
from equivalence.redaction_policy_evidence import SOURCE_HASHES, validate_redaction_policy_source_execution
from equivalence.runtime_oracle import MAX_DIAGNOSTIC_BYTES, MAX_SINGLE_TRACE_BYTES, _owned_regular
from equivalence.secret_boundary_inputs import CHUNKED_ID, ERROR_ID, SESSION_ID, WHOLE_ID, build_cases


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _streams(meta):
    root = ROOT / ".equivalence-results" / "secret-redaction"
    directory = Path(meta["directory"])
    require(directory.parent == root and directory.name.startswith("native-attempt-")
            and directory.resolve(strict=True) == directory, "Foreign secret boundary process streams")
    streams = {}
    for name in ("stdout", "stderr"):
        raw = _owned_regular(root, directory / (name + ".log"), 32 * 1024 * 1024)
        require(meta[name] == {"bytes": len(raw), "sha256": digest(raw)}, "Original process stream changed")
        streams[name] = raw
    return directory, _json(streams["stdout"].decode("utf-8")), {
        "originalStdoutSha256": digest(streams["stdout"]), "originalStderrSha256": digest(streams["stderr"])}


def _source(case, public, record, reference, node):
    _, stdout, result = _streams(record["originalStreams"])
    x = record["sourceExecution"]
    require(record["id"] == case["id"] and _same_json(stdout["sourceExecution"], x), "Wrong original source-policy caller")
    response = {"id": case["id"], "ok": True, "result": public}
    require(_same_json(stdout["results"], [response]), "Different original source-policy output")
    values = {s["path"]: s["sha256"] for s in stdout["sources"]}
    originals = set(SOURCE_HASHES) | {"src/logging/redact-bounded.ts"}
    for path in originals:
        require(values.get(path) == _committed_digest(reference, path) == digest((reference / path).read_bytes()),
                "Original source graph lost a bounded redaction owner")
    frame = x["observations"][0]
    base = Path(frame["logging"]["json"]["file"]).parent
    validate_redaction_policy_source_execution(stdout, case, node_authority=node, process_pid=x["pid"],
        coordinator_pid=x["ppid"], fixture_root=base)
    units = len(case["input"]["text"].encode("utf-16-le")) // 2
    masked = public["result"]["explicitSensitiveText"]
    require(units == (32769 if case["id"] == CHUNKED_ID else 32768) and
            ("BOUNDARY-1234" in masked) == (case["id"] == CHUNKED_ID) and
            "BOUNDARY-9876" not in masked and masked.count("***") == (1 if case["id"] == CHUNKED_ID else 2),
            "Original bounded redaction did not exercise its exact whole-to-chunk transition")
    return {**result, "utf16Units": units, "boundedSourceOwners": len(originals),
            "originalCalls": len(frame["calls"]), "straddlingInnocuousMarkerVisible": "BOUNDARY-1234" in masked}


def _runtime_actors(trace, node, adapters, runtime, release_sources):
    carriers = trace["secretBoundaryTransport"]["rawProcessWorkerTraces"]
    allowed = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    actual = {(p["package"], p["path"]): p["sha256"] for p in release_sources}
    require(len(release_sources) == len(actual), "Duplicate actual released source")
    loaded = set()
    seen, contexts, parents = set(), set(), {}
    boot, workers = [], []
    native, local = defaultdict(set), defaultdict(set)
    for carrier in carriers:
        raw = carrier["text"].encode("utf-8")
        require(0 < len(raw) <= MAX_SINGLE_TRACE_BYTES and raw.endswith(b"\n")
                and carrier["bytes"] == len(raw) and carrier["sha256"] == digest(raw), "Changed process trace")
        events = [_json(line.decode("utf-8")) for line in raw.splitlines()]
        init = events[0]
        pid, tid = init["pid"], init["threadId"]
        require(type(pid) is int and pid > 0 and type(tid) is int and tid >= 0 and (pid, tid) not in seen
                and carrier["name"] == f"{pid}-{tid}.jsonl" and init["event"] == "bootstrap"
                and init["isMainThread"] is (tid == 0) and init["fetchDenied"] is True
                and init["providerMode"] == "none" and _same_json(init["runtime"], node)
                and init["preloadSha256"] == adapters["release-preload.mjs"]
                and re.fullmatch("[a-f0-9]{64}", init["contextSha256"]), "Invalid original child bootstrap")
        seen.add((pid, tid))
        contexts.add(init["contextSha256"])
        if tid == 0:
            parents[pid] = init["ppid"]
        boot.append({k: init[k] for k in ("pid", "threadId", "isMainThread", "runtime")})
        for event in events[1:]:
            require((event["pid"], event["threadId"]) == (pid, tid)
                    and event["event"] in {"load", "resolve-native"}, "Unapproved secret boundary process event")
            name = event["path"]
            if event["kind"] == "oracle":
                path = Path(name)
                require(path.parent == ROOT / "equivalence" and event["sha256"] == adapters.get(path.name)
                        == digest(path.read_bytes()), "Changed original caller adapter")
                if tid == 0 and event["event"] == "load":
                    local[pid].add(name)
            else:
                key = (event["package"], name)
                require(event["kind"] == "release" and event["sha256"] == allowed.get(key), "Unapproved release owner")
                if event["event"] == "load":
                    require(event["sha256"] == actual.get(key), "Original release owner missing from report")
                    loaded.add(key)
                    if key[0] == "node_modules/openclaw":
                        native[pid].add(name)
                    if tid:
                        workers.append({"package": key[0], "path": name, "threadId": tid, "pid": pid})
    require(len(contexts) == 1 and _same_json(boot, trace["threads"])
            and trace["protectedWorkerThreads"] == sum(t > 0 for _, t in seen)
            and trace["loadedReleaseFiles"] == len(loaded)
            and trace["networkFetchDenied"] is True and trace["provider"] == "none", "Process trace index disagrees")
    return dict(bootstrap=boot, release_by_pid=native, local_by_pid=local, process_parents=parents, worker_imports=workers)


def _stage_checks(case, record):
    if case["id"] == ERROR_ID:
        observed = record["child"]["raw"]
        require([v["name"] for v in observed["invocations"]] == ["get", "search"]
                and all(v["thrownErrorIsOriginal"] is True for v in observed["requests"])
                and "EPIPE" in observed["formatter"] and "demo-supplement-credential" not in observed["formatter"],
                "The original tool or causal formatter did not exercise the declared failure")
        return {"supplementThrows": len(observed["requests"]), "publicToolCalls": len(observed["invocations"]),
                "terminalCode": "EPIPE"}
    write, continued, read = [p["raw"] for p in record["phases"]]
    execution, = write["executions"]
    late = case["input"]["phases"][0]["lateRegisteredSecret"]
    tool_stages = [s for s in write["stages"] if s["stage"] == "tool-return" or s["message"].get("role") == "toolResult"]
    require([s["stage"] for s in tool_stages] == ["tool-return", "event:message_start", "event:message_end", "persisted-callback"]
            and late in tool_stages[2]["message"]["content"][0]["text"]
            and late not in tool_stages[3]["message"]["content"][0]["text"]
            and all(s["secret"] == late for s in write["registry"] if s["stage"] == "live-event-registration")
            and [s["stage"] for s in write["registry"]].count("live-event-registration") == 1
            and _same_json(write["sessionSqlAfter"], continued["sessionSqlBefore"])
            and _same_json(continued["sessionSqlAfter"], read["sessionSqlAfter"])
            and execution["telemetry"]["content"][0]["text"].endswith("…(truncated)…"), "Missing genuine truncation, listener or fresh SQL reread")
    return {"freshPhases": 3, "originalEvents": [len(v["events"]) for v in (write, continued, read)],
            "sourceRawInputReuseDiagnostic": execution["identities"]["originalInputReuse"],
            "preparedOutputReuseDiagnostic": execution["identities"]["preparedOutputReuse"],
            "persistedMessages": [len(v["persisted"]) for v in (write, continued, read)]}


def check_native(case, public, *, source_policy=None, native=None, trace=None, reference, node, release_runtime,
                 release_sources, adapters):
    frozen = {c["id"]: c for c in build_cases()}
    require(_same_json(case, frozen.get(case.get("id"))) and _same_json(adapters, _adapter_identity()),
            "Unknown redaction caller or changed adapter owner")
    executable = prepare_model_node_authority(node)
    if case["id"] in {WHOLE_ID, CHUNKED_ID}:
        return _source(case, public, source_policy, reference, executable)
    directory, stdout, result = _streams(trace["secretBoundaryTransport"]["originalStreams"])
    row = {"id": case["id"], "ok": True, "result": public}
    require(_same_json(stdout, {"kind": "official-release-runtime-comparison", "sources": [], "results": [row]})
            and native["side"] == "native" and native["id"] == trace["id"] == case["id"], "Wrong original result")
    raw_path = directory / "native-raw.json"
    require(native["retainedNativeRawPath"] == str(raw_path), "Wrong original raw path")
    raw = _owned_regular(directory, raw_path, MAX_DIAGNOSTIC_BYTES)
    snapshots = _json(raw.decode("utf-8"))
    require(native["nativeRawBytes"] == len(raw) and native["sha256"] == digest(raw)
            and _same_json(snapshots, native["rawSnapshots"]), "Changed native capture")
    actors = _runtime_actors(trace, executable, adapters, release_runtime, release_sources)
    record, = snapshots
    owner = validate_model_session_raw if case["id"] == SESSION_ID else validate_model_tool_error_raw
    owner(row, case, snapshots, Path(record["fixtureBase"]).parent, runtime_root=release_runtime["runtimeRoot"], **actors)
    return {**result, **_stage_checks(case, record), "nativeRawSha256": digest(raw), "nativeRawBytes": len(raw),
            "protectedProcesses": len(actors["process_parents"]), "protectedThreads": trace["protectedWorkerThreads"]}
