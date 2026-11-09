"""The default lane retains all original cases and actual fresh SDK execution."""
import json
import os

import pytest

from equivalence.trust_worker_probe import _cases
from equivalence.trust_worker_profile import (
    build_trust_worker_cases, run_trust_worker,
)


def test_default_lane_retains_every_original_worker_scheduling_input():
    cases = build_trust_worker_cases()
    assert len(cases) == 5
    assert [case["input"] for case in cases] == [case["input"] for case in _cases()]
    assert all(case["covers"] == [] and case["operation"] == "trust-worker-runtime" for case in cases)
    assert len({case["id"] for case in cases}) == 5
    cases[0]["input"]["secret"] = "changed locally"
    assert build_trust_worker_cases()[0]["input"]["secret"] == "worker-fixture-credential"


@pytest.mark.parametrize("value", [
    {"secret": "undeclared", "sessionKind": "interactive", "mutations": 0},
    {"secret": "worker-fixture-credential", "sessionKind": "interactive", "mutations": True},
    {"secret": "worker-fixture-credential", "sessionKind": "interactive", "mutations": 1.0},
    {"secret": "worker-fixture-credential", "sessionKind": "interactive", "mutations": 3},
    {"secret": "worker-fixture-credential", "sessionKind": "interactive", "mutations": 0, "registry": []},
])
def test_nonliteral_or_ambient_registry_capability_is_rejected_before_execution(value, tmp_path):
    with pytest.raises(ValueError, match="Only the five declared synthetic worker inputs"):
        run_trust_worker(value, evidence_directory=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("case", build_trust_worker_cases(), ids=lambda case: case["id"])
def test_actual_sdk_child_retains_complete_streams_source_and_process_receipts(case, tmp_path):
    result = run_trust_worker(case["input"], evidence_directory=tmp_path)
    raw, = json.loads((tmp_path / "python-raw.json").read_text())
    child = raw["child"]
    observed = child["observation"]
    assert raw["coordinatorPid"] == os.getpid() and child["pid"] != os.getpid()
    assert raw["input"] == child["request"]["input"] == case["input"]
    assert json.loads(child["stdout"]) == observed
    assert set(result) == {"provider", "result", "error", "transcript"}
    assert result["transcript"] == {"before": observed["before"]["events"], "after": observed["after"]["events"]}
    assert observed["before"] == observed["after"]
    assert child["exit"] == {"code": 0}
    assert "preparations" in observed and "mutations" in observed and "callbackObservations" in observed
    assert set(child["environmentKeys"]) == {"PATH", "PYTHONPATH", "LANG", "TZ", "OPENCLAW_STATE_DIR",
                                             "OPENCLAW_CONFIG_PATH", "OPENCLAW_HOME"}
