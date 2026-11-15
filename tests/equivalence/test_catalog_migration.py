"""Exact reviewed Host/FIF, HOME-policy and outcome migration; no engines."""
from copy import deepcopy
import hashlib
import json

import pytest

from equivalence.cases import build_cases
from equivalence.catalog_migration import ORIGINAL_PREFIX_SHA256, _restore_reviewed_policies, definition_authority
from equivalence import forget_index_fence_v5, forget_index_fence_v6
from equivalence import host_turn_barrier as old_host
from equivalence import host_turn_barrier_v4 as host


def test_default_catalog_explicitly_migrates_only_four_host_and_thirteen_fif_definitions():
    cases = build_cases()
    proof = definition_authority(cases, fif_version="v6")
    assert len(cases) == proof["registeredCases"] == 1468
    assert len(proof["policyReplacements"]) == 13 and len(proof["lineageAppend"]) == 3
    assert proof["originalPrefixUnchanged"] is False
    assert proof["currentPrefixSha256"] != proof["originalPrefixSha256"] == ORIGINAL_PREFIX_SHA256
    assert len(proof["hostReplacements"]) == 4 and len(proof["fifReplacements"]) == 13
    assert [row["originalId"] for row in proof["hostReplacements"]] == list(old_host.CASE_HASHES)
    assert [row["currentId"] for row in proof["hostReplacements"]] == list(host.CASE_HASHES)
    assert [row["originalId"] for row in proof["fifReplacements"]] == list(forget_index_fence_v5.CASE_HASHES)
    assert [row["currentId"] for row in proof["fifReplacements"]] == list(forget_index_fence_v6.CASE_HASHES)
    restored = deepcopy(cases[:1452])
    probes = host.build_cases()
    for replacement, probe in zip(proof["hostReplacements"], probes, strict=True):
        current = cases[replacement["index"]]
        assert current == host.registered_case(probe)
        assert current["covers"] == host.business_case(probe)["covers"] == ["host.turn-barrier.outcomes"]
        unchanged = deepcopy(current)
        unchanged["covers"] = []
        assert unchanged == probe
        restored[replacement["index"]] = host.business_case(current)
    _restore_reviewed_policies(restored)
    wire = json.dumps(restored, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(wire).hexdigest() == ORIGINAL_PREFIX_SHA256


@pytest.mark.parametrize("attack", [
    "one-old-host", "all-old-host", "reorder-hosts", "duplicate-host", "host-covers", "host-metadata",
    "host-input", "host-scalar-type", "unrelated-input", "unrelated-metadata", "annotation",
    "one-old-fif", "all-old-fif", "missing-fif", "extra-case", "wrong-version",
])
def test_catalog_migration_rejects_any_unreviewed_definition_or_membership(attack):
    cases = build_cases()
    proof = definition_authority(cases, fif_version="v6")
    positions = [row["index"] for row in proof["hostReplacements"]]
    chosen = cases[positions[0]]
    version = "v6"
    if attack == "one-old-host":
        cases[positions[0]] = old_host.build_cases()[0]
    elif attack == "all-old-host":
        for position, original in zip(positions, old_host.build_cases(), strict=True):
            cases[position] = original
    elif attack == "reorder-hosts":
        cases[positions[0]], cases[positions[1]] = cases[positions[1]], cases[positions[0]]
    elif attack == "duplicate-host":
        cases[positions[1]] = deepcopy(chosen)
    elif attack == "host-covers":
        chosen["covers"].append("host.turn-barrier.boundaries")
    elif attack == "host-metadata":
        chosen["declaredDeviation"] = "unreviewed"
    elif attack == "host-input":
        chosen["input"]["unreviewed"] = True
    elif attack == "host-scalar-type":
        def change(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if type(item) is bool:
                        value[key] = int(item)
                        return True
                    if change(item):
                        return True
            elif isinstance(value, list):
                return any(change(item) for item in value)
            return False
        assert change(chosen["input"])
    elif attack == "unrelated-input":
        cases[0]["input"]["text"] += "unreviewed"
    elif attack == "unrelated-metadata":
        cases[0]["declaredDeviation"] = "unreviewed"
    elif attack == "annotation":
        del next(case for case in cases if "fixtureSource" in case)["fixtureSource"]
    elif attack == "one-old-fif":
        cases[1452] = forget_index_fence_v5.build_cases()[0]
    elif attack == "all-old-fif":
        cases[1452:] = forget_index_fence_v5.build_cases()
    elif attack == "missing-fif":
        cases.pop()
    elif attack == "extra-case":
        cases.append(deepcopy(cases[0]))
    else:
        version = "v7"
    with pytest.raises(ValueError):
        definition_authority(cases, fif_version=version)


def test_historical_v5_authority_remains_an_explicit_unchanged_prefix_identity():
    current = build_cases()
    original = [host.business_case(case) if case["operation"] == host.OPERATION else case for case in current[:1452]]
    _restore_reviewed_policies(original)
    proof = definition_authority(original + forget_index_fence_v5.build_cases(), fif_version="v5")
    assert proof["originalPrefixUnchanged"] is True
    assert proof["currentPrefixSha256"] == ORIGINAL_PREFIX_SHA256
    assert proof["hostReplacements"] == proof["fifReplacements"] == []
    with pytest.raises(ValueError):
        definition_authority(current, fif_version="v5")


def test_historical_retention_targets_add_only_fourteen_existing_ids_to_the_seventeen_runtime_pairs():
    from equivalence.catalog_migration import HISTORICAL_MISMATCH_REPORT_IDS

    assert type(HISTORICAL_MISMATCH_REPORT_IDS) is tuple
    historical = set(HISTORICAL_MISMATCH_REPORT_IDS)
    assert len(historical) == len(HISTORICAL_MISMATCH_REPORT_IDS) == 14
    cases = build_cases()
    known = {case["id"] for case in cases}
    runtime_pairs = set(host.CASE_HASHES) | set(forget_index_fence_v6.CASE_HASHES)
    assert historical <= known
    assert not historical & runtime_pairs
    assert len(historical | runtime_pairs) == 31


def test_historical_retention_tuple_matches_the_explicitly_selected_pinned_independent_baseline():
    import os
    from pathlib import Path
    from equivalence.catalog_migration import (
        HISTORICAL_MISMATCH_REPORT_BASELINE_SHA256, HISTORICAL_MISMATCH_REPORT_IDS,
    )

    selector = os.environ.get("MEMORY_EQ_HISTORICAL_REPORT_BASELINE")
    if selector is None:
        pytest.skip("No explicitly selected independent baseline; no original parity credit")
    path = Path(selector)
    before = path.read_bytes()
    assert hashlib.sha256(before).hexdigest() == HISTORICAL_MISMATCH_REPORT_BASELINE_SHA256
    actual = json.loads(before)["data"]["mismatchPayloads"]
    assert tuple(actual) == HISTORICAL_MISMATCH_REPORT_IDS
    assert path.read_bytes() == before
