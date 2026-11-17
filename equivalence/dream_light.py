"""Frozen real-workspace inputs for the two original light-dreaming conditions."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

OPERATION = "dream-light-runtime"
POINTS = ("dreaming.light.outcomes", "dreaming.light.boundaries")
NOW = 1_767_268_800_000  # 2026-01-01 12:00 UTC
TODAY = "memory/2026-01-01.md"
NOTE = "memory/2025-12-21-notes.md"
RECALL = "memory/.dreams/short-term-recall.json"
SIGNALS = "memory/.dreams/phase-signals.json"
ISO = "2026-01-01T09:00:00.000Z"
POLICY = (
    "Run real light dreaming with the same files, source input, operation times and options. "
    "Compare the ordered completed/failed phase receipts and complete published report bytes, "
    "source text, canonical phase-signal entries, staged keys and retained recall state at each "
    "boundary. Retain all raw workspace files, events, stdout, stderr and failures. Only the "
    "declared owned workspace path and engine-specific file observation metadata are diagnostic."
)
DRIVER_SCOPE = (
    "Single local UTC workspace, original runDreamingSweepPhases with light enabled and REM "
    "disabled, unconfigured narrative subagent, actual daily ingestion and local filesystem "
    "checks/publication. Candidate signals, an empty session corpus, inline/separate reports, "
    "source deletion and re-opened sweeps are in scope. Remote narrative delivery, live provider "
    "selection, session-corpus admission policy and concurrent forget orchestration are separate contracts."
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode()


def _entry(key, text, *, count=1, when=ISO, path=NOTE, line=1, score=0.75, **fields):
    return {"key": key, "path": path, "startLine": line, "endLine": line,
            "source": "memory", "snippet": text, "recallCount": count, "dailyCount": 0,
            "groundedCount": 0, "totalScore": score * count, "maxScore": score,
            "firstRecalledAt": when, "lastRecalledAt": when, "queryHashes": [key],
            "recallDays": [], "conceptTags": [key], **fields}


def _case(name, entries, *, files=None, signals=None, operations=None, limit=3, mode="separate"):
    files = dict(files or {})
    if entries:
        files[RECALL] = json.dumps({"version": 1, "updatedAt": ISO, "entries":
            {entry["key"]: entry for entry in entries}}, ensure_ascii=False)
    if signals:
        files[SIGNALS] = json.dumps({"version": 1, "updatedAt": ISO, "entries": signals})
    return {"id": "dream-light-" + name, "operation": OPERATION,
            "input": {"files": files, "options": {"enabled": True, "timezone": "UTC",
                "lookbackDays": 2, "limit": limit, "dedupeSimilarity": 0.7, "storageMode": mode},
                "operations": operations or [{"op": "light", "nowMs": NOW}]},
            "covers": list(POINTS), "comparisonPolicy": POLICY, "driverScope": DRIVER_SCOPE}


def _frozen_cases():
    note = "# Field notes\ncedar amber forestry\ncedar amber forestry archive\nshoreline wave study\n"
    files = {NOTE: note}
    cedar = _entry("cedar", "cedar amber forestry", count=3, line=2)
    duplicate = _entry("archive", "cedar amber forestry archive", count=2, line=3)
    wave = _entry("wave", "shoreline wave study", line=4)
    return [
        _case("daily-ingestion", [], files={TODAY: "# Field work\n\n- Copper sample stayed dry for three cold nights.\n- Dragonfly counts rose after the warm rain.\n"}, mode="both"),
        _case("group-and-order", [duplicate, wave, cedar], files=files, limit=2),
        _case("diary-priority", [cedar, wave], files={**files, "DREAMS.md":
            "# Dream Diary\n\n<!-- openclaw:dreaming:diary:start -->\n---\n\n*Wednesday*\ncedar amber forestry.\n<!-- openclaw:dreaming:diary:end -->\n"}, limit=1),
        _case("freshness", [cedar, wave, _entry("expired", "old sample", when="2025-12-16T09:00:00.000Z")],
            files=files, signals={"cedar": {"key": "cedar", "lightHits": 1, "remHits": 0, "lastLightAt": ISO},
                                  "wave": {"key": "wave", "lightHits": 2, "remHits": 1,
                                           "lastLightAt": "2025-12-31T09:00:00.000Z"}},
            operations=[{"op": "light", "nowMs": NOW}, {"op": "light", "nowMs": NOW + 1000}]),
        _case("missing-and-tainted", [cedar, wave, _entry("absent", "removed item", path="memory/2025-12-19-removed.md"),
            _entry("blocked", "blocked item", provenance={"originClass": "untrusted", "sessionKind": "unknown",
                                                          "observedAt": NOW - 1000})],
            files=files, operations=[{"op": "light", "nowMs": NOW}, {"op": "remove", "path": NOTE},
                                     {"op": "light", "nowMs": NOW + 1000}]),
        _case("empty-inline", [], files={TODAY: ""}, mode="both"),
        _case("disabled-limit", [deepcopy(cedar)], files=files, mode="both", limit=0),
    ]


def input_contract():
    return {case["id"]: hashlib.sha256(canonical(case)).hexdigest() for case in _frozen_cases()}

# The original seven complete fixture definitions were sealed before either runtime was invoked.
DEFINITION_SHA256 = "57124a71a7c5b387e7b872ed45f0b7f705432cbbcde59a496619cb6cc6031904"


def build_cases():
    rows = _frozen_cases()
    if hashlib.sha256(canonical(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("Light dreaming fixture definitions changed")
    for row in rows:
        row["requirement"] = "dreaming.light"
        row["normalizationPolicy"] = row.pop("comparisonPolicy")
    return rows


def validate_case(case):
    rows = {row["id"]: row for row in build_cases()}
    expected = rows.get(case.get("id"))
    if expected is None or canonical({key: case.get(key) for key in expected}) != canonical(expected):
        raise ValueError("Light dreaming requires a frozen case and both original points")


def members(cases):
    return [case for case in cases if case.get("requirement") == "dreaming.light" or
            case.get("operation") == OPERATION or set(case.get("covers", ())).intersection(POINTS)]


def validate_registration(cases):
    family = members(cases)
    if family:
        if [row["id"] for row in family] != [row["id"] for row in build_cases()]:
            raise ValueError("Both light dreaming points require the full ordered family")
        for row in family:
            validate_case(row)


def family_complete(rows):
    family = members(rows)
    if not family:
        return False
    try:
        validate_registration(rows)
    except (KeyError, TypeError, ValueError):
        return False
    return all(row["status"] == "matched" and row.get("runtimeEvidenceValidated") is True for row in family)


def profile_for(case, node):
    from equivalence.model_runtime_authority import prepare_model_node_authority

    validate_case(case)
    return {"caseId": case["id"], "operation": OPERATION, "nodeRuntime": prepare_model_node_authority(node),
            "inputSha256": hashlib.sha256(canonical(case["input"])).hexdigest()}


def validate_profile(profile):
    from equivalence.model_runtime_authority import validate_model_node_authority

    if not isinstance(profile, dict) or set(profile) != {"caseId", "inputSha256", "operation", "nodeRuntime"}:
        raise ValueError("Incomplete light dreaming authority")
    ids = {row["id"]: hashlib.sha256(canonical(row["input"])).hexdigest() for row in build_cases()}
    if (profile["operation"] != OPERATION or profile["caseId"] not in ids
            or profile["inputSha256"] != ids[profile["caseId"]]):
        raise ValueError("Light dreaming requires one frozen input")
    validate_model_node_authority(profile["nodeRuntime"])
    return deepcopy(profile)
