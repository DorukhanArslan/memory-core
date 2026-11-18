"""Frozen host-level OpenClaw memory-flush configuration and preparation scenarios."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

OPERATION = "flush-plan-target-runtime"
POINTS = ("flush.plan-target.outcomes",)
BOUNDARY = "flush.plan-target.boundaries"
DRAFT_SHA256 = "355843d09b108783334491b460701fbc867c80a41938239267728422dfe4a656"
LEGACY_SHA256 = "dc23c90f17528f6e93699bcf884a61d234dd7a0a25fc535ce8be4395d72243cd"
NOW = 1_767_305_100_000  # UTC near Istanbul's next local day.
PROVIDER = "fixture-memory-model"
SCOPE = (
    "The actual automatic host flush invokes the registered memory plan owner, resolves the "
    "model and prepares the target in an owned workspace. A deterministic local model returns "
    "the declared result. OS links and special file policies retain their documented SDK differences."
)
POLICY = (
    "Compare every resolved plan field, full plan prompts, validated target, exact observed model "
    "routes and attempts, admission outcome and surviving workspace file bytes. Preserve all "
    "original errors, calls, process streams and engine-only model context as raw evidence."
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def definitions():
    base = {"nowMs": NOW, "timezone": "UTC", "hostTimezone": "UTC", "formats": {"sdk": "12", "nativeLocale": "en_US.UTF-8"},
            "contextWindowTokens": 200000, "flush": {}, "primary": "scripted-model", "fallbacks": ["backup"],
            "clock": "fixed", "files": {}, "directories": [], "responses": {"scripted-model": "NO_REPLY",
            "backup": "NO_REPLY", "maintenance": "NO_REPLY"}}

    def case(name, **settings):
        request = deepcopy(base)
        request.update(settings)
        return {"id": "flush-plan-target-" + name, "operation": OPERATION, "requirement": "flush.plan-target",
                "covers": [*POINTS, BOUNDARY], "input": request, "driverScope": SCOPE, "normalizationPolicy": POLICY}

    return [
        case("default-istanbul-midnight", timezone="Europe/Istanbul"),
        case("los-angeles-preserve", timezone="America/Los_Angeles",
             files={"memory/2026-01-01.md": "Prior note – café\n", "MEMORY.md": "# Durable memory\n"}),
        case("disabled", flush={"enabled": False, "model": PROVIDER + "/maintenance"}),
        case("small-window", contextWindowTokens=6000, flush={"softThresholdTokens": 99999,
             "forceFlushTranscriptBytes": "3mb", "prompt": "retired user text", "systemPrompt": "retired system text"}),
        case("unqualified-model", flush={"model": " maintenance "}),
        case("qualified-model", flush={"model": " " + PROVIDER + "/maintenance "}),
        case("exact-model-failure", flush={"model": PROVIDER + "/maintenance"},
             responses={"scripted-model": "NO_REPLY", "backup": "NO_REPLY", "maintenance": "unavailable"}),
        case("ordinary-model-fallback", responses={"scripted-model": "unavailable", "backup": "NO_REPLY"}),
        case("blank-model-and-zone-fallback", timezone="Invalid/Zone", flush={"model": "   "}),
        case("parent-is-regular-file", files={"memory": "existing ordinary file\n"}),
        case("target-is-directory", directories=["memory/2026-01-01.md"]),
        case("short-year", nowMs=-59_042_995_200_000),
        case("expanded-year", nowMs=253_402_300_800_000),
    ]


def build_cases():
    rows = definitions()
    if hashlib.sha256(canonical(rows)).hexdigest() != DRAFT_SHA256:
        raise ValueError("The original automatic flush plan inputs changed")
    for row in rows:
        row["covers"] = list(POINTS)
        row["normalizationPolicy"] += (
            " The plan owner supplies both complete prompts. The model fallback owner supplies the "
            "ordered candidate attempts. Retry calls within one candidate and complete provider "
            "envelopes remain raw. Read every seeded path and every changed workspace entry after "
            "maintenance and keep full before/after snapshots, including foreground provisioning."
        )
    return rows


def validate_case(case):
    expected = next((row for row in build_cases() if row["id"] == case.get("id")), None)
    if expected is None or canonical({key: case.get(key) for key in expected}) != canonical(expected):
        raise ValueError("Memory flush preparation must use an exact registered host input")


def members(cases):
    return [r for r in cases if r.get("operation") == OPERATION or
            set(r.get("covers", ())).intersection((*POINTS, BOUNDARY))]


def validate_registration(cases):
    family = members(cases)
    legacy = [r for r in cases if r.get("requirement") == "flush.plan-target" and r.get("operation") != OPERATION]
    if family and legacy:
        definitions_keys = ("id", "operation", "input", "requirement", "covers", "driverScope", "normalizationPolicy", "declaredDeviation")
        entries = [{key: row[key] for key in definitions_keys if key in row} for row in legacy]
        if hashlib.sha256(canonical(entries)).hexdigest() != LEGACY_SHA256:
            raise ValueError("The original 92 flush contract cases must retain their definitions and zero credit")
    if family:
        if [r["id"] for r in family] != [r["id"] for r in build_cases()]:
            raise ValueError("Flush plan outcomes require the complete frozen host family")
        for row in family:
            validate_case(row)


def family_complete(rows):
    try:
        validate_registration(rows)
        return bool(members(rows)) and all(r.get("status") == "matched" and r.get("runtimeEvidenceValidated") is True
                                           for r in members(rows))
    except (TypeError, KeyError, ValueError):
        return False


def profile_for(case, node):
    from equivalence.model_runtime_authority import prepare_model_node_authority

    validate_case(case)
    return {"caseId": case["id"], "operation": OPERATION, "inputSha256": hashlib.sha256(canonical(case["input"])).hexdigest(),
            "nodeRuntime": prepare_model_node_authority(node)}


def validate_profile(profile):
    from equivalence.model_runtime_authority import validate_model_node_authority

    if not isinstance(profile, dict) or set(profile) != {"caseId", "operation", "inputSha256", "nodeRuntime"}:
        raise ValueError("Incomplete flush plan authority")
    expected = {row["id"]: hashlib.sha256(canonical(row["input"])).hexdigest() for row in build_cases()}
    if profile["operation"] != OPERATION or profile["caseId"] not in expected or profile["inputSha256"] != expected[profile["caseId"]]:
        raise ValueError("The flush model capability must use one frozen input")
    validate_model_node_authority(profile["nodeRuntime"])
    return deepcopy(profile)


def published_workspace(seed, before, after):
    """Reopen every literal fixture entry and every path touched by maintenance.

    Preserve complete trees separately. A full SDK foreground opens a provisioned
    agent workspace before maintenance while the native test enters after the turn.
    """
    names = set(seed) | {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    return {name: after.get(name) for name in sorted(names)}
