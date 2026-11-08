"""Fixture and transport integrity; native comparisons establish equivalence."""
from copy import deepcopy
import json

import pytest

from equivalence.search_contract import (
    build_search_contract_cases, decode_search_tool_envelope, run_search_contract,
)


def _case(identifier):
    return next(case for case in build_search_contract_cases()
                if case["id"] == "search-contract-" + identifier)


def test_matrix_is_deterministic_unique_standard_json_and_explicitly_bounded():
    cases = build_search_contract_cases()
    assert cases == build_search_contract_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, ensure_ascii=False, allow_nan=False)) == cases
    assert all(set(case["covers"]) <= {"tools.search-contract.outcomes", "tools.search-contract.boundaries"}
               for case in cases)
    assert all(case["requirement"] == "tools.search-contract" for case in cases)
    assert {case["input"]["kind"] for case in cases} == {
        "definition", "prepare-arguments", "params", "presentation", "unavailable", "tool",
    }
    assert sum(case["input"]["kind"] == "tool" for case in cases) == 11
    assert all(case["operation"] == ("search-contract-helper-runtime" if case["input"]["kind"] in {
        "definition", "prepare-arguments",
    } else "search-contract-runtime" if case["input"]["kind"] == "tool" else "search-contract")
               for case in cases)
    assert all("Deadline/cooldown timing" in case["driverScope"] for case in cases)
    assert all("without field projection" in case["normalizationPolicy"] for case in cases)


def test_reviewed_coverage_keeps_helper_and_whole_tool_proofs_separate():
    cases = build_search_contract_cases()
    outcomes = [case for case in cases if "tools.search-contract.outcomes" in case["covers"]]
    boundaries = [case for case in cases if "tools.search-contract.boundaries" in case["covers"]]
    assert len(outcomes) == 45 and len(boundaries) == 26
    assert sum(case["input"]["kind"] == "tool" for case in outcomes) == 6
    assert sum(case["input"]["kind"] == "tool" for case in boundaries) == 8
    assert _case("presentation-empty")["covers"] == []
    assert not any("tools.deadline-cooldown" in str(case["covers"]) for case in cases)
    assert all("real transcript visibility, stale/rebuild lifecycle" in case["driverScope"] for case in cases)


