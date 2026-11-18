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

from followup_datetime import SOURCE_OWNERS as DATETIME_SOURCE_OWNERS
from equivalence.engine_unicode_collation import (DIAGNOSTIC as UNICODE_TIE_ID, MEASURED_SDK_F01_SHA256,
                                                  OWNERS as UNICODE_SOURCE_OWNERS, PRIOR_NATIVE_F01_SHA256)
from followup_families import FAMILIES, REPORT_FIELDS, family_key, replay_followup
from followup_heartbeat import CORPUS_OWNERS
from followup_seal import (CATALOG_SHA, EXPECTED_RESOLUTIONS, PREVIOUS_CASES, PREVIOUS_CATALOG_SHA, PREVIOUS_COMPARISON,
                           PRODUCT, REGISTERED_CASES, SCOPE_SHA as SCOPE, SDK_FILES, SDK_SHA, check_seal)

SDK = {"sourceSha256": SDK_SHA, "sourceFiles": SDK_FILES}
OPERATIONS = ("host-restart-session-runtime", "host-update-isolation-runtime",
              "host-turn-barrier-boundaries-runtime", "index-identity-boundaries-runtime",
              "query-sync-outcomes-runtime", "query-sync-boundaries-runtime",
              "host-turn-barrier-v4-runtime", "forget-index-fence-v6-runtime", "forget-lineage-runtime",
              "forget-boundaries-runtime", "recall-signals-runtime", "embed-cache-lifecycle-runtime",
              "session-reset-boundaries-runtime", "prompt-runtime-context-runtime", "prompt-history-repair-runtime")


PREVIOUS_MISMATCH_PUBLIC_SHA256 = {
    "bootstrap-discovery-legacy-state-gate": {
        "openclaw": "0c17c9620066864fed5e7643e4cb638e91b6691dfa3f4a4156d37abc2890dcb1",
        "python": "0b823b74e790da7178a5847a1061c73ed7a731dd3486a373297aa00668f8577f"
    },
    "bootstrap-discovery-memory-core-layout-extension": {
        "openclaw": "46c3d401bd850bbfb4fa529e3bef93680d0f88c0d8c1df9832a2fbb68f4043a9",
        "python": "4426dc0e10fee7057e3d2f819367cd7954fee262858c8c3f5bcfc2abb0f8d4a2"
    },
    "flush-execution-warm-index-first-recall": {
        "openclaw": "4cdb2aa71ea06ed46a094e47e3739276fae9238c4480d82a6eee896d6451b569",
        "python": "f5f748474b212ead4420d77fe1a6c3ba3425db777e1f15c318be567057925802"
    },
    "hybrid-unicode-path-collation-diagnostic": {
        "openclaw": "5557cac38760fa4dfada60946a7009a3c9c021ba550297aaa6ba0677b2c00471",
        "python": "dca8c3c148c1dc0c20f0a0320218f082cfe5da7d147f5803657897e9732fe2a5"
    },
    "model-session-configured-letter-capture-reset-engine-diagnostic": {
        "openclaw": "9248d6dba21b71826ed2efe5c2fe0ae830e435e5185b8beb524b506e7d090503",
        "python": "bf8ee6825f6c90deba80c03d841afde41a5dfa521431283354337937d8fc81f3"
    },
    "model-session-configured-letter-mixed-i-engine-diagnostic": {
        "openclaw": "91d7649bc1bf451de1b2466eeee0ab51880beabfb95c6dcaae6091a844b777f8",
        "python": "add5c1cf6ea31b013bca49540a3ca8c62bb0454cc1c2785f07f1e4b2ad3e2380"
    },
    "model-tool-complete-tool-result": {
        "openclaw": "a3135c0aa970596a5ce0fe2abb7ab26d5a0f0f5db784e56549d10627f04ca45f",
        "python": "b2c845eacfc95324d39fabc14b082805f624a507990628553ae73af2d092255c"
    },
    "model-tool-utf16-redaction-truncation-order": {
        "openclaw": "da86e568f2f9e385369483a11979d9ee6999c1bd41fdd7f7f6bded6ac6182129",
        "python": "07d49892bce1b138d57f27e57cc122ae1765ad76666c47a8983c3d2359086d1d"
    },
    "promotion-ranking-primitive-provenance-safety-diagnostic": {
        "openclaw": "ce9199b6cadbcca42e7b2e918271317c69a6cffdd0d6ca542227ca2457c94715",
        "python": "db6ed4a22a533156005c77236fd270ba7da4a637053384a96cb6b2685988bd47"
    },
    "redaction-policy-letter-mixed-i-engine-diagnostic": {
        "openclaw": "448ed9ba5b67a5057fa9d0d959f19ee0edda75c19b2b8f7ac3ccd9c9fceddd13",
        "python": "2e03268c4c8476d4b5565ee6e8cc3f4a65dd57c30ff3459d27acc004dc7205dd"
    },
    "redaction-policy-letter-repeated-capture-engine-diagnostic": {
        "openclaw": "cdcd0e27a6c94180b1952ad0dca3444e4cd5ac061e5bf77152f54950e4cffd83",
        "python": "4ee1649de0f248317deaab5d0fb86fbca937f76f2d5b3cbbad22f16828013dec"
    },
    "redaction-policy-unsupported-valid-general-property": {
        "openclaw": "4ef98d271081c5ebed5ec22f9c56aeed8d9c908e9e4d8f30f95b66ea16259401",
        "python": "ac0b3b39d011fa5c948cd7f3d6bc98b504a2551752ac864b7d704136e89593db"
    },
    "redaction-policy-unsupported-valid-v-direct-compiler": {
        "openclaw": "a059ed3d41305bdda13ef19b60a2b3769ab8bd5e424f50dc563821cbb1fa0411",
        "python": "3aeacb9187ff040f407c9bc2e054e61d4b3675d33636c22a023fc36aba523d82"
    },
    "transcript-boundary-compressed-same-size-mtime-cache-diagnostic": {
        "openclaw": "8f6db98b6ee9e807a5441407b35092d7b29a42d09d4745212a8f343b80044ad2",
        "python": "baa4194f693b5a6dd5ea564fa243af3c10085bd9a82d964fe778028ef274c28b"
    }
}


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


