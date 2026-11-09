"""Guard the independent family inputs and exact comparison semantics."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest

from equivalence.promotion_apply_family import build_cases, differences, validate_case
from equivalence.promotion_apply_profile import validate_promotion_apply_input
from equivalence.promotion_apply_family_sdk import run_family_sdk
from equivalence.promotion_apply_family_evidence import validate_receipts


@pytest.mark.parametrize("case", build_cases(), ids=lambda case: case["id"])
def test_family_literal_is_bound_before_owner_invocation(case, tmp_path):
    original = deepcopy(case)
    assert validate_case(case) == original
    case["input"]["nowMs"] += 1
    with pytest.raises(ValueError, match="exact separate literal"):
        run_family_sdk(case, tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize("case", build_cases(), ids=lambda case: case["id"])
def test_original_single_case_capability_stays_closed(case):
    with pytest.raises(ValueError, match="only its reviewed literal"):
        validate_promotion_apply_input(case["input"])


def test_cannot_assign_coverage_or_impersonate_another_identity():
    case = build_cases()[0]
    case["covers"] = ["promotion.apply-reconcile.outcomes"]
    with pytest.raises(ValueError):
        validate_case(case)
    case["covers"] = []
    case["id"] = build_cases()[1]["id"]
    with pytest.raises(ValueError):
        validate_case(case)


def test_json_numbers_share_one_type_without_conflating_booleans():
    assert differences({"number": 1}, {"number": 1.0}) == []
    assert differences({"number": 0}, {"number": False})
    assert differences({"number": 1}, {"number": 1.0000000000000002})


def test_order_missing_null_and_complete_errors_remain_visible():
    assert differences([1, 2], [2, 1])
    assert differences({}, {"value": None}) == [
        {"path": "$.value", "nativePresent": False, "sdkPresent": True, "sdk": None}]
    assert differences({"error": {"message": "a", "code": "ENOENT"}},
                       {"error": {"message": "a", "code": "EACCES"}}) == [
        {"path": "$.error.code", "native": "ENOENT", "sdk": "EACCES"}]


def journal():
    # Synthetic codec data only, never a protected Native capture.
    return [
        {"sequence": 1, "operation": "fs.rename", "when": "before", "monotonicNs": "10", "arguments": ["a", "b"]},
        {"sequence": 2, "operation": "fs.rename", "when": "after", "monotonicNs": "11", "call": 1, "result": None},
    ]


@pytest.mark.parametrize("mutation", ["missing-return", "wrong-owner", "backwards-clock", "missing-sequence"])
def test_journal_rejects_lost_or_reassigned_original_facts(mutation):
    rows = journal()
    if mutation == "missing-return":
        rows.pop()
    elif mutation == "wrong-owner":
        rows[1]["operation"] = "fs.unlink"
    elif mutation == "backwards-clock":
        rows[1]["monotonicNs"] = "9"
    else:
        rows[1]["sequence"] = 3
    with pytest.raises(ValueError):
        validate_receipts(rows)


def test_observer_delegates_exact_calls_returns_errors_and_restores():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the JavaScript observer guard")
    helper = Path(__file__).resolve().parents[2] / "equivalence/promotion-apply-family-observers.mjs"
    source = '''
      import assert from "node:assert/strict";
      const { callObservers } = await import(process.argv[1]);
      const actual = { retained: 7 }, thrown = Error("original error");
      let calls = 0;
      const binding = {
        success(value) { calls++; assert.equal(value, actual); return actual; },
        failure() { calls++; throw thrown; },
        async asynchronous() { calls++; return actual; },
      };
      const originals = { ...binding }, rows = [], observer = callObservers(rows);
      observer.observeBinding(binding);
      assert.equal(binding.success(actual), actual);
      assert.equal(rows.length, 0);
      observer.start();
      try {
        assert.equal(binding.success(actual), actual);
        assert.throws(() => binding.failure(), error => error === thrown);
        assert.equal(await binding.asynchronous(), actual);
        assert.equal(rows.length, 6);
        assert.equal(calls, 4);
        assert.equal(rows[3].error.message, thrown.message);
      } finally { observer.restore(); }
      for (const name of Object.keys(binding)) assert.equal(binding[name], originals[name]);
    '''
    result = subprocess.run([node, "--input-type=module", "--eval", source, helper.as_uri()],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
