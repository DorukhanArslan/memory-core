"""The scratch lane cannot borrow unrelated execution or source authority."""
import pytest

from equivalence.heartbeat_node_authority import APPROVED_NODE, validate_heartbeat_node_authority
from equivalence.heartbeat_scratch_probe import build_cases, _same_json_wire


def _capability():
    return {"kind": "heartbeat-scratch-node-capability", "profile": "heartbeat-scratch-store",
            "node": {"execPath": "/approved/node", **APPROVED_NODE}}


@pytest.mark.parametrize("change", [
    lambda value: value.update(profile="turn-trust-runtime"),
    lambda value: value.update(profile="entry-provider-preparation-runtime"),
    lambda value: value.update(approvedReferenceSources=[]),
    lambda value: value["node"].update(sha256="0" * 64),
    lambda value: value["node"].update(unicodeVersion="16.0"),
    lambda value: value["node"].update(execPath="relative/node"),
])
def test_heartbeat_capability_rejects_cross_profile_and_changed_runtime(change):
    value = _capability()
    change(value)
    with pytest.raises(ValueError):
        validate_heartbeat_node_authority(value)


def test_heartbeat_capability_copies_its_exact_approved_identity():
    value = _capability()
    validated = validate_heartbeat_node_authority(value)
    value["node"]["sha256"] = "0" * 64
    assert validated["node"]["sha256"] == APPROVED_NODE["sha256"]


def test_proposal_keeps_all_fixed_scope_conditions_uncredited_and_has_reconstruction_inputs():
    cases = build_cases()
    assert all(case["covers"] == [] and case["requirement"] == "heartbeat.scratch" for case in cases)
    assert len({case["id"] for case in cases}) == len(cases)
    reconstructed = [case for case in cases if len(case["phases"]) > 1]
    assert reconstructed
    assert all(not phase["initialize"] for case in reconstructed for phase in case["phases"][1:])


def test_input_wire_comparison_preserves_exact_utf16_and_normalization_forms():
    assert _same_json_wire({"input": "a\ud83d\ude00b"}, {"input": "a😀b"})
    assert not _same_json_wire({"input": "\ud800"}, {"input": "�"})
    assert not _same_json_wire({"input": "café"}, {"input": "cafe\u0301"})