def project(path, host_ids, lineage_ids, boundary_ids, recall_ids, cache_ids, reset_ids, prompt_ids, history_ids,
            numeric_ids=frozenset(), deep_ids=frozenset(), followup_ids=frozenset()):
    from equivalence.engine_numeric_family import SOURCE_OWNERS
    from equivalence.promotion_ranking_bindings import COMPILED_HASHES as rank_compiled

    kept = {"schemaVersion", "kind", "mode", "status", "fullScopePassed", "implementation",
            "reference", "manifestSha256", "adapterSha256", "casesSha256", "definitionMigration",
            "summary", "requirements", "errors", "startedAt", "finishedAt", "durationSeconds",
            "referenceExecution", "paidProviderCalls", "providerCredentialsForwarded",
            "forgetLineageOutcomesFamilyComplete", "forgetBoundariesFamilyComplete",
            "forgetLineageBindings", "forgetLineageNode", "recallSignalsFamilyComplete",
            "recallSignalsBindings", "recallSignalsNode", "embeddingCacheFamilyComplete",
            "embeddingCacheBindings", "embeddingCacheNode", "sessionResetBoundariesFamilyComplete",
            "sessionResetBoundariesBindings", "sessionResetBoundariesNode",
            "promptRuntimeContextFamilyComplete", "promptRuntimeContextBindings", "promptRuntimeContextNode",
            "promptHistoryRepairFamilyComplete", "promptHistoryRepairBindings", "promptHistoryRepairNode",
            "engineNumericFamilyComplete", "numericSourceImports", "promotionRankingRuntimeBindings", "promotionRankingProfile",
            "deepConsolidationFamilyComplete", "deepConsolidationBindings", "promotionApplyFamilyBindings", "promotionApplyFamilyNode"}
    kept.update(REPORT_FIELDS)
    result = {"followupRows": {}, "unicodeSources": [], "datetimeSources": [], "heartbeatSources": [], "followupReleaseSources": [], "cases": [], "hostPairs": {}, "hostDiagnostics": {},
              "lineagePairs": {}, "lineageDiagnostics": {}, "lineageTraces": {},
              "boundaryPairs": {}, "boundaryDiagnostics": {}, "boundaryTraces": {},
              "recallPairs": {}, "recallDiagnostics": {}, "recallTraces": {},
              "cachePairs": {}, "cacheDiagnostics": {}, "cacheTraces": {},
              "resetPairs": {}, "resetDiagnostics": {}, "resetTraces": {},
              "promptPairs": {}, "promptDiagnostics": {}, "promptTraces": {},
              "historyPairs": {}, "historyDiagnostics": {}, "historyTraces": {},
              "numericPairs": {}, "numericDiagnostics": {}, "numericTraces": {}, "numericSources": [], "numericReleaseSources": [],
              "deepPairs": {}, "deepDiagnostics": {}, "deepTraces": {}}
    before = digest(path)

    def accept(key, value, array):
        if array == "array-done":
            if key in kept:
                result.setdefault(key, [])
            return
        if key == "sources" and value["path"] in UNICODE_SOURCE_OWNERS:
            result["unicodeSources"].append(value)
        if key == "sources" and value["path"] in DATETIME_SOURCE_OWNERS:
            result["datetimeSources"].append(value)
        if key == "sources" and value["path"] in CORPUS_OWNERS:
            result["heartbeatSources"].append(value)
        if key == "releaseSources":
            result["followupReleaseSources"].append(value)
        if key in {"cases", "releaseTraces", "runtimeDiagnostics", "sourcePolicyDiagnostics"} and value.get("id") in followup_ids:
            name = {"cases": "case", "releaseTraces": "trace", "sourcePolicyDiagnostics": "sourcePolicy"}.get(key)
            if key == "runtimeDiagnostics":
                name = value.get("side")
                require(name in {"native", "python"}, "Unknown appended diagnostic side")
            row = result["followupRows"].setdefault(value["id"], {})
            require(name not in row, "Duplicate appended case, diagnostic or trace")
            row[name] = value
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
                if value["id"] == UNICODE_TIE_ID:
                    result["unicodeTiePair"] = pair
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
                if value["id"] in reset_ids:
                    result["resetPairs"][value["id"]] = pair
                if value["id"] in numeric_ids:
                    result["numericPairs"][value["id"]] = pair
                if value["id"] in deep_ids:
                    result["deepPairs"][value["id"]] = pair
                if value["id"] in history_ids:
                    result["historyPairs"][value["id"]] = pair
                if value["id"] in prompt_ids:
                    result["promptPairs"][value["id"]] = pair
            require(value["status"] != "mismatched" or "python" in value, "Mismatch omitted whole public values")
            result["cases"].append(row)
        elif key == "sources" and value["path"] in SOURCE_OWNERS:
            result["numericSources"].append(value)
        elif key == "releaseSources" and value["package"] == "node_modules/openclaw" and value["path"] in rank_compiled:
            result["numericReleaseSources"].append(value)
        elif key in {"runtimeDiagnostics", "releaseTraces"} and value.get("id") in numeric_ids | deep_ids:
            family = "numeric" if value["id"] in numeric_ids else "deep"
            target = result[family + ("Traces" if key == "releaseTraces" else "Diagnostics")]
            if key == "runtimeDiagnostics":
                require(value.get("side") in {"native", "python"}, "Unexpected captured diagnostic side")
                require(isinstance(value.get("rawSnapshots"), list) and len(value["rawSnapshots"]) == 1,
                        "The complete original capture is required")
                identity = value["id"] + "--" + value["side"]
            else:
                identity = value["id"]
            require(identity not in target, "Duplicate protected trace or diagnostic")
            target[identity] = value
        elif key == "runtimeDiagnostics" and (value.get("id") in prompt_ids or value.get("id") in history_ids):
            diagnostics = result["historyDiagnostics"] if value["id"] in history_ids else result["promptDiagnostics"]
            require(value.get("side") in {"native", "python"}, "Unknown prompt diagnostic side")
            identity = value["id"] + "--" + value["side"]
            require(identity not in diagnostics, "Duplicate prompt diagnostic")
            require(isinstance(value.get("rawSnapshots"), list) and len(value["rawSnapshots"]) == 1
                    and isinstance(value["rawSnapshots"][0], dict),
                    "Prompt diagnostic is not a complete singleton packet")
            diagnostics[identity] = value
        elif key == "releaseTraces" and (value.get("id") in prompt_ids or value.get("id") in history_ids):
            traces = result["historyTraces"] if value["id"] in history_ids else result["promptTraces"]
            require(value["id"] not in traces, "Duplicate prompt process trace")
            traces[value["id"]] = value
        elif key == "runtimeDiagnostics" and value.get("id") in reset_ids:
            require(value.get("side") in {"native", "python"}, "Unknown reset boundary diagnostic side")
            identity = value["id"] + "--" + value["side"]
            require(identity not in result["resetDiagnostics"], "Duplicate reset boundary diagnostic")
            require(isinstance(value.get("rawSnapshots"), list) and len(value["rawSnapshots"]) == 1
                    and isinstance(value["rawSnapshots"][0], dict),
                    "Reset boundary diagnostic is not a complete singleton packet")
            result["resetDiagnostics"][identity] = value
        elif key == "releaseTraces" and value.get("id") in reset_ids:
            require(value["id"] not in result["resetTraces"], "Duplicate reset boundary process trace")
            result["resetTraces"][value["id"]] = value
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
    entries = result["followupReleaseSources"]
    require(len({(entry["package"], entry["path"]) for entry in entries}) == len(entries),
            "Duplicate release source in the complete report")
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


def replay_reset(data, cases, args):
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.release_runtime import prepare_release_runtime
    from equivalence.session_reset_boundaries import CASE_HASHES, validate_registration
    from equivalence.session_reset_boundaries_bindings import (
        COMPILED_HASHES, REQUIRED_RUNTIME_ARTIFACTS, prepare_session_reset_boundaries_bindings,
    )
    from equivalence.session_reset_boundaries_evidence import validate_pair
    from equivalence.session_reset_boundaries_profile import prepare_session_reset_boundaries_profile

    validate_registration(cases)
    require(len(cases) == 7 and [case["id"] for case in cases] == list(CASE_HASHES),
            "Reset replay requires the complete frozen seven-case family")
    require(set(data["resetPairs"]) == set(data["resetTraces"]) == set(CASE_HASHES)
            and set(data["resetDiagnostics"]) == {
                cid + "--" + side for cid in CASE_HASHES for side in ("native", "python")},
            "Reset replay omitted a complete public pair, raw packet or process trace")
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    node = prepare_model_node_authority(args.node)
    require(_same_json(data["sessionResetBoundariesBindings"], prepare_session_reset_boundaries_bindings(
        args.reference, Path(runtime["runtimeRoot"]))) and _same_json(data["sessionResetBoundariesNode"], node),
        "Reset source/artifact/executable authority changed")
    authenticated = {(package["location"], item["path"]): item["sha256"]
                     for package in runtime["packages"] for item in package["files"]}
    family = ROOT / ".equivalence-results/session-reset-boundaries"
    require(family.resolve(strict=True) == family and not family.is_symlink(),
            "Reset evidence family is not its canonical owned directory")
    results = []
    for case in cases:
        cid = case["id"]
        native, sdk = (data["resetDiagnostics"][cid + "--" + side] for side in ("native", "python"))
        require(native["validationStatus"] == sdk["validationStatus"] == "verified"
                and isinstance(native["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", native["sha256"]),
                "Reset original singleton raw packet was not affirmatively validated")
        directory = Path(sdk["evidenceDirectory"])
        require(directory.is_absolute() and directory.resolve(strict=True) == directory
                and directory.parent == family and directory.name.startswith("sdk-attempt-"),
                "Reset SDK capture escaped its actual family root")
        raw_path = directory / "python-raw.json"
        require(raw_path.is_file() and not raw_path.is_symlink() and raw_path.resolve(strict=True) == raw_path,
                "Reset SDK raw file is not its original owned regular path")
        raw_sha, records = digest(raw_path), load(raw_path)
        require(isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict)
                and raw_sha == sdk["sha256"] and _same_json(records, sdk["rawSnapshots"]),
                "Complete retained reset SDK raw bytes differ from the full report")
        sdk_raw, native_raw = records[0], native["rawSnapshots"][0]
        trace = data["resetTraces"][cid]
        transport = trace["sessionResetBoundariesTransport"]
        profile = prepare_session_reset_boundaries_profile(case, args.node)
        require(trace["kind"] == "authenticated-process-thread-trace"
                and trace["provider"] == "none" and trace["networkFetchDenied"] is True
                and set(transport) == {"profile", "traceFiles", "originalProcessStreams"}
                and _same_json(transport["profile"], profile),
                "Reset original process capability changed or borrowed another capability")
        require(isinstance(transport["traceFiles"], list) and transport["traceFiles"]
                and isinstance(transport["originalProcessStreams"], dict)
                and set(transport["originalProcessStreams"]) == {"stdout", "stderr"},
                "The complete reset traces or original process streams are missing")
        threads, loaded, locals_loaded, contexts, names = [], set(), set(), set(), set()
        for carrier in transport["traceFiles"]:
            require(set(carrier) == {"name", "bytes", "sha256", "text"}, "Reset trace carrier lost fields")
            payload = carrier["text"].encode("utf8")
            require(type(carrier["bytes"]) is int and len(payload) == carrier["bytes"]
                    and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
                    "A complete original reset trace carrier changed")
            matched = re.fullmatch(r"([1-9][0-9]*)-([0-9]+)\.jsonl", carrier["name"])
            require(matched is not None and carrier["name"] not in names and payload.endswith(b"\n"),
                    "Reset thread carrier is duplicated or incomplete")
            names.add(carrier["name"])
            pid, thread = int(matched[1]), int(matched[2])
            events = [json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
                      for line in payload.splitlines()]
            _finite(events)
            require(events and all(isinstance(event, dict) for event in events),
                    "Reset protected thread trace is empty or invalid")
            first = events[0]
            require(first.get("event") == "bootstrap" and first.get("pid") == pid
                    and first.get("threadId") == thread and first.get("isMainThread") is (thread == 0)
                    and first.get("fetchDenied") is True and first.get("providerMode") == "none"
                    and first.get("preloadSha256") == digest(ROOT / "equivalence/release-preload.mjs")
                    and isinstance(first.get("contextSha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", first["contextSha256"])
                    and _same_json(first.get("runtime"), node)
                    and _same_json(first.get("sessionResetBoundariesProfile"), profile),
                    "Reset thread bypassed its declared protected runtime")
            contexts.add(first["contextSha256"])
            threads.append({"pid": pid, "threadId": thread, "isMainThread": thread == 0,
                            "runtime": node, "sessionResetBoundariesProfile": profile})
            for event in events[1:]:
                require(event.get("event") in {"load", "resolve-native"}
                        and event.get("pid") == pid and event.get("threadId") == thread,
                        "Reset trace contains an undeclared import or network event")
                if event.get("kind") == "release":
                    key = event.get("package"), event.get("path")
                    require(authenticated.get(key) == event.get("sha256"),
                            "Reset import lost its authenticated official artifact")
                    if event["event"] == "load":
                        loaded.add((*key, event["sha256"]))
                elif event.get("kind") == "oracle":
                    path = Path(event["path"])
                    require(path.parent == ROOT / "equivalence" and path.suffix == ".mjs"
                            and data["adapterSha256"].get(path.name) == event.get("sha256"),
                            "Reset import borrowed an unreviewed local or source capability")
                    if event["event"] == "load":
                        locals_loaded.add(path.name)
                else:
                    raise ValueError("Reset replay encountered an undeclared source/provider import authority")
        require(len(contexts) == 1 and _same_json(trace["threads"], threads)
                and any(row["isMainThread"] for row in threads)
                and type(trace["protectedWorkerThreads"]) is int
                and trace["protectedWorkerThreads"] == sum(not row["isMainThread"] for row in threads),
                "Reset protected process/worker inventory changed")
        require({"release-oracle.mjs", "session-reset-boundaries-runtime.mjs"} <= locals_loaded
                and all(("node_modules/openclaw", relative, COMPILED_HASHES[relative]) in loaded
                        for relative in REQUIRED_RUNTIME_ARTIFACTS)
                and trace["loadedReleaseFiles"] == len(loaded),
                "Reset replay omitted an actual declared compiled owner or adapter")
        for carrier in transport["originalProcessStreams"].values():
            require(set(carrier) == {"text", "bytes", "sha256"}, "Reset process stream lost fields")
            payload = carrier["text"].encode("utf8")
            require(type(carrier["bytes"]) is int and len(payload) == carrier["bytes"]
                    and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
                    "A complete original reset process stream changed")
        stream = transport["originalProcessStreams"]["stdout"]
        original = json.loads(stream["text"], object_pairs_hook=_object, parse_constant=_constant)
        _finite(original)
        require(isinstance(original, dict) and isinstance(original.get("results"), list)
                and len(original["results"]) == 1 and original["results"][0]["id"] == cid
                and original["results"][0]["ok"] is True,
                "Original reset stdout omitted its complete return")
        require(native_raw["runtimeRoot"] == runtime["runtimeRoot"]
                and native_raw["node"] == {"version": node["nodeVersion"], "executable": node["execPath"]}
                and any(row["isMainThread"] and row["pid"] == native_raw["pid"] for row in threads),
                "The retained reset hook belongs to another original process or runtime")
        native_public = original["results"][0]["result"]
        sdk_public = {"provider": "none", "before": sdk_raw["initialState"],
                      "observations": [row["observed"] for row in sdk_raw["operations"]]}
        actual_native, actual_sdk = validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, directory)
        pair = data["resetPairs"][cid]
        require(_same_json(actual_native, pair["openclaw"]) and _same_json(actual_sdk, pair["python"])
                and digest(raw_path) == raw_sha, "Reset whole public projection or raw bytes changed during replay")
        operations = case["input"]["operations"]
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(actual_native, actual_sdk),
                        "sdkRawSha256": raw_sha, "nativeCollectorRawSha256": native["sha256"],
                        "nativeRawSnapshotsSha256": hashlib.sha256(canonical(native["rawSnapshots"])).hexdigest(),
                        "originalStdoutSha256": stream["sha256"],
                        "originalStderrSha256": transport["originalProcessStreams"]["stderr"]["sha256"],
                        "actualOperations": len(actual_native["observations"]),
                        **{"actual" + label + "Operations": sum(op["op"] == name for op in operations)
                           for label, name in (("Hook", "hook"), ("Sync", "sync"),
                                               ("Search", "search"), ("GetAll", "get-all"))},
                        "protectedWorkerThreads": trace["protectedWorkerThreads"], "nativeOnDiskRawReopened": False})
    return results


