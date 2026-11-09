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
        "retrieval.vector-scoring",
        "retrieval.hybrid-scoring",
        "retrieval.exact-path-priority",
        "retrieval.importance-project",
        "tools.search-contract",
        "tools.get-contract",
        "tools.deadline-cooldown", "tools.unavailable-partial",
        "sessions.corpus-admission", "sessions.visibility-lineage", "sessions.durable-context",
        "trust.configured-redaction", "trust.secret-redaction",
        "engine.unicode-collation",
        "storage.discovery", "storage.workspace-isolation", "storage.path-safety", "storage.atomic-writes", "indexing.identity",
        "indexing.embedding-cache", "indexing.incremental-sync",
        "indexing.transaction-publication",
        "chunking.markdown-boundaries", "chunking.utf16-cjk-budget", "chunking.entry-provenance",
        "prompt.bootstrap-budget", "flush.trigger-usage", "sessions.transcript-filtering",
        "flush.plan-target",
        "flush.execute-finalize",
    }


def test_default_catalog_registers_each_reviewed_atomic_case_once_with_unchanged_literals():
    from equivalence.atomic_publication_cases import build_atomic_publication_cases

    atomic = build_atomic_publication_cases()
    registered = [case for case in build_cases() if case["requirement"] == "storage.atomic-writes"]
    assert len(registered) == len({case["id"] for case in registered}) == 41
    assert registered == atomic
    assert all(case["covers"][0] == "storage.atomic-writes.outcomes" for case in registered)
    assert sum("storage.atomic-writes.boundaries" in case["covers"] for case in registered) == 32


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


def test_completed_prospective_fixtures_are_registered_without_dropping_inputs():
    from equivalence.flush_contract import build_prospective_flush_contract_cases
    from equivalence.session_projection import build_prospective_session_projection_cases

    registered = {case["id"]: case for case in build_cases()}
    all_cases = build_cases(include_prospective=True)
    assert len({case["id"] for case in all_cases}) == len(all_cases)
    assert {case["id"]: case for case in all_cases} == registered
    completed = [*build_prospective_flush_contract_cases(),
                 *build_prospective_session_projection_cases()]
    assert len(completed) == 190
    assert all(case["id"] in registered and registered[case["id"]]["input"] == case["input"]
               for case in completed)
    assert all_cases == build_cases(include_prospective=True)


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


def test_original_mmr_difference_is_retained_with_whitespace_boundary_cases():
    cases = {case["id"]: case for case in build_cases()}
    original = cases["mmr-empty-token-text"]
    assert original["input"]["items"][0]["snippet"] == " Привет "
    assert original["input"]["lambda"] == 0
    for name in (
        "bom-punctuation", "nbsp-cyrillic", "unicode-space-cyrillic", "emoji",
        "all-whitespace", "nel-distinct", "separator-distinct", "zero-width-distinct",
        "balanced", "equal-scores", "disabled",
    ):
        case = cases[f"mmr-normalization-{name}"]
        assert case["operation"] == "mmr"
        assert set(case["covers"]) == {"retrieval.mmr.order", "retrieval.mmr.text-boundaries"}
