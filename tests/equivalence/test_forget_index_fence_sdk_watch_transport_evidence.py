"""SDK transport input/deadline checks, with no invented positive capture."""
from copy import deepcopy

import pytest

from equivalence.forget_index_fence_sdk_watch_transport_evidence import (
    HOLD_NS, _held_kill_interval, validate_sdk_watch_transport_v5,
)
from equivalence.forget_index_fence_v5 import build_cases


def test_held_kill_exact_deadline_arithmetic_does_not_claim_a_capture():
    assert _held_kill_interval("1000", "1001", "1002", "1003", "1004") is None


@pytest.mark.parametrize("values", [
    ("1000", "999", "1002", "1003", "1004"),
    ("1000", "1002", "1001", "1003", "1004"),
    ("1000", "1001", "1002", "1001", "1004"),
    ("1000", "1001", "1002", "1003", "1002"),
    ("1000", "1001", str(1000 + HOLD_NS), str(1001 + HOLD_NS), str(1002 + HOLD_NS)),
    ("1000", "1001", str(1001 + HOLD_NS), str(1002 + HOLD_NS), str(1003 + HOLD_NS)),
    (True, "1001", "1002", "1003", "1004"),
    (1000, "1001", "1002", "1003", "1004"),
])
def test_interruption_cannot_outlive_its_actual_gate_or_coerce_clock_fields(values):
    with pytest.raises(ValueError):
        _held_kill_interval(*values)


@pytest.mark.parametrize("case", build_cases(), ids=lambda case: case["id"])
def test_omitted_real_host_steps_never_supply_watch_transport_proof(case):
    with pytest.raises(ValueError, match="omitted frozen host steps"):
        validate_sdk_watch_transport_v5(case, {"input": case["input"], "steps": []}, {}, {}, {})


def test_transport_rejects_unfrozen_profile_before_consuming_actor_metadata():
    case = deepcopy(build_cases()[0])
    case["input"]["kind"] = "forget-index-fence-v5-unregistered"
    with pytest.raises(ValueError):
        validate_sdk_watch_transport_v5(case, {}, {}, {}, {})