def replay_prompt(data, cases, args, *, history=False):
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.release_runtime import prepare_release_runtime
    if history:
        from equivalence.prompt_history_repair import CASE_HASHES, validate_registration
        from equivalence.prompt_history_repair_bindings import (
            COMPILED_HASHES, REQUIRED_RUNTIME_ARTIFACTS, prepare_prompt_history_repair_bindings as prepare_bindings,
        )
        from equivalence.prompt_history_repair_evidence import decode_native_capture, validate_pair
        from equivalence.prompt_history_repair_profile import (
            PROVIDER_SOURCE_HASHES, prepare_prompt_history_repair_profile as prepare_profile,
        )
        family_name, authority, collection, timezone = "prompt-history-repair", "promptHistoryRepair", "history", "UTC"
    else:
        from equivalence.prompt_runtime_context import CASE_HASHES, HOST_TIMEZONE, validate_registration
        from equivalence.prompt_runtime_context_bindings import (
            COMPILED_HASHES, REQUIRED_RUNTIME_ARTIFACTS, prepare_prompt_runtime_context_bindings as prepare_bindings,
        )
        from equivalence.prompt_runtime_context_evidence import decode_native_capture, validate_pair
        from equivalence.prompt_runtime_context_profile import (
            PROVIDER_SOURCE_HASHES, prepare_prompt_runtime_context_profile as prepare_profile,
        )
        family_name = "prompt-runtime-context"
        authority, collection, timezone = "promptRuntimeContext", "prompt", HOST_TIMEZONE

    validate_registration(cases)
    require(cases and [case["id"] for case in cases] == list(CASE_HASHES),
            "Prompt replay requires the complete frozen prompt family")
    require(set(data[collection + "Pairs"]) == set(data[collection + "Traces"]) == set(CASE_HASHES)
            and set(data[collection + "Diagnostics"]) == {
                cid + "--" + side for cid in CASE_HASHES for side in ("native", "python")},
            "Prompt replay omitted a complete public pair, raw packet or process trace")
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    node = prepare_model_node_authority(args.node)
    require(_same_json(data[authority + "Bindings"], prepare_bindings(
        args.reference, Path(runtime["runtimeRoot"]))) and _same_json(data[authority + "Node"], node),
        "Prompt source/artifact/executable authority changed")
    authenticated = {(package["location"], item["path"]): item["sha256"]
                     for package in runtime["packages"] for item in package["files"]}
    for relative, expected in PROVIDER_SOURCE_HASHES.items():
        source_file = ROOT / "equivalence" / relative
        require(not source_file.is_symlink() and source_file.resolve(strict=True) == source_file
                and digest(source_file) == expected,
                "The frozen prompt provider source or manifest changed")
    capture_pattern = re.compile(
        r"tmp/plugin-captures/[0-9a-f-]{36}/captures/openclaw-plugin-build-[A-Za-z0-9]{6}"
        r"/package-0/node_modules/prompt-runtime-provider/index\.mjs\Z")
    provider_source = ROOT / "equivalence/prompt-runtime-provider/index.mjs"
    provider_sha = PROVIDER_SOURCE_HASHES["prompt-runtime-provider/index.mjs"]
    family = ROOT / ".equivalence-results" / family_name
    require(family.resolve(strict=True) == family and not family.is_symlink(),
            "Prompt evidence family is not its canonical owned directory")
    results = []
    for case in cases:
        cid = case["id"]
        native, sdk = (data[collection + "Diagnostics"][cid + "--" + side] for side in ("native", "python"))
        require(native["validationStatus"] == sdk["validationStatus"] == "verified"
                and isinstance(native["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", native["sha256"]),
                "Prompt original singleton raw packet was not affirmatively validated")
        directory = Path(sdk["evidenceDirectory"])
        require(directory.is_absolute() and directory.resolve(strict=True) == directory
                and directory.parent == family and directory.name.startswith("sdk-attempt-"),
                "Prompt SDK capture escaped its actual family root")
        raw_path = directory / "python-raw.json"
        require(raw_path.is_file() and not raw_path.is_symlink() and raw_path.resolve(strict=True) == raw_path,
                "Prompt SDK raw file is not its original owned regular path")
        raw_sha, records = digest(raw_path), load(raw_path)
        require(isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict)
                and raw_sha == sdk["sha256"] and _same_json(records, sdk["rawSnapshots"]),
                "Complete retained prompt SDK raw bytes differ from the full report")
        native_path = Path(native["retainedNativeRawPath"])
        require(native_path.is_absolute() and native_path.name == "native-raw.json"
                and native_path.resolve(strict=True) == native_path
                and native_path.parent.parent == family
                and native_path.parent.name.startswith("native-attempt-")
                and not native_path.parent.is_symlink() and not native_path.is_symlink(),
                "Prompt original raw envelope escaped its retained canonical owner")
        native_info = native_path.lstat()
        require(native_path.is_file() and native_info.st_nlink == 1
                and type(native["nativeRawBytes"]) is int
                and 0 < native_info.st_size == native["nativeRawBytes"] <= 16 * 1024**2,
                "Prompt original raw envelope is unsafe or exceeds the unchanged wire-file bound")
        with native_path.open("rb") as native_stream:
            native_payload = native_stream.read(16 * 1024**2 + 1)
        native_sha = hashlib.sha256(native_payload).hexdigest()
        require(len(native_payload) == native_info.st_size and native_sha == native["sha256"],
                "Retained prompt envelope differs from the complete original wire bytes")
        envelope = json.loads(native_payload.decode("utf8"), object_pairs_hook=_object, parse_constant=_constant)
        _finite(envelope)
        native_records = decode_native_capture(envelope)
        require(_same_json(native_records, native["rawSnapshots"]),
                "Losslessly decoded prompt envelope differs from the whole original collector packet")
        sdk_raw, native_raw = records[0], native_records[0]
        trace = data[collection + "Traces"][cid]
        transport = trace[authority + "Transport"]
        profile = prepare_profile(case, args.node)
        require(trace["kind"] == "authenticated-process-thread-trace"
                and trace["provider"] == "none" and trace["networkFetchDenied"] is True
                and set(transport) == {"profile", "traceFiles", "fixtureSourceCaptures", "originalProcessStreams"}
                and _same_json(transport["profile"], profile),
                "Prompt original process capability changed or borrowed another capability")
        require(isinstance(transport["traceFiles"], list) and transport["traceFiles"]
                and isinstance(transport["originalProcessStreams"], dict)
                and set(transport["originalProcessStreams"]) == {"stdout", "stderr"}
                and isinstance(transport["fixtureSourceCaptures"], list),
                "The complete prompt traces or original process streams are missing")
        threads, loaded, locals_loaded, contexts, names, capture_loads = [], set(), set(), set(), set(), {}
        for carrier in transport["traceFiles"]:
            require(set(carrier) == {"name", "bytes", "sha256", "text"}, "Prompt trace carrier lost fields")
            payload = carrier["text"].encode("utf8")
            require(type(carrier["bytes"]) is int and len(payload) == carrier["bytes"]
                    and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
                    "A complete original prompt trace carrier changed")
            matched = re.fullmatch(r"([1-9][0-9]*)-([0-9]+)\.jsonl", carrier["name"])
            require(matched is not None and carrier["name"] not in names and payload.endswith(b"\n"),
                    "Prompt thread carrier is duplicated or incomplete")
            names.add(carrier["name"])
            pid, thread = int(matched[1]), int(matched[2])
            events = [json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
                      for line in payload.splitlines()]
            _finite(events)
            require(events and all(isinstance(event, dict) for event in events),
                    "Prompt protected thread trace is empty or invalid")
            first = events[0]
            require(first.get("event") == "bootstrap" and first.get("pid") == pid
                    and first.get("threadId") == thread and first.get("isMainThread") is (thread == 0)
                    and first.get("fetchDenied") is True and first.get("providerMode") == "none"
                    and first.get("preloadSha256") == digest(ROOT / "equivalence/release-preload.mjs")
                    and isinstance(first.get("contextSha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", first["contextSha256"])
                    and _same_json(first.get("runtime"), node)
                    and _same_json(first.get(authority + "Profile"), profile)
                    and first.get(authority + "HostTimezone") == timezone,
                    "Prompt thread bypassed its declared protected runtime")
            contexts.add(first["contextSha256"])
            threads.append({"pid": pid, "threadId": thread, "isMainThread": thread == 0,
                            "runtime": node, authority + "Profile": profile,
                            authority + "HostTimezone": timezone})
            for event in events[1:]:
                require(event.get("event") in {"load", "resolve-native"}
                        and event.get("pid") == pid and event.get("threadId") == thread,
                        "Prompt trace contains an undeclared import or network event")
                if event.get("kind") == "release":
                    key = event.get("package"), event.get("path")
                    require(authenticated.get(key) == event.get("sha256"),
                            "Prompt import lost its authenticated official artifact")
                    if event["event"] == "load":
                        loaded.add((*key, event["sha256"]))
                elif event.get("kind") == "oracle":
                    path = Path(event["path"])
                    require(path.parent == ROOT / "equivalence" and path.suffix == ".mjs"
                            and data["adapterSha256"].get(path.name) == event.get("sha256"),
                            "Prompt import borrowed an unreviewed local or source capability")
                    if event["event"] == "load":
                        locals_loaded.add(path.name)
                elif event.get("kind") == "prompt-fixture-capture":
                    capture = event.get("capturePath")
                    require(event["event"] == "load" and isinstance(capture, str)
                            and capture_pattern.fullmatch(capture),
                            "Prompt provider source capture escaped its exact protected package")
                    capture_loads.setdefault(capture, []).append(event)
                else:
                    raise ValueError("Prompt replay encountered an undeclared source/provider import authority")
        require(len(contexts) == 1 and _same_json(trace["threads"], threads)
                and any(row["isMainThread"] for row in threads)
                and type(trace["protectedWorkerThreads"]) is int
                and trace["protectedWorkerThreads"] == sum(not row["isMainThread"] for row in threads),
                "Prompt protected process/worker inventory changed")
        require({"release-oracle.mjs", family_name + "-runtime.mjs"} <= locals_loaded
                and all(("node_modules/openclaw", relative, COMPILED_HASHES[relative]) in loaded
                        for relative in REQUIRED_RUNTIME_ARTIFACTS)
                and trace["loadedReleaseFiles"] == len(loaded),
                "Prompt replay omitted an actual declared compiled owner or adapter")
        captured = {}
        for carrier in transport["fixtureSourceCaptures"]:
            payload = _cache_carrier(carrier, (
                "sourcePath", "capturePath", "sha256", "proofPath", "proofSha256", "bytes", "text"))
            capture = carrier["capturePath"]
            require(isinstance(capture, str) and capture_pattern.fullmatch(capture)
                    and capture not in captured and carrier["sourcePath"] == str(provider_source)
                    and carrier["sha256"] == carrier["proofSha256"] == provider_sha
                    and payload == provider_source.read_bytes()
                    and carrier["proofPath"] == "prompt-fixture-source-captures/" + hashlib.sha256(
                        (capture + "\0" + provider_sha).encode()).hexdigest() + ".mjs",
                    "Prompt provider proof escaped its exact frozen source authority")
            captured[capture] = carrier
        require(captured and set(captured) == set(capture_loads),
                "Prompt provider source load and complete retained proof list differ")
        for capture, events in capture_loads.items():
            proof = captured[capture]
            require(all(event.get("sourcePath") == event.get("path") == proof["sourcePath"]
                        and event.get("sha256") == proof["sha256"]
                        and event.get("proofPath") == proof["proofPath"] for event in events),
                    "Prompt source proof does not authenticate its actual provider load")
        for carrier in transport["originalProcessStreams"].values():
            require(set(carrier) == {"text", "bytes", "sha256"}, "Prompt process stream lost fields")
            payload = carrier["text"].encode("utf8")
            require(type(carrier["bytes"]) is int and len(payload) == carrier["bytes"]
                    and hashlib.sha256(payload).hexdigest() == carrier["sha256"],
                    "A complete original prompt process stream changed")
        stream = transport["originalProcessStreams"]["stdout"]
        original = json.loads(stream["text"], object_pairs_hook=_object, parse_constant=_constant)
        _finite(original)
        require(isinstance(original, dict) and isinstance(original.get("results"), list)
                and len(original["results"]) == 1 and original["results"][0]["id"] == cid
                and original["results"][0]["ok"] is True,
                "Original prompt stdout omitted its complete return")
        require(native_raw["runtimeRoot"] == runtime["runtimeRoot"]
                and native_raw["node"] == {"version": node["nodeVersion"], "executable": node["execPath"]}
                and any(row["isMainThread"] and row["pid"] == native_raw["pid"] for row in threads),
                "The retained prompt attempt belongs to another original process or runtime")
        native_public = original["results"][0]["result"]
        sdk_public = sdk_raw["output"]
        actual_native, actual_sdk = validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, directory)
        pair = data[collection + "Pairs"][cid]
        require(_same_json(actual_native, pair["openclaw"]) and _same_json(actual_sdk, pair["python"])
                and digest(raw_path) == raw_sha and digest(native_path) == native_sha,
                "Prompt whole public projection or actual original/SDK raw bytes changed during replay")
        results.append({"id": cid, "validated": True, "publicMatch": _same_json(actual_native, actual_sdk),
                        "sdkRawSha256": raw_sha, "nativeCollectorRawSha256": native["sha256"],
                        "nativeRawFileSha256": native_sha, "nativeRawFileBytes": len(native_payload),
                        "nativeRawSnapshotsSha256": hashlib.sha256(canonical(native["rawSnapshots"])).hexdigest(),
                        "originalStdoutSha256": stream["sha256"],
                        "originalStderrSha256": transport["originalProcessStreams"]["stderr"]["sha256"],
                        "protectedWorkerThreads": trace["protectedWorkerThreads"], "nativeOnDiskRawReopened": True})
    return results



