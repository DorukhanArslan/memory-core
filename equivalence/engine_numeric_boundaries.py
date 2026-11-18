"""Frozen numeric inputs for the original flush planner and the production SDK.

Binary64 literals transport values which JSON itself cannot round-trip. Decoding
happens only at the external call boundary. No expected planner result is stored.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct

from equivalence.flush_contract import NOW_MS, run_flush_contract

OPERATION = "engine-numeric-boundaries"
POINTS = ["engine.numeric-boundaries.outcomes", "engine.numeric-boundaries.boundaries"]
FIELDS = ("softThresholdTokens", "forceFlushTranscriptBytes", "contextWindowTokens")
POLICY = (
    "Compare the whole returned memory flush plan, its numeric fields' exact binary64 encodings, "
    "the numeric fields' model JSON scalar text, and the observed type, value bits and model JSON "
    "of the decoded input. All probes use a named model, UTC, and a fixed clock. The original "
    "host detects its 12-hour display and the SDK takes that display as input. No numeric tolerance."
)
SCOPE = (
    "The original pinned buildMemoryFlushPlan and public SDK build_memory_flush_plan_from_config "
    "own the configuration decisions. The original JSON.stringify and SDK model JSON renderer "
    "serialize actual input scalars and actual returned fields. These plan probes and the separate "
    "exact promotion score gates qualify both numeric boundary conditions together."
)


def _bits(hex_digits):
    return {"binary64": hex_digits}


def _probes(values, fields):
    return [{"label": f"{field}/{name}", "field": field, "value": value}
            for field in fields for name, value in values]


def build_numeric_flush_cases():
    ieee = [("positive-zero", _bits("0000000000000000")),
            ("negative-zero", _bits("8000000000000000")),
            ("least-positive", _bits("0000000000000001")),
            ("least-negative", _bits("8000000000000001")),
            ("nan", _bits("7ff8000000000000")),
            ("infinity", _bits("7ff0000000000000")),
            ("negative-infinity", _bits("fff0000000000000"))]
    limits = [("safe-max", _bits("433fffffffffffff")),
              ("safe-max-plus-one", _bits("4340000000000000")),
              ("next-representable", _bits("4340000000000001")),
              ("exponential-form", _bits("444b1ae4d6e2ef50"))]
    coercion = [("true", True), ("false", False), ("null", None),
                ("fraction", 2.75), ("negative-fraction", -0.125),
                ("text-number", "2.75"), ("text-unit", "1.5kb"),
                ("text-whitespace", "\ufeff2.5b\u00a0"), ("unsafe-decimal-text", "9007199254740993"),
                ("binary64-rounding", "9007199254740991.5"), ("text-invalid", "1e3kb")]
    groups = [("ieee", ieee), ("integer-limits", limits), ("coercion", coercion)]
    return [{"id": "numeric-flush-" + name, "requirement": "engine.numeric-boundaries",
             "operation": OPERATION, "covers": list(POINTS), "normalizationPolicy": POLICY,
             "driverScope": SCOPE, "input": {"kind": "numeric-flush", "nowMs": NOW_MS,
                "hostTimeFormat": "12", "probes": _probes(values, FIELDS)}}
            for name, values in groups]


def decode_numeric_input(value):
    if not isinstance(value, dict):
        return value
    if set(value) != {"binary64"} or not isinstance(value["binary64"], str) or not re.fullmatch(
            "[0-9a-f]{16}", value["binary64"]):
        raise ValueError("Expected one exact eight-byte big-endian binary64 input")
    return struct.unpack(">d", bytes.fromhex(value["binary64"]))[0]


def _observe(value):
    from memory_core.model_prompt import serialize_model_tool_json

    if type(value) in (int, float):
        return {"type": "number", "bits": struct.pack(">d", value).hex(),
                "json": serialize_model_tool_json(value)}
    kind = {bool: "boolean", str: "string", type(None): "null"}[type(value)]
    return {"type": kind, "json": serialize_model_tool_json(value)}


def run_engine_numeric_boundaries(arguments):
    if arguments["kind"] != "numeric-flush":
        raise ValueError("Expected a numeric flush planner request")
    output = []
    for probe in arguments["probes"]:
        field = probe["field"]
        if field not in FIELDS:
            raise ValueError("Unknown numeric flush option")
        value = decode_numeric_input(probe["value"])
        options = {"model": "numeric-plan-model"}
        params = {"cfg": {"agents": {"defaults": {"userTimezone": "UTC",
                  "compaction": {"memoryFlush": options}}}}, "nowMs": arguments["nowMs"]}
        target = params if field == "contextWindowTokens" else options
        target[field] = value
        returned = run_flush_contract({"kind": "plan", "params": params,
            "fallbackNowMs": arguments["nowMs"], "hostTimeFormat": arguments["hostTimeFormat"]})
        output.append({"label": probe["label"], "input": _observe(target[field]), "returned": returned,
                       "numbers": {key: _observe(item) for key, item in returned["plan"].items()
                                   if type(item) in (float, int)}})
    return output


# Common inputs fixed before either language was run. The comparison harness
# binds the separate original ranking groups before admitting any score.
FLUSH_INPUT_HASHES = {
    "numeric-flush-ieee": "d41072ba368a5f335e31c1fa8cbd70174a9d2f1b987350abc803fb00ddd84d10",
    "numeric-flush-integer-limits": "3d36e68f15c7d2a2b2f647c3deb5b6f7ed5dc59657fa8531e6d855066c34b4c4",
    "numeric-flush-coercion": "a4d4d162ec87f3d2c44f915f9f9c1b7b0af671786e2effb3ac9850619a043ca2",
}


def _scalar_receipt(observed, actual, *, before_json=False):
    numeric = type(actual) in (int, float)
    expected_type = "number" if numeric else {type(None): "null", str: "string", bool: "boolean"}[type(actual)]
    keys = {"type", "json", "bits"} if numeric else {"type", "json"}
    if (not isinstance(observed, dict) or set(observed) != keys
            or observed["type"] != expected_type or not isinstance(observed["json"], str)):
        raise ValueError("Numeric observation lost the declared input or result type")
    if numeric:
        bits = observed["bits"]
        if not isinstance(bits, str) or not re.fullmatch("[0-9a-f]{16}", bits):
            raise ValueError("Numeric observation lost its exact binary64 representation")
        from_bits = struct.unpack(">d", bytes.fromhex(bits))[0]
        if before_json or actual != 0:
            if bits != struct.pack(">d", actual).hex():
                raise ValueError("Number bits disagree with the actual input or returned field")
        elif from_bits != 0:
            # The stdout JSON boundary does not preserve the sign of zero. The
            # observations from both engines still compare these original bits.
            raise ValueError("Returned zero has nonzero bits")
    decoded = json.loads(observed["json"])
    if numeric:
        if math.isfinite(actual):
            if type(decoded) not in (float, int) or decoded != actual:
                raise ValueError("JSON scalar disagrees with the actual numeric value")
        elif observed["json"] != "null":
            raise ValueError("A nonfinite model JSON input must serialize to null")
    elif type(decoded) is not type(actual) or decoded != actual:
        raise ValueError("JSON scalar disagrees with the actual nonnumeric value")


def validate_numeric_flush(case, result):
    """Bind each whole observed plan and scalar witness to its original probe."""
    encoded = json.dumps(case["input"], sort_keys=True, ensure_ascii=True,
                         allow_nan=False, separators=(",", ":")).encode("ascii")
    if (hashlib.sha256(encoded).hexdigest() != FLUSH_INPUT_HASHES.get(case["id"])
            or case["operation"] != OPERATION or case["covers"] != POINTS
            or case["normalizationPolicy"] != POLICY or case["driverScope"] != SCOPE):
        raise ValueError("Numeric flush case does not match its frozen definition")
    probes = case["input"]["probes"]
    if not isinstance(result, list) or len(result) != len(probes):
        raise ValueError("Numeric flush planner lost observations")
    numeric_keys = {"softThresholdTokens", "forceFlushTranscriptBytes", "reserveTokensFloor"}
    text_keys = {"model", "prompt", "systemPrompt", "relativePath"}
    for probe, observed in zip(probes, result, strict=True):
        if set(observed) != {"label", "input", "returned", "numbers"} or observed["label"] != probe["label"]:
            raise ValueError("Numeric flush observations were replaced or reordered")
        _scalar_receipt(observed["input"], decode_numeric_input(probe["value"]), before_json=True)
        returned = observed["returned"]
        if set(returned) != {"hostTimeFormat", "plan"} or returned["hostTimeFormat"] not in ("12", "24"):
            raise ValueError("Missing original host clock or complete planner result")
        plan = returned["plan"]
        if (set(plan) != numeric_keys | text_keys or set(observed["numbers"]) != numeric_keys
                or any(type(plan[key]) not in (float, int) for key in numeric_keys)
                or any(not isinstance(plan[key], str) for key in text_keys)):
            raise ValueError("Missing fields of the complete returned flush plan")
        for key in numeric_keys:
            _scalar_receipt(observed["numbers"][key], plan[key])
