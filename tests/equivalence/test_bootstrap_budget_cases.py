"""Offline transport guards; the strict native oracle establishes equivalence."""

from copy import deepcopy
import json

from equivalence.bootstrap_budget import build_bootstrap_budget_cases, run_bootstrap_budget


def test_bootstrap_budget_cases_are_reproducible_and_cover_named_boundaries():
    cases = build_bootstrap_budget_cases()
    assert cases == build_bootstrap_budget_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["operation"] for case in cases} == {"bootstrap-budget"}
    assert {case["requirement"] for case in cases} == {"prompt.bootstrap-budget"}
    assert {point for case in cases for point in case["covers"]} == {
        "prompt.bootstrap-budget.outcomes", "prompt.bootstrap-budget.boundaries"}
    names = {case["id"] for case in cases}
    assert {f"bootstrap-budget-{name}" for name in (
        "head-tail-probe", "compact-marker-probe", "fixed-user-4000", "fixed-user-4001",
        "aggregate-63", "aggregate-64", "aggregate-65", "missing-marker-exhaustion",
        "utf16-exact-100", "utf16-exact-101", "warning-off-once-always-state",
        "personal-user-4000", "personal-user-4001", "personal-user-aggregate-skip",
    )}.issubset(names)


def test_bootstrap_budget_adapter_preserves_inputs_and_standard_json_results():
    for case in build_bootstrap_budget_cases():
        before = deepcopy(case)
        json.dumps(run_bootstrap_budget(case["input"]), allow_nan=False)
        assert case == before


def test_warning_sequence_uses_the_returned_signature_history():
    case = next(case for case in build_bootstrap_budget_cases()
                if case["id"] == "bootstrap-budget-warning-off-once-always-state")
    steps = run_bootstrap_budget(case["input"])["warningTransitions"]
    assert [step["warningShown"] for step in steps] == [False, True, False, True]
    assert steps[0]["warningSignaturesSeen"] == []
    assert steps[1]["warningSignaturesSeen"] == [steps[1]["signature"]]
    assert steps[2]["notice"] is None


def test_personal_instructions_are_whole_or_skipped_without_spending_budget():
    cases = {case["id"]: case["input"] for case in build_bootstrap_budget_cases()}
    exact = run_bootstrap_budget(cases["bootstrap-budget-personal-user-4000"])
    assert exact["files"][1]["personalUser"] is True
    assert exact["files"][1]["content"] == "p" * 4000
    oversized = run_bootstrap_budget(cases["bootstrap-budget-personal-user-4001"])
    aggregate = run_bootstrap_budget(cases["bootstrap-budget-personal-user-aggregate-skip"])
    for result in (oversized, aggregate):
        assert not any(file.get("personalUser") for file in result["files"])
        assert result["files"][-1] == {"path": "/w/MEMORY.md", "content": "facts"}
        assert result["warnings"] == [
            "Personal USER.md exceeds the bootstrap budget; using shared defaults."]