def replay_deep(data, cases, args):
    """Read both actual captures and independently rebuild the whole consolidation comparison."""
    from equivalence.deep_consolidation import CASE_HASHES, validate_registration
    from equivalence.deep_consolidation_evidence import compare_deep_state
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.promotion_apply_family_bindings import prepare_deep_consolidation_bindings, prepare_family_bindings
    from equivalence.promotion_apply_family_evidence import validate_native_capture, validate_pair
    from equivalence.promotion_apply_family_native import LOCAL, validate_traces
    from equivalence.release_runtime import prepare_release_runtime

    validate_registration(cases)
    ids = [c['id'] for c in cases]
    require(len(ids) == 7 and ids == list(CASE_HASHES) and set(ids) == set(data['deepPairs']) == set(data['deepTraces'])
            and set(data['deepDiagnostics']) == {cid + '--' + side for cid in ids for side in ('native', 'python')},
            'Deep consolidation replay requires its seven original cases and all public/raw pairs')

    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    runtime_root = Path(runtime['runtimeRoot'])
    authority = prepare_model_node_authority(args.node)
    family = ROOT / '.equivalence-results/deep-consolidation'
    require(family.resolve(strict=True) == family and family.is_dir(), 'Invalid deep consolidation artifact root')
    used_native, used_sdk = set(), set()
    local_sources = [{'path': str(ROOT / 'equivalence' / name), 'sha256': digest(ROOT / 'equivalence' / name)}
                     for name in LOCAL]

    def verify_bindings():
        require(_same_json(data['promotionApplyFamilyBindings'], prepare_family_bindings(args.reference, runtime_root))
                and _same_json(data['deepConsolidationBindings'], prepare_deep_consolidation_bindings(args.reference, runtime_root))
                and _same_json(data['promotionApplyFamilyNode'], authority), 'Deep original source or release authority changed')

    verify_bindings()
    results = []
    for case in cases:
        cid = case['id']
        trace = data['deepTraces'][cid]
        original = data['deepDiagnostics'][cid + '--native']
        python = data['deepDiagnostics'][cid + '--python']
        require(trace['id'] == original['id'] == python['id'] == cid and original['side'] == 'native'
                and python['side'] == 'python' and python['validationStatus'] == 'verified',
                'Deep consolidation diagnostics borrowed another case or process')
        case_path = Path(trace['familyProfile']['casePath'])
        directory, sdk_path = case_path.parent, Path(python['retainedSdkRawPath'])
        sdk_dir = sdk_path.parent
        require(case_path.name == 'case.json' and directory.name == 'case' and directory.parent.parent == family
                and re.fullmatch(r'attempt-[a-zA-Z0-9_-]+', directory.parent.name) and directory not in used_native
                and sdk_path.name == 'python-raw.json' and sdk_dir.parent == family
                and re.fullmatch(r'sdk-attempt-[a-zA-Z0-9_-]+', sdk_dir.name) and sdk_dir not in used_sdk,
                'Deep consolidation capture does not belong to a distinct canonical attempt')
        used_native.add(directory)
        used_sdk.add(sdk_dir)
        hashes = {}

        def owned(path):
            require(path.resolve(strict=True) == path and path.is_file() and path.stat().st_nlink == 1,
                    'A deep artifact was replaced by a link or nonregular file')
            hashes[path] = digest(path)
            return path

        case_file = load(owned(case_path))
        context_path = owned(directory / 'context.json')
        context = load(context_path)
        profile = {'kind': 'deep-consolidation-family', 'operation': case['operation'], 'casePath': str(case_path),
                   'caseFileSha256': hashes[case_path], 'caseWireSha256': CASE_HASHES[cid], 'nodeRuntime': authority,
                   'acceptancePointsAwarded': 0}
        traces, evidence = directory / 'traces', directory / 'evidence'
        expected_context = {'schemaVersion': 1, 'kind': 'release-oracle-execution', 'runtime': runtime, 'providerMode': 'none',
                            'fetchPolicy': 'deny', 'approvedNodeRuntime': authority, 'promotionApplyFamilyProfile': profile,
                            'allowedLocal': local_sources, 'traceDirectory': str(traces), 'evidenceDirectory': str(evidence),
                            'stateDirectory': str(directory / 'state'), 'configPath': str(directory / 'openclaw.json'),
                            'approvedReferenceSources': [], 'fixtureSourceCaptures': []}
        require(_same_json(case_file, case) and _same_json(context, expected_context) and _same_json(trace['familyProfile'], profile)
                and traces.is_dir() and traces.resolve(strict=True) == traces, 'Deep case, context, or worker profile changed')
        native_path = owned(evidence / 'native-raw.json')
        sdk_path = owned(sdk_path)
        packets = []
        for path, diagnostic in ((native_path, original), (sdk_path, python)):
            packet = load(path)
            require(hashes[path] == diagnostic['sha256'] and isinstance(packet, list) and len(packet) == 1
                    and _same_json(packet, diagnostic['rawSnapshots']), 'Deep raw file does not reproduce its full-report packet')
            packets.append(packet[0])
        native_raw, sdk_raw = packets
        require(sdk_path.stat().st_size == python['sdkRawBytes'] and Path(native_raw['fixtureBase']).parent == evidence
                and Path(sdk_raw['fixtureBase']) == sdk_dir / 'sdk-promotion-apply-fixture', 'Wrong deep fixture owner')
        sdk_owners = {}
        for source in sdk_raw['sourceOwners']:
            path = Path(source['path'])
            require(path.resolve(strict=True) == path and path.is_file() and path.suffix == '.py' and path not in sdk_owners
                    and (path.is_relative_to(ROOT / 'memory_core') or path.parent == ROOT / 'equivalence')
                    and source['sourceBytes'].encode('utf-8') == path.read_bytes() and digest(path) == source['sha256'],
                    'A captured Python source changed or escaped the measured SDK')
            sdk_owners[path] = source['sha256']
        require({ROOT / 'memory_core/consolidation' / name for name in ('llm_consolidation.py', 'origins.py', 'promotion.py')}
                <= sdk_owners.keys(), 'SDK consolidation, promotion or origin owner was omitted')
        receipt = trace['processReceipt']
        require(type(receipt['processPid']) is int and type(receipt['coordinatorPid']) is int
                and receipt['processPid'] == native_raw['pid'] and receipt['coordinatorPid'] == native_raw['ppid']
                and receipt['processPid'] > 0 and receipt['coordinatorPid'] > 0 and receipt['processPid'] != receipt['coordinatorPid']
                and type(receipt['actualReturnCode']) is int and receipt['actualReturnCode'] == 0,
                'Original consolidation child process or exit code changed')
        stdout, stderr = owned(directory / 'stdout.json'), owned(directory / 'stderr.log')
        streams = {name: {'sha256': hashes[path], 'bytes': path.stat().st_size}
                   for name, path in (('stdout', stdout), ('stderr', stderr))}
        require(_same_json(receipt['originalProcessStreams'], streams), 'Deep process stream bytes do not match their capture')
        returned = load(stdout)
        require(_same_json(returned, {'id': cid, 'ok': True, 'result': native_raw['output']}),
                'Original stdout does not contain the complete original return')
        captures = []
        for file in sorted(traces.iterdir()):
            owned(file)
            captures.append({'name': file.name, 'text': file.read_bytes().decode('utf-8'), 'sha256': hashes[file]})
        require(_same_json(captures, trace['rawProcessWorkerTraces']), 'One of the whole original worker traces changed')
        observed = validate_traces(traces, {**context, '_sha256': hashes[context_path]}, runtime, authority,
                                   process_pid=receipt['processPid'], coordinator_pid=receipt['coordinatorPid'])
        require(_same_json(observed['bootstraps'], trace['threads']) and trace['provider'] == 'none'
                and trace['kind'] == 'authenticated-promotion-family-process-thread-trace' and trace['networkFetchDenied'] is True
                and trace['protectedWorkerThreads'] == len(observed['bootstraps']) - 1, 'Deep worker attestation changed')
        loaded = {(entry['path'], entry['sha256']) for entry in observed['loaded'] if entry['package'] == 'node_modules/openclaw'}
        require(all((entry['path'], entry['sha256']) in loaded for entry in data['deepConsolidationBindings']['compiledBindings']),
                'The original consolidation apply or origin module did not execute')
        validate_native_capture(case, native_raw, returned['result'], authority=authority, pid=receipt['processPid'])
        validate_pair(case, native_raw, sdk_raw, returned['result'], sdk_raw['output'])
        native_state, sdk_state = compare_deep_state(case, native_raw, sdk_raw)
        native = {**returned['result'], 'consolidationState': native_state}
        sdk = {**sdk_raw['output'], 'consolidationState': sdk_state}
        pair = data['deepPairs'][cid]
        require(_same_json(pair['openclaw'], native) and _same_json(pair['python'], sdk),
                'The complete deep public results differ from original raw evidence')
        require(all(path.resolve(strict=True) == path and digest(path) == sha for path, sha in (hashes | sdk_owners).items()),
                'Deep captures or SDK source changed during independent replay')
        results.append({'id': cid, 'validated': True, 'publicMatch': _same_json(native, sdk), 'nativeRawSha256': hashes[native_path],
                        'sdkRawSha256': hashes[sdk_path], 'originalStdoutSha256': hashes[stdout], 'originalStderrSha256': hashes[stderr],
                        'originalContextSha256': hashes[context_path], 'nativeRawFileBytes': native_path.stat().st_size,
                        'sdkRawFileBytes': sdk_path.stat().st_size, 'protectedWorkerThreads': trace['protectedWorkerThreads'],
                        'nativeOnDiskRawReopened': True, 'sdkOnDiskRawReopened': True, 'physicalStateRebuilt': True})
    verify_bindings()
    require(_same_json(prepare_model_node_authority(args.node), authority)
            and all(digest(Path(item['path'])) == item['sha256'] for item in local_sources),
            'The deep Node or adapter sources changed during independent replay')
    return results


