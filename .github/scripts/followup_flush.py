"""Reopen the physical SDK and OpenClaw evidence without running either engine."""
from __future__ import annotations

import hashlib
from pathlib import Path

from equivalence import flush_plan_target as family
from equivalence.flush_plan_target import build_boundary_cases as build_cases, boundaries_complete as family_complete
from equivalence.flush_execution_bindings import prepare_flush_execution_bindings
from equivalence.flush_plan_target_evidence import validate_native, validate_sdk
from equivalence.harness import ROOT, _adapter_identity, _implementation_identity, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import validate_release_sources
from equivalence.runtime_oracle import (
    MAX_DIAGNOSTIC_BYTES, MAX_REJECTED_STREAM_BYTES, MAX_SINGLE_TRACE_BYTES, _FIXTURE_CAPTURE, _owned_regular,
)


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def record_bytes(directory, filename, record, limit):
    raw = _owned_regular(directory, directory / filename, limit)
    require(len(raw) == record["bytes"] and digest(raw) == record["sha256"] and
            raw == record["text"].encode("utf-8"), f"Retained {filename} changed")
    return raw


def raw_capture(item, case_id, side, root, used):
    native = side == "native"
    path = Path(item["retainedNativeRawPath" if native else "retainedSdkRawPath"])
    require(item["id"] == case_id and item["side"] == side and item["validationStatus"] == "verified" and
            path.name == ("native-raw.json" if native else "python-raw.json") and path.parent.parent == root and
            path.parent.name.startswith("native-attempt-" if native else "sdk-attempt-") and path not in used and
            path.parent == Path(item["evidenceDirectory"]), "Unbound or reused flush evidence path")
    used.add(path)
    raw = _owned_regular(root, path, MAX_DIAGNOSTIC_BYTES)
    require(digest(raw) == item["sha256"] and len(raw) == item["nativeRawBytes" if native else "sdkRawBytes"],
            "Physical flush wire capture changed")
    parsed = _json(raw.decode("utf-8"))
    require(isinstance(parsed, list) and len(parsed) == 1 and _same_json(parsed, item["rawSnapshots"]),
            "Flush report does not match its original wire capture")
    return path.parent, parsed, len(raw)


def provider(event, captured, directory, adapters):
    key = event["capturePath"]
    require(_FIXTURE_CAPTURE.fullmatch(key) and key not in captured, "Unexpected or duplicate model plugin capture")
    source = ROOT / "equivalence" / "flush-execution.mjs"
    require(event["sourcePath"] == event["path"] == str(source) and event["sha256"] == adapters[source.name],
            "Model fixture loaded from a different source")
    sha = event["sha256"]
    name = "fixture-source-captures/" + digest((key + "\0" + sha).encode()) + ".mjs"
    require(event["proofPath"] == name, "Provider proof does not identify the actual loaded fixture")
    raw = _owned_regular(directory, directory / name, MAX_DIAGNOSTIC_BYTES)
    require(digest(raw) == sha and raw == source.read_bytes(), "Loaded fixture source differs from its physical copy")
    captured[key] = {"sourcePath": str(source), "capturePath": key, "sha256": sha, "proofPath": name,
                     "proofSha256": sha, "bytes": len(raw), "text": raw.decode("utf-8")}


