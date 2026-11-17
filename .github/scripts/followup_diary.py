"""Independent CI replay of the dedicated diary publication originals and SDK bytes."""
from pathlib import Path

from equivalence import dream_diary as family
from equivalence.dream_diary_evidence import validate_native, validate_sdk
from equivalence.dream_light_bindings import prepare_dream_light_bindings
from equivalence.harness import ROOT, _adapter_identity, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.runtime_oracle import MAX_DIAGNOSTIC_BYTES, _owned_regular
from followup_dreams import capture, checked_text, digest, loaded_sources, require


def replay_diary(data, cases, args, runtime):
    family.validate_registration(cases)
    require(_same_json(cases, family.build_cases()), "Diary replay requires all frozen inputs")
    report_root = args.report.resolve(strict=True).parent
    directory = report_root / "dream-diary"
    require(report_root == ROOT / ".equivalence-results" and directory == directory.resolve(strict=True),
            "Misbound diary capture directory")
    node = prepare_model_node_authority(args.node)
    adapters = _adapter_identity()
    release_root = Path(runtime["runtimeRoot"])
    bindings = prepare_dream_light_bindings(args.reference, release_root, phase="diary")
    require(_same_json(node, data["dreamDiaryNode"]) and _same_json(bindings, data["dreamDiaryBindings"]),
            "Diary source, binary or release bindings changed")
    sources = {(row["package"], row["path"]): row["sha256"] for row in data["followupReleaseSources"]}
    require(len(sources) == len(data["followupReleaseSources"]), "Duplicate native release source")
    paths, results = set(), []
    for case in cases:
        cid = case["id"]
        record = data["followupRows"][cid]
        pair, native, sdk, trace = (record[key] for key in ("case", "native", "python", "trace"))
        family.validate_case(pair)
        require(pair["status"] == "matched" and pair.get("runtimeEvidenceValidated") is True
                and pair["referenceMode"] == "authenticated-official-release"
                and _same_json(pair["openclaw"], pair["python"]), "Unverified diary case")
        native_path, original, native_size = capture(native, cid, "native", directory, paths)
        sdk_path, actual, sdk_size = capture(sdk, cid, "python", directory, paths)
        profile = family.profile_for(case, args.node)
        loaded = loaded_sources(case, trace, original[0], profile, runtime, adapters, sources)
        streams = trace["dreamDiaryTransport"]["originalProcessStreams"]
        stdout = checked_text(streams["stdout"], 4 * 1024 * 1024)
        stderr = checked_text(streams["stderr"], 4 * 1024 * 1024)
        require(_same_json(_json(stdout.decode()), {"kind": "official-release-runtime-comparison", "sources": [],
                "results": [{"id": cid, "ok": True, "result": pair["openclaw"]}]}),
                "Retained diary result differs from original process stdout")
        root = Path(original[0]["root"]).parent
        require(root.name == digest(cid.encode()) and root.parent.name == "evidence", "Unbound native diary root")
        validate_native(case, pair["openclaw"], original, root, loaded, archived=True)
        validate_sdk(case, pair["python"], actual, sdk_path.parent)
        require(digest(_owned_regular(ROOT, native_path, MAX_DIAGNOSTIC_BYTES)) == native["sha256"]
                and digest(_owned_regular(ROOT, sdk_path, MAX_DIAGNOSTIC_BYTES)) == sdk["sha256"],
                "Diary files changed during independent replay")
        results.append({"id": cid, "publicMatch": True, "validated": True, "nativeRawSha256": native["sha256"],
                        "sdkRawSha256": sdk["sha256"], "nativeRawFileBytes": native_size, "sdkRawFileBytes": sdk_size,
                        "originalStdoutSha256": digest(stdout), "originalStderrSha256": digest(stderr),
                        "protectedWorkerThreads": 1, "physicalBoundaries": len(case["input"]["operations"]),
                        "nativeOnDiskRawReopened": True, "sdkOnDiskRawReopened": True, "physicalStateRebuilt": True,
                        "reopenedSqliteSnapshots": len(original[0]["rows"]) + 1 + bool(original[0]["race"])})
    require(_same_json(adapters, _adapter_identity()) and _same_json(node, prepare_model_node_authority(args.node))
            and _same_json(bindings, prepare_dream_light_bindings(args.reference, release_root, phase="diary")),
            "Diary authority changed during replay")
    return results
