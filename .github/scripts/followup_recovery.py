"""Reopen nine authenticated recovery captures from the complete streamed comparison."""
from pathlib import Path

from equivalence import recovery_repair
from equivalence.harness import ROOT, _adapter_identity, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.workspace_case_families import evidence_family, native_validator, prepare_bindings, report_key, sdk_validator
from followup_dreams import capture, checked_text, digest, loaded_sources, require


def replay_recovery(data, cases, args, runtime):
    require(_same_json(cases, recovery_repair.build_cases()), "The complete recovery family is required")
    recovery_repair.validate_registration(cases)
    root = args.report.parent.resolve(strict=True)
    require(root == ROOT / ".equivalence-results", "Recovery replay requires the designated recording root")
    authority = prepare_model_node_authority(args.node)
    owners = Path(runtime["runtimeRoot"])
    adapters = _adapter_identity()
    checked = {op: prepare_bindings(args.reference, owners, op) for op in (recovery_repair.ARTIFACT, recovery_repair.INDEX)}
    for operation, bindings in checked.items():
        require(_same_json(bindings, data[report_key(operation, "Bindings")]) and
                _same_json(authority, data[report_key(operation, "Node")]), "Recovery bindings or Node changed")
    global_sources = {(r["package"],r["path"]):r["sha256"] for r in data["followupReleaseSources"]}
    require(len(global_sources) == len(data["followupReleaseSources"]), "Duplicate protected release owner")
    evidence = []
    used = set()
    for case in cases:
        cid, op = case["id"], case["operation"]
        row = data["followupRows"][cid]
        pair, trace = row["case"], row["trace"]
        recovery_repair.validate_case(pair)
        require(pair["status"] == "matched" and pair["runtimeEvidenceValidated"] is True
                and pair["referenceMode"] == "authenticated-official-release", "Missing genuine repair pair")
        family_root = root/evidence_family(op)
        require(family_root.resolve(strict=True) == family_root, "Recovery raw path is aliased")
        nd, sd = row["native"], row["python"]
        np, ns, nbytes = capture(nd,cid,"native",family_root,used)
        sp, ss, sbytes = capture(sd,cid,"python",family_root,used)
        native_root = Path(ns[0]["root" if op==recovery_repair.ARTIFACT else "fixtureBase"])
        require(native_root.parent.name == digest(cid.encode()) and native_root.parent.parent.name == "evidence",
                "Retained native repair path does not belong to this observed case")
        profile = recovery_repair.profile_for(case,args.node)
        observed = loaded_sources(case,trace,ns[0],profile,runtime,adapters,global_sources)
        streams = trace[report_key(op,"Transport")]["originalProcessStreams"]
        stdout = checked_text(streams["stdout"],4*1024**2)
        stderr = checked_text(streams["stderr"],4*1024**2)
        require(_same_json(_json(stdout.decode()), {"kind":"official-release-runtime-comparison","sources":[],
            "results":[{"id":cid,"ok":True,"result":pair["openclaw"]}]}), "Recovery output differs from its original process")
        native = native_validator(op)(case,pair["openclaw"],ns,np.parent,observed,archived=True)
        sdk = sdk_validator(op)(case,pair["python"],ss,sp.parent,archived=True)
        require(native["stages"] == sdk["stages"] and _same_json(pair["openclaw"],pair["python"]),
                "Reopened recovery boundaries diverged")
        evidence.append({"id":cid,"validated":True,"publicMatch":True,"physicalBoundaries":native["stages"],
            "protectedWorkerThreads":trace["protectedWorkerThreads"],"nativeRawSha256":nd["sha256"],
            "sdkRawSha256":sd["sha256"],"nativeRawFileBytes":nbytes,"sdkRawFileBytes":sbytes,
            "originalStdoutSha256":digest(stdout),"originalStderrSha256":digest(stderr),
            "nativeOnDiskRawReopened":True,"sdkOnDiskRawReopened":True,"physicalStateRebuilt":True})
    require(all(_same_json(v,prepare_bindings(args.reference,owners,op)) for op,v in checked.items()) and
            _same_json(adapters,_adapter_identity()) and _same_json(authority,prepare_model_node_authority(args.node)),
            "Recovery sources, runtime, or adapters changed during replay")
    return evidence
