"""Fixture integrity controls, not evidence of native behavioral equivalence."""
from copy import deepcopy
import json

from equivalence.flush_execution import _tool_receipt, build_flush_execution_cases, run_flush_execution


def test_execution_catalog_is_deterministic_unique_and_standard_json():
    cases = build_flush_execution_cases()
    assert cases == build_flush_execution_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, ensure_ascii=False, allow_nan=False)) == cases
    assert all(case["operation"] == "flush-execution-runtime" for case in cases)
    assert all(case["requirement"] == "flush.execute-finalize" for case in cases)
    warm = [case for case in cases if case["input"].get("warmIndex")]
    ordinary = [case for case in cases if not case["input"].get("warmIndex")]
    assert len(warm) == 1 and len(ordinary) == 14
    assert all(case["covers"] == ["flush.execute-finalize.outcomes"] for case in ordinary)
    assert warm[0]["covers"] == []
    assert not any("flush.execute-finalize.boundaries" in case["covers"] for case in cases)


def test_content_fixtures_keep_silent_tokens_whitespace_and_newlines_as_actual_tool_inputs():
    cases = build_flush_execution_cases()
    before = deepcopy(cases)
    contents = [call["arguments"]["content"] for case in cases
                for step in case["input"]["steps"] for reply in step["replies"]
                for call in reply.get("toolCalls", []) if call["name"] == "write"]
    for value in ("", "  \r\n", "\n", "NO_REPLY", "  NO_REPLY\n", "tail\r\n"):
        assert value in contents
    assert all(step["replies"][-1] == {"text": "NO_REPLY", "toolCalls": []}
               for case in cases for step in case["input"]["steps"])
    assert cases == before


def test_driver_inputs_preserve_finalization_retries_and_source_identity():
    cases = {case["id"]: case["input"] for case in build_flush_execution_cases()}
    failures = cases["flush-execution-model-failure-exhaustion"]["steps"]
    assert [step["label"] for step in failures] == [
        "failure-one", "failure-two", "failure-three", "same-cycle-suppressed", "next-cycle-success",
    ]
    assert failures[-1]["entryPatch"] == {"compactionCount": 1}
    for arguments in cases.values():
        assert arguments["entry"]["sessionId"] == "source-session"
        assert arguments["sessionKey"] == "agent:main:main"
        assert arguments["sourceMessages"][0]["role"] == "user"


def test_warm_first_recall_is_declared_separately_from_a_forced_sync():
    warm = next(case for case in build_flush_execution_cases()
                if case["id"] == "flush-execution-warm-index-first-recall")
    assert warm["input"]["warmIndex"] is True
    assert warm["input"]["queries"] == ["obsoletekiwi", "freshmangosteen"]
    assert "First recall" in warm["normalizationPolicy"]
    assert "Every actual first-recall result remains compared" in warm["declaredDeviation"]
    assert "boundaries remains uncredited" in warm["declaredDeviation"]
    assert not any("expected" in key.lower() for key in warm)


def test_public_host_driver_preserves_fixture_inputs_and_standard_json_outputs():
    for case in build_flush_execution_cases():
        before = deepcopy(case)
        result = run_flush_execution(case["input"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        assert case == before
        assert len(result["snapshots"]) == len(case["input"]["steps"])


def test_raw_evidence_keeps_actual_model_receipts_and_internal_writer_identity(tmp_path):
    case = next(case for case in build_flush_execution_cases()
                if case["id"] == "flush-execution-sequential-tool-rounds")
    result = run_flush_execution(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list) and len(raw) == 1
    assert raw[0]["request"]["messages"] and raw[0]["request"]["tools"]
    assert raw[0]["request"]["executionSessionId"] != case["input"]["entry"]["sessionId"]
    for receipt, original in zip(result["snapshots"][0]["toolResults"], raw[0]["receipts"], strict=True):
        assert receipt["content"] == original["result"]["content"]
        assert receipt["details"] == original["result"]["details"]
    assert raw[0]["provenanceRaw"][0]["session_id"] == raw[0]["request"]["executionSessionId"]


def test_legacy_receipt_projection_does_not_invent_changed_or_an_error_flag():
    payload = {"status": "ok", "action": "skipped"}
    assert _tool_receipt("write", payload) == {
        "name": "write", "isError": False, "nativeReceiptSupported": False,
        "legacyPayload": payload,
    }
    model_error = {"content": [{"type": "text", "text": '{"status":"error"}'}],
                   "details": {"status": "error"}}
    assert _tool_receipt("write", model_error)["isError"] is False
