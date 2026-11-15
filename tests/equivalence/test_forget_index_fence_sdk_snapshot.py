"""Pure live-journal and JSON transport regressions; no SDK engine or actor runs."""
from copy import deepcopy
import io
import json
import threading
from types import SimpleNamespace

import pytest

from equivalence import forget_index_fence_sdk as sdk


def _copy_during_real_thread_mutation(copy):
    entered, mutated = threading.Event(), threading.Event()

    class PauseNestedCopy:
        def __deepcopy__(self, memo):
            entered.set()
            assert mutated.wait(3), "The real writer thread did not mutate the live journal"
            return {"copiedNestedWitness": True}

    journal = {"first": PauseNestedCopy(), "later": {"before": True}}

    def write():
        assert entered.wait(3), "Recursive copying did not reach the controlled nested value"
        journal["addedByWorker"] = {"actual": True}
        journal["later"]["addedBeforeItsOwnCopy"] = 9
        mutated.set()

    worker = threading.Thread(target=write)
    worker.start()
    try:
        return copy(journal), journal
    finally:
        worker.join(4)
        assert not worker.is_alive()


def test_old_deepcopy_reproduces_live_journal_size_failure_with_real_writer_thread():
    with pytest.raises(RuntimeError, match="dictionary changed size during iteration"):
        _copy_during_real_thread_mutation(deepcopy)


def test_observation_copy_captures_each_container_membership_without_claiming_global_atomicity():
    copied, original = _copy_during_real_thread_mutation(sdk._observation_copy)
    assert "addedByWorker" in original and "addedByWorker" not in copied
    assert copied["first"] == {"copiedNestedWitness": True}
    # The outer dict was copied before the writer; this nested dict was copied
    # afterwards. That is per-container custody, not one global atomic snapshot.
    assert copied["later"] == {"before": True, "addedBeforeItsOwnCopy": 9}
    assert copied["later"] is not original["later"]


def _fake_process(monkeypatch, response):
    line = json.dumps(response, separators=(",", ":")) + "\n"
    process = sdk._ActorProcess.__new__(sdk._ActorProcess)
    process.actor = "labelled-test-actor"
    process.counter = 0
    process.acquired = False
    process.child = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(line), pid=902)
    process.receipt = {"stdinCommands": [], "stdoutResponses": [], "stdoutLines": []}
    monkeypatch.setattr(sdk.select, "select", lambda readers, writers, errors, timeout: (readers, [], []))
    return process, line


def test_fatal_before_command_id_is_classified_as_control_failure_and_complete_line_is_retained(monkeypatch):
    response = {"fatal": {"name": "LabelledCodecFailure", "message": "exact fatal message",
                           "traceback": "complete original fatal stack"},
                "pid": 902, "result": {"alreadyCaptured": {"rawCount": 4, "typedFlag": False}}}
    process, line = _fake_process(monkeypatch, response)
    with pytest.raises(RuntimeError, match="fatal control failure") as raised:
        process.command("observe")
    assert "another command" not in str(raised.value)
    assert process.receipt["stdoutLines"] == [line]
    assert process.receipt["stdoutResponses"] == [response]
    assert process.receipt["observationFailures"] == [{"commandId": 1, "fatal": response["fatal"]}]
    assert process.receipt["stdoutResponses"][0]["result"] == response["result"]
    assert json.loads(process.child.stdin.getvalue()) == {"id": 1, "operation": "observe"}


def test_observation_invalid_keeps_actual_public_settlement_separate_from_observer_failure(monkeypatch):
    actual = {"kind": "sync", "label": "old", "returned": 3,
              "outcome": {"status": "fulfilled", "isTypedConflict": False}, "returnSeq": 19}
    invalid = {"phase": "actor-observation", "error": {"name": "LabelledCopyFailure", "message": "journal changed"}}
    response = {"id": 1, "ok": True, "result": actual, "observationInvalid": invalid}
    process, line = _fake_process(monkeypatch, response)
    before = deepcopy(response)
    with pytest.raises(RuntimeError, match="observer failed after the actual command settlement"):
        process.command("await-call", kind="sync", label="old")
    assert response == before
    assert process.receipt["stdoutLines"] == [line]
    captured = process.receipt["stdoutResponses"][0]
    assert captured["ok"] is True and captured["result"] == actual
    assert type(captured["result"]["returned"]) is int
    assert "error" not in captured["result"]
    assert process.receipt["observationFailures"] == [{"commandId": 1, **invalid}]


def test_genuine_wrong_command_id_remains_rejected_after_retaining_complete_response(monkeypatch):
    response = {"id": 2, "ok": True, "result": {"actual": "other-command-result"}}
    process, line = _fake_process(monkeypatch, response)
    with pytest.raises(RuntimeError, match="another command's receipt"):
        process.command("observe")
    assert process.receipt["stdoutLines"] == [line]
    assert process.receipt["stdoutResponses"] == [response]
    assert "observationFailures" not in process.receipt
