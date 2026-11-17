"""Closed prompt authority and evidence forgery checks; no business engine runs."""
from copy import deepcopy
import base64
import gzip
import hashlib
import json

import pytest

from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.prompt_runtime_context import (
    CASE_HASHES, POINTS, build_cases, canonical, family_complete, validate_registration,
)
from equivalence.prompt_runtime_context_evidence import (
    MAX_NATIVE_CAPTURE_BYTES, _history, _ordered_tokens, _tools, decode_native_capture,
)
from equivalence.prompt_runtime_context_profile import case_bindings, validate_prompt_runtime_context_profile
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError


def _profile():
    case = build_cases()[0]
    return {"kind": "approved-prompt-runtime-context-profile", "operation": case["operation"],
            "inputKind": "prompt-runtime-context", "caseId": case["id"], "caseBindings": case_bindings(),
            "nodeRuntime": {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME}}


def test_exact_complete_family_authorizes_only_both_original_prompt_points():
    cases = build_cases()
    validate_registration(cases)
    assert len(cases) == len(CASE_HASHES) == 10
    assert POINTS == ("prompt.runtime-context.outcomes", "prompt.runtime-context.boundaries")
    assert all(case["covers"] == list(POINTS) for case in cases)
    assert hashlib.sha256(canonical(CASE_HASHES)).hexdigest() == (
        "1a245537eb8ca6f96d8987756ae607a24f6fef010acc2a26f803d18f6358fe22")
    assert validate_prompt_runtime_context_profile(_profile()) == _profile()


def test_missing_duplicated_reordered_mutated_or_widened_family_is_rejected():
    for mutation in ("missing", "duplicate", "order", "input", "coverage"):
        cases = deepcopy(build_cases())
        if mutation == "missing":
            cases.pop()
        elif mutation == "duplicate":
            cases.append(deepcopy(cases[0]))
        elif mutation == "order":
            cases.reverse()
        elif mutation == "input":
            cases[0]["input"]["operations"][0]["tools"].append("memory_search")
        else:
            cases[0]["covers"].append("prompt.unapproved.outcomes")
        with pytest.raises(ValueError):
            validate_registration(cases)


def test_two_point_credit_requires_every_case_matched_and_actual_evidence_validated():
    baseline = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in build_cases()]
    assert family_complete(baseline)
    for mutation in ("missing", "failed", "unvalidated", "false-validation"):
        rows = deepcopy(baseline)
        if mutation == "missing":
            rows.pop()
        elif mutation == "failed":
            rows[-1]["status"] = "mismatched"
        elif mutation == "unvalidated":
            rows[-1].pop("runtimeEvidenceValidated")
        else:
            rows[-1]["runtimeEvidenceValidated"] = False
        assert not family_complete(rows)
    assert not family_complete([])


def test_forged_or_borrowed_profile_fails_before_original_context_creation():
    for key in ("caseId", "caseBindings", "operation", "covers"):
        profile = _profile()
        if key == "caseBindings":
            profile[key][profile["caseId"]] = "0" * 64
        elif key == "covers":
            profile[key] = list(POINTS)
        else:
            profile[key] = "unapproved"
        with pytest.raises(ValueError):
            validate_prompt_runtime_context_profile(profile)
    for peer in ({"fixture_captures": True}, {"session_reset_boundaries_profile": {}},
                 {"embedding_cache_profile": {}}):
        with pytest.raises(RuntimeOracleError, match="cannot borrow"):
            with ReleaseOracleExecution({}, {}, prompt_runtime_context_profile=_profile(), **peer):
                raise AssertionError("Borrowed authority reached original execution")


def test_fragment_order_and_durable_history_custody_reject_forged_evidence():
    _ordered_tokens("inbound instruction data", ["inbound", "instruction", "data"])
    with pytest.raises(ValueError, match="insertion order"):
        _ordered_tokens("data instruction inbound", ["inbound", "instruction", "data"])
    sql = {"schema": [], "tables": {}}
    original = {"type": "message", "id": "old", "message": {"role": "user", "content": "retained"}}
    operation = {"beforeTranscript": [original], "afterTranscript": [deepcopy(original)],
                 "beforeSql": {"catalog": sql}, "afterSql": {"catalog": sql}}
    _history(operation, {"op": "submit"}, {"transientTokens": ["runtimeprivate"]})
    altered = deepcopy(operation)
    altered["afterTranscript"][0]["message"]["content"] = "rewritten"
    with pytest.raises(ValueError, match="existing durable"):
        _history(altered, {"op": "submit"}, {})
    leaked = deepcopy(operation)
    leaked["afterTranscript"].append({"type": "message", "message": {"role": "user", "content": "runtimeprivate"}})
    with pytest.raises(ValueError, match="leaked"):
        _history(leaked, {"op": "submit"}, {"transientTokens": ["runtimeprivate"]})


