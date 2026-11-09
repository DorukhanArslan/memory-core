"""Offline tests of the opt-in LLM consolidation step (the model is a stub callable)."""

from __future__ import annotations

import json
import logging
from dataclasses import replace

import pytest

from memory_core.consolidation import (
    LlmConsolidationOptions,
    PromotionCandidate,
    consolidate_memory,
    run_llm_consolidation,
)
from memory_core.consolidation.curated_annotations import (
    extract_project_keys_from_curated_entry,
    normalize_project_annotation_key,
)

NOW_MS = 1782986400000


@pytest.mark.parametrize("observed_at, wire", [(1.0, "1"), (-0.0, "0"), (1e-7, "1e-7")])
def test_model_prompt_uses_javascript_number_text_for_recalled_provenance(observed_at, wire):
    from memory_core.consolidation.llm_consolidation import build_consolidation_prompt

    candidate = replace(_candidate("source-key", "- A durable preference."),
                        provenance={"originClass": "agent", "sessionKind": "unknown", "observedAt": observed_at})
    prompt = build_consolidation_prompt("# Current memory\n", [candidate], 200)
    assert f'"observedAt":{wire}}}' in prompt
    assert json.loads(prompt)["currentMemory"] == "# Current memory\n"


def _candidate(key: str, snippet: str, project: str | None = None) -> PromotionCandidate:
    return PromotionCandidate(
        key=key,
        path="memory/2026-07-01.md",
        start_line=1,
        end_line=1,
        snippet=snippet,
        recall_count=3,
        daily_count=0,
        grounded_count=0,
        signal_count=3,
        avg_score=0.9,
        max_score=0.9,
        unique_queries=2,
        score=0.9,
        first_recalled_at="2026-07-01T10:00:00.000Z",
        last_recalled_at="2026-07-01T10:00:00.000Z",
        concept_tags=("preference",),
        project_key=project,
        provenance={"originClass": "agent", "sessionKind": "interactive"},
    )


def _adds(request):
    prompt = json.loads(request.message)
    return json.dumps(
        {
            "operations": [
                {"candidateKey": item["key"], "action": "added", "priorEntries": []}
                for item in prompt["candidates"]
            ]
        }
    )


def test_disabled_by_default_never_calls_the_model_or_writes(tmp_path):
    calls = []

    def model(request):
        calls.append(request)
        return _adds(request)

    outcome = run_llm_consolidation(
        tmp_path, [_candidate("a", "Fact.")], model, now_ms=NOW_MS
    )

    assert outcome.applied is False and outcome.reason == "disabled"
    assert calls == []
    assert not (tmp_path / "MEMORY.md").exists()


def test_enabled_without_a_model_does_nothing(tmp_path):
    outcome = run_llm_consolidation(
        tmp_path, [_candidate("a", "Fact.")], None, LlmConsolidationOptions(enabled=True), now_ms=NOW_MS
    )

    assert outcome.applied is False and outcome.reason == "no model"


def test_enabled_writes_memory_and_a_preimage(tmp_path):
    (tmp_path / "MEMORY.md").write_text("# Memory\n\n- Old fact.\n", encoding="utf-8")

    outcome = run_llm_consolidation(
        tmp_path,
        [_candidate("a", "New fact.")],
        _adds,
        LlmConsolidationOptions(enabled=True, model_name="m"),
        now_ms=NOW_MS,
        timezone="UTC",
    )

    assert outcome.applied is True
    text = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert text == outcome.result.content
    assert "## Consolidated Memory (2026-07-02)" in text
    assert "- Old fact." in text and "- New fact. Source: memory/2026-07-01.md#L1-L1" in text
    preimages = json.loads((tmp_path / "memory/.dreams/consolidation-preimages.json").read_text())
    assert [entry["content"] for entry in preimages["entries"]] == ["# Memory\n\n- Old fact.\n"]


def test_rejection_leaves_memory_untouched_and_warns(tmp_path, caplog):
    original = "# Memory\n\n- Old fact.\n"
    (tmp_path / "MEMORY.md").write_text(original, encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="memory_core.consolidation.llm"):
        outcome = run_llm_consolidation(
            tmp_path,
            [_candidate("a", "New fact.")],
            lambda request: "not json",
            LlmConsolidationOptions(enabled=True),
            now_ms=NOW_MS,
        )

    assert outcome.applied is False and outcome.reason == "rejected"
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == original
    assert "no structured output" in caplog.text


def test_model_never_sees_a_network_and_text_objects_are_accepted():
    class Reply:
        text = json.dumps({"operations": [{"candidateKey": "a", "action": "added", "priorEntries": []}]})

    plan = consolidate_memory(
        model=lambda request: Reply(),
        existing_memory="# Memory\n",
        candidates=[_candidate("a", "Fact.")],
        max_prior_entry_loss_fraction=0.25,
        now_ms=NOW_MS,
    )

    assert plan is not None and [op.action for op in plan.operations] == ["added"]


def test_project_keys_parse_like_upstream():
    parsed = extract_project_keys_from_curated_entry(
        "- x <!-- project: GitHub.com/Acme/Repo; path:/Work -->"
    )
    assert parsed.valid and parsed.keys == ("github.com/Acme/Repo", "path:/Work")
    assert not extract_project_keys_from_curated_entry("- x <!-- project: -->").valid
    assert extract_project_keys_from_curated_entry("- plain").keys == ()
    assert normalize_project_annotation_key("a<b") is None
