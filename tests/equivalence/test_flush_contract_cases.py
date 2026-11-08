"""Fixture integrity checks; native equivalence requires the pinned-source run."""
from collections import Counter
from copy import deepcopy
import json

import pytest

from equivalence.flush_contract import (
    build_flush_contract_cases,
    build_prospective_flush_contract_cases,
    run_flush_contract,
)


def test_flush_fixtures_are_reproducible_unique_json_and_honest_about_scope():
    cases = build_flush_contract_cases()
    assert cases == build_flush_contract_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["covers"] == [] for case in cases)
    assert Counter(case["input"]["kind"] for case in cases) == {
        "plan": 62, "target": 8, "gate": 19, "fresh": 10, "threshold": 4, "error": 8,
    }
    assert cases == build_prospective_flush_contract_cases()


def test_flush_transport_preserves_inputs_and_returns_complete_standard_json():
    for case in build_flush_contract_cases():
        before = deepcopy(case)
        output = run_flush_contract(case["input"])
        json.dumps(output, allow_nan=False)
        assert case == before
        if case["input"]["kind"] == "plan" and output["plan"] is not None:
            assert output["hostTimeFormat"] == case["input"]["hostTimeFormat"]
            assert set(output["plan"]) == {
                "softThresholdTokens", "forceFlushTranscriptBytes", "reserveTokensFloor",
                "model", "prompt", "systemPrompt", "relativePath",
            }


def test_reused_fixtures_cover_config_usage_boundaries_and_target_preservation():
    cases = {case["id"]: case["input"] for case in build_prospective_flush_contract_cases()}
    assert run_flush_contract(cases["flush-plan-disabled"])["plan"] is None
    assert run_flush_contract(cases["flush-target-preserve-existing"]) == {
        "ok": True, "files": {"memory/2026-09-25.md": "- kept\n"},
    }
    assert run_flush_contract(cases["flush-target-parent"]) == {
        "ok": False, "error": {"message": "Memory flush target path must stay inside the workspace"},
        "files": {},
    }
    assert run_flush_contract(cases["flush-gate-at"])["shouldRun"] is True
    assert run_flush_contract(cases["flush-gate-stale"])["shouldRun"] is False
    assert run_flush_contract(cases["flush-gate-same-cycle"])["shouldRun"] is False
    assert run_flush_contract(cases["flush-gate-next-cycle"])["shouldRun"] is True


def test_unknown_flush_kind_is_an_error_instead_of_a_placeholder():
    with pytest.raises(ValueError, match="Unsupported flush contract operation"):
        run_flush_contract({"kind": "invented-runtime-phase"})