def original_trace(case, trace, native, directory, runtime, adapters, global_sources, profile, public):
    transport = trace["flushPlanTargetTransport"]
    proc = native["process"]
    require(trace["id"] == case["id"] and trace["kind"] == "authenticated-process-thread-trace" and
            trace["provider"] == "none" and trace["networkFetchDenied"] is True and
            _same_json(transport["profile"], profile) and proc["executable"] == profile["nodeRuntime"]["execPath"],
            "Unbound native flush process or Node executable")
    files = transport["traceFiles"]
    require({t["name"] for t in files} == {p.name for p in directory.glob("*.jsonl")} and
            len({t["name"] for t in files}) == len(files) == 1 + trace["protectedWorkerThreads"],
            "The retained flush thread set is incomplete")
    loaded, captures, observed_contexts, drivers, bootstraps = {}, {}, set(), set(), []
    worker_sources = set()
    packages = {p["location"]: p for p in runtime["packages"]}
    for artifact in files:
        stream = record_bytes(directory, artifact["name"], artifact, MAX_SINGLE_TRACE_BYTES)
        require(stream.endswith(b"\n"), "Truncated native process trace")
        events = iter(stream.splitlines())
        first = _json(next(events).decode("utf-8"))
        tid = first["threadId"]
        context = first["contextSha256"]
        require(type(tid) is int and tid >= 0 and artifact["name"] == f"{proc['pid']}-{tid}.jsonl" and
                first["event"] == "bootstrap" and first["pid"] == proc["pid"] and first["ppid"] == proc["ppid"]
                and first["isMainThread"] is (tid == 0) and first["fetchDenied"] is True and
                first["providerMode"] == "none" and len(context) == 64 and all(c in "0123456789abcdef" for c in context) and
                first["preloadSha256"] == adapters["release-preload.mjs"] and
                _same_json(first["runtime"], profile["nodeRuntime"]) and _same_json(first["flushPlanTargetProfile"], profile),
                "Wrong thread origin, executable, engine input or protected preload")
        observed_contexts.add(context)
        bootstraps.append({k: first[k] for k in ("pid", "threadId", "isMainThread", "runtime", "flushPlanTargetProfile")})
        for line in events:
            event = _json(line.decode("utf-8"))
            require(event["pid"] == proc["pid"] and event["threadId"] == tid, "Foreign native trace event")
            kind, action, path = event["kind"], event["event"], event["path"]
            if kind == "oracle":
                filename = Path(path)
                require(action == "load" and tid == 0 and filename.parent == ROOT / "equivalence"
                        and event["sha256"] == adapters[filename.name], "Flush loaded another adapter")
                drivers.add(filename.name)
            elif kind == "fixture-capture":
                require(action == "load" and tid == 0, "Provider plugin was not loaded in the native caller")
                provider(event, captures, directory, adapters)
            else:
                require(kind == "release" and action in {"load", "resolve-native"}, "Unapproved executable event")
                key = event["package"], path
                if action == "resolve-native":
                    from equivalence.promotion_apply_bindings import NATIVE_ARTIFACTS
                    library = Path(packages[key[0]]["directory"]) / key[1]
                    require(NATIVE_ARTIFACTS.get(key) == event["sha256"] and library.resolve(strict=True) == library
                            and digest(library.read_bytes()) == event["sha256"], "Unexpected native runtime dependency")
                else:
                    require(global_sources.get(key) == event["sha256"], "Missing pinned package file")
                    loaded[key] = {k: event[k] for k in ("package", "path", "sha256")}
                    if tid and key[0] == "node_modules/openclaw":
                        worker_sources.add(key[1])
    require(drivers == {"release-oracle.mjs", "flush-plan-target-runtime.mjs", "flush-plan-selection.mjs", "flush-execution.mjs"}
            and len(observed_contexts) == 1 and any(t["isMainThread"] for t in bootstraps) and
            _same_json(bootstraps, trace["threads"]) and len(loaded) == trace["loadedReleaseFiles"] and
            (captures or not native["modelStarts"]) and _same_json([captures[k] for k in sorted(captures)],
            transport["fixtureSourceCaptures"]), "Native flush trace summaries are incomplete")
    validate_release_sources(runtime, list(loaded.values()), required_entry="dist/agent-runner-memory-Cc4lCZcs.mjs")
    stdout = record_bytes(directory, "stdout.log", transport["originalProcessStreams"]["stdout"], MAX_REJECTED_STREAM_BYTES)
    stderr = record_bytes(directory, "stderr.log", transport["originalProcessStreams"]["stderr"], MAX_REJECTED_STREAM_BYTES)
    original = _json(stdout.decode())
    require(_same_json(original, {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": public}]}), "Native process stdout disagrees with the report")
    progress = _owned_regular(directory, directory / "native-progress.json", MAX_DIAGNOSTIC_BYTES)
    require(_same_json(_json(progress.decode()), native["progress"]), "Physical progress observations changed")
    return loaded, {"protectedWorkerThreads": len(files) - 1, "fixtureSourceCaptures": len(captures),
                    "originalStdoutSha256": digest(stdout), "originalStderrSha256": digest(stderr)}


def replay_flush(data, cases, args, runtime):
    boundaries = any(family.BOUNDARY in case["covers"] for case in cases)
    expected = family.build_boundary_cases() if boundaries else family.build_cases()
    require(_same_json(cases, expected), "Flush plan replay requires the frozen ordered family")
    family.validate_registration(cases)
    root = ROOT / ".equivalence-results" / "flush-plan-target"
    require(root.resolve(strict=True) == root, "Flush retention directory is not canonical")
    bindings = prepare_flush_execution_bindings(args.reference, Path(runtime["runtimeRoot"]))
    node = prepare_model_node_authority(args.node)
    adapters = _adapter_identity()
    sdk_identity = _implementation_identity()
    require(_same_json(bindings, data["flushExecutionBindings"]) and _same_json(node, data["flushPlanTargetNode"])
            and _same_json(adapters, data["adapterSha256"]) and
            sdk_identity["sourceSha256"] == data["implementation"]["sourceSha256"], "Flush source or executable identity changed")
    sources = {(r["package"], r["path"]): r["sha256"] for r in data["followupReleaseSources"]}
    require(len(sources) == len(data["followupReleaseSources"]), "Duplicate release source")
    used, results = set(), []
    for case in cases:
        cid = case["id"]
        records = data["followupRows"][cid]
        row = records["case"]
        family.validate_case(row)
        public_match = _same_json(row["openclaw"], row["python"])
        require(row["status"] == ("matched" if public_match else "mismatched") and
                row.get("runtimeEvidenceValidated") is True and row["referenceMode"] == "authenticated-official-release",
                "Flush status disagrees with authenticated outputs")
        n, s = records["native"], records["python"]
        ndir, nr, nbytes = raw_capture(n, cid, "native", root, used)
        sdir, sr, sbytes = raw_capture(s, cid, "python", root, used)
        profile = {"caseId": cid, "operation": family.OPERATION, "inputSha256": digest(family.canonical(case["input"])),
                   "nodeRuntime": node}
        loaded, trace = original_trace(case, records["trace"], nr[0], ndir, runtime, adapters, sources, profile, row["openclaw"])
        validate_native(case, row["openclaw"], nr, ndir, loaded)
        validate_sdk(case, row["python"], sr, sdir)
        require(digest(_owned_regular(root, ndir / "native-raw.json", MAX_DIAGNOSTIC_BYTES)) == n["sha256"] and
                digest(_owned_regular(root, sdir / "python-raw.json", MAX_DIAGNOSTIC_BYTES)) == s["sha256"],
                "Flush evidence changed during replay")
        receipt = {
            "id": cid, "publicMatch": public_match, "validated": True,
            "nativeRawSha256": n["sha256"], "sdkRawSha256": s["sha256"],
            "nativeRawFileBytes": nbytes, "sdkRawFileBytes": sbytes,
            "outcome": row["openclaw"]["outcome"], "nativeWorkspaceEntries": len(nr[0]["final"]),
            "sdkWorkspaceEntries": len(sr[0]["final"]), "selectedModelCandidates": len(row["python"]["candidates"]),
            "nativeModelAttempts": len(nr[0]["modelStarts"]), **trace,
        }
        if boundaries:
            receipt["aliasWitnesses"] = {"openclaw": nr[0].get("aliasWitnesses", []),
                                         "python": sr[0].get("aliasWitnesses", [])}
            receipt["modelReplies"] = {"openclaw": [start["emittedAssistant"] for start in nr[0]["modelStarts"]],
                                       "python": [call["recordedAssistant"] for call in sr[0]["deliveries"]]}
            receipt["toolResults"] = {"openclaw": nr[0]["toolResults"], "python": sr[0]["result"]["fields"]["tools"]}
        results.append(receipt)
    require(_same_json(adapters, _adapter_identity()) and _implementation_identity()["sourceSha256"] == sdk_identity["sourceSha256"],
            "Flush evidence owners changed during replay")
    return results
