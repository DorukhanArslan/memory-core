"""Reopen both implementations' original dreaming captures and replay their physical state."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from equivalence.dream_light_bindings import prepare_dream_light_bindings
from equivalence.dream_light_evidence import validate_dream_light_native
from equivalence.dream_light_sdk_evidence import validate_sdk
from equivalence.dream_phase_family import FAMILIES, PHASES, evidence_family, report_key
from equivalence.harness import ROOT, _adapter_identity, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.promotion_ranking_bindings import PROMOTION_WORKER_ROUTE
from equivalence.release_runtime import validate_release_sources
from equivalence.runtime_oracle import MAX_DIAGNOSTIC_BYTES, MAX_SINGLE_TRACE_BYTES, _owned_regular


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_text(record, limit):
    raw = record["text"].encode("utf-8")
    require(len(raw) <= limit and len(raw) == record["bytes"] and digest(raw) == record["sha256"],
            "Dreaming trace or process stream bytes changed")
    return raw


def capture(diagnostic, case_id, side, family_root, used_paths):
    require(diagnostic["id"] == case_id and diagnostic["side"] == side
            and diagnostic["validationStatus"] == "verified", "Wrong dreaming capture")
    if side == "native":
        path = Path(diagnostic["retainedNativeRawPath"])
        prefix = "native-attempt-"
    else:
        path = Path(diagnostic["evidenceDirectory"]) / "python-raw.json"
        prefix = "sdk-attempt-"
    require(path.parent.parent == family_root and path.parent.name.startswith(prefix)
            and path.name == ("native-raw.json" if side == "native" else "python-raw.json")
            and path not in used_paths, "Dreaming capture escaped or reused an original attempt")
    used_paths.add(path)
    raw = _owned_regular(ROOT, path, MAX_DIAGNOSTIC_BYTES)
    require(digest(raw) == diagnostic["sha256"] and
            (side != "native" or len(raw) == diagnostic["nativeRawBytes"]), "Dreaming wire file changed")
    decoded = _json(raw.decode("utf-8"))
    require(isinstance(decoded, list) and len(decoded) == 1 and
            _same_json(decoded, diagnostic["rawSnapshots"]), "Dreaming diagnostics differ from retained wire bytes")
    return path, decoded, len(raw)


def loaded_sources(case, trace, raw, profile, runtime, adapters, global_sources):
    operation = case["operation"]
    transport = trace[report_key(operation, "Transport")]
    require(trace["id"] == case["id"] and trace["kind"] == "authenticated-process-thread-trace"
            and trace["networkFetchDenied"] is True and trace["provider"] == "none"
            and trace["protectedWorkerThreads"] == 1 and len(transport["traceFiles"]) == 2
            and _same_json(transport["profile"], profile), "Dreaming process profile or SQLite worker changed")
    files, bootstraps, locals_loaded = {}, [], set()
    observed_contexts = set()
    seen_threads = set()
    commit = (ROOT / "equivalence").resolve()
    for file in transport["traceFiles"]:
        stream = checked_text(file, MAX_SINGLE_TRACE_BYTES)
        require(stream.endswith(b"\n"), "Incomplete dreaming thread trace")
        events = [_json(row.decode("utf-8")) for row in stream.splitlines()]
        first = events[0]
        thread = first["threadId"]
        is_main = first["isMainThread"]
        require(first["event"] == "bootstrap" and type(is_main) is bool and type(thread) is int
                and thread >= 0 and is_main == (thread == 0) and thread not in seen_threads
                and file["name"] == f"{raw['pid']}-{thread}.jsonl" and first["pid"] == raw["pid"]
                and first["ppid"] == raw["ppid"] and first["fetchDenied"] is True and first["providerMode"] == "none"
                and first["preloadSha256"] == adapters["release-preload.mjs"]
                and re.fullmatch(r"[0-9a-f]{64}", first["contextSha256"])
                and _same_json(first["dreamPhaseProfile"], profile) and _same_json(first["runtime"], profile["nodeRuntime"]),
                "Dreaming thread did not inherit the original case, binary and preload")
        observed_contexts.add(first["contextSha256"])
        seen_threads.add(thread)
        bootstraps.append({key: first[key] for key in ("pid", "threadId", "isMainThread", "runtime", "dreamPhaseProfile")})
        worker_paths = set()
        for event in events[1:]:
            require(event["event"] == "load" and event["pid"] == raw["pid"] and event["threadId"] == thread,
                    "Unexpected dreaming trace event")
            if event["kind"] == "oracle":
                path = Path(event["path"])
                require(is_main and path.parent == commit and adapters.get(path.name) == event["sha256"],
                        "Dreaming invocation loaded an unapproved adapter")
                locals_loaded.add(path.name)
            else:
                require(event["kind"] == "release", "Unknown dreaming source transport")
                key = event["package"], event["path"]
                require(global_sources.get(key) == event["sha256"], "Missing dreaming release source")
                files[key] = {name: event[name] for name in ("package", "path", "sha256")}
                if not is_main and key[0] == "node_modules/openclaw":
                    worker_paths.add(key[1])
        if not is_main:
            require(set(PROMOTION_WORKER_ROUTE) <= worker_paths, "Missing original SQLite worker in dreaming trace")
    require(0 in seen_threads and len(observed_contexts) == 1 and _same_json(bootstraps, trace["threads"])
            and len(files) == trace["loadedReleaseFiles"] and {"dream-light-runtime.mjs", "release-oracle.mjs"} <= locals_loaded
            and (operation != "dream-rem-runtime" or "dream-rem-runtime.mjs" in locals_loaded),
            "Dreaming traces disagree with their case receipt")
    validate_release_sources(runtime, list(files.values()), required_entry="dist/dreaming-phases-rmgXNBLP.mjs")
    return files


def replay_dreams(data, cases, args, runtime):
    require(cases, "Dreaming replay requires one complete phase")
    operation = cases[0]["operation"]
    family = FAMILIES[operation]
    family.validate_registration(cases)
    require(_same_json(cases, family.build_cases()), "Dreaming replay requires the complete frozen family")
    root = args.report.parent.resolve(strict=True)
    require(root == ROOT / ".equivalence-results", "Dreaming replay requires the designated artifact root")
    family_root = root / evidence_family(operation)
    require(family_root.resolve(strict=True) == family_root, "Aliased dreaming artifact root")
    authority = prepare_model_node_authority(args.node)
    adapters = _adapter_identity()
    bindings = prepare_dream_light_bindings(args.reference, Path(runtime["runtimeRoot"]), phase=PHASES[operation])
    require(_same_json(authority, data[report_key(operation, "Node")]) and
            _same_json(bindings, data[report_key(operation, "Bindings")]), "Dreaming release or source bindings changed")
    global_sources = {(row["package"], row["path"]): row["sha256"] for row in data["followupReleaseSources"]}
    require(len(global_sources) == len(data["followupReleaseSources"]), "Duplicate release source in full report")
    used_paths, results = set(), []
    for case in cases:
        cid = case["id"]
        row = data["followupRows"][cid]
        pair, native, sdk = row["case"], row["native"], row["python"]
        family.validate_case(pair)
        require(pair["status"] == "matched" and pair.get("runtimeEvidenceValidated") is True
                and pair["referenceMode"] == "authenticated-official-release", "Missing matched dreaming sources")
        np, ns, native_size = capture(native, cid, "native", family_root, used_paths)
        sp, ss, sdk_size = capture(sdk, cid, "python", family_root, used_paths)
        trace = row["trace"]
        profile = family.profile_for(case, args.node)
        observed = loaded_sources(case, trace, ns[0], profile, runtime, adapters, global_sources)
        streams = trace[report_key(operation, "Transport")]["originalProcessStreams"]
        stdout = checked_text(streams["stdout"], 4 * 1024 * 1024)
        stderr = checked_text(streams["stderr"], 4 * 1024 * 1024)
        original = _json(stdout.decode("utf-8"))
        require(_same_json(original, {"kind": "official-release-runtime-comparison", "sources": [],
                "results": [{"id": cid, "ok": True, "result": pair["openclaw"]}]}),
                "Dreaming output differs from the original process stream")
        directory = Path(ns[0]["root"]).parent
        require(directory.name == digest(cid.encode("utf-8")) and directory.parent.name == "evidence",
                "Dreaming original root does not bind the case")
        validate_dream_light_native(case, pair["openclaw"], ns, directory, observed)
        validate_sdk(case, pair["python"], ss, sp.parent)
        require(digest(_owned_regular(ROOT, np, MAX_DIAGNOSTIC_BYTES)) == native["sha256"]
                and digest(_owned_regular(ROOT, sp, MAX_DIAGNOSTIC_BYTES)) == sdk["sha256"],
                "Dreaming capture changed during replay")
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(pair["openclaw"], pair["python"]),
                        "nativeRawSha256": native["sha256"], "sdkRawSha256": sdk["sha256"],
                        "nativeRawFileBytes": native_size, "sdkRawFileBytes": sdk_size,
                        "originalStdoutSha256": digest(stdout), "originalStderrSha256": digest(stderr),
                        "physicalBoundaries": len(case["input"]["operations"]), "protectedWorkerThreads": 1,
                        "nativeOnDiskRawReopened": True, "sdkOnDiskRawReopened": True, "physicalStateRebuilt": True})
    require(_same_json(adapters, _adapter_identity()) and _same_json(authority, prepare_model_node_authority(args.node))
            and _same_json(bindings, prepare_dream_light_bindings(args.reference, Path(runtime["runtimeRoot"]), phase=PHASES[operation])),
            "Dreaming adapters, source, executable or release bindings changed during replay")
    return results
