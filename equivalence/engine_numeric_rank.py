"""Observe exact binary64 threshold decisions through both persisted ranking owners."""

from copy import deepcopy
import hashlib
import json
import math

from equivalence.promotion_ranking_fixtures import NOW_ISO, NOW_MS, RELEVANCE_ONLY, _entry, _query
from equivalence.search_contract import _same_json

RANK_ID = "engine-numeric-persisted-rank-adjacent-scores"
RANK_POINTS = ("engine.numeric-boundaries.outcomes", "engine.numeric-boundaries.boundaries")
RANK_SHA256 = "131ec42e890f6c024b3569182e3a0a106d2ae90b7e6203e377d2f7f3c6d7c3d3"


def build_rank_cases():
    center = 0.625
    lower = math.nextafter(center, -math.inf)
    upper = math.nextafter(center, math.inf)
    entries = {}
    for name, score in (("center", center), ("lower", lower), ("upper", upper)):
        key = f"numeric-{name}"
        entries[key] = _entry(key, path=f"memory/2026-04-01-{name}.md", recallCount=1,
                              totalScore=score, maxScore=score,
                              queryHashes=["one"], userQueryHashes=["one"], recallDays=["2026-04-03"])
    queries = [_query(name, minScore=score, weights=deepcopy(RELEVANCE_ONLY), limit=limit)
               for name, score, limit in (("all", lower, 3), ("equal", center, 3),
                                          ("upper", upper, 3), ("none", math.nextafter(upper, math.inf), 3),
                                          ("single", lower, 1))]
    return [{
        "id": RANK_ID,
        "requirement": "engine.numeric-boundaries",
        "operation": "promotion-ranking-runtime",
        "covers": list(RANK_POINTS),
        "input": {"kind": "promotion-ranking", "nowMs": NOW_MS,
                  "store": {"version": 1, "updatedAt": NOW_ISO, "entries": entries},
                  "phase": {"version": 1, "updatedAt": NOW_ISO, "entries": {}},
                  "queries": queries},
        "driverScope": "Three distinct binary64 recall scores survive genuine writes, reads and five "
                       "production ranking calls. Each query returns its complete ordered candidate list. "
                       "The last query caps the list after real score ordering.",
        "normalizationPolicy": "Compare complete before/after store reads and every public serialized "
                               "candidate field exactly with no numeric tolerance. Retain original "
                               "SQLite rows, SDK JSON file bytes and the individual rank call receipts.",
    }]


def validate_rank_case(case):
    encoded = json.dumps({key: case[key] for key in build_rank_cases()[0]}, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest() != RANK_SHA256:
        raise ValueError("The exact numeric ranking fixture, scope or coverage changed")


def _same(actual, expected, message):
    if not _same_json(actual, expected):
        raise ValueError(message)


def validate_numeric_rank(case, native_result, sdk_result, native_diagnostic, sdk_snapshots):
    """Authenticate actual public results and SDK persistence alongside the Native runtime validator."""
    validate_rank_case(case)
    if len(native_diagnostic) != 1 or len(sdk_snapshots) != 1:
        raise ValueError("Numeric ranking needs one genuine capture from each side")
    native, sdk = native_diagnostic[0], sdk_snapshots[0]
    value = case["input"]
    for raw, public in ((native, native_result), (sdk, sdk_result)):
        _same(raw["input"], value, "Numeric rank used another literal store or query")
        _same(raw["output"], public, "Numeric rank lost complete model-independent public output")

    _same([call["operation"] for call in sdk["calls"]], [
        "write_recall_store", "seed_phase_file", *(["rank_short_term_promotion_candidates"] * len(value["queries"]))
    ], "Numeric rank omitted a genuine write or rank call")
    _same(sdk["calls"][0]["arguments"], value["store"], "Persisted SDK input changed")
    _same(sdk["calls"][1]["arguments"], value["phase"], "Persisted SDK phase input changed")
    for query, call, actual in zip(value["queries"], sdk["calls"][2:], sdk_result["queries"], strict=True):
        _same(call["options"], query["options"], "Numeric rank received different thresholds")
        _same([query["label"], call["label"]], [actual["label"]] * 2, "Numeric query order changed")
        _same(call["result"], actual["candidates"], "SDK serialized candidate sequence was projected")
        _same([item["score"] for item in call["candidateDataclasses"]],
              [item["score"] for item in actual["candidates"]], "A rank score changed at serialization")

    for snapshot, label in zip(sdk["snapshots"], ("before", "after"), strict=True):
        _same(snapshot["phase"], label, "Missing complete SDK ranking snapshots")
        _same(snapshot["logical"], sdk_result[label], "The SDK store read changed")
        matches = [f for f in snapshot["files"] if f["path"] == "workspace/memory/.dreams/short-term-recall.json"]
        if len(matches) != 1:
            raise ValueError("Numeric scores require the genuine SDK persisted recall JSON")
        disk = bytes.fromhex(matches[0]["hex"])
        if len(disk) != matches[0]["stat"]["size"]:
            raise ValueError("Numeric score evidence lost SDK file bytes")
        _same(json.loads(disk), sdk["calls"][0]["postCallArguments"], "Persisted score serialization changed")

    # A comparison over empty/irrelevant stores must never verify a threshold.
    # Apply this reachability guard only to the genuine reference. SDK behavior
    # differences remain ordinary full-output mismatches, with both payloads.
    observed = native_result["queries"]
    expected_order = ["numeric-upper", "numeric-center", "numeric-lower"]
    _same([[row["key"] for row in query["candidates"]] for query in observed],
          [expected_order, expected_order[:2], expected_order[:1], [], expected_order[:1]],
          "Original runtime did not exercise the adjacent cuts and limited ordering")
    for candidate in observed[0]["candidates"]:
        _same(candidate["score"], value["store"]["entries"][candidate["key"]]["totalScore"],
              "The distinct original scores did not reach the ranking decision")
