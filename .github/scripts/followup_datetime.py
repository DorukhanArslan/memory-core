"""Verify original clock source receipts, regex child processes and persisted ranking observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from equivalence import datetime_regex_family as family
from equivalence.datetime_regex_evidence import same, validate_clock, validate_regex
from equivalence.harness import _committed_digest, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.promotion_ranking_bindings import COMPILED_HASHES
from equivalence.redaction_policy_evidence import (
    SOURCE_HASHES, prepare_redaction_policy_source_bindings, validate_redaction_policy_source_execution,
)

SOURCE_OWNERS = set(family.CLOCK_OWNERS) | set(SOURCE_HASHES)


def replay_datetime(data, cases, args, runtime, replay_rank):
    family.validate_registration(cases)
    same(cases, family.build_cases())
    sources = data["datetimeSources"]
    receipts = {r["path"]: r["sha256"] for r in sources}
    same(len(receipts), len(sources))
    if set(receipts) != SOURCE_OWNERS:
        raise ValueError("Missing a date or regex reference source owner")
    for name, sha in receipts.items():
        current = (args.reference / name).read_bytes()
        if hashlib.sha256(current).hexdigest() != sha or _committed_digest(args.reference, name) != sha:
            raise ValueError("An original date/regex reference owner changed")
    node = prepare_model_node_authority(args.node)
    same(data["modelNodeAuthority"], node)
    same(prepare_redaction_policy_source_bindings(args.reference), data["redactionPolicySourceBindings"])
    results = []
    for case in cases:
        cid = case["id"]
        packets = data["followupRows"][cid]
        row = packets["case"]
        same({k: row[k] for k in case}, case)
        if row.get("datetimeRegexValidated") is not True:
            raise ValueError("A date/regex case lacks its original producer receipts")
        native, sdk = row["openclaw"], row["python"]
        evidence = {"id": cid, "publicMatch": _same_json(native, sdk)}
        if case["operation"] == family.CLOCK:
            validate_clock(case, data["datetimeSourceImports"][cid], sources, native, sdk)
            same(sdk, family.run_clock(case["input"]))
            evidence.update(instants=len(native["instants"]), owners=family.CLOCK_OWNERS)
        elif case["operation"] == "promotion-ranking-runtime":
            projected = [r for r in data["followupReleaseSources"]
                         if r["package"] == "node_modules/openclaw" and r["path"] in COMPILED_HASHES]
            evidence = replay_rank(case, {"openclaw": native, "python": sdk},
                packets["native"], packets["python"], packets["trace"], projected,
                data["promotionRankingRuntimeBindings"], data["promotionRankingProfile"], args, runtime)
        else:
            x = packets["sourcePolicy"]["sourceExecution"]
            response = {"sources": sources, "sourceExecution": x,
                        "results": [{"id": cid, "ok": True, "result": native}]}
            base = Path(x["observations"][0]["logging"]["json"]["file"]).parent
            validate_redaction_policy_source_execution(response, case, node_authority=node,
                process_pid=x["pid"], coordinator_pid=x["ppid"], fixture_root=base)
            packet = packets["python"]
            encoded = (json.dumps(packet["rawSnapshots"], ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()
            same([packet["id"], packet["side"], packet["sha256"]], [cid, "python", hashlib.sha256(encoded).hexdigest()])
            validate_regex(case, native, sdk, x, packet["rawSnapshots"])
            [snapshot] = packet["rawSnapshots"]
            [child] = snapshot["children"]
            if (child["pid"] == snapshot["coordinatorPid"] or child["raw"]["pid"] != child["pid"]
                    or child["raw"]["ppid"] != snapshot["coordinatorPid"] or child["exit"] != {"code": 0, "signal": None}):
                raise ValueError("Regex SDK execution lacks a successful separately owned child")
            same(_json(child["stdout"]), {"result": sdk, "raw": child["raw"]})
            evidence.update(nativeCalls=len(x["observations"][0]["calls"]), sdkRawSha256=packet["sha256"],
                sdkStdoutSha256=hashlib.sha256(child["stdout"].encode()).hexdigest(),
                sdkStderrSha256=hashlib.sha256(child["stderr"].encode()).hexdigest(), exactCompilerCompared=True)
        results.append(evidence)
    return results
