"""Reject tampering with captured genuine source-worker confidentiality evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.trust_worker_probe import _assert_synthetic_registry, _validate_native


def _capture():
    return json.loads((Path(__file__).parents[1] / "fixtures/trust-worker-changed-once.json").read_text())


def test_actual_captured_worker_pair_is_valid_without_ignoring_its_complete_result():
    captured = _capture()
    _validate_native(captured["native"], captured["input"], captured["runtimeRoot"])


@pytest.mark.parametrize("tamper", ["accepted-result", "reply-result", "reply-task", "snapshot-revision",
                                   "worker-url", "source-mutation", "missing-dispatch", "extra-attempt"])
def test_forged_worker_acceptance_or_source_is_rejected(tamper):
    captured = _capture()
    value = captured["native"]
    dispatches = [item for item in value["observations"] if item["event"] == "preparation-dispatch"]
    replies = [item for item in value["observations"] if item["event"] == "actual-preparation-reply"]
    if tamper == "accepted-result":
        value["result"]["content"] = "A forged accepted source"
    elif tamper == "reply-result":
        replies[-1]["reply"]["value"]["value"]["entry"]["content"] = "A forged prepared source"
    elif tamper == "reply-task":
        replies[-1]["reply"]["taskId"] += 1
    elif tamper == "snapshot-revision":
        dispatches[0]["message"]["input"]["redaction"]["registryRevision"] += 100
    elif tamper == "worker-url":
        dispatches[-1]["url"] = "file:///reference/openclaw/dist/unrelated-worker.js"
    elif tamper == "source-mutation":
        value["after"][-1]["message"]["content"] = "Source changed during proof"
    elif tamper == "missing-dispatch":
        value["observations"].remove(dispatches[0])
    else:
        value["observations"].extend([deepcopy(dispatches[-1]), deepcopy(replies[-1])])
        value["attempts"] += 1
    with pytest.raises(ValueError):
        _validate_native(value, captured["input"], captured["runtimeRoot"])


def test_a_stable_first_reply_cannot_be_reported_as_needing_another_original_retry():
    captured = _capture()
    captured["native"]["mutations"].clear()
    with pytest.raises(ValueError, match="must accept a stable preparation"):
        _validate_native(captured["native"], captured["input"], captured["runtimeRoot"])


@pytest.mark.parametrize("values", [["not-a-declared-fixture"], [7], [{}], "worker-fixture-credential"])
def test_sensitive_snapshot_rejection_never_prints_an_undeclared_value(values):
    with pytest.raises(ValueError) as raised:
        _assert_synthetic_registry(values)
    assert str(raised.value) == "Undeclared registry member; sensitive snapshot was not recorded"
