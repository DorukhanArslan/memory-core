"""Offline contract checks for fresh inputs; no upstream equivalence is claimed here."""

from copy import deepcopy
import json

import pytest

from equivalence.cases import build_cases, run_python


def test_case_catalog_is_deterministic_unique_and_standard_json():
    first = build_cases()
    assert first == build_cases()
    assert len({case["id"] for case in first}) == len(first)
    assert json.loads(json.dumps(first, allow_nan=False)) == first
    assert {case["requirement"] for case in first} == {
        "lexical.fts-query", "lexical.tokenization", "lexical.bm25",
        "retrieval.temporal-decay", "retrieval.mmr",
    }


def test_python_adapters_preserve_inputs_and_return_standard_json():
    for case in build_cases():
        before = deepcopy(case)
        result = run_python(case)
        json.dumps(result, allow_nan=False)
        assert case == before


def test_generated_lexical_coverage_is_backed_by_reproducible_seeded_strings():
    cases = build_cases()
    for operation in ("fts-query", "tokenization"):
        generated = [case for case in cases
                     if case["operation"] == operation and "-generated-" in case["id"]]
        named_texts = {case["input"]["text"] for case in cases
                       if case["operation"] == operation and "-generated-" not in case["id"]}
        assert len(generated) == 16
        assert len({case["input"]["text"] for case in generated}) == 16
        assert all(len(case["input"]["text"]) == 80 for case in generated)
        assert not named_texts.intersection(case["input"]["text"] for case in generated)
        assert all(any(point.endswith(".generated") for point in case["covers"])
                   for case in generated)
    assert cases == build_cases()


def test_unknown_operation_is_an_error_not_a_success_placeholder():
    with pytest.raises(ValueError, match="Unsupported equivalence operation"):
        run_python({"operation": "unimplemented-rem-phase", "input": {}})


def test_mmr_disabled_preserves_input_order_and_payload():
    case = next(case for case in build_cases() if case["id"] == "mmr-disabled")
    assert run_python(case) == case["input"]["items"]


def test_disabled_decay_preserves_scores_without_inventing_metadata():
    case = next(case for case in build_cases() if case["id"] == "decay-disabled")
    assert run_python(case) == case["input"]["results"]


def test_tokenization_compares_sets_without_losing_case_sensitive_results():
    case = {"operation": "tokenization", "input": {"text": "A a 我我"}}
    tokens = run_python(case)
    assert tokens == sorted(set(tokens))
    assert "a" in tokens and "我" in tokens and "我我" in tokens
