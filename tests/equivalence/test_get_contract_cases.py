"""Fixture/transport integrity; genuine native execution proves equivalence."""
from copy import deepcopy
import json

import pytest

from equivalence.get_contract import build_get_contract_cases, map_get_fixture_paths, run_get_contract
from equivalence.search_contract import decode_search_tool_envelope


def _case(identifier):
    return next(case for case in build_get_contract_cases()
                if case["id"] == "get-contract-" + identifier)


def _payloads(identifier):
    return [step["result"]["details"] for step in run_get_contract(_case(identifier)["input"])["steps"]]


def test_matrix_is_deterministic_unique_json_and_explicitly_bounded():
    cases = build_get_contract_cases()
    assert cases == build_get_contract_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, ensure_ascii=False, allow_nan=False)) == cases
    assert all(set(case["covers"]) <= {"tools.get-contract.outcomes", "tools.get-contract.boundaries"}
               for case in cases)
    assert all(case["requirement"] in {"tools.get-contract", "storage.path-safety"} for case in cases)
    assert {case["input"]["kind"] for case in cases} == {
        "definition", "params", "read-result", "read-result-slice", "tool",
    }
    assert sum(case["input"]["kind"] == "tool" and case["requirement"] == "tools.get-contract"
               for case in cases) == 12
    assert all(case["operation"] == ("get-contract-helper-runtime" if case["input"]["kind"] == "definition"
               else "get-contract-runtime" if case["input"]["kind"] == "tool" else "get-contract") for case in cases)
    assert all("glob patterns are outside this profile" in case["driverScope"] for case in cases)
    assert all("operating-system-specific ELOOP cause text" in case["driverScope"] for case in cases)
    assert all("exact owned private fixture-base prefix" in case["normalizationPolicy"]
               if case["input"].get("normalizeFixturePaths") else "no output path normalization"
               in case["normalizationPolicy"] for case in cases)


def test_reviewed_coverage_requires_real_read_helpers_and_whole_tool_execution():
    cases = build_get_contract_cases()
    outcomes = [case for case in cases if "tools.get-contract.outcomes" in case["covers"]]
    boundaries = [case for case in cases if "tools.get-contract.boundaries" in case["covers"]]
    assert len(outcomes) == 36 and len(boundaries) == 56
    assert sum(case["input"]["kind"] == "tool" for case in outcomes) == 11
    assert sum(case["input"]["kind"] == "tool" for case in boundaries) == 12
    assert all(case["requirement"] == "tools.get-contract" for case in [*outcomes, *boundaries])
    assert _case("read-empty")["covers"] == _case("slice-empty")["covers"] == []
    assert _case("definition-default")["covers"] == []
    assert _case("params-numeric-strings")["covers"] == []


def test_existing_loop_counterexample_stays_visible_uncredited_and_outside_tool_acceptance():
    diagnostic = _case("symlink-loop-cause-diagnostic")
    assert diagnostic["covers"] == [] and diagnostic["requirement"] == "storage.path-safety"
    portable = _case("tool-filesystem-policy")
    assert not any(step["params"]["path"] == "memory/loop/a.md" for step in portable["input"]["steps"])
    assert diagnostic["input"]["steps"] == [{"params": {"path": "memory/loop/a.md"}}]
    assert "existing Python/Node operating-system symlink-loop cause difference remains visible" in diagnostic["driverScope"]


