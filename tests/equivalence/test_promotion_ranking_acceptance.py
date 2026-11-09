"""Condition claims require the actual frozen families, including known drift."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.cases import build_cases
from equivalence.harness import HarnessError, _validate_scope
from equivalence.promotion_ranking_acceptance import (
    PROMOTION_RANKING_BOUNDARIES,
    PROMOTION_RANKING_BOUNDARIES_REQUIRED_CASE_IDS,
    PROMOTION_RANKING_FROZEN_REPORT_SHA256,
    PROMOTION_RANKING_FROZEN_SOURCE_COMMIT,
    PROMOTION_RANKING_INPUT_WIRE_SHA256,
    PROMOTION_RANKING_OUTCOMES,
    PROMOTION_RANKING_OUTCOMES_REQUIRED_CASE_IDS,
    PROMOTION_RANKING_PRIMITIVE_CASE_ID,
    promotion_ranking_coverage,
    promotion_ranking_input_wire_sha256,
    validate_promotion_ranking_acceptance,
)
from equivalence.promotion_ranking_fixtures import build_promotion_ranking_cases


ROOT = Path(__file__).parents[2]
PROPER_IDS = {
    "promotion-ranking-signals-and-components", "promotion-ranking-custom-weights",
    "promotion-ranking-score-boundary", "promotion-ranking-frequency-boundary",
    "promotion-ranking-diversity-and-age", "promotion-ranking-tie-order-and-limit",
    "promotion-ranking-origin-and-promoted-visibility", "promotion-ranking-path-and-transcript-gates",
    "promotion-ranking-phase-boost", "promotion-ranking-multiline-store-diagnostic",
    "promotion-ranking-equal-path-stability-diagnostic", "promotion-ranking-old-phase-diagnostic",
    "promotion-ranking-limit-boundaries", "promotion-ranking-numeric-gate-normalization",
    "promotion-ranking-current-default-query-diversity",
}


def _scope():
    return json.loads((ROOT / "equivalence/scope.json").read_text())


def test_default_claim_map_requires_the_complete_fifteen_and_sixteen_literal_families():
    cases = build_promotion_ranking_cases()
    before = deepcopy(cases)
    validate_promotion_ranking_acceptance(cases)
    _validate_scope(_scope(), cases)
    assert cases == before
    assert set(PROMOTION_RANKING_OUTCOMES_REQUIRED_CASE_IDS) == PROPER_IDS
    assert len(PROMOTION_RANKING_OUTCOMES_REQUIRED_CASE_IDS) == len(PROPER_IDS) == 15
    all_ids = PROPER_IDS | {PROMOTION_RANKING_PRIMITIVE_CASE_ID}
    assert set(PROMOTION_RANKING_BOUNDARIES_REQUIRED_CASE_IDS) == all_ids
    assert len(PROMOTION_RANKING_BOUNDARIES_REQUIRED_CASE_IDS) == len(all_ids) == 16
    default = build_cases()
    for point, expected in ((PROMOTION_RANKING_OUTCOMES, PROPER_IDS), (PROMOTION_RANKING_BOUNDARIES, all_ids)):
        assert {case["id"] for case in default if point in case["covers"]} == expected
    assert {case["id"]: promotion_ranking_input_wire_sha256(case["input"]) for case in cases} == PROMOTION_RANKING_INPUT_WIRE_SHA256
    assert PROMOTION_RANKING_FROZEN_REPORT_SHA256 == "57431cdc8025593e342b97fc4f29d1d17a6a827495e47d994fb78440746342e3"
    assert PROMOTION_RANKING_FROZEN_SOURCE_COMMIT == "f3d23635dd9866e8678515396c72489fc43ea1f8"
    primitive, = [case for case in cases if case["id"] == PROMOTION_RANKING_PRIMITIVE_CASE_ID]
    assert primitive["covers"] == [PROMOTION_RANKING_BOUNDARIES]
    assert primitive["input"]["store"]["entries"]["malformed-trust"]["provenance"] == 1
    assert "stronger privacy policy" in primitive["declaredDeviation"]


@pytest.mark.parametrize("change", [
    "missing-proper", "missing-primitive", "outcomes-only-subset", "substitute-family", "substitute-input",
    "entry-order", "object-order", "query-order", "numeric-type", "primitive-type", "clock", "operation",
    "requirement", "remove-outcomes", "remove-boundaries", "remove-all-outcomes", "remove-all-boundaries",
    "primitive-outcome", "extra-point-family", "duplicate-uncredited-family", "nonfinite-input", "tag-order",
])
def test_real_claims_reject_subsets_substitutions_changed_wire_and_hidden_known_mismatch(change):
    cases = build_promotion_ranking_cases()
    primitive = next(case for case in cases if case["id"] == PROMOTION_RANKING_PRIMITIVE_CASE_ID)
    if change == "missing-proper":
        del cases[0]
    elif change == "missing-primitive":
        cases.remove(primitive)
    elif change == "outcomes-only-subset":
        cases.remove(primitive)
        for case in cases:
            case["covers"] = [PROMOTION_RANKING_OUTCOMES]
    elif change == "substitute-family":
        cases[0]["id"] = "promotion-ranking-replacement"
    elif change == "substitute-input":
        cases[0]["input"] = deepcopy(cases[1]["input"])
    elif change == "entry-order":
        entries = cases[0]["input"]["store"]["entries"]
        cases[0]["input"]["store"]["entries"] = dict(reversed(list(entries.items())))
    elif change == "object-order":
        cases[0]["input"] = dict(reversed(list(cases[0]["input"].items())))
    elif change == "query-order":
        cases[0]["input"]["queries"].reverse()
    elif change == "numeric-type":
        cases[0]["input"]["nowMs"] = float(cases[0]["input"]["nowMs"])
    elif change == "primitive-type":
        primitive["input"]["store"]["entries"]["malformed-trust"]["provenance"] = True
    elif change == "clock":
        cases[0]["input"]["nowMs"] += 1
    elif change == "operation":
        cases[0]["operation"] = "memory-budget-runtime"
    elif change == "requirement":
        cases[0]["requirement"] = "promotion.apply-reconcile"
    elif change in {"remove-outcomes", "remove-boundaries"}:
        cases[0]["covers"].remove(PROMOTION_RANKING_OUTCOMES if change == "remove-outcomes" else PROMOTION_RANKING_BOUNDARIES)
    elif change in {"remove-all-outcomes", "remove-all-boundaries"}:
        point = PROMOTION_RANKING_OUTCOMES if change == "remove-all-outcomes" else PROMOTION_RANKING_BOUNDARIES
        for case in cases:
            case["covers"] = [tag for tag in case["covers"] if tag != point]
    elif change == "primitive-outcome":
        primitive["covers"].insert(0, PROMOTION_RANKING_OUTCOMES)
    elif change == "extra-point-family":
        extra = deepcopy(cases[0])
        extra["id"] = "promotion-ranking-added-family"
        cases.append(extra)
    elif change == "duplicate-uncredited-family":
        extra = deepcopy(cases[0])
        extra["covers"] = []
        cases.append(extra)
    elif change == "nonfinite-input":
        cases[0]["input"]["nowMs"] = float("inf")
    elif change == "tag-order":
        cases[0]["covers"].reverse()
    else:
        raise AssertionError(change)
    before = deepcopy(cases)
    with pytest.raises(ValueError):
        validate_promotion_ranking_acceptance(cases)
    with pytest.raises(HarnessError) as rejected:
        _validate_scope(_scope(), cases)
    assert rejected.value.code == "cases-invalid"
    assert cases == before


def test_historical_and_custom_uncredited_smoke_inputs_remain_allowed():
    cases = build_promotion_ranking_cases()
    for case in cases:
        case["covers"] = []
    custom = deepcopy(cases[0])
    custom.update(id="custom-uncredited-ranking", input={"kind": "promotion-ranking", "custom": "literal"})
    cases.append(custom)
    validate_promotion_ranking_acceptance(cases)
    _validate_scope(_scope(), cases)
    validate_promotion_ranking_acceptance([custom])
    _validate_scope(_scope(), [custom])


def test_extra_uncredited_diagnostic_does_not_replace_or_change_any_claimed_family():
    cases = build_promotion_ranking_cases()
    cases.append({**deepcopy(cases[0]), "id": "uncredited-extra", "covers": [], "input": {"diagnostic": True}})
    validate_promotion_ranking_acceptance(cases)
    _validate_scope(_scope(), cases)


def test_wire_hash_preserves_order_and_typed_values_but_compares_the_same_utf16_units():
    digest = promotion_ranking_input_wire_sha256
    assert digest({"text": "😀"}) == digest({"text": "\ud83d\ude00"})
    assert digest({"text": "\ud800"}) != digest({"text": "\ufffd"})
    assert digest({"a": 1, "b": 2}) != digest({"b": 2, "a": 1})
    assert digest({"entries": {"z": 1, "a": 1}}) != digest({"entries": {"a": 1, "z": 1}})
    assert digest({"value": 1}) != digest({"value": 1.0}) != digest({"value": True})
    assert digest({"value": None}) != digest({})


@pytest.mark.parametrize("value", [(1, 2), {1: "not-a-JSON-key"}, {"bad": float("nan")}, {"bad": float("inf")}, {"bad": {1, 2}}])
def test_wire_hash_rejects_nonstandard_or_nonfinite_values(value):
    with pytest.raises(ValueError):
        promotion_ranking_input_wire_sha256(value)


def test_unknown_family_cannot_request_point_tags():
    with pytest.raises(ValueError):
        promotion_ranking_coverage("unregistered")



def test_missing_family_is_rejected_before_native_or_sdk_execution(tmp_path, monkeypatch):
    from equivalence import harness

    cases = build_promotion_ranking_cases()
    cases = [case for case in cases if case["id"] != PROMOTION_RANKING_PRIMITIVE_CASE_ID]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("A rejected point claim must not execute either implementation")

    monkeypatch.setattr(harness, "_oracle", forbidden)
    report, code = harness.run_suite(checkout=tmp_path / "absent-reference",
        node=tmp_path / "absent-node", cases=cases, python_runner=forbidden)
    assert code == 2 and report["status"] == "blocked"
    assert report["errors"] == [{"code": "cases-invalid", "message":
        "A ranking point claim requires all sixteen fixed families, including the primitive boundary mismatch"}]