def replay_persisted_rank(case, pair, native, sdk, trace, release_sources, bindings, profile, args, runtime):
    from equivalence.engine_numeric_rank import RANK_ID, validate_numeric_rank, validate_rank_case
    from equivalence.promotion_ranking_bindings import (
        COMPILED_HASHES, prepare_promotion_ranking_bindings, prepare_promotion_ranking_profile,
    )
    from equivalence.promotion_ranking_evidence import validate_promotion_ranking_raw
    from equivalence.runtime_oracle import MAX_SINGLE_TRACE_BYTES, MAX_DIAGNOSTIC_BYTES

    cid = case["id"]
    if cid == RANK_ID:
        validate_rank_case(case)
        validate_pair = validate_numeric_rank
    else:
        from equivalence.datetime_regex_family import build_cases as date_cases
        from equivalence.datetime_regex_evidence import validate_rank as validate_pair
        [fixed] = [c for c in date_cases() if c["operation"] == "promotion-ranking-runtime"]
        require(_same_json(case, fixed), "Unregistered persisted ranking case")
    require(set(pair) == {"openclaw", "python"}, "Missing complete persisted ranking pair")
    for packet, side in ((native, "native"), (sdk, "python")):
        require(packet["id"] == cid and packet["side"] == side
                and re.fullmatch(r"[a-f0-9]{64}", packet["sha256"])
                and isinstance(packet["rawSnapshots"], list) and len(packet["rawSnapshots"]) == 1,
                "Numeric ranking raw packet belongs to a different producer")
    original, python = native["rawSnapshots"][0], sdk["rawSnapshots"][0]
    # The collector retained parsed packets. Reconstruct each producer's wire format
    # and check the original byte digest. Neither temporary database is reopened here.
    sdk_wire = (json.dumps(sdk["rawSnapshots"], ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()
    native_wire = subprocess.run(
        [str(args.node.resolve()), "-e",
         "process.stdout.write(JSON.stringify(JSON.parse(require('node:fs').readFileSync(0,'utf8'))))"],
        input=json.dumps(native["rawSnapshots"], ensure_ascii=True, allow_nan=False).encode("ascii"),
        check=True, stdout=subprocess.PIPE, timeout=30,
    ).stdout
    for packet, encoded in ((native, native_wire), (sdk, sdk_wire)):
        require(0 < len(encoded) <= MAX_DIAGNOSTIC_BYTES
                and hashlib.sha256(encoded).hexdigest() == packet["sha256"],
                "Numeric ranking raw packet did not reproduce its original wire-byte digest")

    root = Path(runtime["runtimeRoot"])
    require(_same_json(bindings, prepare_promotion_ranking_bindings(args.reference, root))
            and _same_json(profile, prepare_promotion_ranking_profile(args.node)),
            "Numeric ranking source, official release or executable changed")
    transport = trace["promotionRankingTransport"]
    require(trace["id"] == cid and trace["kind"] == "authenticated-process-thread-trace"
            and trace["networkFetchDenied"] is True and trace["provider"] == "none"
            and transport["kind"] == "actual-promotion-ranking-validator-inputs"
            and transport["runtimeRoot"] == str(root) and transport["adapterRoot"] == str(ROOT)
            and python["implementationRoot"] == str(ROOT) and _same_json(transport["profile"], profile),
            "Numeric ranking was executed under another capability or source tree")

    allowed = {(package["location"], item["path"]): item["sha256"]
               for package in runtime["packages"] for item in package["files"]}
    projected = {(row["package"], row["path"]): row["sha256"] for row in release_sources}
    required = {("node_modules/openclaw", path): sha for path, sha in COMPILED_HASHES.items()}
    require(len(projected) == len(release_sources) and projected == required,
            "Full report omits, duplicates or substitutes a numeric ranking compiled owner")
    local_paths = {str(ROOT / "equivalence" / name): digest(ROOT / "equivalence" / name)
                   for name in ("release-oracle.mjs", "promotion-ranking-runtime.mjs", "model-runtime-observation.mjs")}
    preload_sha = digest(ROOT / "equivalence/release-preload.mjs")
    carriers = transport["rawProcessWorkerTraces"]
    require(len(carriers) == 2, "Numeric ranking needs the original main process and its protected worker")
    pid, ppid = original["pid"], original["ppid"]
    require(type(pid) is int and type(ppid) is int and min(pid, ppid) > 0, "Missing numeric ranking process IDs")
    bootstrap, worker_imports, loaded, locals_loaded, context_hashes = [], [], {}, set(), set()
    for carrier in carriers:
        blob = carrier["text"].encode("utf-8")
        require(0 < len(blob) == carrier["bytes"] <= MAX_SINGLE_TRACE_BYTES and blob.endswith(b"\n")
                and hashlib.sha256(blob).hexdigest() == carrier["sha256"], "Incomplete numeric ranking trace bytes")
        records = [json.loads(line) for line in carrier["text"].splitlines()]
        first = records[0]
        thread = first["threadId"]
        require(type(thread) is int and thread >= 0 and first["event"] == "bootstrap"
                and first["pid"] == pid and first["ppid"] == ppid and first["isMainThread"] is (thread == 0)
                and carrier["name"] == f"{pid}-{thread}.jsonl" and first["preloadSha256"] == preload_sha
                and first["fetchDenied"] is True and first["providerMode"] == "none"
                and re.fullmatch(r"[a-f0-9]{64}", first["contextSha256"])
                and _same_json(first["promotionProfile"], profile) and _same_json(first["runtime"], profile["nodeRuntime"])
                and {key for key in first if key.endswith("Profile")} == {"promotionProfile"},
                "Numeric ranking thread lacks its original protected bootstrap")
        context_hashes.add(first["contextSha256"])
        bootstrap.append({key: first[key] for key in ("pid", "threadId", "isMainThread", "runtime", "promotionProfile")})
        for event in records[1:]:
            require(event["pid"] == pid and event["threadId"] == thread and event["event"] in {"load", "resolve-native"},
                    "Numeric ranking trace escaped the declared processes")
            path = event["path"]
            if event["kind"] == "oracle":
                require(thread == 0 and event["event"] == "load" and local_paths.get(path) == event["sha256"],
                        "Numeric ranking loaded an unrelated comparison adapter")
                locals_loaded.add(path)
                continue
            key = (event.get("package"), path)
            require(event["kind"] == "release" and key in allowed and allowed[key] == event["sha256"],
                    "Numeric ranking import differs from its original authenticated release file")
            if event["event"] == "load":
                loaded[key] = event["sha256"]
                if thread:
                    worker_imports.append({"package": key[0], "path": path, "threadId": thread, "pid": pid})
    release_loaded = {path for package, path in loaded if package == "node_modules/openclaw"}
    require(len(context_hashes) == 1 and _same_json(bootstrap, transport["bootstrap"])
            and _same_json(bootstrap, trace["threads"]) and len({b["threadId"] for b in bootstrap}) == 2
            and trace["protectedWorkerThreads"] == 1 and trace["loadedReleaseFiles"] == len(loaded)
            and transport["processParents"] == {str(pid): ppid}
            and locals_loaded == set(local_paths) and transport["localByPid"] == {str(pid): sorted(locals_loaded)}
            and transport["releaseByPid"] == {str(pid): sorted(release_loaded)}
            and _same_json(worker_imports, transport["workerImports"])
            and all(loaded.get(key) == sha for key, sha in required.items()),
            "Actual numeric ranking load traces disagree with the process, worker or source projection")

    directory = Path(original["fixtureBase"]).parent
    require(directory.is_absolute() and directory.name == hashlib.sha256(cid.encode()).hexdigest()
            and directory.parent.name == "evidence" and directory.parent.parent.name.startswith("memory-release-oracle-"),
            "Retained numeric ranking SQLite receipts escaped the owned fixture")
    validate_promotion_ranking_raw(
        {"id": cid, "ok": True, "result": pair["openclaw"]}, case, native["rawSnapshots"], directory,
        runtime_root=root, bootstrap=bootstrap, release_by_pid={pid: release_loaded},
        local_by_pid={pid: locals_loaded}, worker_imports=worker_imports,
        process_parents={pid: ppid}, adapter_root=ROOT)
    validate_pair(case, pair["openclaw"], pair["python"], native["rawSnapshots"], sdk["rawSnapshots"])
    return {"id": cid, "validated": True, "publicMatch": _same_json(pair["openclaw"], pair["python"]),
            "sdkRawSha256": sdk["sha256"], "nativeCollectorRawSha256": native["sha256"],
            "rawWireHashesReproduced": True, "nativeOnDiskRawReopened": False,
            "protectedWorkerThreads": trace["protectedWorkerThreads"],
            "rawTraceSha256": [carrier["sha256"] for carrier in carriers],
            "compiledOwners": len(required), "sourceOwners": len(bindings["sourceBindings"]),
            "candidateCounts": [len(row["candidates"]) for row in pair["openclaw"]["queries"]]}


def replay_numeric(data, cases, args):
    from equivalence.engine_numeric_family import SOURCE_OPERATION, SOURCE_OWNERS, validate_registration, validate_source_pair
    from equivalence.engine_numeric_rank import RANK_ID
    from equivalence.promotion_ranking_bindings import prepare_promotion_ranking_bindings, prepare_promotion_ranking_profile
    from equivalence.release_runtime import prepare_release_runtime

    validate_registration(cases)
    case_ids = {case["id"] for case in cases}
    sources = {case["id"] for case in cases if case["operation"] == SOURCE_OPERATION}
    require(len(cases) == 4 and case_ids == set(data["numericPairs"]) == sources | {RANK_ID}
            and set(data["numericSourceImports"]) == sources
            and set(data["numericTraces"]) == {RANK_ID}
            and set(data["numericDiagnostics"]) == {RANK_ID + "--native", RANK_ID + "--python"},
            "Numeric acceptance needs every whole plan and ranking observation")
    require(case_ids.intersection(data["referenceExecution"]["trackedTypeScriptCaseIds"]) == sources
            and case_ids.intersection(data["referenceExecution"]["compiledReleaseCaseIds"]) == {RANK_ID},
            "Numeric inputs were dispatched to the wrong execution owners")
    source_receipts = data["numericSources"]
    require(len(source_receipts) == len(SOURCE_OWNERS)
            and {owner["path"] for owner in source_receipts} == set(SOURCE_OWNERS),
            "Missing source receipts for original numeric plans")
    for owner in source_receipts:
        original = subprocess.check_output(["git", "show", data["reference"]["commit"] + ":" + owner["path"]],
                                           cwd=args.reference)
        require(digest(args.reference / owner["path"]) == hashlib.sha256(original).hexdigest() == owner["sha256"],
                "Original numeric source bytes changed")
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    bindings = prepare_promotion_ranking_bindings(args.reference, Path(runtime["runtimeRoot"]))
    profile = prepare_promotion_ranking_profile(args.node)
    require(_same_json(data["promotionRankingRuntimeBindings"], bindings)
            and _same_json(data["promotionRankingProfile"], profile), "Original ranking identity changed")
    results = []
    for case in cases:
        cid = case["id"]
        pair = data["numericPairs"][cid]
        if cid == RANK_ID:
            results.append(replay_persisted_rank(case, pair, data["numericDiagnostics"][cid + "--native"],
                                               data["numericDiagnostics"][cid + "--python"], data["numericTraces"][cid],
                                               data["numericReleaseSources"], bindings, profile, args, runtime))
        else:
            imports = data["numericSourceImports"][cid]
            validate_source_pair(case, imports, source_receipts, pair["openclaw"], pair["python"])
            results.append({"id": cid, "validated": True, "publicMatch": _same_json(pair["openclaw"], pair["python"]),
                            "probes": len(case["input"]["probes"]), "sourceImports": imports,
                            "publicValueSha256": {side: hashlib.sha256(canonical(row)).hexdigest()
                                                 for side, row in pair.items()}})
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
    numeric = [row for row in rows if row["requirement"] == "engine.numeric-boundaries"]
    require(numeric, "Numeric acceptance family is missing")
    states["engine.numeric-boundaries"] = all(row["status"] == "matched" and row.get("numericEvidenceValidated") is True
                                              for row in numeric)
    for point in {point for row in numeric for point in row["covers"]}:
        gates.setdefault(point, []).append("engine.numeric-boundaries")
    deep = [row for row in rows if row["operation"] == "deep-consolidation-runtime"]
    if deep:
        states["deep-consolidation-runtime"] = all(row["status"] == "matched" and row.get("runtimeEvidenceValidated") is True
                                                  for row in deep)
        for point in {point for row in deep for point in row["covers"]}:
            gates.setdefault(point, []).append("deep-consolidation-runtime")
    for operation, (family, _, _) in FAMILIES.items():
        family_rows = [row for row in rows if family_key(row) == operation]
        require(family_rows, "An appended family is missing")
        states[operation] = family.family_complete(rows)
        for point in {p for row in family_rows for p in row["covers"]}:
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


def verify_process_exit(args, data):
    summary = args.seal.parent
    launch = load(summary / "launch.json")
    exited = load(summary / "os-exit.json")
    output = load(summary / "run-summary.json")
    stdout = digest(summary / "run-summary.json")
    stderr = digest(summary / "comparison.stderr.log")
    require(launch["automaticRetry"] is False and type(launch["pid"]) is int and launch["pid"] > 0
            and launch["kind"] == "single-full-comparison-launch" and launch["cwd"] == str(ROOT)
            and launch["argv"][1:] == ["scripts/check_equivalence.py", "--reference", ".reference/openclaw",
                "--node", str(args.node.resolve()), "--release-runtime", ".reference/release-runtime",
                "--report", ".equivalence-results/full.json"]
            and all(_same_json(exited[k], v) for k, v in launch.items() if k != "pid")
            and exited["sourceSealSha256"] == digest(args.seal) and exited["fullReportSha256"] == data["report"]["sha256"]
            and exited["stdoutSha256"] == stdout and exited["stderrSha256"] == stderr,
            "The collector process or its original report/streams changed")
    require(output["reportSha256"] == data["report"]["sha256"]
            and all(_same_json(output[k], data[k]) for k in ("mode", "status", "summary", "errors", "fullScopePassed"))
            and all(output[label] == [row["id"] for row in data["cases"] if row["status"] == status]
                    for label, status in (("mismatchedCaseIds", "mismatched"), ("blockedCaseIds", "blocked")))
            and type(exited["actualReturnCode"]) is int
            and exited["actualReturnCode"] == {"passed": 0, "mismatched": 1, "incomplete": 1, "blocked": 2}[data["status"]],
            "The real comparison exit or stdout contradicts the report")
    return {"actualReturnCode": exited["actualReturnCode"], "pid": launch["pid"], "stdoutSha256": stdout,
            "stderrSha256": stderr, "reportBytes": data["report"]["bytes"], "reportSha256": data["report"]["sha256"]}


def compact_case(row, definition):
    receipt = {key: value for key, value in row.items()
               if key in {"id", "status", "publicValueSha256", "datetimeRegexValidated", "datetimeBoundaryEvidence"} or key.endswith("EvidenceValidated")}
    omitted = sorted(definition.keys() - row.keys())
    if omitted:
        receipt["omittedDefinitionFields"] = omitted
    return receipt


def check_resolved_row(row, prior, unicode_pair):
    expected = {"openclaw": prior["openclaw"], "python": prior["openclaw"]}
    if row["id"] == UNICODE_TIE_ID:
        # Scores such as 1 and 1.0 compare equally in JSON while preserving distinct producer bytes.
        expected["python"] = MEASURED_SDK_F01_SHA256
        observed = {side: hashlib.sha256(canonical(unicode_pair[side])).hexdigest() for side in expected}
        require(prior["openclaw"] == PRIOR_NATIVE_F01_SHA256 and observed == expected
                and _same_json(unicode_pair["openclaw"], unicode_pair["python"]),
                "The complete Unicode tie values or their measured producer receipts changed")
    require(row["status"] == "matched" and row["publicValueSha256"] == expected,
            "A declared fix differs from the required whole producer outputs")


def assess(args, result):
    check_seal()
    seal = load(args.seal)
    source_unchanged(seal)
    definitions = build_cases()
    migration = definition_authority(definitions, fif_version="v6")
    require(len(definitions) == seal["registeredCases"]
            and hashlib.sha256(canonical(definitions)).hexdigest() == seal["catalogSha256"], "Sealed catalog changed")
    previous = {"registeredCases": PREVIOUS_CASES, "sha256": PREVIOUS_CATALOG_SHA,
                "completePrefixUnchanged": True}
    require(len(definitions) == REGISTERED_CASES and REGISTERED_CASES > previous["registeredCases"]
            and seal["catalogSha256"] == CATALOG_SHA
            and _same_json(seal["previousCatalog"], previous)
            and hashlib.sha256(canonical(definitions[:previous["registeredCases"]])).hexdigest() == previous["sha256"],
            "The complete prior comparison catalog changed or the frozen appended cases are incomplete")
    host_cases = [case for case in definitions if case["operation"] == "host-turn-barrier-v4-runtime"]
    lineage_cases = [case for case in definitions if case["operation"] == "forget-lineage-runtime"]
    boundary_cases = [case for case in definitions if case["operation"] == "forget-boundaries-runtime"]
    recall_cases = [case for case in definitions if case["operation"] == "recall-signals-runtime"]
    cache_cases = [case for case in definitions if case["operation"] == "embed-cache-lifecycle-runtime"]
    reset_cases = [case for case in definitions if case["operation"] == "session-reset-boundaries-runtime"]
    prompt_cases = [case for case in definitions if case["operation"] == "prompt-runtime-context-runtime"]
    history_cases = [case for case in definitions if case["operation"] == "prompt-history-repair-runtime"]
    numeric_cases = [case for case in definitions if case["requirement"] == "engine.numeric-boundaries"]
    deep_cases = [case for case in definitions if case["operation"] == "deep-consolidation-runtime"]
    data = project(args.report, {case["id"] for case in host_cases}, {case["id"] for case in lineage_cases},
                   {case["id"] for case in boundary_cases}, {case["id"] for case in recall_cases},
                   {case["id"] for case in cache_cases}, {case["id"] for case in reset_cases},
                   {case["id"] for case in prompt_cases}, {case["id"] for case in history_cases},
                   {case["id"] for case in numeric_cases}, {case["id"] for case in deep_cases},
                   {case["id"] for case in definitions if family_key(case) in FAMILIES})
    result.update(completeReportParsed=True, report=data["report"], projection={
        key: data[key] for key in ("reference", "mode", "status", "fullScopePassed", "summary", "manifestSha256",
                                   "paidProviderCalls", "providerCredentialsForwarded", "startedAt", "finishedAt")})
    require(data["errors"] == [] and data["mode"] == "full" and data["kind"] == "pinned-differential-acceptance",
            "Global collector error or non-full report; no candidate score")
    require(_same_json(data["implementation"], seal["implementation"])
            and _same_json(data["adapterSha256"], seal["adapters"])
            and _same_json(data["definitionMigration"], migration)
            and _same_json(seal["definitionMigration"], migration), "Report source or definition authority differs")
    for key, name in (("scope", "scope.json"), ("reference", "reference.json"), ("sourceMap", "source-map.json")):
        require(data["manifestSha256"][key] == digest(ROOT / "equivalence" / name), "Report manifest changed")
    from equivalence.harness import _validate_reference

    require(_same_json(data["reference"], _validate_reference(args.reference.resolve(), args.node.resolve(),
                       load(ROOT / "equivalence/reference.json"))), "The pinned release, executable or source tree changed")
    require(data["paidProviderCalls"] == 0 and data["providerCredentialsForwarded"] is False, "Unexpected provider access")
    metrics = recompute(data, definitions, load(ROOT / "equivalence/scope.json")["requirements"])
    # Keep the second review reproducible without duplicating every literal input
    # or requiring reviewers to download the original process captures.
    compact_rows = []
    observed_definitions = []
    for row, definition in zip(data["cases"], definitions, strict=True):
        observed = {key: row[key] for key in definition if key in row}
        observed_definitions.append(observed)
        compact_rows.append(compact_case(row, definition))
    result["projection"].update(
        cases=compact_rows, requirements=data["requirements"],
        observedDefinitionsSha256=hashlib.sha256(canonical(observed_definitions)).hexdigest(),
        casesSha256=data["casesSha256"], errors=data["errors"], kind=data["kind"],
        catalogFamilyGates={key: value for key, value in data.items()
                            if key.endswith("Complete") and type(value) is bool})
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
    result["sessionResetBoundariesReplays"] = replay_reset(data, reset_cases, args)
    result["promptRuntimeContextReplays"] = replay_prompt(data, prompt_cases, args)
    result["promptHistoryRepairReplays"] = replay_prompt(data, history_cases, args, history=True)
    from equivalence.embedding_cache_lifecycle import family_complete as cache_complete
    from equivalence.forget_boundaries import family_complete as boundaries_complete
    from equivalence.forget_lineage_outcomes import family_complete
    from equivalence.recall_signals import family_complete as recall_complete
    from equivalence.session_reset_boundaries import family_complete as reset_complete
    from equivalence.prompt_runtime_context import family_complete as prompt_complete
    from equivalence.prompt_history_repair import family_complete as history_complete

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
    require(data["sessionResetBoundariesFamilyComplete"] is reset_complete(data["cases"])
            is metrics["families"]["session-reset-boundaries-runtime"]
            is all(row["publicMatch"] for row in result["sessionResetBoundariesReplays"]),
            "Session reset boundary complete-family gate differs")
    require(data["promptRuntimeContextFamilyComplete"] is prompt_complete(data["cases"])
            is metrics["families"]["prompt-runtime-context-runtime"]
            is all(row["publicMatch"] for row in result["promptRuntimeContextReplays"]),
            "Prompt runtime-context complete-family gate differs")
    require(data["promptHistoryRepairFamilyComplete"] is history_complete(data["cases"])
            is metrics["families"]["prompt-history-repair-runtime"]
            is all(row["publicMatch"] for row in result["promptHistoryRepairReplays"]),
            "Prompt history repair complete-family gate differs")
    from equivalence.engine_numeric_family import family_complete as numeric_complete

    result["engineNumericReplays"] = replay_numeric(data, numeric_cases, args)
    require(data["engineNumericFamilyComplete"] is numeric_complete(data["cases"])
            is metrics["families"]["engine.numeric-boundaries"]
            is all(row["publicMatch"] for row in result["engineNumericReplays"]),
            "Numeric whole-family replay contradicts the complete point calculation")
    from equivalence.deep_consolidation import family_complete as deep_complete

    result["deepConsolidationReplays"] = replay_deep(data, deep_cases, args)
    require(data["deepConsolidationFamilyComplete"] is deep_complete(data["cases"])
            is metrics["families"]["deep-consolidation-runtime"]
            is all(row["publicMatch"] for row in result["deepConsolidationReplays"]),
            "Consolidation replay contradicts the complete point calculation")
    result["appendedFamilyReplays"] = replay_followup(data, definitions, args, metrics, replay_persisted_rank)
    process = verify_process_exit(args, data)
    result["comparisonProcess"] = process
    public = {row["id"]: row.get("publicValueSha256") for row in data["cases"]}
    require(set(PREVIOUS_MISMATCH_PUBLIC_SHA256) <= set(public), "A previous mismatch case disappeared")
    earlier = PREVIOUS_COMPARISON["familyGates"]
    newly_measured = {"prompt-history-repair-runtime", "engine.numeric-boundaries", "deep-consolidation-runtime"}
    require(set(metrics["families"]) == set(earlier) | newly_measured | set(FAMILIES)
            and all(metrics["families"][name] is passed for name, passed in earlier.items()),
            "A previously accepted family gate differs from its retained assessment")
    previous_hashes = dict(PREVIOUS_MISMATCH_PUBLIC_SHA256)
    previous_hashes["flush-execution-warm-index-first-recall"] = {
        **previous_hashes["flush-execution-warm-index-first-recall"],
        "openclaw": PREVIOUS_COMPARISON["warmFlushNativeSha256"]}
    result["previousComparison"] = PREVIOUS_COMPARISON
    mismatches = [r for r in data["cases"] if r["status"] == "mismatched"]
    result["mismatchMetadata"] = [{k: r[k] for k in ("id", "operation", "requirement", "covers", "publicValueSha256")}
                                  for r in mismatches]
    result["previousMismatchPublicHashChanges"] = {
        cid: {"before": before, "after": public[cid]}
        for cid, before in previous_hashes.items() if not _same_json(before, public[cid])}
    rows_by_id = {row["id"]: row for row in data["cases"]}
    resolved = set(EXPECTED_RESOLUTIONS)
    require(resolved <= set(previous_hashes), "The expected resolutions include a case outside the previous differences")
    for cid in resolved:
        check_resolved_row(rows_by_id[cid], previous_hashes[cid], data["unicodeTiePair"])
    sdk_changes = [cid for cid, before in previous_hashes.items()
                   if before["python"] != (public[cid] or {}).get("python")]
    native_changes = [cid for cid, before in previous_hashes.items()
                      if before["openclaw"] != (public[cid] or {}).get("openclaw")]
    allowed_warm_changes = [cid for cid in native_changes
                            if cid == "flush-execution-warm-index-first-recall" and cid not in sdk_changes
                            and rows_by_id[cid]["status"] == "mismatched" and rows_by_id[cid]["covers"] == []]
    result["previousMismatchPublicHashReview"] = {
        "sdkChangedCaseIds": sdk_changes, "nativeChangedCaseIds": native_changes,
        "allSdkWholePublicHashesUnchanged": not sdk_changes,
        "allowedUncreditedNativeWarmFlushChanges": allowed_warm_changes,
        "resolvedCaseIds": sorted(resolved),
        "otherChangedCaseIds": sorted((set(sdk_changes) | set(native_changes)) - set(allowed_warm_changes) - resolved)}
    from followup_date_boundaries import DIAGNOSTIC, verify_legacy_diagnostic
    verify_legacy_diagnostic(rows_by_id[DIAGNOSTIC])
    require({row["id"] for row in mismatches} == (set(previous_hashes) - resolved) | {DIAGNOSTIC}
            and not result["previousMismatchPublicHashReview"]["otherChangedCaseIds"],
            "Unexpected change to a retained difference or its complete public value")
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
                  deltaFromHistorical81=metrics["verified"] - 81,
                  deltaFromHistorical82=metrics["verified"] - 82,
                  deltaFromHistorical84=metrics["verified"] - 84,
                  deltaFromPreviousHosted=metrics["verified"] - PREVIOUS_COMPARISON["verified"],
                  fifReplaySha256=replay_sha, fullScopePassed=data["fullScopePassed"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "seal", "fif-replay", "reference", "node", "release-runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = {"kind": "approved-product-complete-eof-candidate-assessment", "status": "blocked",
              "metadataOnlyAssessment": True, "completeRootAudit": False, "acceptancePointsAwarded": 0,
              "originalEnginesExecuted": False, "historicalVerifiedConditions": (PREVIOUS_COMPARISON or {}).get("verified"),
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