def test_all_actual_adapters_preserve_inputs_and_return_standard_json():
    for case in build_get_contract_cases():
        before = deepcopy(case)
        result = run_get_contract(case["input"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        assert case == before


def test_optional_parameters_remain_absent_and_real_input_errors_keep_public_metadata():
    omitted = run_get_contract(_case("params-omitted-window")["input"])
    assert omitted == {"params": {"path": "MEMORY.md"}}
    assert run_get_contract(_case("params-null-window")["input"]) == omitted
    assert run_get_contract(_case("params-blank-window")["input"]) == omitted
    assert run_get_contract(_case("params-from-zero")["input"]) == {
        "error": {"name": "ToolInputError", "status": 400, "message": "from must be a positive integer"},
    }


def test_shared_excerpt_defaults_and_terminal_newline_are_observable():
    result = run_get_contract(_case("read-default-120-lines")["input"])["result"]
    assert result["lines"] == 120 and result["nextFrom"] == 121
    assert result["truncated"] is True and "line 121" not in result["text"]
    assert run_get_contract(_case("read-terminal-newline")["input"])["result"]["lines"] == 2
    assert run_get_contract(_case("read-trailing-blank-line")["input"])["result"]["text"] == "one\n"
    assert run_get_contract(_case("read-crlf-preserved")["input"])["result"]["text"] == "one\r\ntwo\r"


def test_utf16_cap_never_splits_astral_and_retains_notice_even_without_text():
    empty_prefix = run_get_contract(_case("read-astral-one-unit-empty-text-notice")["input"])["result"]
    assert empty_prefix["lines"] == 1 and empty_prefix["truncated"] is True
    assert empty_prefix["text"].startswith("\n\n[More content available.")
    assert "use read on the source file" in empty_prefix["text"]
    assert "nextFrom" not in empty_prefix
    assert run_get_contract(_case("read-astral-fits-two-units")["input"])["result"]["text"].startswith("😀\n\n")
    assert run_get_contract(_case("read-astral-boundary-not-split")["input"])["result"]["text"].startswith("a\n\n")


def test_line_boundary_budget_retains_continuation_and_oversized_line_omits_it():
    fitted = run_get_contract(_case("read-line-boundary-char-cap")["input"])["result"]
    assert fitted["lines"] == 2 and fitted["nextFrom"] == 3
    assert fitted["text"].startswith("ab\ncd\n\n")
    hard = run_get_contract(_case("read-oversized-first-line")["input"])["result"]
    assert hard["lines"] == 1 and "nextFrom" not in hard
    assert hard["text"].startswith("abc\n\n")


def test_factory_definitions_retain_full_schema_and_are_absent_when_disabled(tmp_path):
    value = run_get_contract(_case("definition-extra-paths")["input"], evidence_directory=tmp_path)
    assert value["definition"].keys() == {"name", "label", "description", "parameters"}
    assert value["definition"]["label"] == "Memory Get"
    assert "configured extra paths" in value["definition"]["description"]
    assert "prepareArguments" not in value["definition"]
    assert run_get_contract(_case("definition-disabled")["input"])["definition"] is None
    assert run_get_contract(_case("definition-missing-config")["input"])["definition"] is None
    assert json.loads((tmp_path / "python-raw.json").read_text())[0]["result"] == value


def test_whole_tool_distinguishes_argument_rejection_corpus_error_and_revocation():
    steps = run_get_contract(_case("tool-raw-arguments-and-corpora")["input"])["steps"]
    assert steps[0]["error"]["name"] == "ToolInputError" and steps[0]["error"]["status"] == 400
    assert steps[11]["error"]["name"] == "Error" and "status" not in steps[11]["error"]
    disabled = run_get_contract(_case("tool-live-disabled")["input"])["steps"][0]
    assert disabled["error"]["name"] == "Error" and "status" not in disabled["error"]


def test_real_file_reads_use_actual_config_cap_and_decoder():
    first, astral = _payloads("tool-trusted-character-cap")
    assert first["text"].startswith("a\n\n")
    assert astral["text"].startswith("\n\n[More content available.")
    decoded, second_line = _payloads("tool-utf8-and-line-endings")
    assert decoded["text"] == "\ufeffa\ufffd\r\nb\r"
    assert second_line["text"] == "b\r"


def test_real_filesystem_admits_internal_parent_symlink_and_refuses_leaf_links():
    rows = _payloads("tool-filesystem-policy")
    assert rows[0]["status"] == "error" and rows[0]["code"] == "symlink"
    assert rows[1]["status"] == "error" and rows[1]["code"] == "symlink"
    assert rows[2]["status"] == "ok" and rows[2]["text"] == "Actual within-root content."


def test_whole_tool_preserves_all_provider_metadata_and_raw_lookup_range_context():
    arguments = _case("tool-wiki-full-metadata-and-memory-precedence")["input"]
    result = run_get_contract(arguments)
    first = result["steps"][0]["result"]["details"]
    provider = arguments["supplements"][1]["result"]
    for key, value in provider.items():
        if key not in {"content", "status"}:
            assert first[key] == value
    assert first["status"] == "ok" and first["text"] == provider["content"] and "content" not in first
    assert first["from"] == 44 and first["lines"] == 2  # The provider owns its excerpt.
    assert result["requests"][:2] == [
        {"pluginId": plugin, "query": {"lookup": "./wiki/cedar", "fromLine": 2, "lineCount": 1,
                                      "agentId": "main", "agentSessionKey": "agent:main:main", "sandboxed": True}}
        for plugin in ("alpha", "zeta")
    ]
    assert result["requests"][2]["query"]["lookup"] == "/wiki/opaque\\lookup"


def test_provider_empty_null_and_missing_content_remain_distinct():
    rows = _payloads("tool-wiki-full-metadata-and-memory-precedence")
    assert rows[2]["text"] == ""
    assert rows[3]["text"] is None
    assert "text" not in rows[4]
    assert rows[3]["opaque"] is None and rows[4]["opaque"] is None


def test_provider_warnings_and_order_are_genuine_next_to_available_results():
    partial = _payloads("tool-wiki-partial-failure")
    assert partial[0]["status"] == "ok" and partial[0]["warning"]
    assert partial[1]["text"] == "Builtin memory." and partial[1]["warning"]
    failures = _payloads("tool-wiki-multiple-failure-order")
    assert failures[0]["error"] == "alpha: alpha read unavailable; zeta: zeta read unavailable"
    assert failures[0]["warning"] and failures[1]["warning"]


def test_raw_evidence_keeps_complete_actual_wire_and_every_provider_request(tmp_path):
    result = run_get_contract(_case("tool-wiki-full-metadata-and-memory-precedence")["input"],
                              evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())
    assert isinstance(raw, list) and len(raw) == len(result["steps"])
    assert all(row["factoryExecuted"] is True and row["provider"] == "none" for row in raw)
    assert isinstance(raw[0]["result"]["content"][0]["text"], str)
    assert decode_search_tool_envelope(raw[0]["result"]) == result["steps"][0]["result"]
    assert raw[-1]["requests"] == result["requests"]


def test_fixture_paths_cannot_escape_their_owned_root():
    arguments = deepcopy(_case("tool-default-and-explicit-lines")["input"])
    arguments["files"] = {"../escape.md": "Outside."}
    with pytest.raises(ValueError, match="owned root"):
        run_get_contract(arguments)


def test_unknown_operation_is_an_error():
    with pytest.raises(ValueError, match="Unsupported get-contract operation"):
        run_get_contract({"kind": "invented"})


def test_private_path_codec_preserves_all_fields_error_words_and_order_without_touching_input():
    base = "/tmp/private-fixture-case"
    payload = {"status": "error", "code": "outside-workspace", "path": "memory/outside/a.md",
               "error": f"file is outside workspace root | Symlink escapes root ({base}/workspace): {base}/workspace/memory/outside",
               "opaque": [None, {"path": base + "-other/workspace/a.md"}, base]}
    envelope = {"content": [{"type": "text", "text": payload}, {"type": "text", "text": "literal untouched"}],
                "details": payload, "other": [False, 0]}
    before = deepcopy(envelope)
    mapped = map_get_fixture_paths(envelope, base)
    assert envelope == before
    assert mapped["details"]["error"] == "file is outside workspace root | Symlink escapes root ($FIXTURE/workspace): $FIXTURE/workspace/memory/outside"
    assert mapped["details"]["code"] == payload["code"] and mapped["details"]["status"] == payload["status"]
    assert mapped["details"]["opaque"] == [None, {"path": base + "-other/workspace/a.md"}, "$FIXTURE"]
    assert mapped["content"][0]["text"] == mapped["details"]
    assert mapped["content"][1:] == envelope["content"][1:] and mapped["other"] == envelope["other"]


def test_fs_comparison_validates_wire_first_and_keeps_original_wire_text(tmp_path):
    case = _case("tool-filesystem-policy")
    result = run_get_contract(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())
    for observed, evidence in zip(result["steps"], raw, strict=True):
        envelope = evidence["result"]
        assert isinstance(envelope["content"][0]["text"], str)
        assert map_get_fixture_paths(decode_search_tool_envelope(envelope), evidence["fixtureBase"]) == observed["result"]
        assert "$FIXTURE" not in envelope["content"][0]["text"]
    malformed = {"content": [{"type": "text", "text": '{"path":"/tmp/one/workspace/a.md"}'}],
                 "details": {"path": "/tmp/two/workspace/a.md"}}
    with pytest.raises(ValueError, match="differs from its actual details"):
        decode_search_tool_envelope(malformed)
