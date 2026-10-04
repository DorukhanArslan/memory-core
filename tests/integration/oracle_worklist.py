"""Oracle worklist of the re-pin to OpenClaw v2026.9.6 (stage 1, shrinking through stage 2).

Stage 1 moved the oracle target from pin 4c428153 to release tag v2026.9.6 without changing
Python behaviour. Each oracle test that fails at the tag because memory-core still follows the pin
is listed in PENDING_PORTS, grouped by area with the upstream change that moved it and the
number of the plan area that owns it (``plan_area``);
tests/integration/conftest.py marks those tests ``xfail(strict=True)``, so the suite stays
green, an unexpected pass fails it, and this module is the stage-2 worklist
(docs/upstream_port_v2026_9_6.md). Oracle operations whose upstream function no longer exists
at the tag are RETIRED_OPS; their tests carry a ``retired_upstream`` skip.

Entries are node ids relative to tests/integration/. An entry ending in ``*`` matches every
node id starting with the text before it (for long parameter ids).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

ORACLE_TAG = "v2026.9.6"
ORACLE_TAG_COMMIT = "eb377ac59e6c9fd6c7705028034812becf00271b"


@dataclass(frozen=True)
class PendingPort:
    area: str
    upstream: str
    tests: tuple[str, ...]
    # The docs/upstream_port_v2026_9_6.md area ("### N.") whose "Worklist areas" line owns
    # this label; the parity matrix audit notes use the same numbers.
    plan_area: int

    @property
    def reason(self) -> str:
        return (
            f"pending port to {ORACLE_TAG}: area {self.plan_area} {self.area}; "
            f"upstream {self.upstream}"
        )


@dataclass(frozen=True)
class RetiredOp:
    operation: str
    commit: str
    stage2: str

    @property
    def reason(self) -> str:
        return f"retired upstream in {self.commit} ({ORACLE_TAG}); re-port in stage 2: {self.stage2}"


RETIRED_OPS: tuple[RetiredOp, ...] = ()
RETIRED_BY_OPERATION = {op.operation: op for op in RETIRED_OPS}


def retired_upstream(operation: str) -> pytest.MarkDecorator:
    return pytest.mark.skip(reason=RETIRED_BY_OPERATION[operation].reason)


def _oracle(*names: str) -> tuple[str, ...]:
    return tuple(f"test_openclaw_ts_oracle.py::test_real_openclaw_oracle_{name}" for name in names)


PENDING_PORTS: tuple[PendingPort, ...] = (
    PendingPort(
        "concept vocabulary (qmd tag gone with the QMD backend)",
        "8b0735e89f2 (#120936)",
        _oracle("derives_concept_vocabulary_tags"),
        plan_area=7,
    ),
    PendingPort(
        "short-term recall and promotion (provenance, userQueryHashes and claimHash on recall "
        "entries, signals/trigger/importance promotion metadata, quarantined captures)",
        "28630a9a650 (#114819), 20668eed037 (#115818), fe6556b643e (#119624), a7d2f0bd685 (#113223)",
        _oracle(
            "records_short_term_recall",
            "records_short_term_recall_sequence",
            "first_promotion_write_bootstraps_memory_header",
            "second_apply_reconciles_existing_marker_without_duplicate",
            "reconciles_existing_promotion_marker",
            "reconciles_spaced_case_insensitive_promotion_marker",
            "compacts_oldest_promotion_section_when_memory_budget_exceeded",
            "leaves_memory_unchanged_before_append_when_budget_fits",
            "drops_all_old_promotion_sections_when_budget_cannot_fit_otherwise",
            "keeps_candidate_like_daily_memory_evidence",
            "apply_skips_candidate_when_live_note_no_longer_contains_snippet",
            "promotion_header_uses_dreaming_timezone",
            "promotion_metadata_rounds_ties_like_to_fixed",
            "snippet_caps_count_utf16_units[emoji-prefix]",
            "snippet_caps_count_utf16_units[split-pair]",
        ),
        plan_area=7,
    ),
    PendingPort(
        "MEMORY.md budget compaction (bounded prior-entry loss)",
        "extensions/memory-core/src/memory-budget.ts, 4 commits after 4c428153, latest fc0360dab2e",
        _oracle("memory_budget_compaction_matches_python"),
        plan_area=7,
    ),
    PendingPort(
        "transcript and replay helpers (history-limit hysteresis, runtime context prompt, "
        "assistant replay normalization, tool-result truncation, startup context)",
        "d5dee714c4f (#115281); runtime-context-prompt.ts 5, "
        "replay-history.ts 23, tool-result-truncation.ts 36 and startup-context.ts 2 commits "
        "after 4c428153",
        (
            *_oracle(
                "history_limit_helpers_match_python",
                "runtime_context_prompt_helpers_match_python",
                "normalize_assistant_replay_content_matches_python",
                "startup_context_matches_python[emoji-at-file-cap]",
            ),
            "test_openclaw_ts_oracle.py::test_real_openclaw_oracle_truncate_tool_result_text_matches_python[Line 1*",
        ),
        plan_area=10,
    ),
    PendingPort(
        "overflow run loop (the mid-turn precheck retry no longer sends the continuation prompt; "
        "the run loop moved out of run.ts into run/*)",
        "src/agents/embedded-agent-runner/run.ts, 43 commits after 4c428153 (latest "
        "9497450511d); the pin's continuation prompt (run.ts:260) is gone",
        (
            "test_openclaw_run_loop_oracle.py::"
            "test_real_openclaw_run_loop_mid_turn_precheck_continuation",
        ),
        plan_area=10,
    ),
)


def pending_port_reason(nodeid: str) -> str | None:
    """Return the xfail reason for a node id relative to tests/integration/, if listed."""
    for port in PENDING_PORTS:
        for entry in port.tests:
            if entry.endswith("*") and nodeid.startswith(entry[:-1]):
                return port.reason
            if nodeid == entry:
                return port.reason
    return None
