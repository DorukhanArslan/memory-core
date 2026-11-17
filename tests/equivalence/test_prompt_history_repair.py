"""Closed family authority and evidence forgery guards; no business engine runs."""
from copy import deepcopy
import base64
import gzip
import hashlib
import json

import pytest

from equivalence.prompt_history_repair import (
    CASE_HASHES, POINTS, build_cases, canonical, family_complete, validate_registration,
)
from equivalence.prompt_history_repair_evidence import (
    MAX_NATIVE_CAPTURE_BYTES, _messages_guard, _operations, _preserve_history, _tool_catalog,
    decode_native_capture,
)
from equivalence.prompt_history_repair_profile import case_bindings


def test_complete_frozen_family_authorizes_only_both_existing_history_points():
    cases = build_cases()
    validate_registration(cases)
    assert len(cases) == len(CASE_HASHES) == 8
    assert POINTS == ("prompt.history-repair.outcomes", "prompt.history-repair.boundaries")
    assert all(case["covers"] == list(POINTS) for case in cases)
    assert case_bindings() == CASE_HASHES
    assert len({case["id"] for case in cases}) == 8
    assert cases[0]["input"]["operations"][0]["scriptedTools"][0]["name"] == "memory_get"
    assert len(cases[0]["input"]["files"]) == 1


def test_mutated_missing_reordered_or_widened_family_cannot_borrow_authority():
    for mutation in ("input", "missing", "duplicate", "order", "coverage", "scope"):
        cases = deepcopy(build_cases())
        if mutation == "input":
            cases[0]["input"]["operations"][0]["tools"].append("retired_history_tool")
        elif mutation == "missing":
            cases.pop()
        elif mutation == "duplicate":
            cases.append(deepcopy(cases[0]))
        elif mutation == "order":
            cases.reverse()
        elif mutation == "coverage":
            cases[0]["covers"].append("prompt.unapproved.outcomes")
        else:
            cases[0]["driverScope"] += " widened"
        with pytest.raises(ValueError):
            validate_registration(cases)


def test_both_points_require_every_integrated_case_and_actual_evidence():
    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in build_cases()]
    assert family_complete(rows)
    for mutation in ("missing", "mismatch", "unvalidated", "helper-only"):
        altered = deepcopy(rows)
        if mutation == "missing":
            altered.pop()
        elif mutation == "mismatch":
            altered[-1]["status"] = "mismatched"
        elif mutation == "unvalidated":
            altered[-1]["runtimeEvidenceValidated"] = False
        else:
            altered[-1].pop("runtimeEvidenceValidated")
            altered[-1]["helperOutputMatched"] = True
        assert not family_complete(altered)
    assert not family_complete([])


def test_durable_event_payloads_and_reopen_are_preserved_and_synthetics_rejected():
    original = build_cases()[0]["input"]["transcriptEvents"]
    _preserve_history(original, deepcopy(original), reopen=True)
    rewritten = deepcopy(original)
    rewritten[0]["message"]["content"] = "rewritten"
    with pytest.raises(ValueError, match="rewritten"):
        _preserve_history(original, rewritten)
    synthetic = {"type": "message", "message": {"role": "toolResult", "toolCallId": "invented"}}
    with pytest.raises(ValueError, match="synthetic"):
        _preserve_history(original, [*original, synthetic])
    with pytest.raises(ValueError, match="reopen"):
        _preserve_history(original, [*original, {"type": "custom", "customType": "invented"}], reopen=True)


def test_history_window_cushion_and_cut_cannot_be_hidden_by_message_filtering():
    case = next(case for case in build_cases() if case["id"].endswith("window-batches"))
    messages = [{"role": "user", "content": "historypreludecedar historyturn0cedar historyturn1cedar historyturn2cedar"}]
    _messages_guard(case, 0, messages)
    with pytest.raises(ValueError, match="evicted"):
        _messages_guard(case, 1, messages)
    with pytest.raises(ValueError, match="retained"):
        _messages_guard(case, 0, [{"role": "user", "content": "historypreludecedar historyturn2cedar"}])


