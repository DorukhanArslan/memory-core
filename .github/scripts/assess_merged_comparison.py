"""Strict EOF projection and candidate coverage; not a complete root audit."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from equivalence.cases import build_cases  # noqa: E402
from equivalence.catalog_migration import definition_authority  # noqa: E402
from equivalence.harness import _adapter_identity, _implementation_identity, _same_json  # noqa: E402
from equivalence.strict_report_reader import Reader, _constant, _finite, _object  # noqa: E402

PRODUCT = "f8a8ffd09f633996f299a93ab7306282f0448130"
SCOPE = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
SDK = {"sourceSha256": "48973e195a41e1d2dfdc8bbe366293b8ebed0830571b3d0764ebe8a8a7b443a0", "sourceFiles": 162}
OPERATIONS = ("host-restart-session-runtime", "host-update-isolation-runtime",
              "host-turn-barrier-boundaries-runtime", "index-identity-boundaries-runtime",
              "query-sync-outcomes-runtime", "query-sync-boundaries-runtime",
              "host-turn-barrier-v4-runtime", "forget-index-fence-v6-runtime", "forget-lineage-runtime",
              "forget-boundaries-runtime", "recall-signals-runtime", "embed-cache-lifecycle-runtime")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def load(path):
    value = json.loads(Path(path).read_text(), object_pairs_hook=_object, parse_constant=_constant)
    _finite(value)
    return value


def project(path, host_ids, lineage_ids, boundary_ids, recall_ids, cache_ids):
    kept = {"schemaVersion", "kind", "mode", "status", "fullScopePassed", "implementation",
            "reference", "manifestSha256", "adapterSha256", "casesSha256", "definitionMigration",
            "summary", "requirements", "errors", "startedAt", "finishedAt", "durationSeconds",
            "referenceExecution", "paidProviderCalls", "providerCredentialsForwarded",
            "forgetLineageOutcomesFamilyComplete", "forgetBoundariesFamilyComplete",
            "forgetLineageBindings", "forgetLineageNode", "recallSignalsFamilyComplete",
            "recallSignalsBindings", "recallSignalsNode", "embeddingCacheFamilyComplete",
            "embeddingCacheBindings", "embeddingCacheNode"}
    result = {"cases": [], "hostPairs": {}, "hostDiagnostics": {}, "mismatchPairs": {},
              "lineagePairs": {}, "lineageDiagnostics": {}, "lineageTraces": {},
              "boundaryPairs": {}, "boundaryDiagnostics": {}, "boundaryTraces": {},
              "recallPairs": {}, "recallDiagnostics": {}, "recallTraces": {},
              "cachePairs": {}, "cacheDiagnostics": {}, "cacheTraces": {}}
    before = digest(path)

    def accept(key, value, array):
        if array == "array-done":
            if key in kept:
                result.setdefault(key, [])
            return
        if key == "cases":
            row = {k: v for k, v in value.items() if k not in {"openclaw", "python"}}
            if {"openclaw", "python"} & set(value):
                require({"openclaw", "python"} <= set(value), "Incomplete retained public pair")
                equal = _same_json(value["openclaw"], value["python"])
                require(value["status"] in {"matched", "mismatched"}
                        and equal is (value["status"] == "matched"), "Whole public values contradict row status")
                pair = {side: value[side] for side in ("openclaw", "python")}
                row["publicValueSha256"] = {side: hashlib.sha256(canonical(item)).hexdigest()
                                           for side, item in pair.items()}
                if value["id"] in host_ids:
                    result["hostPairs"][value["id"]] = pair
                if value["id"] in lineage_ids:
                    result["lineagePairs"][value["id"]] = pair
                if value["id"] in boundary_ids:
                    result["boundaryPairs"][value["id"]] = pair
                if value["id"] in recall_ids:
                    result["recallPairs"][value["id"]] = pair
                if value["id"] in cache_ids:
                    result["cachePairs"][value["id"]] = pair
                if value["status"] == "mismatched":
                    result["mismatchPairs"][value["id"]] = pair
            require(value["status"] != "mismatched" or "python" in value, "Mismatch omitted whole public values")
            result["cases"].append(row)
        elif key == "runtimeDiagnostics" and value.get("id") in cache_ids:
            require(value.get("side") in {"native", "python"}, "Unknown embedding cache diagnostic side")
            identity = value["id"] + "--" + value["side"]
            require(identity not in result["cacheDiagnostics"], "Duplicate embedding cache diagnostic")
            require(isinstance(value.get("rawSnapshots"), list) and len(value["rawSnapshots"]) == 1
                    and isinstance(value["rawSnapshots"][0], dict),
                    "Embedding cache diagnostic is not a complete singleton packet")
            result["cacheDiagnostics"][identity] = value
        elif key == "releaseTraces" and value.get("id") in cache_ids:
            require(value["id"] not in result["cacheTraces"], "Duplicate embedding cache process trace")
            result["cacheTraces"][value["id"]] = value
        elif key == "runtimeDiagnostics" and value.get("id") in recall_ids:
            require(value.get("side") in {"native", "python"}, "Unknown recall diagnostic side")
            identity = value["id"] + "--" + value["side"]
            require(identity not in result["recallDiagnostics"], "Duplicate recall diagnostic")
            require(isinstance(value.get("rawSnapshots"), list) and len(value["rawSnapshots"]) == 1,
                    "Recall diagnostic is not a complete singleton packet")
            result["recallDiagnostics"][identity] = value
        elif key == "releaseTraces" and value.get("id") in recall_ids:
            require(value["id"] not in result["recallTraces"], "Duplicate recall process trace")
            result["recallTraces"][value["id"]] = value
        elif key == "runtimeDiagnostics" and value.get("id") in lineage_ids:
            identity = value["id"] + "--" + value["side"]
            require(identity not in result["lineageDiagnostics"], "Duplicate lineage diagnostic")
            require(isinstance(value.get("rawSnapshots"), list) and len(value["rawSnapshots"]) == 1,
                    "Lineage diagnostic is not a complete singleton packet")
            result["lineageDiagnostics"][identity] = value
        elif key == "releaseTraces" and value.get("id") in lineage_ids:
            require(value["id"] not in result["lineageTraces"], "Duplicate lineage process trace")
            result["lineageTraces"][value["id"]] = value
        elif key == "runtimeDiagnostics" and value.get("id") in boundary_ids:
            identity = value["id"] + "--" + value["side"]
            require(identity not in result["boundaryDiagnostics"], "Duplicate boundary diagnostic")
            require(isinstance(value.get("rawSnapshots"), list) and len(value["rawSnapshots"]) == 1,
                    "Boundary diagnostic is not a complete singleton packet")
            result["boundaryDiagnostics"][identity] = value
        elif key == "releaseTraces" and value.get("id") in boundary_ids:
            require(value["id"] not in result["boundaryTraces"], "Duplicate boundary process trace")
            result["boundaryTraces"][value["id"]] = value
        elif key == "runtimeDiagnostics" and value.get("id") in host_ids:
            identity = value["id"] + "--" + value["side"]
            require(identity not in result["hostDiagnostics"], "Duplicate Host diagnostic")
            raw = value.get("rawSnapshots")
            require(isinstance(raw, list) and len(raw) == 1, "Host diagnostic is not a whole singleton packet")
            result["hostDiagnostics"][identity] = {
                **{k: v for k, v in value.items() if k != "rawSnapshots"},
                "rawSnapshotsSha256": hashlib.sha256(canonical(raw)).hexdigest()}
        elif key in kept:
            if array:
                result.setdefault(key, []).append(value)
            else:
                result[key] = value

    Reader(path).top(accept)
    require(digest(path) == before, "Full report changed during complete EOF parsing")
    result["report"] = {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": before}
    return result


def source_unchanged(seal):
    require(seal["kind"] == "approved-product-comparison-source-seal"
            and seal["productSourceCommit"] == PRODUCT and _same_json(seal["productSdk"], SDK)
            and seal["sdkBytesEqualProductSource"] is True, "Wrong approved product source authority")
    require(seal["scopeSha256"] == digest(ROOT / "equivalence/scope.json") == SCOPE, "Fixed scope changed")
    require(_same_json(_implementation_identity(), seal["implementation"])
            and all(seal["implementation"][key] == value for key, value in SDK.items())
            and seal["implementation"]["trackedWorkingTreeDirty"] is False, "SDK/source identity changed")
    require(_same_json(_adapter_identity(), seal["adapters"]), "Adapter inventory changed")
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    current = {name: digest(ROOT / name) for name in names if name and (ROOT / name).is_file()}
    require(current == seal["allTrackedFileHashes"], "Complete tracked source inventory changed")


def replay_hosts(data, cases, args):
    from equivalence.host_turn_barrier_v4_evidence import replay_case
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.release_runtime import prepare_release_runtime

    node = prepare_model_node_authority(args.node)
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    family = (ROOT / ".equivalence-results/host-turn-barrier-v4").resolve(strict=True)
    results = []
    for case in cases:
        cid, directories, files = case["id"], {}, []
        for side in ("native", "python"):
            diagnostic = data["hostDiagnostics"][cid + "--" + side]
            directory = Path(diagnostic["evidenceDirectory"])
            require(directory.is_absolute() and directory.resolve(strict=True) == directory
                    and directory.is_relative_to(family), "Host capture escaped its actual family root")
            raw = directory / ("evidence/native-raw.json" if side == "native" else "python-raw.json")
            require(diagnostic["validationStatus"] == "verified" and digest(raw) == diagnostic["sha256"]
                    and hashlib.sha256(canonical(load(raw))).hexdigest() == diagnostic["rawSnapshotsSha256"],
                    "Actual Host raw bytes differ from complete report")
            directories[side] = directory
            files.append((raw, digest(raw)))
        actual = replay_case(case, directories["native"], directories["python"], approved_node=node,
                             approved_runtime=runtime, approved_reference=args.reference,
                             approved_source_root=ROOT, registered=True)
        pair = data["hostPairs"][cid]
        require(actual["validated"] is True and actual["acceptancePointsAwarded"] == 0
                and _same_json(actual["nativeResult"], pair["openclaw"])
                and _same_json(actual["sdkResult"], pair["python"]), "Reopened Host whole results changed")
        require(all(digest(path) == sha for path, sha in files), "Host raw changed during replay")
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(pair["openclaw"], pair["python"])})
    return results


def replay_lineage(data, cases, args):
    from equivalence.forget_lineage_bindings import prepare_forget_lineage_bindings
    from equivalence.forget_lineage_outcomes_evidence import validate_pair
    from equivalence.forget_lineage_profile import prepare_forget_lineage_profile
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.release_runtime import prepare_release_runtime

    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    require(_same_json(data["forgetLineageBindings"], prepare_forget_lineage_bindings(
        args.reference, Path(runtime["runtimeRoot"])))
        and _same_json(data["forgetLineageNode"], prepare_model_node_authority(args.node)),
        "Lineage source/artifact/executable authority changed")
    family = (ROOT / ".equivalence-results/forget-lineage-outcomes").resolve(strict=True)
    results = []
    for case in cases:
        cid = case["id"]
        native = data["lineageDiagnostics"][cid + "--native"]
        sdk = data["lineageDiagnostics"][cid + "--python"]
        require(native["validationStatus"] == sdk["validationStatus"] == "verified",
                "Lineage capture was not affirmatively validated")
        directory = Path(sdk["evidenceDirectory"])
        require(directory.is_absolute() and directory.resolve(strict=True) == directory
                and directory.is_relative_to(family), "Lineage SDK capture escaped its actual family root")
        raw_path = directory / "python-raw.json"
        raw_sha, sdk_raw = digest(raw_path), load(raw_path)
        require(raw_sha == sdk["sha256"] and _same_json([sdk_raw], sdk["rawSnapshots"]),
                "Complete retained SDK raw bytes differ from the full report")
        trace = data["lineageTraces"][cid]
        transport = trace["forgetLineageTransport"]
        require(trace["provider"] == "none" and trace["networkFetchDenied"] is True
                and _same_json(transport["profile"], prepare_forget_lineage_profile(case, args.node)),
                "Lineage original process capability changed")
        for carrier in (*transport["traceFiles"], *transport["originalProcessStreams"].values()):
            payload = carrier["text"].encode("utf8")
            require(len(payload) == carrier["bytes"] and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
                    "A complete original lineage process carrier changed")
        stream = transport["originalProcessStreams"]["stdout"]
        original = json.loads(stream["text"], object_pairs_hook=_object, parse_constant=_constant)
        _finite(original)
        require(len(original["results"]) == 1 and original["results"][0]["id"] == cid
                and original["results"][0]["ok"] is True, "Original lineage stdout omitted its complete return")
        native_public = original["results"][0]["result"]
        sdk_public = {"kind": sdk_raw["input"]["kind"], "provider": "none", "acceptancePointsAwarded": 0,
                      "observations": [row["observed"] for row in sdk_raw["operations"]]}
        actual_native, actual_sdk = validate_pair(case, native["rawSnapshots"][0], sdk_raw,
                                                 native_public, sdk_public, directory)
        pair = data["lineagePairs"][cid]
        require(_same_json(actual_native, pair["openclaw"]) and _same_json(actual_sdk, pair["python"])
                and digest(raw_path) == raw_sha, "Lineage projection or actual raw bytes changed during replay")
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(actual_native, actual_sdk),
                        "sdkRawSha256": raw_sha, "nativeRawSnapshotsSha256": hashlib.sha256(
                            canonical(native["rawSnapshots"])).hexdigest(), "originalStdoutSha256": stream["sha256"],
                        "actualForgetReports": len(actual_native["observations"])})
    return results


def replay_boundaries(data, cases, args):
    from equivalence.forget_boundaries_evidence import validate_pair
    from equivalence.forget_boundaries_profile import prepare_forget_boundaries_profile
    from equivalence.forget_lineage_bindings import prepare_forget_lineage_bindings
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.release_runtime import prepare_release_runtime

    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    require(_same_json(data["forgetLineageBindings"], prepare_forget_lineage_bindings(
        args.reference, Path(runtime["runtimeRoot"])))
        and _same_json(data["forgetLineageNode"], prepare_model_node_authority(args.node)),
        "Boundary source/artifact/executable authority changed")
    family = (ROOT / ".equivalence-results/forget-boundaries").resolve(strict=True)
    require([case["id"] for case in cases] == ["forget-boundaries-session-replay"],
            "Boundary replay requires the exact complete singleton family")
    results = []
    for case in cases:
        cid = case["id"]
        native = data["boundaryDiagnostics"][cid + "--native"]
        sdk = data["boundaryDiagnostics"][cid + "--python"]
        require(native["validationStatus"] == sdk["validationStatus"] == "verified",
                "Boundary capture was not affirmatively validated")
        directory = Path(sdk["evidenceDirectory"])
        require(directory.is_absolute() and directory.resolve(strict=True) == directory
                and directory.parent == family and directory.name.startswith("sdk-attempt-"),
                "Boundary SDK capture escaped its actual family root")
        raw_path = directory / "python-raw.json"
        raw_sha, sdk_raw = digest(raw_path), load(raw_path)
        require(raw_sha == sdk["sha256"] and _same_json([sdk_raw], sdk["rawSnapshots"]),
                "Complete retained boundary SDK raw bytes differ from the full report")
        trace = data["boundaryTraces"][cid]
        transport = trace["forgetBoundariesTransport"]
        require(trace["provider"] == "none" and trace["networkFetchDenied"] is True
                and _same_json(transport["profile"], prepare_forget_boundaries_profile(case, args.node)),
                "Boundary original process capability changed")
        for carrier in (*transport["traceFiles"], *transport["originalProcessStreams"].values()):
            payload = carrier["text"].encode("utf8")
            require(len(payload) == carrier["bytes"] and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
                    "A complete original boundary process carrier changed")
        stream = transport["originalProcessStreams"]["stdout"]
        original = json.loads(stream["text"], object_pairs_hook=_object, parse_constant=_constant)
        _finite(original)
        require(len(original["results"]) == 1 and original["results"][0]["id"] == cid
                and original["results"][0]["ok"] is True, "Original boundary stdout omitted its complete return")
        native_public = original["results"][0]["result"]
        sdk_public = {"kind": "forget-lineage-tombstones", "provider": "none", "acceptancePointsAwarded": 0,
                      "observations": [row["observed"] for row in sdk_raw["operations"]]}
        actual_native, actual_sdk = validate_pair(case, native["rawSnapshots"][0], sdk_raw,
                                                 native_public, sdk_public, directory)
        pair = data["boundaryPairs"][cid]
        require(_same_json(actual_native, pair["openclaw"]) and _same_json(actual_sdk, pair["python"])
                and digest(raw_path) == raw_sha, "Boundary projection or actual raw bytes changed during replay")
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(actual_native, actual_sdk),
                        "sdkRawSha256": raw_sha, "nativeRawSnapshotsSha256": hashlib.sha256(
                            canonical(native["rawSnapshots"])).hexdigest(), "originalStdoutSha256": stream["sha256"],
                        "actualOperations": len(actual_native["observations"])})
    return results


def replay_recall(data, cases, args):
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.recall_signals import validate_registration
    from equivalence.recall_signals_bindings import prepare_recall_signals_bindings
    from equivalence.recall_signals_evidence import validate_pair
    from equivalence.recall_signals_profile import prepare_recall_signals_profile
    from equivalence.release_runtime import prepare_release_runtime

    validate_registration(cases)
    require(len(cases) == 6, "Recall replay requires the complete frozen six-case family")
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    require(_same_json(data["recallSignalsBindings"], prepare_recall_signals_bindings(
        args.reference, Path(runtime["runtimeRoot"])))
        and _same_json(data["recallSignalsNode"], prepare_model_node_authority(args.node)),
        "Recall source/artifact/executable authority changed")
    family = (ROOT / ".equivalence-results/recall-signals").resolve(strict=True)
    results = []
    for case in cases:
        cid = case["id"]
        native = data["recallDiagnostics"][cid + "--native"]
        sdk = data["recallDiagnostics"][cid + "--python"]
        require(native["validationStatus"] == sdk["validationStatus"] == "verified",
                "Recall capture was not affirmatively validated")
        directory = Path(sdk["evidenceDirectory"])
        require(directory.is_absolute() and directory.resolve(strict=True) == directory
                and directory.parent == family and directory.name.startswith("sdk-attempt-"),
                "Recall SDK capture escaped its actual family root")
        raw_path = directory / "python-raw.json"
        require(not raw_path.is_symlink() and raw_path.resolve(strict=True) == raw_path,
                "Recall SDK raw file is not its original owned regular path")
        raw_sha, records = digest(raw_path), load(raw_path)
        require(isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict)
                and raw_sha == sdk["sha256"] and _same_json(records, sdk["rawSnapshots"]),
                "Complete retained recall SDK raw bytes differ from the full report")
        sdk_raw = records[0]
        trace = data["recallTraces"][cid]
        transport = trace["recallSignalsTransport"]
        require(trace["kind"] == "authenticated-process-thread-trace"
                and trace["provider"] == "none" and trace["networkFetchDenied"] is True
                and _same_json(transport["profile"], prepare_recall_signals_profile(case, args.node)),
                "Recall original process capability changed")
        require(isinstance(transport["traceFiles"], list) and transport["traceFiles"]
                and set(transport["originalProcessStreams"]) == {"stdout", "stderr"},
                "The complete protected recall traces or original process streams are missing")
        for carrier in (*transport["traceFiles"], *transport["originalProcessStreams"].values()):
            payload = carrier["text"].encode("utf8")
            require(len(payload) == carrier["bytes"] and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
                    "A complete original recall process carrier changed")
        stream = transport["originalProcessStreams"]["stdout"]
        original = json.loads(stream["text"], object_pairs_hook=_object, parse_constant=_constant)
        _finite(original)
        require(len(original["results"]) == 1 and original["results"][0]["id"] == cid
                and original["results"][0]["ok"] is True, "Original recall stdout omitted its complete return")
        native_public = original["results"][0]["result"]
        sdk_public = {"before": sdk_raw["initialState"],
                      "observations": [row["observed"] for row in sdk_raw["operations"]]}
        actual_native, actual_sdk = validate_pair(case, native["rawSnapshots"][0], sdk_raw,
                                                 native_public, sdk_public, directory)
        pair = data["recallPairs"][cid]
        require(_same_json(actual_native, pair["openclaw"]) and _same_json(actual_sdk, pair["python"])
                and digest(raw_path) == raw_sha, "Recall projection or actual raw bytes changed during replay")
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(actual_native, actual_sdk),
                        "sdkRawSha256": raw_sha, "nativeCollectorRawSha256": native["sha256"],
                        "nativeRawSnapshotsSha256": hashlib.sha256(canonical(native["rawSnapshots"])).hexdigest(),
                        "originalStdoutSha256": stream["sha256"],
                        "originalStderrSha256": transport["originalProcessStreams"]["stderr"]["sha256"],
                        "actualOperations": len(actual_native["observations"]),
                        "actualSourceProducerOperations": sum("producer" in row for row in sdk_raw["operations"]),
                        "actualFailedOperations": sum(row["completed"] is False for row in actual_native["observations"]),
                        "nativeOnDiskRawReopened": False})
    return results


def _cache_carrier(carrier, fields):
    require(isinstance(carrier, dict) and set(carrier) == set(fields)
            and isinstance(carrier.get("text"), str) and type(carrier.get("bytes")) is int
            and carrier["bytes"] >= 0 and isinstance(carrier.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", carrier["sha256"]),
            "Embedding cache transport carrier has an invalid complete shape")
    payload = carrier["text"].encode("utf8")
    require(len(payload) == carrier["bytes"] and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
            "A complete original embedding cache transport carrier changed")
    return payload


def replay_cache(data, cases, args):
    from equivalence.embedding_cache_lifecycle import CASE_HASHES, validate_registration
    from equivalence.embedding_cache_lifecycle_bindings import (
        COMPILED_HASHES, REQUIRED_RUNTIME_ARTIFACTS, REQUIRED_WORKER_ROUTE,
        prepare_embedding_cache_lifecycle_bindings,
    )
    from equivalence.embedding_cache_lifecycle_evidence import validate_pair
    from equivalence.embedding_cache_lifecycle_profile import (
        PROVIDER_MODE, PROVIDER_SOURCE_HASHES, prepare_embedding_cache_lifecycle_profile,
    )
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.release_runtime import prepare_release_runtime

    validate_registration(cases)
    require(len(cases) == 8 and [case["id"] for case in cases] == list(CASE_HASHES),
            "Embedding cache replay requires the complete frozen eight-case family")
    require(set(data["cachePairs"]) == set(data["cacheTraces"]) == set(CASE_HASHES)
            and set(data["cacheDiagnostics"]) == {
                cid + "--" + side for cid in CASE_HASHES for side in ("native", "python")},
            "Embedding cache replay omitted a whole public pair, raw packet or process trace")
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    node = prepare_model_node_authority(args.node)
    require(_same_json(data["embeddingCacheBindings"], prepare_embedding_cache_lifecycle_bindings(
        args.reference, Path(runtime["runtimeRoot"]))) and _same_json(data["embeddingCacheNode"], node),
        "Embedding cache source/artifact/executable authority changed")
    for relative, expected in PROVIDER_SOURCE_HASHES.items():
        source = ROOT / "equivalence" / relative
        require(not source.is_symlink() and source.resolve(strict=True) == source and digest(source) == expected,
                "The reviewed embedding cache provider source or manifest changed")
    family = ROOT / ".equivalence-results/embedding-cache-lifecycle"
    require(family.resolve(strict=True) == family and not family.is_symlink(),
            "Embedding cache evidence family is not its canonical owned directory")
    capture_pattern = re.compile(
        r"tmp/plugin-captures/[0-9a-f-]{36}/captures/openclaw-plugin-build-[A-Za-z0-9]{6}"
        r"/package-0/node_modules/embedding-cache-provider/index\.mjs\Z")
    source = ROOT / "equivalence/embedding-cache-provider/index.mjs"
    provider_sha = PROVIDER_SOURCE_HASHES["embedding-cache-provider/index.mjs"]
    results = []
    for case in cases:
        cid = case["id"]
        native = data["cacheDiagnostics"][cid + "--native"]
        sdk = data["cacheDiagnostics"][cid + "--python"]
        require(native["validationStatus"] == sdk["validationStatus"] == "verified"
                and isinstance(native["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", native["sha256"]),
                "Embedding cache capture was not affirmatively validated")
        directory = Path(sdk["evidenceDirectory"])
        require(directory.is_absolute() and directory.resolve(strict=True) == directory
                and directory.parent == family and directory.name.startswith("sdk-attempt-"),
                "Embedding cache SDK capture escaped its actual family root")
        raw_path = directory / "python-raw.json"
        require(raw_path.is_file() and not raw_path.is_symlink() and raw_path.resolve(strict=True) == raw_path,
                "Embedding cache SDK raw file is not its original owned regular path")
        raw_sha, records = digest(raw_path), load(raw_path)
        require(isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict)
                and raw_sha == sdk["sha256"] and _same_json(records, sdk["rawSnapshots"]),
                "Complete retained embedding cache SDK raw bytes differ from the full report")
        sdk_raw = records[0]
        trace = data["cacheTraces"][cid]
        transport = trace["embeddingCacheTransport"]
        profile = prepare_embedding_cache_lifecycle_profile(case, args.node)
        require(trace["kind"] == "authenticated-process-thread-trace"
                and trace["provider"] == PROVIDER_MODE and trace["networkFetchDenied"] is True
                and _same_json(transport["profile"], profile),
                "Embedding cache original process capability changed")
        require(isinstance(transport["traceFiles"], list) and transport["traceFiles"]
                and isinstance(transport["originalProcessStreams"], dict)
                and set(transport["originalProcessStreams"]) == {"stdout", "stderr"}
                and isinstance(transport["fixtureSourceCaptures"], list),
                "The complete embedding cache traces, process streams or source proof list are missing")
        threads, loaded, worker_loaded, capture_loads, trace_names = [], set(), set(), {}, set()
        for carrier in transport["traceFiles"]:
            payload = _cache_carrier(carrier, ("name", "bytes", "sha256", "text"))
            name = carrier["name"]
            matched = re.fullmatch(r"([1-9][0-9]*)-([0-9]+)\.jsonl", name)
            require(matched is not None and name not in trace_names and payload.endswith(b"\n"),
                    "Embedding cache thread carrier is duplicated or incomplete")
            trace_names.add(name)
            pid, thread = int(matched[1]), int(matched[2])
            events = [json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
                      for line in payload.splitlines()]
            _finite(events)
            require(events and all(isinstance(event, dict) for event in events),
                    "Embedding cache protected thread trace is empty or invalid")
            first = events[0]
            require(first.get("event") == "bootstrap" and first.get("pid") == pid
                    and first.get("threadId") == thread and first.get("isMainThread") is (thread == 0)
                    and first.get("fetchDenied") is True and first.get("providerMode") == PROVIDER_MODE
                    and first.get("preloadSha256") == digest(ROOT / "equivalence/release-preload.mjs")
                    and _same_json(first.get("runtime"), node)
                    and _same_json(first.get("embeddingCacheProfile"), profile),
                    "Embedding cache thread bypassed its declared protected runtime")
            threads.append({"pid": pid, "threadId": thread, "isMainThread": thread == 0, "runtime": node,
                            "embeddingCacheProfile": profile, "providerMode": PROVIDER_MODE})
            for event in events[1:]:
                require(event.get("event") in {"load", "resolve-native"}
                        and event.get("pid") == pid and event.get("threadId") == thread,
                        "Embedding cache trace contains an undeclared import or network event")
                if event["event"] != "load":
                    continue
                if event.get("kind") == "release":
                    key = (event.get("package"), event.get("path"), event.get("sha256"))
                    loaded.add(key)
                    if thread > 0:
                        worker_loaded.add(key)
                elif event.get("kind") == "embedding-fixture-capture":
                    key = event.get("capturePath")
                    require(isinstance(key, str), "Embedding provider source capture path is invalid")
                    capture_loads.setdefault(key, []).append(event)
        require(_same_json(trace["threads"], threads)
                and any(row["isMainThread"] for row in threads)
                and type(trace["protectedWorkerThreads"]) is int and trace["protectedWorkerThreads"] > 0
                and trace["protectedWorkerThreads"] == sum(not row["isMainThread"] for row in threads),
                "Embedding cache protected process/worker inventory changed")
        require(all(("node_modules/openclaw", relative, COMPILED_HASHES[relative]) in loaded
                    for relative in REQUIRED_RUNTIME_ARTIFACTS)
                and all(("node_modules/openclaw", relative, COMPILED_HASHES[relative]) in worker_loaded
                        for relative in REQUIRED_WORKER_ROUTE),
                "Embedding cache replay omitted an actual declared compiled owner or worker route")
        captured = {}
        for carrier in transport["fixtureSourceCaptures"]:
            payload = _cache_carrier(carrier, (
                "sourcePath", "capturePath", "sha256", "proofPath", "proofSha256", "bytes", "text"))
            capture = carrier["capturePath"]
            require(isinstance(capture, str) and capture_pattern.fullmatch(capture)
                    and capture not in captured and carrier["sourcePath"] == str(source)
                    and carrier["sha256"] == carrier["proofSha256"] == provider_sha
                    and payload == source.read_bytes()
                    and carrier["proofPath"] == "embedding-fixture-source-captures/" + hashlib.sha256(
                        (capture + "\0" + provider_sha).encode()).hexdigest() + ".mjs",
                    "Embedding cache provider proof escaped its exact frozen source authority")
            captured[capture] = carrier
        require(set(captured) == set(capture_loads),
                "Embedding cache provider source load and complete retained proof list differ")
        for capture, events in capture_loads.items():
            proof = captured[capture]
            require(all(event.get("sourcePath") == event.get("path") == proof["sourcePath"]
                        and event.get("sha256") == proof["sha256"]
                        and event.get("proofPath") == proof["proofPath"] for event in events),
                    "Embedding cache source proof does not authenticate its actual provider load")
        for carrier in transport["originalProcessStreams"].values():
            _cache_carrier(carrier, ("text", "bytes", "sha256"))
        stream = transport["originalProcessStreams"]["stdout"]
        original = json.loads(stream["text"], object_pairs_hook=_object, parse_constant=_constant)
        _finite(original)
        require(isinstance(original, dict) and isinstance(original.get("results"), list)
                and len(original["results"]) == 1 and original["results"][0]["id"] == cid
                and original["results"][0]["ok"] is True,
                "Original embedding cache stdout omitted its complete return")
        native_public = original["results"][0]["result"]
        native_raw = native["rawSnapshots"][0]
        require(native_raw["runtimeRoot"] == runtime["runtimeRoot"]
                and native_raw["node"] == {"version": node["nodeVersion"], "executable": node["execPath"]}
                and any(row["isMainThread"] and row["pid"] == native_raw["pid"] for row in threads),
                "The retained cache manager belongs to another original process or runtime")
        sdk_public = {"provider": PROVIDER_MODE, "before": sdk_raw["initialState"],
                      "observations": [row["observed"] for row in sdk_raw["operations"]]}
        actual_native, actual_sdk = validate_pair(case, native_raw, sdk_raw,
                                                 native_public, sdk_public, directory)
        pair = data["cachePairs"][cid]
        require(_same_json(actual_native, pair["openclaw"]) and _same_json(actual_sdk, pair["python"])
                and digest(raw_path) == raw_sha,
                "Embedding cache whole public projection or actual raw bytes changed during replay")
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(actual_native, actual_sdk),
                        "sdkRawSha256": raw_sha, "nativeCollectorRawSha256": native["sha256"],
                        "nativeRawSnapshotsSha256": hashlib.sha256(canonical(native["rawSnapshots"])).hexdigest(),
                        "originalStdoutSha256": stream["sha256"],
                        "originalStderrSha256": transport["originalProcessStreams"]["stderr"]["sha256"],
                        "actualOperations": len(actual_native["observations"]),
                        "actualProviderCalls": len(actual_native["observations"][-1]["state"]["providerCalls"]),
                        "protectedWorkerThreads": trace["protectedWorkerThreads"],
                        "fixtureSourceCaptures": len(captured), "nativeOnDiskRawReopened": False})
    return results


def recompute(data, definitions, scope):
    rows = data["cases"]
    require(len(rows) == len(definitions) and len({row["id"] for row in rows}) == len(definitions),
            "Incomplete or duplicate actual catalog; no candidate score")
    for row, definition in zip(rows, definitions, strict=True):
        for key, value in definition.items():
            require(key not in row and key in {"fixtureSource", "diagnosticOnly"}
                    or key in row and _same_json(row[key], value), "Case definition or annotation changed")
    states, gates = {}, {}
    for operation in OPERATIONS:
        members = [row for row in rows if row["operation"] == operation]
        require(members, "Closed family omitted")
        states[operation] = all(row["status"] == "matched" and row.get("runtimeEvidenceValidated") is True
                                for row in members)
        for point in {p for row in members for p in row["covers"]}:
            gates.setdefault(point, []).append(operation)
    requirements = data["requirements"]
    require(len(scope) == len(requirements) == 64, "Fixed requirement count changed")
    counts, contracts, points = Counter(row["status"] for row in rows), Counter(), []
    verified = uncovered = unresolved = 0
    require(set(counts) <= {"matched", "mismatched", "blocked"}, "Unknown case status")
    for expected, requirement in zip(scope, requirements, strict=True):
        require(_same_json({k: requirement[k] for k in ("id", "required")},
                           {k: expected[k] for k in ("id", "required")})
                and [p["id"] for p in requirement["acceptance"]] == [p["id"] for p in expected["acceptance"]],
                "Required acceptance identities changed")
        selected = [row for row in rows if row["requirement"] == requirement["id"]]
        require(type(requirement["registeredCases"]) is int and requirement["registeredCases"] == len(selected),
                "Registered case count differs")
        complete = 0
        for point in requirement["acceptance"]:
            covered = [row for row in selected if point["id"] in row["covers"]]
            allowed = all(states[op] for op in gates.get(point["id"], ()))
            matched = [row["id"] for row in covered if row["status"] == "matched" and allowed]
            require(point["caseIds"] == [row["id"] for row in covered] and point["matchedCaseIds"] == matched,
                    "Reported coverage differs from independently recomputed family gate")
            passed = bool(covered) and len(matched) == len(covered)
            verified += passed
            complete += passed
            uncovered += not covered
            unresolved += bool(covered) and not passed
            points.append({"id": point["id"], "verified": passed})
        contracts["complete" if complete == len(requirement["acceptance"]) else "partial" if complete else "pending"] += 1
    require(len(points) == len({p["id"] for p in points}) == 128, "Fixed 128-point scope changed")
    require(all(type(data["summary"].get(key)) is int and data["summary"][key] == counts[key]
                for key in ("matched", "mismatched", "blocked"))
            and type(data["summary"].get("uncoveredAcceptance")) is int
            and data["summary"]["uncoveredAcceptance"] == uncovered, "Summary contradicts actual complete rows")
    return {"verified": verified, "remaining": uncovered + unresolved, "uncovered": uncovered,
            "registeredUnresolved": unresolved, "contracts": dict(contracts),
            "cases": {key: counts[key] for key in ("matched", "mismatched", "blocked")},
            "families": states, "points": points}


def assess(args, result):
    seal = load(args.seal)
    source_unchanged(seal)
    definitions = build_cases()
    migration = definition_authority(definitions, fif_version="v6")
    require(len(definitions) == seal["registeredCases"]
            and hashlib.sha256(canonical(definitions)).hexdigest() == seal["catalogSha256"], "Sealed catalog changed")
    previous = {"registeredCases": 1475,
                "sha256": "8c6f2adb034b7360f0ef9beeb45383d77b7df9bfe9057d2f8df98eb1ac397335",
                "completePrefixUnchanged": True}
    require(len(definitions) == 1483 and seal["catalogSha256"] ==
            "33277abb724a6b89423085e735fc08b950b647b577db9879df8f2395e519a93d"
            and _same_json(seal["previousCatalog"], previous)
            and hashlib.sha256(canonical(definitions[:1475])).hexdigest() == previous["sha256"],
            "The complete prior comparison catalog changed or the frozen cache append is incomplete")
    host_cases = [case for case in definitions if case["operation"] == "host-turn-barrier-v4-runtime"]
    lineage_cases = [case for case in definitions if case["operation"] == "forget-lineage-runtime"]
    boundary_cases = [case for case in definitions if case["operation"] == "forget-boundaries-runtime"]
    recall_cases = [case for case in definitions if case["operation"] == "recall-signals-runtime"]
    cache_cases = [case for case in definitions if case["operation"] == "embed-cache-lifecycle-runtime"]
    data = project(args.report, {case["id"] for case in host_cases}, {case["id"] for case in lineage_cases},
                   {case["id"] for case in boundary_cases}, {case["id"] for case in recall_cases},
                   {case["id"] for case in cache_cases})
    result.update(completeReportParsed=True, report=data["report"], projection={
        key: value for key, value in data.items() if key not in {
            "lineagePairs", "lineageDiagnostics", "lineageTraces", "boundaryPairs", "boundaryDiagnostics", "boundaryTraces",
            "recallPairs", "recallDiagnostics", "recallTraces", "cachePairs", "cacheDiagnostics", "cacheTraces"}})
    require(data["errors"] == [] and data["mode"] == "full" and data["kind"] == "pinned-differential-acceptance",
            "Global collector error or non-full report; no candidate score")
    require(_same_json(data["implementation"], seal["implementation"])
            and _same_json(data["adapterSha256"], seal["adapters"])
            and _same_json(data["definitionMigration"], migration)
            and _same_json(seal["definitionMigration"], migration), "Report source or definition authority differs")
    for key, name in (("scope", "scope.json"), ("reference", "reference.json"), ("sourceMap", "source-map.json")):
        require(data["manifestSha256"][key] == digest(ROOT / "equivalence" / name), "Report manifest changed")
    require(data["paidProviderCalls"] == 0 and data["providerCredentialsForwarded"] is False, "Unexpected provider access")
    metrics = recompute(data, definitions, load(ROOT / "equivalence/scope.json")["requirements"])
    replay_sha = digest(args.fif_replay)
    replay = load(args.fif_replay)
    fif_ids = [case["id"] for case in definitions if case["operation"] == "forget-index-fence-v6-runtime"]
    require(replay.get("finalAuthenticationPassed") is True and replay.get("validCompleteBaseline") is True
            and replay.get("errors") == [] and [r["id"] for r in replay["cases"]] == fif_ids
            and replay["authority"]["sdk"]["sourceSha256"] == SDK["sourceSha256"]
            and len(replay["sourceReports"]) == 1
            and replay["sourceReports"][0]["report"]["sha256"] == data["report"]["sha256"],
            "Complete independently authenticated FIF replay unavailable; no candidate score")
    require(replay.get("candidateFamilyMatched") is metrics["families"]["forget-index-fence-v6-runtime"],
            "Independent FIF replay contradicts candidate family gate")
    result["hostReplays"] = replay_hosts(data, host_cases, args)
    result["lineageReplays"] = replay_lineage(data, lineage_cases, args)
    result["boundaryReplays"] = replay_boundaries(data, boundary_cases, args)
    result["recallReplays"] = replay_recall(data, recall_cases, args)
    result["embeddingCacheReplays"] = replay_cache(data, cache_cases, args)
    from equivalence.embedding_cache_lifecycle import family_complete as cache_complete
    from equivalence.forget_boundaries import family_complete as boundaries_complete
    from equivalence.forget_lineage_outcomes import family_complete
    from equivalence.recall_signals import family_complete as recall_complete

    require(data["forgetLineageOutcomesFamilyComplete"] is family_complete(data["cases"])
            is metrics["families"]["forget-lineage-runtime"], "Lineage complete-family gate differs")
    require(data["forgetBoundariesFamilyComplete"] is boundaries_complete(data["cases"])
            is metrics["families"]["forget-boundaries-runtime"], "Boundary complete-family gate differs")
    require(data["recallSignalsFamilyComplete"] is recall_complete(data["cases"])
            is metrics["families"]["recall-signals-runtime"]
            is all(row["publicMatch"] for row in result["recallReplays"]), "Recall complete-family gate differs")
    require(data["embeddingCacheFamilyComplete"] is cache_complete(data["cases"])
            is metrics["families"]["embed-cache-lifecycle-runtime"]
            is all(row["publicMatch"] for row in result["embeddingCacheReplays"]),
            "Embedding cache complete-family gate differs")
    expected_status = ("blocked" if metrics["cases"].get("blocked") else "mismatched"
                       if metrics["cases"].get("mismatched") else "incomplete" if metrics["uncovered"] else "passed")
    require(data["status"] == expected_status and data["fullScopePassed"] is (expected_status == "passed"),
            "Actual complete gate contradicts independently recomputed status")
    source_unchanged(seal)
    require(digest(args.report) == data["report"]["sha256"], "Report changed during assessment")
    require(digest(args.fif_replay) == replay_sha, "FIF replay changed during assessment")
    result.update(status="assessed", candidateAssessment=metrics, deltaFromHistorical71=metrics["verified"] - 71,
                  deltaFromHistorical77=metrics["verified"] - 77,
                  deltaFromHistorical79=metrics["verified"] - 79,
                  fifReplaySha256=replay_sha, fullScopePassed=data["fullScopePassed"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "seal", "fif-replay", "reference", "node", "release-runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = {"kind": "approved-product-complete-eof-candidate-assessment", "status": "blocked",
              "metadataOnlyAssessment": True, "completeRootAudit": False, "acceptancePointsAwarded": 0,
              "originalEnginesExecuted": False, "historicalVerifiedConditions": 79,
              "completeReportParsed": False, "candidateAssessment": None, "errors": []}
    try:
        assess(args, result)
    except Exception as error:
        result["errors"].append({"type": type(error).__name__, "message": str(error)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        stream.write("\n")
    print(json.dumps({"status": result["status"], "completeReportParsed": result["completeReportParsed"],
                      "candidateVerifiedConditions": (result["candidateAssessment"] or {}).get("verified"),
                      "errors": result["errors"]}))
    return 0 if result["status"] == "assessed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
