"""SDK transport input/deadline checks, with no invented positive capture."""
from copy import deepcopy
import os

import pytest

from equivalence.forget_index_fence_sdk_watch_transport_evidence import (
    HOLD_NS, _held_kill_interval, _no_interrupted_source_mutations, validate_sdk_watch_transport_v5,
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


def _labelled_open_fragments(flags):
    """Labelled argument fragments, never a fabricated genuine capture."""
    arguments = ["/labelled/workspace/MEMORY.md", flags]
    io = [{"event": "original-source-io-return", "syscall": "open",
           "arguments": arguments, "returned": 17}]
    calls = {1: {"event": "original-call", "name": "_io", "callKind": "forget",
                 "callLabel": "selected", "arguments": {
                     "function": {"module": "posix", "qualname": "open"}, "args": arguments}}}
    return io, calls


@pytest.mark.parametrize("flags", [os.O_RDONLY, os.O_RDONLY | os.O_NOFOLLOW,
                                    os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY])
def test_readonly_source_open_fragments_remain_nonmutating_without_capture_credit(flags):
    io, events = _labelled_open_fragments(flags)
    assert _no_interrupted_source_mutations(io, events, label="selected") is None


@pytest.mark.parametrize("channel", ["original-return", "original-entry-only"])
@pytest.mark.parametrize("flags", [os.O_WRONLY, os.O_RDWR, os.O_WRONLY | os.O_APPEND,
                                    os.O_RDONLY | os.O_TRUNC, os.O_RDONLY | os.O_CREAT,
                                    os.O_WRONLY | os.O_CREAT | os.O_EXCL])
def test_interrupted_negative_refuses_original_source_writable_open_admission(channel, flags):
    io, events = _labelled_open_fragments(flags)
    if channel == "original-return":
        events = {}
    else:
        io = []
    with pytest.raises(ValueError, match="open admission"):
        _no_interrupted_source_mutations(io, events, label="selected")


@pytest.mark.parametrize("flags", [False, True, "0", 0.0, -1])
@pytest.mark.parametrize("channel", ["original-return", "original-entry-only"])
def test_source_open_flags_are_exact_integer_arguments(channel, flags):
    io, events = _labelled_open_fragments(flags)
    with pytest.raises(ValueError, match="integer flags"):
        _no_interrupted_source_mutations(io if channel == "original-return" else [],
                                        events if channel == "original-entry-only" else {}, label="selected")


@pytest.mark.parametrize("syscall", ["write", "pwrite", "replace", "unlink", "ftruncate"])
@pytest.mark.parametrize("channel", ["original-return", "original-entry-only"])
def test_existing_interrupted_source_mutation_refusals_remain_exact(syscall, channel):
    io = [{"event": "original-source-io-return", "syscall": syscall}]
    events = {1: {"event": "original-call", "name": "_io", "callKind": "forget",
                  "callLabel": "selected", "arguments": {"function": {"qualname": syscall}}}}
    with pytest.raises(ValueError, match="mutation|write attempt"):
        _no_interrupted_source_mutations(io if channel == "original-return" else [],
                                        events if channel == "original-entry-only" else {}, label="selected")