def test_all_actual_adapters_preserve_input_and_return_standard_json():
    for case in build_search_contract_cases():
        before = deepcopy(case)
        result = run_search_contract(case["input"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        assert case == before


def test_error_transport_retains_real_production_name_status_and_message():
    from memory_core.tools.common import MemoryToolInputError

    actual = MemoryToolInputError("maxResults must be a positive integer")
    result = run_search_contract(_case("params-limit-zero")["input"])
    assert result == {"error": {"name": actual.name, "status": actual.status,
                               "message": actual.message}}
    assert run_search_contract(_case("params-camel-invalid-precedence")["input"]) == result


def test_optional_parameter_absence_is_preserved_without_null_fillers():
    omitted = run_search_contract(_case("params-omitted")["input"])
    assert omitted == {"params": {"query": "cedar"}}
    assert run_search_contract(_case("params-null")["input"]) == omitted
    assert run_search_contract(_case("params-blank-js-whitespace")["input"]) == omitted


def test_presentation_preserves_all_owner_metadata_and_nested_values():
    arguments = _case("presentation-on-full-metadata")["input"]
    row = run_search_contract(arguments)["results"][0]
    original = arguments["results"][0]
    for key, value in original.items():
        if key != "snippet":
            assert row[key] == value
    assert row["opaque"] == {"nested": [None, False, 0]}
    assert {"vectorScore", "textScore", "id", "sourceMtime", "originClass", "provenance"} <= row.keys()
    assert row["corpus"] == row["source"]
    assert row["citation"] in row["snippet"]


def test_presentation_retains_missing_vs_explicit_null_and_complete_long_text():
    null_row = run_search_contract(_case("presentation-single-line-session")["input"])["results"][0]
    absent_row = run_search_contract(_case("presentation-auto-direct")["input"])["results"][0]
    assert null_row["importance"] is None and null_row["provenance"] is None
    assert "importance" not in absent_row and "provenance" not in absent_row
    arguments = _case("presentation-long-snippet-is-complete")["input"]
    row = run_search_contract(arguments)["results"][0]
    assert row["snippet"] == arguments["results"][0]["snippet"]
    assert not {"truncated", "originalChars", "citation"} & row.keys()


def test_presentation_citation_off_removes_caller_citation_but_preserves_row_order():
    arguments = deepcopy(_case("presentation-off-removes-existing-citation")["input"])
    second = {**arguments["results"][0], "path": "memory/second.md"}
    arguments["results"].append(second)
    result = run_search_contract(arguments)
    assert [row["path"] for row in result["results"]] == [row["path"] for row in arguments["results"]]
    assert all("citation" not in row and row["corpus"] == row["source"] for row in result["results"])


def test_unknown_operation_is_an_error():
    with pytest.raises(ValueError, match="Unsupported search-contract operation"):
        run_search_contract({"kind": "invented"})


def test_carrier_codec_preserves_every_field_content_item_and_details_value():
    details = {"rows": [{"source": "memory", "optional": None, "score": 1}],
               "metadata": {"text": "Çay 😀\x00", "flags": [False, True]}}
    envelope = {"content": [{"type": "text", "text": json.dumps(details, indent=2), "extra": None},
                            {"type": "image", "data": "opaque bytes", "metadata": {"keep": True}},
                            {"type": "text", "text": "additional literal text"}],
                "details": details, "opaqueEnvelopeField": [None, "keep"]}
    before = deepcopy(envelope)
    decoded = decode_search_tool_envelope(envelope)
    assert envelope == before
    assert decoded == {**envelope, "content": [{**envelope["content"][0], "text": details},
                                               *envelope["content"][1:]]}


@pytest.mark.parametrize("envelope", [
    {"content": [], "details": {}},
    {"content": [{"type": "text", "text": "{}"}]},
    {"content": [{"type": "text", "text": "{}"}], "details": {"missing": None}},
    {"content": [{"type": "text", "text": "false"}], "details": 0},
    {"content": [{"type": "text", "text": "{\"nested\":[false]}"}], "details": {"nested": [0]}},
    {"content": [{"type": "text", "text": "NaN"}], "details": None},
    {"content": [{"type": "text", "text": "unparseable"}], "details": {}},
])
def test_carrier_codec_rejects_lossy_missing_or_mismatched_public_data(envelope):
    with pytest.raises(ValueError, match="Search tool"):
        decode_search_tool_envelope(envelope)


def test_carrier_codec_only_relaxes_equivalent_json_syntax():
    envelope = {"content": [{"type": "text", "text": '{ "score": 1.0, "rows": [] }'}],
                "details": {"rows": [], "score": 1}}
    decoded = decode_search_tool_envelope(envelope)
    assert decoded["details"] == envelope["details"]
    assert decoded["content"][0]["text"] == envelope["details"]


def test_actual_factory_definition_and_preparation_owner_keep_alias_identity_semantics(tmp_path):
    disabled = run_search_contract(_case("definition-disabled-factory")["input"])
    assert disabled == {"provider": "none", "definition": None}
    result = run_search_contract(_case("definition-sessions-extra-paths")["input"],
                                 evidence_directory=tmp_path)
    assert {"name", "label", "description", "parameters"} == result["definition"].keys()
    assert "configured extra paths, indexed session transcripts" in result["definition"]["description"]
    assert json.loads((tmp_path / "python-raw.json").read_text())[0]["result"] == result
    assert run_search_contract(_case("prepare-unchanged")["input"])["sameInput"] is True
    prepared = run_search_contract(_case("prepare-camel-precedence")["input"])
    assert prepared["sameInput"] is False
    assert "max_results" not in prepared["params"] and "max_results" in prepared["inputAfter"]


def test_runtime_evidence_keeps_genuine_full_wire_envelope_and_private_publication(tmp_path):
    result = run_search_contract(_case("tool-citation-on-full-metadata")["input"],
                                 evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())
    assert isinstance(raw, list) and len(raw) == len(result["steps"])
    assert raw[0]["constructorExecuted"] is True and raw[0]["provider"] == "none"
    envelope = raw[0]["result"]
    assert isinstance(envelope["content"][0]["text"], str)
    assert json.loads(envelope["content"][0]["text"]) == envelope["details"]
    assert decode_search_tool_envelope(envelope) == result["steps"][0]["result"]
    assert raw[0]["published"]["chunks"]
    assert all("id" in row and "updatedAt" in row for row in raw[0]["published"]["chunks"])
    assert any(row.get("triggers") == "tea; Çay 😀" for row in envelope["details"]["results"])


def test_whole_boundary_keeps_input_errors_distinct_and_validates_before_trusted_override():
    invalid = run_search_contract(_case("tool-invalid-arguments")["input"])["steps"][0]
    assert invalid["error"]["name"] == "ToolInputError" and invalid["error"]["status"] == 400
    trusted = run_search_contract(_case("tool-trusted-session-override")["input"])["steps"]
    assert trusted[0]["result"]["details"]["results"] == []
    assert trusted[1]["error"]["name"] == "Error" and "status" not in trusted[1]["error"]


def test_real_registered_supplement_failures_are_visible_next_to_memory_results():
    result = run_search_contract(_case("tool-supplement-multiple-failure-order")["input"])
    mixed, wiki = (step["result"]["details"] for step in result["steps"])
    assert mixed["results"] and wiki["results"] == []
    assert mixed["corpora"][-1]["outcome"] == "unavailable"
    assert mixed["corpora"][-1]["error"] == "alpha: alpha corpus unavailable; zeta: zeta corpus unavailable"
    assert mixed["warning"] and wiki["warning"]


def test_actual_store_query_defaults_and_explicit_overrides_are_observably_distinct():
    result = run_search_contract(_case("tool-configured-query-defaults")["input"])
    rows = [step["result"]["details"]["results"] for step in result["steps"]]
    assert [len(batch) for batch in rows] == [1, 2, 3]
    assert rows[0][0]["importance"] == 10
    assert rows[0][0]["score"] >= 0.75 > rows[1][1]["score"]


def test_private_fixture_files_cannot_escape_their_owned_root(tmp_path):
    arguments = deepcopy(_case("tool-citation-off")["input"])
    arguments["files"] = {"../escape.md": "outside"}
    with pytest.raises(ValueError, match="private fixture root"):
        run_search_contract(arguments, evidence_directory=tmp_path)
