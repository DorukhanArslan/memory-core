"""Both independently damaged index artifacts and the live workspace audits form one family."""
from copy import deepcopy
from hashlib import sha256

from equivalence.dream_light import canonical
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority
from equivalence.recovery_index_fixtures import OPERATION as INDEX, recovery_index_cases
from equivalence.recovery_repair_fixtures import OPERATION as ARTIFACT, POINTS, REQUIREMENT, artifact_cases

INDEX_SHA = "7beaa2b4f198b98655ff8a4235bcdc5f8dfe08ac3bea10b9f4b35902077406a4"


def build_cases():
    index = recovery_index_cases()
    if sha256(canonical(index)).hexdigest() != INDEX_SHA:
        raise ValueError("Recovery index fixtures changed")
    return [*artifact_cases(), *index]


def validate_case(case):
    row = next((r for r in build_cases() if r["id"] == case.get("id")), None)
    if row is None or canonical({k: case.get(k) for k in row}) != canonical(row):
        raise ValueError("Recovery requires the independently frozen full input")


def _members(rows):
    return [r for r in rows if r.get("requirement") == REQUIREMENT or r.get("operation") in {ARTIFACT, INDEX}
            or set(r.get("covers", ())).intersection(POINTS)]


def validate_registration(rows):
    selected = _members(rows)
    if selected:
        if [r["id"] for r in selected] != [r["id"] for r in build_cases()]:
            raise ValueError("Recovery requires all nine controls and corruptions in order")
        for row in selected:
            validate_case(row)


def family_complete(rows):
    try:
        validate_registration(rows)
    except (KeyError, ValueError, TypeError):
        return False
    selected = _members(rows)
    return bool(selected) and all(r.get("status") == "matched" and r.get("runtimeEvidenceValidated") is True for r in selected)


def profile_for(case, node):
    validate_case(case)
    return {"caseId": case["id"], "operation": case["operation"], "nodeRuntime": prepare_model_node_authority(node),
            "inputSha256": sha256(canonical(case["input"])).hexdigest()}


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != {"caseId", "operation", "nodeRuntime", "inputSha256"}:
        raise ValueError("Incomplete recovery authority")
    row = next((r for r in build_cases() if r["id"] == profile["caseId"]), None)
    if row is None or profile["operation"] != row["operation"] or profile["inputSha256"] != sha256(canonical(row["input"])).hexdigest():
        raise ValueError("The recovery operation must use its own frozen inputs")
    validate_model_node_authority(profile["nodeRuntime"])
    return deepcopy(profile)
