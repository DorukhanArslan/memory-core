"""Require six genuine interruption routes before recording interrupted publication coverage."""
from copy import deepcopy
from hashlib import sha256

from equivalence.dream_light import canonical
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority

REQUIREMENT = "recovery.failure-publication"
OPERATION = "recovery-forget-interruption-runtime"
POINTS = (REQUIREMENT + ".outcomes",)
# These fixed publisher cases already run in the full comparison. Their paired
# results are required alongside the missing cut within forget's real transaction.
OTHER_PUBLISHERS = {
    "write": ("storage.atomic-writes.temp-file-fsync-eio", "storage.atomic-writes.rename-mutates-then-rejects"),
    "index": ("publication-commit-failure-reader-snapshot", "publication-post-commit-failure"),
    "flush": ("flush-execution-cancel-before-write", "flush-execution-cancel-after-write"),
    "consolidation": ("deep-consolidation-concurrent-edit", "dream-deep-report-publication-failure"),
    "diary": ("dream-diary-publisher-failure",),
}
MEMORY = ("# Notes\n\n<!-- openclaw-memory-promotion:key-a -->\n- A saved shell collection.\n"
          "<!-- openclaw-memory-promotion:key-b -->\n- B owns the workshop.\n")
OPS = ["seed", "arm", "forget", "reopen", "disarm", "retry", "reopen", "repeat"]
SHAS = ('52be38f0b2ddda145d5c56f6cd370f31eafda5306d2991a8b2bba69fe5468342', '25e2b0024565bd42afa37087f964d245de10fb6eed7ab8efd022a50b892baedb')


def build_cases():
    return [{
        "id": "recovery-forget-" + name, "operation": OPERATION, "requirement": REQUIREMENT,
        "covers": list(POINTS),
        "input": {"agentId": "main", "session": "A", "previous": "unrelated-prior",
                  "nowMs": 1_794_268_800_000, "memory": MEMORY,
                  "origins": [{"agentId": "main", "sessionId": sid, "sessionKey": "agent:main:" + sid,
                               "entryKey": "key-" + sid.lower(), "originClass": "owner", "observedAt": 100}
                              for sid in ("A", "B")],
                  "cut": name, "stages": list(OPS)},
        "driverScope": "The original forget CLI and SDK owner use a real SQLite abort at marker insertion or final origin deletion. Independent connections reopen every database image. Retry goes through the same public owner after the external fault is removed.",
        "normalizationPolicy": "Compare complete successful reports, all note bytes, origin and tombstone rows. A failing original CLI wraps the exact SQLite error. Raw owner errors and actual stdout are retained; only the verified injected SQLite message classifies the cut."
    } for name in ("before-marker", "after-note")]


def validate_case(case):
    for row, digest in zip(build_cases(), SHAS, strict=True):
        if row["id"] == case.get("id") and sha256(canonical(row)).hexdigest() == digest:
            if canonical(row) == canonical({key:case.get(key) for key in row}):
                return
    raise ValueError("Wrong frozen interrupted publisher case")


def _own(rows):
    return [r for r in rows if r.get("operation") == OPERATION or set(r.get("covers", ())).intersection(POINTS)]


def validate_registration(rows):
    selected = _own(rows)
    if selected and [r["id"] for r in selected] != [case["id"] for case in build_cases()]:
        raise ValueError("Both forget interruption edges must be present")
    for row in selected:
        validate_case(row)


def family_complete(rows):
    try:
        validate_registration(rows)
        seen = {r["id"]:r for r in rows}
        if len(seen) != len(rows) or len(_own(rows)) != 2:
            return False
        for ident in [r["id"] for r in _own(rows)] + [ident for group in OTHER_PUBLISHERS.values() for ident in group]:
            row = seen[ident]
            if row.get("status") != "matched" or canonical(row["openclaw"]) != canonical(row["python"]):
                return False
            if row["operation"] != "index-publication" and row.get("referenceMode") != "authenticated-official-release":
                return False
            if row["operation"] == OPERATION and row.get("runtimeEvidenceValidated") is not True:
                return False
        return True
    except (KeyError, ValueError, TypeError):
        return False


def profile_for(case, node):
    validate_case(case)
    return {"caseId":case["id"], "operation":OPERATION, "nodeRuntime":prepare_model_node_authority(node),
            "inputSha256":sha256(canonical(case["input"])).hexdigest()}


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != {"caseId","operation","nodeRuntime","inputSha256"}:
        raise ValueError("Incomplete interrupted publisher profile")
    row = next((r for r in build_cases() if r["id"] == profile["caseId"]), None)
    if not row or profile["operation"] != OPERATION or sha256(canonical(row["input"])).hexdigest() != profile["inputSha256"]:
        raise ValueError("Interrupted publisher case/profile mismatch")
    validate_case(row)
    validate_model_node_authority(profile["nodeRuntime"])
    return deepcopy(profile)
