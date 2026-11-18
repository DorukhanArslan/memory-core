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
DEPENDENCY_SHA256 = {
    'publication-commit-failure-reader-snapshot': 'c73939fab1468a2e5162cc286de334fd52c2dd70045ba2b4f5cb5f54583ea3e3',
    'publication-post-commit-failure': '036938a280d58f1bc3d47aabd05b68ed427dd67a8bda889efc363d49267aa2d9',
    'flush-execution-cancel-before-write': 'b4282e2df3421240297bc8763f6e8d6038f472de67e3a7cd0e1245dcbe0f3fec',
    'flush-execution-cancel-after-write': '9a3fbb83f3b493546c176d44594967a5bde118a2cbd1b0d178cbbe0dfec03287',
    'storage.atomic-writes.temp-file-fsync-eio': '267a123ed0a7afbd06972ee2efe85803f3fb3b1d73b07affccecf67b1e02065e',
    'storage.atomic-writes.rename-mutates-then-rejects': '407a01622c2bab12832f14ff836e844208310a59f4f5a6ed9126c7abd941bc37',
    'deep-consolidation-concurrent-edit': 'dca9c810666db373f9b97946bb50789fd5554af91be43754cb7d4966c7ab3de3',
    'dream-diary-publisher-failure': '3d6bbccafb7912f2cbddf1694db36efd6e6e2262ce30d4d0b696b8cfba969cd9',
    'dream-deep-report-publication-failure': '5a2f5a37a6f1e0408eccd822260053d3594052261859eac2a3276d4b3e41a5a2',
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
            if row.get("status") != "matched":
                return False
            if "openclaw" in row and canonical(row["openclaw"]) != canonical(row["python"]):
                return False
            if ident in DEPENDENCY_SHA256 and sha256(canonical({k:row[k] for k in
                    ("id","requirement","operation","input","covers")})).hexdigest()!=DEPENDENCY_SHA256[ident]:
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