def test_whole_tool_result_requires_real_before_after_receipts_and_source_custody():
    script = {"id": "get", "name": "memory_get", "arguments": {"path": "memory/a.md", "from": 1, "lines": 20}}
    business = {"status": "ok", "path": "memory/a.md", "from": 1, "lines": 1, "text": "owned source\n"}
    content = [{"type": "text", "text": json.dumps(business)}]
    result = {"content": content, "details": business}
    response = {"role": "assistant", "content": [{"type": "toolCall", **script}]}
    tool_message = {"role": "toolResult", "toolCallId": "get", "toolName": "memory_get", "isError": False,
                    "content": deepcopy(content)}
    payload = b"owned source\n"
    operation = {"providerCalls": [{"response": response}, {"request": {"context": {
        "messages": [deepcopy(response), tool_message]}}}], "toolCalls": [
            {"hook": "before_tool_call", "event": {"toolName": "memory_get", "toolCallId": "get", "params": script["arguments"]}},
            {"hook": "after_tool_call", "event": {"toolName": "memory_get", "toolCallId": "get",
             "params": script["arguments"], "result": result}}],
        "sourcesAfter": {"memory/a.md": {"bytes": {"hex": payload.hex(), "size": len(payload),
                                                 "sha256": hashlib.sha256(payload).hexdigest()}}}}
    specification = {"scriptedTools": [script]}
    _tools(specification, operation, True)
    for mutation in ("missing-hook", "forged-content", "forged-source"):
        altered = deepcopy(operation)
        if mutation == "missing-hook":
            altered["toolCalls"].pop()
        elif mutation == "forged-content":
            altered["providerCalls"][1]["request"]["context"]["messages"][-1]["content"][0]["text"] = "replacement"
        else:
            altered["toolCalls"][-1]["event"]["result"]["details"]["text"] = "invented source"
            altered["toolCalls"][-1]["event"]["result"]["content"][0]["text"] = json.dumps(
                altered["toolCalls"][-1]["event"]["result"]["details"])
            altered["providerCalls"][1]["request"]["context"]["messages"][-1]["content"] = deepcopy(
                altered["toolCalls"][-1]["event"]["result"]["content"])
        with pytest.raises(ValueError):
            _tools(specification, altered, True)


def _transport(raw):
    data = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    return {"kind": "prompt-runtime-context-lossless-raw", "encoding": "gzip-json-base64",
            "uncompressedBytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "data": base64.b64encode(gzip.compress(data)).decode("ascii")}


def test_lossless_native_capture_retains_whole_raw_and_rejects_corruption():
    raw = [{"kind": "prompt-runtime-context-native-raw", "unknownFields": {
        "messages": [{"role": "user", "content": "İstanbul\n\u0085\ufeff"}],
        "complete": [None, True, False, {"physicalBytes": "00ff"}]}}]
    transport = _transport(raw)
    assert decode_native_capture(transport) == raw
    for mutation in ("base64", "truncated", "extra-frame", "hash", "length", "duplicate-key", "overflow"):
        altered = deepcopy(transport)
        compressed = base64.b64decode(altered["data"])
        if mutation == "base64":
            altered["data"] += "!"
        elif mutation == "truncated":
            altered["data"] = base64.b64encode(compressed[:-1]).decode("ascii")
        elif mutation == "extra-frame":
            altered["data"] = base64.b64encode(compressed + gzip.compress(b"[]")).decode("ascii")
        elif mutation == "hash":
            altered["sha256"] = "0" * 64
        elif mutation == "length":
            altered["uncompressedBytes"] -= 1
        else:
            data = (b'[{"kind":"prompt-runtime-context-native-raw","kind":"prompt-runtime-context-native-raw"}]'
                    if mutation == "duplicate-key" else b'[{"kind":"prompt-runtime-context-native-raw","number":1e400}]')
            altered.update(data=base64.b64encode(gzip.compress(data)).decode("ascii"),
                           sha256=hashlib.sha256(data).hexdigest(), uncompressedBytes=len(data))
        with pytest.raises(ValueError):
            decode_native_capture(altered)


def test_native_raw_size_and_family_authority_fail_closed_before_decompression(monkeypatch):
    from equivalence import prompt_runtime_context_evidence as evidence

    assert MAX_NATIVE_CAPTURE_BYTES == 128 * 1024**2
    transport = _transport([{"kind": "prompt-runtime-context-native-raw"}])

    def forbidden_decompression(*_args, **_kwargs):
        raise AssertionError("Rejected authority reached decompression")

    monkeypatch.setattr(evidence.zlib, "decompressobj", forbidden_decompression)
    for mutation in ("size", "boolean-size", "kind", "encoding", "extra-field", "plain-singleton"):
        altered = deepcopy(transport)
        if mutation == "size":
            altered["uncompressedBytes"] = MAX_NATIVE_CAPTURE_BYTES + 1
        elif mutation == "boolean-size":
            altered["uncompressedBytes"] = True
        elif mutation == "kind":
            altered["kind"] = "another-family-lossless-raw"
        elif mutation == "encoding":
            altered["encoding"] = "identity"
        elif mutation == "extra-field":
            altered["covers"] = list(POINTS)
        else:
            altered = [{"kind": "prompt-runtime-context-native-raw"}]
        with pytest.raises(ValueError):
            decode_native_capture(altered)
