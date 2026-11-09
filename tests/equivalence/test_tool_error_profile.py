"""Default error cases execute real factories and retain complete original wires."""
import json
import os
from pathlib import Path

import pytest

from equivalence.search_contract import decode_search_tool_envelope
from equivalence.tool_error_profile import (
    assert_synthetic_error_registry, build_tool_error_cases, run_tool_error_profile,
)
from equivalence.trust_error_probe import _cases


def test_default_error_lane_retains_all_four_original_literal_inputs():
    cases = build_tool_error_cases()
    assert len(cases) == 4
    assert [case["input"] for case in cases] == [case["input"] for case in _cases()]
    assert all(case["covers"] == [] and case["operation"] == "model-tool-error-runtime" for case in cases)
    cases[0]["input"]["error"]["message"] = "changed"
    assert build_tool_error_cases()[0]["input"]["error"]["message"] != "changed"


@pytest.mark.parametrize("value", [{}, {"error": {"message": "unknown"}},
                                   {"registeredSecrets": ["not-declared"], "error": {"message": "unknown"}}])
def test_arbitrary_errors_or_registry_inputs_reject_before_execution(value, tmp_path):
    with pytest.raises(ValueError, match="Only the four declared synthetic"):
        run_tool_error_profile(value, evidence_directory=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("values", [["not-declared"], [7], "demo-supplement-credential"])
def test_undeclared_registry_rejection_does_not_print_its_contents(values):
    with pytest.raises(ValueError) as raised:
        assert_synthetic_error_registry(values)
    assert str(raised.value) == "Undeclared error registry member; sensitive snapshot was not recorded"


@pytest.mark.parametrize("case", build_tool_error_cases(), ids=lambda case: case["id"])
def test_actual_fresh_sdk_tools_retain_original_formatter_and_every_envelope_field(case, tmp_path):
    public = run_tool_error_profile(case["input"], evidence_directory=tmp_path)
    record, = json.loads((tmp_path / "python-raw.json").read_text())
    child = record["child"]
    observation = child["observation"]
    raw = observation["raw"]
    assert json.loads(child["stdout"]) == observation
    assert record["coordinatorPid"] == os.getpid() != child["pid"] == raw["pid"]
    assert raw["ppid"] == os.getpid()
    assert record["input"] == raw["input"] == child["request"]["input"] == case["input"]
    assert set(public) == {"provider", "formatter", "tools"} and public["provider"] == "none"
    assert raw["registry"]["before"] == {"revision": 0, "values": []}
    assert len(raw["registry"]["registrations"]) == len(case["input"].get("registeredSecrets", []))
    assert [item["tool"] for item in raw["requests"]] == ["get", "search"]
    assert all(item["throwsRegisteredError"] is True for item in raw["requests"])
    assert [item["options"] for item in raw["requests"]] == [
        {"lookup": "topic", "agent_id": "main"}, {"query": "topic", "agent_id": "main"}]
    assert [item["callId"] for item in raw["invocations"]] == ["diagnostic-get", "diagnostic-search"]
    assert raw["error"]["message"] == case["input"]["error"]["message"]
    if "cause" in case["input"]["error"]:
        assert raw["error"]["cause"]["message"] == case["input"]["error"]["cause"]["message"]
        assert raw["error"]["cause"]["properties"]["code"] == "ECONNRESET"
    for tool, invocation in zip(public["tools"], raw["invocations"], strict=True):
        assert set(tool) == {"name", "envelope", "decoded"}
        assert tool["envelope"] == invocation["envelope"]
        assert tool["decoded"] == decode_search_tool_envelope(tool["envelope"])
    captures = json.loads((Path(__file__).parents[1] / "fixtures/tool-error-profile-captures.json").read_text())
    capture, = [item for item in captures["observations"] if item["input"] == case["input"]]
    native = capture["native"]
    assert public["formatter"] == native["result"]["formatter"]
    assert public["tools"] == [{"name": item["tool"], "envelope": item["envelope"],
                                "decoded": native["result"][item["tool"]]} for item in native["raw"]["nativeEnvelopes"]]
    assert set(child["environmentKeys"]) == {"PATH", "PYTHONPATH", "LANG", "TZ", "OPENCLAW_STATE_DIR",
                                             "OPENCLAW_CONFIG_PATH", "OPENCLAW_HOME"}
