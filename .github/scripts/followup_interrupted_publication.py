"""Reopen each actual SQLite refusal, physical note, protected worker and original caller receipt."""
from pathlib import Path

from equivalence import recovery_failure as family
from equivalence.harness import ROOT, _adapter_identity, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.recovery_failure_evidence import validate_native, validate_sdk
from equivalence.workspace_case_families import evidence_family, prepare_bindings, report_key
from followup_dreams import capture, checked_text, digest, loaded_sources, require


def replay_interrupted_publication(data, cases, args, runtime):
    require(_same_json(cases, family.build_cases()), "Both frozen interruptions must be replayed")
    root=args.report.parent.resolve(strict=True)
    require(root==ROOT/".equivalence-results", "Unbound interrupted publication recording")
    op=family.OPERATION
    recorded=root/evidence_family(op)
    require(recorded.resolve(strict=True)==recorded, "Aliased interrupted publication captures")
    owners=Path(runtime["runtimeRoot"])
    authority=prepare_model_node_authority(args.node)
    bindings=prepare_bindings(args.reference,owners,op)
    adapters=_adapter_identity()
    require(_same_json(authority,data[report_key(op,"Node")]) and _same_json(bindings,data[report_key(op,"Bindings")]),
            "Pinned binary, source or release owner differs")
    sources={(r["package"],r["path"]):r["sha256"] for r in data["followupReleaseSources"]}
    require(len(sources)==len(data["followupReleaseSources"]),"Duplicate release source")
    evidence=[]
    used=set()
    for case in cases:
        ident=case["id"]
        row=data["followupRows"][ident]
        pair,trace,native,sdk=(row[k] for k in ("case","trace","native","python"))
        family.validate_case(pair)
        require(pair["status"]=="matched" and pair["runtimeEvidenceValidated"] is True and
                pair["referenceMode"]=="authenticated-official-release" and _same_json(pair["openclaw"],pair["python"]),
                "Unverified interrupted operation")
        np,ns,nsize=capture(native,ident,"native",recorded,used)
        sp,ss,ssize=capture(sdk,ident,"python",recorded,used)
        native_root=Path(ns[0]["root"])
        require(native_root.parent.name==digest(ident.encode()) and native_root.parent.parent.name=="evidence",
                "Native fault was not attached to the designated case")
        loaded=loaded_sources(case,trace,ns[0],family.profile_for(case,args.node),runtime,adapters,sources)
        streams=trace[report_key(op,"Transport")]["originalProcessStreams"]
        stdout=checked_text(streams["stdout"],4*1024**2)
        stderr=checked_text(streams["stderr"],4*1024**2)
        require(_same_json(_json(stdout.decode()),{"kind":"official-release-runtime-comparison","sources":[],
                "results":[{"id":ident,"ok":True,"result":pair["openclaw"]}]}),
                "Original process output does not match the complete caller response")
        left=validate_native(case,pair["openclaw"],ns,np.parent,loaded,archived=True)
        right=validate_sdk(case,pair["python"],ss,sp.parent,archived=True)
        require(left==right,"Independent readers saw different stages")
        evidence.append({"id":ident,"publicMatch":True,"validated":True,"physicalBoundaries":left["stages"],
            "reopenedSqliteSnapshots":left["sqliteImagesReopened"]+right["sqliteImagesReopened"],
            "protectedWorkerThreads":trace["protectedWorkerThreads"],"nativeRawSha256":native["sha256"],
            "sdkRawSha256":sdk["sha256"],"nativeRawFileBytes":nsize,"sdkRawFileBytes":ssize,
            "originalStdoutSha256":digest(stdout),"originalStderrSha256":digest(stderr),
            "nativeOnDiskRawReopened":True,"sdkOnDiskRawReopened":True,"physicalStateRebuilt":True})
    require(_same_json(bindings,prepare_bindings(args.reference,owners,op)) and _same_json(adapters,_adapter_identity())
            and _same_json(authority,prepare_model_node_authority(args.node)), "Interruption source changed during replay")
    return evidence
