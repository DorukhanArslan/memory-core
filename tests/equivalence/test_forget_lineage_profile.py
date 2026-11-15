"""Pure input/capability guards; these checks execute no forget owner."""
from copy import deepcopy
import base64
import gzip
import hashlib
import json

import pytest

from equivalence.forget_lineage_cases import build_cases, validate_case
from equivalence.forget_lineage_profile import case_bindings, validate_forget_lineage_profile
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError
from equivalence.forget_lineage_evidence import physical_snapshot


def profile():
    case = build_cases()[0]
    return {"kind": "approved-forget-lineage-profile", "operation": case["operation"],
            "inputKind": case["input"]["kind"], "caseId": case["id"], "caseBindings": case_bindings(),
            "nodeRuntime": {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME}}


def test_six_input_only_cases_have_no_acceptance_claim():
    cases = build_cases()
    assert len(cases) == len(case_bindings()) == 6
    assert all(case["covers"] == [] and case["requirement"] == "forget.lineage-tombstones" for case in cases)
    assert validate_forget_lineage_profile(profile()) == profile()


@pytest.mark.parametrize("mutation", ["selector", "clock", "coverage", "operation"])
def test_changed_cases_are_rejected_before_execution(mutation):
    case = deepcopy(build_cases()[0])
    if mutation == "selector":
        case["input"]["operations"][0]["sessionIds"] = ["B"]
    elif mutation == "clock":
        case["input"]["nowMs"] += 1
    elif mutation == "coverage":
        case["covers"] = ["forget.lineage-tombstones.outcomes"]
    else:
        case["operation"] = "entry-memory-publication-runtime"
    with pytest.raises(ValueError):
        validate_case(case)


@pytest.mark.parametrize("field", ["kind", "operation", "caseId", "caseBindings", "nodeRuntime"])
def test_a_capability_cannot_authorize_changed_identity_or_binary(field):
    value = profile()
    value[field] = {} if field in {"caseBindings", "nodeRuntime"} else "unapproved"
    with pytest.raises(ValueError):
        validate_forget_lineage_profile(value)


def test_forget_capability_cannot_borrow_another_profile():
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution({}, {}, forget_lineage_profile=profile(), entry_profile={}):
            raise AssertionError("An invalid mixed capability reached an execution context")


def test_physical_transport_is_lossless_and_rejects_changed_bytes():
    original = {"files": {"literal": {"hex": "00" * 20000}}, "rows": [{"field": "all data retained"}]}
    raw = json.dumps(original).encode()
    captured = {"encoding": "gzip-json-base64", "uncompressedBytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "data": base64.b64encode(gzip.compress(raw)).decode()}
    assert physical_snapshot(captured) == original
    captured["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="snapshot changed"):
        physical_snapshot(captured)
