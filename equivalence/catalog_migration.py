"""Exact default definition migration; this module executes no memory owner."""
from copy import deepcopy
import hashlib
import json

ORIGINAL_PREFIX_SHA256 = "0fa31b6393c65303f4fa2e1663671e4ef60eb15edc563f05aba218c8c408349c"
ORIGINAL_PREFIX_CASES = 1452
REGISTERED_CASES = 1465


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def definition_authority(cases, *, fif_version):
    """Authenticate all values, permitting only four named Host replacements.

    V5 is a historical suite identity with the unchanged original prefix. V6
    explicitly replaces the four old Host definitions with frozen V4 wrappers
    and the thirteen V5 tail definitions with their frozen V6 successors.
    """
    from equivalence import forget_index_fence_v5, forget_index_fence_v6

    families = {"v5": forget_index_fence_v5, "v6": forget_index_fence_v6}
    if fif_version not in families or not isinstance(cases, list) or len(cases) != REGISTERED_CASES:
        raise ValueError("Catalog migration requires one complete exact registered definition set")
    frozen = families[fif_version]
    if cases[ORIGINAL_PREFIX_CASES:] != frozen.build_cases():
        raise ValueError("Catalog migration changed or mixed the selected frozen FIF tail")
    frozen.validate_registration(cases)
    prefix = deepcopy(cases[:ORIGINAL_PREFIX_CASES])
    replacements = []
    if fif_version == "v6":
        from equivalence.host_turn_barrier import build_cases as original_hosts
        from equivalence.host_turn_barrier_v4 import build_cases as probes, business_case, registered_case

        old = original_hosts()
        new = [registered_case(probe) for probe in probes()]
        if len(old) != len(new) or len(new) != 4:
            raise ValueError("Catalog migration requires exactly four frozen Host V4 replacements")
        approved = {}
        for prior, current in zip(old, new, strict=True):
            if business_case(current) != prior or current["covers"] != prior["covers"]:
                raise ValueError("A Host wrapper changed its original business definition or point membership")
            approved[current["id"]] = prior, current
        seen = set()
        for index, actual in enumerate(prefix):
            if actual["id"] not in approved:
                continue
            prior, current = approved[actual["id"]]
            if _sha(actual) != _sha(current) or actual["id"] in seen:
                raise ValueError("A Host replacement changed, duplicated or widened its complete frozen wrapper")
            seen.add(actual["id"])
            prefix[index] = prior
            replacements.append({"index": index, "originalId": prior["id"], "currentId": current["id"],
                                 "originalDefinitionSha256": _sha(prior), "currentDefinitionSha256": _sha(current)})
        if seen != set(approved):
            raise ValueError("Catalog migration omitted an exact Host V4 replacement")
    if (_sha(prefix) != ORIGINAL_PREFIX_SHA256
            or sum("fixtureSource" in case for case in cases) != 79
            or sum("diagnosticOnly" in case for case in cases) != 1):
        raise ValueError("Catalog migration changed a definition outside its four Host whitelist")
    tail = []
    if fif_version == "v6":
        for index, (prior, current) in enumerate(zip(forget_index_fence_v5.build_cases(), frozen.build_cases(), strict=True), ORIGINAL_PREFIX_CASES):
            tail.append({"index": index, "originalId": prior["id"], "currentId": current["id"],
                         "originalDefinitionSha256": _sha(prior), "currentDefinitionSha256": _sha(current)})
    return {"kind": "explicit-default-definition-migration", "registeredCases": REGISTERED_CASES,
            "fifVersion": fif_version, "originalPrefixCases": ORIGINAL_PREFIX_CASES,
            "originalPrefixSha256": ORIGINAL_PREFIX_SHA256,
            "currentPrefixSha256": _sha(cases[:ORIGINAL_PREFIX_CASES]),
            "originalPrefixUnchanged": not replacements, "hostReplacements": replacements,
            "fifReplacements": tail}
