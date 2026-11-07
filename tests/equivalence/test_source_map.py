"""Inventory checks; source presence never substitutes for differential evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.harness import HarnessError
from equivalence.source_map import ROOT, validate_source_map


@pytest.fixture
def mapping():
    return {
        "inventory": json.loads((ROOT / "equivalence/source-map.json").read_text()),
        "scope": json.loads((ROOT / "equivalence/scope.json").read_text()),
        "target": json.loads((ROOT / "equivalence/reference.json").read_text()),
    }


def test_inventory_maps_every_fixed_acceptance_point_without_claiming_behavior(mapping):
    before = deepcopy(mapping)
    result = validate_source_map(**mapping)

    assert result["contracts"] == 64
    assert result["acceptancePoints"] == 128
    assert result["upstreamModules"] > 0
    assert result["referenceVerified"] is False
    assert result["behaviorVerified"] is False
    assert mapping == before


@pytest.mark.parametrize("change", [
    "missing-contract", "duplicate-contract", "missing-point", "foreign-point",
    "wrong-reference", "stale-scope", "missing-module", "invalid-status",
])
def test_incomplete_or_relabelled_inventory_is_rejected(mapping, change):
    data = mapping["inventory"]
    if change == "missing-contract":
        data["requirements"].pop()
    elif change == "duplicate-contract":
        data["requirements"][-1] = deepcopy(data["requirements"][0])
    elif change == "missing-point":
        data["requirements"][0]["acceptancePoints"].pop()
    elif change == "foreign-point":
        data["requirements"][0]["acceptancePoints"][0] = "not-in-the-contract"
    elif change == "wrong-reference":
        data["reference"]["commit"] = "0" * 40
    elif change == "stale-scope":
        data["scopeSha256"] = "0" * 64
    elif change == "missing-module":
        data["upstreamModules"].pop()
    else:
        data["requirements"][0]["implementation"] = "matched"

    with pytest.raises(ValueError):
        validate_source_map(**mapping)


@pytest.mark.parametrize("change", ["missing-file", "wrong-anchor", "wrong-line", "outside-root"])
def test_python_locations_must_point_to_real_current_code(mapping, change):
    location = next(row["python"][0] for row in mapping["inventory"]["requirements"] if row["python"])
    if change == "missing-file":
        location["path"] = "memory_core/does_not_exist.py"
    elif change == "wrong-anchor":
        location["anchor"] = "def invented_source_function():"
    elif change == "wrong-line":
        location["line"] += 1
    else:
        location["path"] = "../outside.py"

    with pytest.raises(ValueError):
        validate_source_map(**mapping)


def test_missing_reference_cannot_attest_the_upstream_inventory(mapping, tmp_path: Path):
    with pytest.raises((ValueError, HarnessError)):
        validate_source_map(**mapping, checkout=tmp_path / "missing")
