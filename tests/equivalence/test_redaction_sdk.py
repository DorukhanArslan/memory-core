"""Actual isolated SDK callers retain registry, identity and durable evidence."""
from copy import deepcopy
import json
import os

import pytest

from equivalence.redaction_fixtures import (
    build_redaction_cases, model_helper_fixtures, model_session_fixtures, source_policy_fixtures,
)
from equivalence.redaction_sdk import RedactionChildError, run_model_sessions, run_model_tool_result, run_redaction_policy


def _fixture(rows, suffix):
    return next(row["input"] for row in rows if row["id"].endswith(suffix))


def test_all_existing_redaction_callers_and_residuals_are_ordinary_default_cases():
    cases = build_redaction_cases()
    assert len(cases) == len({row["id"] for row in cases}) == 61
    assert all(row["covers"] == [] for row in cases)
    expected = {"redaction-policy-source": 34, "model-tool-result-runtime": 6, "model-session-runtime": 12,
                "trust-worker-runtime": 5, "model-tool-error-runtime": 4}
    assert {operation: sum(row["operation"] == operation for row in cases) for operation in expected} == expected
    for suffix in ("letter-mixed-i-engine-diagnostic", "letter-repeated-capture-engine-diagnostic",
                   "unsupported-valid-general-property", "unsupported-valid-v-direct-compiler"):
        assert any(row["id"].endswith(suffix) for row in cases)


@pytest.mark.parametrize("suffix", ["host-full-context-cross-16384", "registered-uri-json-off", "unicode-literal-lone-surrogate"])
def test_source_owner_uses_a_fresh_process_without_parent_credentials(suffix, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-parent-only-provider-key")
    value = _fixture(source_policy_fixtures(), suffix)
    output = run_redaction_policy(value, evidence_directory=tmp_path)
    assert output["registry"]["before"] == {"revision": 0, "values": []}
    assert output["result"]["policy"]["registryRevision"] == output["registry"]["after"]["revision"]
    raw_text = (tmp_path / "python-raw.json").read_text()
    assert "synthetic-parent-only-provider-key" not in raw_text
    raw = json.loads(raw_text)[0]
    child = raw["children"][0]
    assert child["raw"]["pid"] == child["pid"] != os.getpid()
    assert child["raw"]["ppid"] == raw["coordinatorPid"] == os.getpid()
    assert child["exit"] == {"code": 0, "signal": None}


@pytest.mark.parametrize("fixture", model_helper_fixtures(), ids=lambda row: row["id"])
def test_whole_model_helper_retains_all_actual_identity_observations(fixture, tmp_path):
    output = run_model_tool_result(fixture["input"], evidence_directory=tmp_path)
    assert set(output) == {"provider", "result", "identity"}
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    actual = raw["children"][0]["raw"]
    assert actual["output"] == output
    assert actual["registrySnapshots"][0] == {"revision": 0, "values": []}
    if "value" in fixture["input"]:
        assert output["identity"] == {"sanitizedOutputReuse": True, "originalInputReuse": False}
    else:
        assert set(output["identity"]) == {"preparedBlockReuse", "storageMessageReuse", "storageBlockPrepared"}


@pytest.mark.parametrize("suffix", ["guarded-nonidempotent-order", "registered-encoded-forms"])
def test_session_uses_three_real_processes_and_identity_only_unregistered_verification(suffix, tmp_path):
    value = _fixture(model_session_fixtures(), suffix)
    output = run_model_sessions(value, evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    assert [row["phase"] for row in output["phases"]] == ["write", "continue", "verify"]
    phases = raw["phases"]
    assert len({row["pid"] for row in phases}) == 3
    assert all(row["pid"] != os.getpid() and row["raw"]["ppid"] == os.getpid() for row in phases)
    assert all(int(left["finishedAtNs"]) <= int(right["startedAtNs"]) for left, right in zip(phases, phases[1:]))
    verify = phases[-1]
    assert set(verify["request"]["input"]) == {"nowMs", "agentId", "sessionId", "sessionKey"}
    assert verify["request"]["phase"] == {"label": "verify"}
    assert verify["raw"]["registrySnapshots"] == [{"revision": 0, "values": []}, {"revision": 0, "values": []}]
    assert verify["raw"]["beforeSql"] == verify["raw"]["afterSql"]
    assert output["phases"][-1]["storedMessages"] == output["phases"][0]["storedMessages"] + output["phases"][1]["persistedMessages"]
    if suffix == "guarded-nonidempotent-order":
        tool = next(row for row in output["phases"][-1]["storedMessages"] if row["role"] == "toolResult")
        assert tool["content"][0]["text"] == "***" and tool["details"]["token"] == "*" * 81


def test_failed_actual_child_keeps_its_original_streams_and_exit_receipt(tmp_path):
    value = deepcopy(source_policy_fixtures()[0]["input"])
    value["kind"] = "invalid"
    with pytest.raises(RedactionChildError, match="process failed"):
        run_redaction_policy(value, evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    child = raw["children"][0]
    assert child["exit"]["code"] != 0
    assert json.loads(child["stdout"])["fatal"]["type"] == "ValueError"
    assert json.loads(child["stdout"])["pid"] == child["pid"]
    assert child["stderr"]
