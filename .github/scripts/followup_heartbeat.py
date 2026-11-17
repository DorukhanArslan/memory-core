"""Verify that automatic polls do not write a note or appear in the searchable session."""
import hashlib
import json
from pathlib import Path
import subprocess

from equivalence import heartbeat_turn_boundaries as heartbeat
from equivalence.flush_execution import _owned_entry
from equivalence.flush_execution_bindings import prepare_flush_execution_bindings
from equivalence.harness import _same_json

HEARTBEAT_GATE = heartbeat.POINT
CORPUS_OWNERS = {"packages/memory-host-sdk/src/host/session-files.ts",
                "packages/memory-host-sdk/src/host/session-reset-recall.ts", "src/auto-reply/heartbeat-filter.ts"}


def require(value, message):
    if not value:
        raise ValueError(message)


def raw_flush(capture, side, node):
    item = capture[side]
    require(item["side"] == side and item["id"] == heartbeat.FLUSH, "Unexpected heartbeat raw capture")
    rows = item["rawSnapshots"]
    if side == "native":
        raw = subprocess.run([str(node), "-e",
            'const fs=require("node:fs");process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,"utf8")))+"\\n")'],
            input=json.dumps(rows, ensure_ascii=True, allow_nan=False).encode(), capture_output=True,
            check=True, timeout=15).stdout
    else:
        raw = (json.dumps(rows, ensure_ascii=False, allow_nan=False) + "\n").encode()
    require(hashlib.sha256(raw).hexdigest() == item["sha256"], "Heartbeat raw receipt digest changed")
    return rows


def replay_heartbeat(data, cases, args, runtime):
    heartbeat.validate_registration(cases)
    source_receipts = {s["path"]: s["sha256"] for s in data["heartbeatSources"]}
    require(set(source_receipts) == CORPUS_OWNERS and len(data["heartbeatSources"]) == len(CORPUS_OWNERS),
            "Missing or duplicate authenticated original corpus sources")
    for path, digest in source_receipts.items():
        require(hashlib.sha256((args.reference / path).read_bytes()).hexdigest() == digest,
                "Heartbeat corpus source changed")
    require(_same_json(data["flushExecutionBindings"], prepare_flush_execution_bindings(
            args.reference, Path(runtime["runtimeRoot"]))), "Original flush caller or owner changed")
    results = []
    for case in cases:
        capture = data["followupRows"][case["id"]]
        row = capture["case"]
        require(row["status"] == "matched" and row["heartbeatExclusionEvidenceValidated"] is True
                and all(_same_json(row[k], v) for k, v in case.items())
                and _same_json(row["openclaw"], row["python"]), "Invalid complete heartbeat pair")
        receipt = {"id": case["id"], "publicMatch": True}
        if case["id"] != heartbeat.FLUSH:
            for side in ("openclaw", "python"):
                heartbeat.validate_corpus(case, row[side], data["heartbeatSources"], data["heartbeatCorpusSourceImports"][case["id"]])
            sample = row["openclaw"]["reads"][0]
            receipt.update(opensPerSide=2, sourceSha256=sample["sourceSha256"],
                           observedMessages=len(sample["observed"]), keptSourceLines=sample["entry"]["lineMap"])
        else:
            trace = capture["trace"]
            require(trace["id"] == case["id"] and trace["kind"] == "authenticated-process-thread-trace"
                    and trace["protectedWorkerThreads"] >= 1 and trace["networkFetchDenied"] is True
                    and trace["provider"] == "none", "Missing protected model or index worker")
            native, sdk = (raw_flush(capture, side, args.node) for side in ("native", "python"))
            for side, raw in (("openclaw", native), ("python", sdk)):
                public = row[side]
                heartbeat.validate_flush(case, public, native, sdk)
                for drive, snapshot in zip(raw, public["snapshots"], strict=True):
                    physical = {key: drive[key] for key in snapshot}
                    if side == "openclaw":
                        physical["persistedEntry"] = _owned_entry(drive["persistedEntry"])
                        physical["modelCalls"] = len(drive["modelCalls"])
                    require(_same_json(physical, snapshot), "Flush public drive differs from its retained raw receipt")
            receipt.update(drives=len(native), modelCalls=[len(d["modelCalls"]) for d in native],
                           rawDigests={side: capture[side]["sha256"] for side in ("native", "python")})
        results.append(receipt)
    return results
