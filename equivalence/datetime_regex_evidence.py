"""Observe the real boundary calls and forbid substituting empty comparisons."""
from __future__ import annotations

import hashlib
import json

from equivalence.datetime_regex_family import CLOCK, CLOCK_OWNERS, wire


def same(actual, expected):
    if wire(actual) != wire(expected):
        raise ValueError("A date/regex caller, retained input or complete output changed")


def validate_clock(case, owners, sources, native, sdk):
    same(owners, CLOCK_OWNERS)
    if not set(owners) <= {item["path"] for item in sources}:
        raise ValueError("Both original date/time owners must be imported and hashed")
    value = case["input"]
    for public in (native, sdk):
        same(set(public) == {"hostTimezone", "hostTimeFormat", "instants"}, True)
        same([item["iso"] for item in public["instants"]], [item["iso"] for item in value["instants"]])
        for entry in public["instants"]:
            same(set(entry) == {"iso", "timestampMs", "resolved", "twelveHour", "twentyFourHour", "refreshed"}, True)
    same([native["hostTimezone"], native["hostTimeFormat"]], [value["hostTimezone"], value["hostTimeFormat"]])
    for entry in native["instants"]:
        if not entry["refreshed"].endswith(entry["resolved"]["timeLine"]) or value["text"] in entry["refreshed"]:
            raise ValueError("The real clock did not replace the prior prompt stamp")
    times = [entry["twentyFourHour"].split(" - ")[-1] for entry in native["instants"]]
    expected = (["01:59", "03:00", "01:30", "01:30"] if case["id"].endswith("dst-jump-and-fold")
                else ["23:59", "00:00", "22:30", "02:00"])
    same(times, expected)


def validate_rank(case, native, sdk, native_rows, sdk_rows):
    same(len(native_rows), 1)
    same(len(sdk_rows), 1)
    value = case["input"]
    for capture, public in [(native_rows[0], native), (sdk_rows[0], sdk)]:
        same(capture["input"], value)
        same(capture["output"], public)
    calls = sdk_rows[0]["calls"]
    same([call["operation"] for call in calls], ["write_recall_store", "seed_phase_file"] +
         ["rank_short_term_promotion_candidates"] * len(value["queries"]))
    for actual, request in zip(calls[2:], value["queries"], strict=True):
        same(actual["options"], request["options"])
    for snapshot in sdk_rows[0]["snapshots"]:
        [record] = [r for r in snapshot["files"] if r["path"] == "workspace/memory/.dreams/short-term-recall.json"]
        raw = bytes.fromhex(record["hex"])
        same(len(raw), record["stat"]["size"])
        same(json.loads(raw), calls[0]["postCallArguments"])
    found = [{r["key"]: r["ageDays"] for r in q["candidates"]} for q in native["queries"]]
    same(sorted(found[0]), sorted(value["store"]["entries"]))
    same(sorted(found[1]), ["east", "invalid", "utc", "west"])
    same(sorted(found[2]), ["invalid"])
    same([found[0][k] for k in ("utc", "east", "west")], [1, 1, 1])


def validate_regex(case, native, sdk, execution, sdk_rows):
    value = case["input"]
    same(execution["requestCase"], case)
    [frame] = execution["observations"]
    same(frame["input"], value)
    same(frame["output"], native)
    [sdk_row] = sdk_rows
    [child] = sdk_row["children"]
    same(child["request"], {"operation": case["operation"], "input": value})
    same(child["raw"]["output"], sdk)
    if native["result"]["explicitSensitiveText"] == value["text"] or native["result"]["directCompiler"]["accepted"] is not True:
        raise ValueError("The real configured regex must compile and change the complete synthetic input text")
    request = child["requestJson"].encode("ascii")
    same(child["requestSha256"], hashlib.sha256(request).hexdigest())


def validate_pair(case, report, native, sdk):
    cid = case["id"]
    if case["operation"] == CLOCK:
        return validate_clock(case, report["datetimeSourceImports"][cid], report["sources"], native, sdk)
    diagnostics = {r["side"]: r["rawSnapshots"] for r in report["runtimeDiagnostics"] if r["id"] == cid}
    if case["operation"] == "promotion-ranking-runtime":
        return validate_rank(case, native, sdk, diagnostics["native"], diagnostics["python"])
    [data] = [r for r in report["sourcePolicyDiagnostics"] if r["id"] == cid]
    return validate_regex(case, native, sdk, data["sourceExecution"], diagnostics["python"])
