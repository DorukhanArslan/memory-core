"""Frozen host-level OpenClaw memory-flush configuration and preparation scenarios."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json

OPERATION = "flush-plan-target-runtime"
POINTS = ("flush.plan-target.outcomes",)
BOUNDARY = "flush.plan-target.boundaries"
DRAFT_SHA256 = "355843d09b108783334491b460701fbc867c80a41938239267728422dfe4a656"
BOUNDARY_SHA256 = "c42563dd68dfae9f4c024034d67ecaa93a318759600a13a6a385df0782835c35"
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


def build_boundary_cases():
    """Additional host inputs appended after the previously measured catalog."""
    target = "memory/2026-01-01.md"
    text = "Campus note – first line.\nSecond line stays here.\n"
    # The adjacent windows straddle the effective reserve cap. The model gives
    # one silent response and performs no maintenance writes in these fixtures.
    controls = (
        ("two-names-read-only", 79999, {target: text}, [], {"target": target, "alias": "memory/campus-notes.md"}),
        ("single-name-read-only", 80000, {target: text}, [], None),
        ("occupied-daily-directory", 80000, {target + "/agenda.txt": "Existing meeting agenda.\n"}, [target], None),
    )
    base = definitions()[0]["input"]
    result = []
    for label, window, files, directories, alias in controls:
        request = deepcopy(base)
        request.update(timezone="UTC", contextWindowTokens=window, files=files, directories=directories,
                       flush={"softThresholdTokens": 60000, "prompt": "Unused custom user instruction.",
                              "systemPrompt": "Unused custom system instruction."})
        if alias:
            request["readOnlyAlias"] = alias
        result.append({"id": "flush-plan-boundary-" + label, "operation": OPERATION, "requirement": "flush.plan-target",
                       "covers": [BOUNDARY], "input": request,
                       "driverScope": "Automatic host flush after an ordinary user turn, with an existing daily note or occupied directory. Each admitted model returns NO_REPLY and requests no tool. The paired-name case gives one ordinary workspace note two directory entries within the same owned workspace.",
                       "normalizationPolicy": "Compare complete resolved plans including both prompts and reserve terms, selected model candidates, replies, finish state, and surviving note bytes. Verify the two names still address the same regular file at setup, model entry and after flush. Retain physical identities on each engine separately."})
    if hashlib.sha256(canonical(result)).hexdigest() != BOUNDARY_SHA256:
        raise ValueError("The read-only automatic flush preparation fixtures changed")
    return result


def validate_case(case):
    expected = next((row for row in [*build_cases(), *build_boundary_cases()] if row["id"] == case.get("id")), None)
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
        for row in family:
            validate_case(row)
        for definitions, points in ((build_cases(), POINTS), (build_boundary_cases(), (BOUNDARY,))):
            selected = [row for row in family if set(points).intersection(row["covers"])]
            if selected and [row["id"] for row in selected] != [row["id"] for row in definitions]:
                raise ValueError("Flush plan coverage requires the complete frozen host family for each condition")


def family_complete(rows):
    """The existing outcomes point depends on the original thirteen measurements."""
    try:
        validate_registration(rows)
        outcomes = [row for row in members(rows) if set(POINTS).intersection(row["covers"])]
        return len(outcomes) == len(build_cases()) and all(
            row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True for row in outcomes)
    except (TypeError, KeyError, ValueError):
        return False


def boundary_prerequisites_complete(rows):
    """Require the old host and helper observations from this same complete report."""
    from equivalence.harness import _same_json

    if not family_complete(rows):
        return False
    relevant = [row for row in rows if row.get("requirement") == "flush.plan-target" and BOUNDARY not in row["covers"]]
    return (len(relevant) == len(build_cases()) + 92 and all(row.get("status") == "matched" and
            (row["operation"] != OPERATION or row.get("referenceMode") == "authenticated-official-release") and
            "openclaw" in row and "python" in row and _same_json(row["openclaw"], row["python"]) for row in relevant))


def confirms_boundary(case, public):
    """A matching skip or silent exit cannot count as actual target preparation."""
    value = case["input"]
    target = "memory/2026-01-01.md"
    plans = public["plans"]
    if len(plans) != 2 or canonical(plans[0]) != canonical(plans[1]):
        return False
    plan = plans[0]
    reserve = 19999 if value["contextWindowTokens"] == 79999 else 20000
    if (plan["relativePath"] != target or plan["reserveTokensFloor"] != reserve
            or plan["softThresholdTokens"] != 30000 or plan["forceFlushTranscriptBytes"] != 2097152
            or any(target not in plan[k] or value["flush"][k] in plan[k] for k in ("prompt", "systemPrompt"))):
        return False
    tree = {"memory": {"kind": "directory"}, **{d: {"kind": "directory"} for d in value["directories"]}}
    for name, content in value["files"].items():
        tree[name] = {"kind": "file", "base64": base64.b64encode(content.encode()).decode("ascii")}
    if pair := value.get("readOnlyAlias"):
        tree[target]["linkedAs"] = sorted(pair.values())
        tree[pair["alias"]] = dict(tree[target])
    if public["files"] != tree:
        return False
    if target in value["directories"]:
        return (public["outcome"] == "failed" and public["stamp"]["kind"] == "failed"
                and public["selection"] is None and public["candidates"] == [] and public["replies"] == [])
    return (public["outcome"] == "completed" and public["stamp"]["kind"] == "succeeded"
            and public["selection"]["model"] == value["primary"] and public["replies"] == ["NO_REPLY"]
            and public["candidates"] == [{"provider": PROVIDER, "model": value["primary"]}])


def boundaries_complete(rows):
    if not boundary_prerequisites_complete(rows):
        return False
    selected = [row for row in rows if BOUNDARY in row.get("covers", ())]
    try:
        return len(selected) == len(build_boundary_cases()) and all(
            row["status"] == "matched" and row["runtimeEvidenceValidated"] is True
            and row["referenceMode"] == "authenticated-official-release" and canonical(row["openclaw"]) == canonical(row["python"])
            and confirms_boundary(row, row["openclaw"]) for row in selected)
    except (KeyError, TypeError, ValueError):
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
    expected = {row["id"]: hashlib.sha256(canonical(row["input"])).hexdigest() for row in [*build_cases(), *build_boundary_cases()]}
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
