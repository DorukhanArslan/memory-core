"""Labelled interruption custody; no completed call or version is invented."""
from copy import deepcopy

import pytest

from equivalence.forget_index_fence_sdk import _interrupted_source_call


def _labelled_cutoff():
    call = {"kind": "forget", "label": "selected", "actor": "forgetter", "pid": 1234,
        "enterSeq": 7, "apiEntry": {"sequence": 8}, "termination": {"signal": "SIGKILL", "pid": 1234}}
    observation = {"publicCalls": {"forget:selected": {key: deepcopy(value) for key, value in call.items()
                    if key != "termination"}},
        "functionalGates": {"marker": {"reached": True, "released": False,
            "specification": {"boundary": "forget.marker-committed-before-purge", "callLabel": "selected"},
            "hits": [{"triggerSequence": 17, "originalFrame": {"qualname": "purge_memory_index"}}]}},
        "originalCalls": [{"sequence": 17}], "sourceClockReceipts": [],
        "sourceClockOriginalIO": [{"sequence": 12, "syscall": "read", "returned": {"bytesHex": "6162"},
            "scope": {"kind": "forget", "label": "selected"}}]}
    process = {"pid": 1234, "kill": {"pid": 1234, "signal": "SIGKILL", "pollBefore": None},
        "exit": {"code": -9}, "reapedAtNs": "101", "stdoutResponses": [{"id": 9, "observation": observation}]}
    return call, process


def test_interrupted_source_receipt_keeps_pending_frame_gate_and_os_proof_separate_from_completion():
    call, process = _labelled_cutoff()
    result = _interrupted_source_call("forget:selected", call, [process])
    assert result["kind"] == "original-interrupted-source-call"
    assert result["sourceObservation"] == {"pid": 1234, "commandId": 9, "stdoutResponseIndex": 0}
    assert result["call"] == call and "returnSeq" not in result["call"]
    assert "watchTargetCapture" not in result["call"]
    assert "versions" not in result and "sourceVersions" not in result
    assert result["kill"] == process["kill"] and result["reap"]["exit"] == {"code": -9}
    assert result["sourceIOCutoff"]["originalIO"] == process["stdoutResponses"][0]["observation"]["sourceClockOriginalIO"]


@pytest.mark.parametrize("mutation", ["completion", "unreaped", "released-gate", "source-write", "clock-commit"])
def test_missing_or_mutating_interruption_proof_fails_without_fabricating_an_empty_capture(mutation):
    call, process = _labelled_cutoff()
    observation = process["stdoutResponses"][0]["observation"]
    if mutation == "completion":
        call["returnSeq"] = 19
    elif mutation == "unreaped":
        process["exit"] = None
    elif mutation == "released-gate":
        observation["functionalGates"]["marker"]["released"] = True
    elif mutation == "source-write":
        observation["sourceClockOriginalIO"].append({"sequence": 13, "syscall": "unlink",
            "scope": {"kind": "forget", "label": "selected"}, "arguments": ["/actual/source.md"], "returned": None})
    else:
        observation["sourceClockReceipts"].append({"callKey": "forget:selected", "committed": True})
    with pytest.raises(RuntimeError):
        _interrupted_source_call("forget:selected", call, [process])
    assert "watchTargetCapture" not in call
