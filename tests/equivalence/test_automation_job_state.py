from copy import deepcopy
import json

import pytest

from equivalence.automation_job_state import build_cases, family_complete, validate_registration
from equivalence.automation_job_state_evidence import validate_sdk
from equivalence.cases import run_python


def test_scheduled_task_requires_the_exact_registered_case_and_evidence():
    [case] = build_cases()
    validate_registration([case])
    missing = deepcopy(case)
    missing["input"]["steps"].pop()
    with pytest.raises(ValueError):
        validate_registration([missing])
    assert not family_complete([{**case, "status": "matched"}])
    assert not family_complete([{**missing, "status": "matched", "runtimeEvidenceValidated": True}])
    assert family_complete([{**case, "status": "matched", "runtimeEvidenceValidated": True}])


def test_scheduled_task_verifies_reopened_store_and_rejects_a_stale_read(tmp_path):
    [case] = build_cases()
    output = run_python({**case, "_diagnosticDirectory": tmp_path})
    [raw] = json.loads((tmp_path / "python-raw.json").read_text())
    validate_sdk(case, raw, output, tmp_path)
    stale = deepcopy(output)
    stale["steps"][-1]["callbacks"][0]["tool"]["result"] = stale["steps"][1]["callbacks"][0]["tool"]["result"]
    with pytest.raises(ValueError, match="current source"):
        validate_sdk(case, raw, stale, tmp_path)
    raw["steps"][2]["beforeStore"] = raw["steps"][0]["beforeStore"]
    with pytest.raises(ValueError, match="did not survive reopen"):
        validate_sdk(case, raw, output, tmp_path)
