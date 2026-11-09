"""Read-only structural replay for family development captures.

This is intentionally not an acceptance-credit validator. The journal observes
the selected main-thread IO/native methods and configured dreaming stores; it
does not observe every core event/origin database operation inside workers.
"""
from pathlib import Path
import json

from equivalence.get_contract import map_get_fixture_paths
from equivalence.promotion_apply_family import differences, validate_case


def replay_case(case, directory: Path):
    validate_case(case)
    evidence = directory / "evidence"
    raw = json.loads((evidence / "native-raw.json").read_text())
    if not isinstance(raw, list) or len(raw) != 1:
        raise ValueError("One genuine original apply observation is required")
    raw = raw[0]
    sdk = json.loads((evidence / "python-raw.json").read_text())
    stdout = json.loads((directory / "stdout.json").read_text())
    if (raw.get("input") != case["input"] or sdk.get("input") != case["input"]
            or raw.get("closed") is not True or stdout.get("id") != case["id"]
            or stdout.get("ok") is not True or stdout.get("result") != raw.get("output")):
        raise ValueError("Original input, output or settlement observations were changed")
    if differences(map_get_fixture_paths(sdk["unmappedOutput"], sdk["fixtureBase"]), sdk["output"]):
        raise ValueError("SDK public projection changed more than the owned fixture prefix")
    public = stdout["result"]
    if set(public) != {"provider", "before", "outcome", "after"}:
        raise ValueError("The complete public envelope is required")
    if "result" in public["outcome"] and set(public["outcome"]["result"]) != {
        "memoryPath", "applied", "appended", "reconciledExisting", "appliedCandidates",
        "rejectedCandidates", "compactedSections", "compactedDates",
    }:
        raise ValueError("An original apply result field was dropped")
    if [snapshot["label"] for snapshot in raw["snapshots"]] != ["before", "settlement-before-readback", "after-readback"]:
        raise ValueError("Settlement must precede additional original readbacks")
    if [snapshot["phase"] for snapshot in sdk["snapshots"]] != ["before-invocation", "actual-settlement-before-extra-readback"]:
        raise ValueError("SDK settlement must precede additional readbacks")
    for snapshot in raw["snapshots"]:
        for database in snapshot["physical"]:
            if database["schemaCount"] != len(database["schema"]):
                raise ValueError("An original physical schema was truncated")
            if any(table["rowCount"] != len(table["rows"]) for table in database["tables"]):
                raise ValueError("Original physical rows were truncated")
    starts, finishes = validate_receipts(raw["ioReceipts"])
    completion = case["input"].get("completion")
    for side in (raw, sdk):
        calls = side["completions"]
        if len(calls) != (1 if completion else 0):
            raise ValueError("The genuine host completion seam was not reached exactly as declared")
        if completion and [m["input"] for m in calls[0]["mutations"]] != completion["mutationsBeforeReturn"]:
            raise ValueError("A declared host mutation did not actually run")
    # Facts, not an inferred acquisition history from absent final lock files.
    observed = [{"call": row["sequence"], "settled": finishes[row["sequence"]]["sequence"],
                 "operation": row["operation"], "arguments": row["arguments"],
                 "result": finishes[row["sequence"]].get("result"),
                 **({"error": finishes[row["sequence"]]["error"]} if "error" in finishes[row["sequence"]] else {})}
                for row in starts.values() if row["operation"] in {"fs.rename", "store[short-term-recall].register",
                    "store[dreaming-memory-backups].register", "store[short-term-locks].compareAndApply"}]
    return {"id": case["id"], "journalCalls": len(starts), "observedPublicationCalls": observed,
            "differences": differences(public, sdk["output"]), "acceptancePointsAwarded": 0}


def validate_receipts(receipts):
    starts, finishes = {}, {}
    for index, row in enumerate(receipts, 1):
        if row["sequence"] != index:
            raise ValueError("The live journal lost its original sequence")
        if row["when"] == "before":
            starts[index] = row
        elif row["when"] == "after":
            call = row["call"]
            if (call not in starts or call in finishes or starts[call]["operation"] != row["operation"]
                    or int(starts[call]["monotonicNs"]) > int(row["monotonicNs"])):
                raise ValueError("A live return/error lost its actual invocation")
            finishes[call] = row
        else:
            raise ValueError("Unknown journal phase")
    if starts.keys() != finishes.keys():
        raise ValueError("An observed owner operation never settled")
    return starts, finishes
