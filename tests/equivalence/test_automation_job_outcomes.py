from copy import deepcopy
from pathlib import Path

import pytest

from equivalence.automation_job_outcomes import build_cases, comparable, family_complete, run_python, validate_registration


def test_automation_outcomes_needs_every_original_owner_and_evidence():
    cases = build_cases()
    validate_registration(cases)
    with pytest.raises(ValueError):
        validate_registration(cases[:2])
    with pytest.raises(ValueError):
        validate_registration([*cases, cases[-1]])
    assert not family_complete([{**row, "status": "matched"} for row in cases])
    assert family_complete([{**row, "status": "matched", "runtimeEvidenceValidated": True} for row in cases])


def test_new_task_attribution_is_verified_and_existing_descriptions_stay_literal(tmp_path: Path):
    migration = build_cases()[1]
    output = run_python(migration, tmp_path)
    jobs = output["scenarios"][0]["phases"][1]["after"]["jobs"]
    original = deepcopy(output)
    jobs[0]["description"] = "operator-authored"
    normalized = comparable(migration, output, "sdk")
    assert normalized["scenarios"][0]["phases"][1]["after"]["jobs"][0]["description"] == "operator-authored"
    jobs[1]["description"] = "different producer"
    with pytest.raises(ValueError, match="description"):
        comparable(migration, output, "sdk")
    assert comparable(migration, original, "sdk") != output
