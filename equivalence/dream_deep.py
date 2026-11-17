"""Literal turns for the complete managed deep phase, including its upstream phases."""
from copy import deepcopy
import hashlib
import json

from equivalence.dream_rem import NOW, RECALL, SIGNALS, canonical

OPERATION = "dream-deep-runtime"
POINTS = ("dreaming.deep.outcomes", "dreaming.deep.boundaries")
TOKEN = "__openclaw_memory_core_short_term_promotion_dream__"
NOTE = "memory/2025-11-01-observatory.md"
AT = "2026-01-01T10:00:00.000Z"
FACT = "A brass telescope is installed by the east dome."
POLICY = ("Compare original managed callback results, phase event order and payloads, exact model requests, "
          "summary counts and all workspace Markdown, normalized recall, phase signals, saved preimages "
          "and source ownership after each turn. Reopen physical captures of the SDK and the pinned release. "
          "Only fixture-owned roots and equivalent storage carriers vary.")
SCOPE = ("Registered memory-core before_agent_reply hook, both managed cron and heartbeat input, original "
         "light, REM, repair, rank, apply, deep report and diary owners. One local UTC memory workspace, "
         "an agent roster, a real source file, injected model responses and committed origin rows.")


def _entry(key, snippet, line, *, owner="owner", path=NOTE, count=4):
    return {"key": key, "path": path, "startLine": line, "endLine": line, "source": "memory",
            "snippet": snippet, "recallCount": count, "dailyCount": 0, "groundedCount": 0,
            "totalScore": 0.8 * count, "maxScore": 0.8, "firstRecalledAt": AT, "lastRecalledAt": AT,
            "queryHashes": ["one", "two"], "userQueryHashes": ["one", "two"],
            "recallDays": [], "conceptTags": ["astronomy"],
            "provenance": {"originClass": owner, "sessionKind": "interactive", "observedAt": NOW - 60_000}}


def _turn(trigger="cron", body=TOKEN, *, queued=False, now=NOW):
    return {"trigger": trigger, "cleanedBody": body, "sessionKey": "agent:main:main:heartbeat",
            "queued": queued, "agentId": "main", "nowMs": now}


def _case(name, records, *, phases=False, provider=None, turns=None, files=None, stages=None, limit=5, enabled=True):
    seeds = {NOTE: "# Notebook\n\n" + FACT + "\nThe old photograph was moved to the south attic.\n",
             RECALL: json.dumps({"version": 1, "updatedAt": AT, "entries": {e["key"]: e for e in records}}),
             **(files or {})}
    if stages:
        seeds[SIGNALS] = json.dumps({"version": 1, "updatedAt": AT, "entries": stages})
    origin_seeds = [{"entryKey": key, "agentId": "main", "sessionId": "field-notes",
                     "sessionKey": "agent:main:field-notes", "originClass": "agent",
                     "observedAt": NOW - 60_000} for key in ("dome", "unreferenced")] if provider else []
    opts = {"enabled": enabled, "timezone": "UTC", "storageMode": "separate", "light": phases, "rem": phases,
            "minScore": 0, "minRecallCount": 1, "minUniqueQueries": 1, "limit": limit}
    return {"id": f"dream-deep-{name}", "requirement": "dreaming.deep", "operation": OPERATION, "covers": list(POINTS),
            "input": {"files": seeds, "options": opts, "provider": provider, "originSeeds": origin_seeds, "turns": turns or [_turn()]},
            "driverScope": SCOPE, "normalizationPolicy": POLICY}


def _cases():
    dome = _entry("dome", FACT, 3)
    rejected = _entry("private-note", "The old photograph was moved to the south attic.", 4, owner="untrusted")
    gone = _entry("gone", "A note on an absent page.", 1, path="memory/2025-11-02-gone.md")
    prior = "# Personal notes\n\n- The compass points to the old pier.\n"
    plan = {"operations": [{"candidateKey": "dome", "action": "added", "priorEntries": []}]}
    return [
        _case("hook-admission", [dome], phases=True, limit=0,
              turns=[_turn("user"), _turn("heartbeat"), _turn("cron", "quoted " + TOKEN),
                     _turn("cron", "[cron:night] " + TOKEN)]),
        _case("disabled", [dome], enabled=False),
        _case("phase-composition", [dome, rejected, gone], phases=True,
              stages={"gone": {"key": "gone", "lightHits": 1, "remHits": 0, "lastLightAt": AT}},
              turns=[_turn(), _turn(now=NOW + 1000)]),
        _case("consolidation", [dome], files={"MEMORY.md": prior}, turns=[_turn("heartbeat", queued=True)],
              provider=[{"text": json.dumps(plan)}, {"text": "The brass tube gathered the blue of dawn."}]),
        _case("invalid-plan-diary-fallback", [dome], files={"MEMORY.md": prior}, turns=[_turn("heartbeat", queued=True)],
              provider=[{"text": "not a consolidation plan"}, {"text": " "}]),
        _case("cron-pending-narrative", [dome], files={"MEMORY.md": prior},
              provider=[{"text": json.dumps(plan)}, {"text": "At dusk I looked through a brass circle."}]),
        _case("report-publication-failure", [dome], files={"DREAMS.md/keep.txt": "Existing directory"}),
    ]


def build_cases():
    rows = _cases()
    if hashlib.sha256(canonical(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("Managed deep dreaming fixture definitions changed")
    return rows


def validate_case(case):
    planned = next((r for r in build_cases() if r["id"] == case.get("id")), None)
    if planned is None or canonical(planned) != canonical({key: case.get(key) for key in planned}):
        raise ValueError("Managed deep dreaming requires the frozen case")


def members(rows):
    return [r for r in rows if r.get("requirement") == "dreaming.deep" or r.get("operation") == OPERATION
            or set(r.get("covers", ())).intersection(POINTS)]


def validate_registration(rows):
    batch = members(rows)
    if batch:
        if [r["id"] for r in batch] != [r["id"] for r in build_cases()]:
            raise ValueError("Both deep dreaming points require all registered managed turns")
        for row in batch:
            validate_case(row)


def family_complete(rows):
    batch = members(rows)
    if not batch:
        return False
    try:
        validate_registration(rows)
    except (KeyError, TypeError, ValueError):
        return False
    return all(r["status"] == "matched" and r.get("runtimeEvidenceValidated") is True for r in batch)

DEFINITION_SHA256 = "d9efba526c91ecbb87a1bd49819ec4f251595de8165fc88fc61a0b07b08506d1"


def profile_for(case, node):
    from equivalence.model_runtime_authority import prepare_model_node_authority

    validate_case(case)
    return {"caseId": case["id"], "operation": OPERATION, "nodeRuntime": prepare_model_node_authority(node),
            "inputSha256": hashlib.sha256(canonical(case["input"])).hexdigest()}


def validate_profile(profile):
    from equivalence.model_runtime_authority import validate_model_node_authority

    if not isinstance(profile, dict) or set(profile) != {"caseId", "inputSha256", "operation", "nodeRuntime"}:
        raise ValueError("Incomplete Deep dreaming authority")
    ids = {row["id"]: hashlib.sha256(canonical(row["input"])).hexdigest() for row in build_cases()}
    if (profile["operation"] != OPERATION or profile["caseId"] not in ids
            or profile["inputSha256"] != ids[profile["caseId"]]):
        raise ValueError("Deep dreaming requires one frozen input")
    validate_model_node_authority(profile["nodeRuntime"])
    return deepcopy(profile)