def test_fake_callbacks_and_replaced_whole_messages_are_rejected():
    case = deepcopy(build_cases()[1])
    case["input"]["operations"] = case["input"]["operations"][:1]
    specification = case["input"]["operations"][0]
    observed = {"operation": deepcopy(specification), "modelCalls": [{"messages": [{"role": "user", "content": "invented"}]}]}
    actual = {"operation": deepcopy(specification), "observation": deepcopy(observed),
              "apiOutcome": {"kind": "return"}, "model": deepcopy(case["input"]["model"]),
              "providerCalls": [{"request": {"model": deepcopy(case["input"]["model"]),
                  "context": {"messages": [{"role": "user", "content": "actual"}]}}}]}
    public = {"observations": [observed]}
    raw = {"input": deepcopy(case["input"]), "output": deepcopy(public), "operations": [actual]}
    with pytest.raises(ValueError, match="whole actual callback"):
        _operations(case, raw, public, False)
    actual["providerCalls"] = []
    with pytest.raises(ValueError, match="genuine model callback"):
        _operations(case, raw, public, False)


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("mutation", ["extra", "missing", "duplicate", "renamed", "absent"])
def test_every_callback_requires_the_exact_unique_tool_catalog(native, mutation):
    specification = build_cases()[0]["input"]["operations"][0]
    definitions = [{"name": name, "parameters": {"type": "object"}} for name in specification["tools"]]
    operation = {"providerCalls": [{"request": {"context": {"tools": deepcopy(definitions)}}}
                                    for _ in range(2)],
                 "registeredTools": deepcopy(definitions),
                 "historyReplay": {"allowedToolNames": deepcopy(specification["tools"])}}
    _tool_catalog(specification, operation, native)
    context = operation["providerCalls"][-1]["request"]["context"]
    if mutation == "extra":
        context["tools"].append({"name": "read"})
    elif mutation == "missing":
        context["tools"].pop()
    elif mutation == "duplicate":
        context["tools"].append(deepcopy(context["tools"][0]))
    elif mutation == "renamed":
        context["tools"][0]["name"] = "retired_history_tool"
    else:
        context.pop("tools")
    with pytest.raises(ValueError, match="actual callback"):
        _tool_catalog(specification, operation, native)


@pytest.mark.parametrize("mutation", ["registry-extra", "registry-duplicate", "definition", "replay-extra"])
def test_sdk_replay_catalog_is_bound_to_actual_registered_definitions(mutation):
    specification = build_cases()[0]["input"]["operations"][0]
    definitions = [{"name": name, "parameters": {"type": "object"}} for name in specification["tools"]]
    operation = {"providerCalls": [{"request": {"context": {"tools": deepcopy(definitions)}}}],
                 "registeredTools": deepcopy(definitions),
                 "historyReplay": {"allowedToolNames": deepcopy(specification["tools"])}}
    if mutation == "registry-extra":
        operation["registeredTools"].append({"name": "read"})
    elif mutation == "registry-duplicate":
        operation["registeredTools"].append(deepcopy(definitions[0]))
    elif mutation == "definition":
        operation["providerCalls"][0]["request"]["context"]["tools"][0]["parameters"] = {"type": "string"}
    else:
        operation["historyReplay"]["allowedToolNames"].append("read")
    with pytest.raises(ValueError, match="actual SDK"):
        _tool_catalog(specification, operation, False)


def test_raw_transport_rejects_borrowed_identity_trailing_data_and_size_widening():
    payload = canonical([{"kind": "prompt-history-repair-native-raw"}])
    compressed = gzip.compress(payload, mtime=0)
    envelope = {"kind": "prompt-history-repair-lossless-raw", "encoding": "gzip-json-base64",
                "uncompressedBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                "data": base64.b64encode(compressed).decode("ascii")}
    assert decode_native_capture(envelope) == json.loads(payload)
    for mutation in ("family", "trailing", "bound", "digest"):
        altered = deepcopy(envelope)
        if mutation == "family":
            altered["kind"] = "prompt-runtime-context-lossless-raw"
        elif mutation == "trailing":
            altered["data"] = base64.b64encode(compressed + b"trailing").decode("ascii")
        elif mutation == "bound":
            altered["uncompressedBytes"] = MAX_NATIVE_CAPTURE_BYTES + 1
        else:
            altered["sha256"] = "0" * 64
        with pytest.raises(ValueError):
            decode_native_capture(altered)
