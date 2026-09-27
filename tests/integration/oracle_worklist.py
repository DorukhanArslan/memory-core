"""Oracle worklist of the re-pin to OpenClaw v2026.9.6 (stage 1).

Stage 1 moved the oracle target from pin 4c428153 to release tag v2026.9.6 without changing
Python behaviour. Each oracle test that fails at the tag because memory-core still follows the pin
is listed in PENDING_PORTS, grouped by area with the upstream change that moved it;
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

    @property
    def reason(self) -> str:
        return f"pending port to {ORACLE_TAG}: {self.area}; upstream {self.upstream}"


@dataclass(frozen=True)
class RetiredOp:
    operation: str
    commit: str
    stage2: str

    @property
    def reason(self) -> str:
        return f"retired upstream in {self.commit} ({ORACLE_TAG}); re-port in stage 2: {self.stage2}"


RETIRED_OPS: tuple[RetiredOp, ...] = (
    RetiredOp(
        "parseHeartbeatTasks",
        "b23c7bd0f84 (#113165)",
        "src/commands/heartbeat-task-legacy.ts analyzeLegacyHeartbeatTasks (doctor migration of "
        "tasks: blocks into cron jobs) plus the cron-owned scheduledTasks of "
        "src/infra/heartbeat-runner-prompt.ts resolveHeartbeatRunPrompt",
    ),
    RetiredOp(
        "heartbeatTaskDue",
        "b23c7bd0f84 (#113165)",
        "none for isTaskDue (cron owns due-ness); the duration and interval cases moved to the "
        "heartbeatDurations op",
    ),
    RetiredOp(
        "heartbeatSystemSection",
        "6a1dedb00c2 (#129642)",
        "src/infra/heartbeat-runner-prompt.ts resolveHeartbeatRunPrompt (the heartbeat prompt "
        "lives only in the scheduled user turn; no '## Heartbeats' section)",
    ),
    RetiredOp(
        "sessionMemoryTranscript",
        "2cc49503a60 (#107412) and 4273ca9dbd9 (#113233)",
        "src/hooks/bundled/session-memory/transcript.ts getRecentSessionProjectionFromEvents "
        "and countSessionMemoryMessages over SQLite transcript events",
    ),
)
RETIRED_BY_OPERATION = {op.operation: op for op in RETIRED_OPS}


def retired_upstream(operation: str) -> pytest.MarkDecorator:
    return pytest.mark.skip(reason=RETIRED_BY_OPERATION[operation].reason)


def _oracle(*names: str) -> tuple[str, ...]:
    return tuple(f"test_openclaw_ts_oracle.py::test_real_openclaw_oracle_{name}" for name in names)


PENDING_PORTS: tuple[PendingPort, ...] = (
    PendingPort(
        "flush plan (read-only hint without TOOLS.md, no reserveTokensFloor or prompt overrides, "
        "reserve and soft threshold derived from the context window)",
        "669db2968fc (#113966), 783a5d21cfc (#111382), edecdbd05ef, 6b6f1969c11 (#130072)",
        _oracle(
            "flush_plan_matches_python_defaults",
            "flush_plan_supports_disabled_and_overrides",
        ),
    ),
    PendingPort(
        "flush gate (shouldRunMemoryFlush takes a threshold, counts only fresh session totals, "
        "and reads entry.memoryFlush.compactionCount)",
        "8ee1d046d33 (#115299), 084d51d0c7b (#152268)",
        _oracle(
            "memory_flush_gate_matches_python[payload3]",
            "memory_flush_gate_matches_python[payload4]",
            "memory_flush_gate_matches_python[payload5]",
        ),
    ),
    PendingPort(
        "memory_get contract (status ok/not_found/error, MEMORY_PATH_NOT_ALLOWED and read-failure "
        "codes, `disabled` dropped, USER.md and DREAMS.md as memory paths)",
        "35e0bc22ead (#125979), 28630a9a650 (#114819)",
        _oracle(
            "memory_get_reads_line_window_like_python",
            "memory_get_reads_root_memory_like_python",
            "memory_get_disabled_error_matches_python",
            "memory_get_missing_file_matches_python",
            "memory_get_char_budget_matches_python",
            "memory_get_path_gate_matches_python[sessions/main/session-nebula.jsonl]",
            "memory_get_path_gate_matches_python[memory/.dreams/session-corpus/2026-05-26.txt]",
            "memory_get_path_gate_matches_python[memory/.dreams/session-corpus/2026-05-27.md]",
            "memory_get_path_gate_matches_python[memory/../AGENTS.md]",
            "memory_get_path_gate_matches_python[memory.md]",
            "memory_get_path_gate_matches_python[dreams.md]",
            "memory_get_path_gate_matches_python[/MEMORY.md]",
            "memory_get_path_gate_matches_python[<abs>/memory/2026-05-26.md]",
            "memory_get_path_gate_matches_python[./memory/2026-05-26.md]",
            "memory_get_path_gate_matches_python[memory/2026-05-26.md]",
            "memory_get_path_gate_matches_python[memory/bytes.md]",
            "memory_get_path_gate_matches_python[memory/link.md]",
            "memory_get_path_gate_matches_python[memory/dir.md]",
            "memory_get_path_gate_matches_python[memory/missing.md]",
            "memory_get_tool_params_match_python[raw_params12]",
            "memory_get_tool_params_match_python[raw_params13]",
            "memory_get_tool_params_match_python[raw_params14]",
            "memory_get_tool_params_match_python[raw_params15]",
            "memory_get_tool_params_match_python[raw_params16]",
            "memory_get_tool_params_match_python[raw_params17]",
            "memory_get_tool_params_match_python[raw_params18]",
        ),
    ),
    PendingPort(
        "memory tool definitions (descriptions name MEMORY.md, USER.md and per-corpus outcomes)",
        "16bec3c7272 (#126552), 3fe833dfa40 (#126530)",
        _oracle("memory_tool_definitions_match_python"),
    ),
    PendingPort(
        "memory_search ranking and indexing (hybrid weights fixed at 0.7/0.3, MMR and temporal "
        "decay on by default, filename/path matching, chunk ranges)",
        "783a5d21cfc (#111382), c37b53868d1 (#121224), 28630a9a650 (#114819), "
        "e9b7a9a9127 (#104449)",
        _oracle(
            "memory_search_memory_corpus_matches_python_paths",
            "memory_search_text_scores_and_line_ranges_match_python",
            "memory_search_vector_scores_match_python",
            "memory_search_hybrid_weighted_scores_match_python",
            "memory_search_all_balances_memory_and_wiki",
            "memory_search_param_coercion_matches_python[camel-case-wins]",
            "memory_search_param_coercion_matches_python[integral-float]",
            "memory_search_param_coercion_matches_python[null-camel-case-hides-alias]",
            "memory_search_param_coercion_matches_python[numeric-strings]",
            "memory_search_param_coercion_matches_python[scientific-string]",
            "memory_search_param_coercion_matches_python[snake-case-aliases]",
            "memory_search_pauses_on_index_model_change",
            "memory_search_finds_session_memory_files",
            "memory_search_indexes_invalid_utf8_markdown",
        ),
    ),
    PendingPort(
        "memory_search params, errors and deadline (empty maxResults rejected, corpus validated, "
        "30 s deadline with partial-timeout guidance, per-corpus outcomes)",
        "d46f9ebf2b2 (#147702), 3fe833dfa40 (#126530)",
        _oracle(
            "memory_search_param_errors_match_python[max-results-empty-string]",
            "memory_search_param_coercion_matches_python[unknown-corpus-searches-all-sources]",
            "memory_search_deadline_and_cooldown_match_python",
        ),
    ),
    PendingPort(
        "memory index identity (provenance_version reason)",
        "28630a9a650 (#114819)",
        _oracle("memory_index_identity_matches_python"),
    ),
    PendingPort(
        "deep dreaming policy (enabled by default, minScore 0.75, integer fields limit, "
        "minRecallCount, minUniqueQueries and recencyHalfLifeDays parsed with "
        "parseStrictNonNegativeInteger instead of Number() coercion)",
        "b2cc5f50420 (#115715), 28630a9a650 (#114819); src/memory-host-sdk/dreaming.ts:480-490",
        _oracle(
            "deep_policy",
            "deep_policy_coerces_malformed_values[deep0]",
            "deep_policy_coerces_malformed_values[deep1]",
            "deep_policy_coerces_malformed_values[deep3]",
            "deep_policy_coerces_malformed_values[deep4]",
            "deep_policy_coerces_malformed_values[deep5]",
            "deep_policy_coerces_malformed_values[deep6]",
            "deep_policy_coerces_malformed_values[deep7]",
        ),
    ),
    PendingPort(
        "concept vocabulary (qmd tag gone with the QMD backend)",
        "8b0735e89f2 (#120936)",
        _oracle("derives_concept_vocabulary_tags"),
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
    ),
    PendingPort(
        "MEMORY.md budget compaction (bounded prior-entry loss)",
        "extensions/memory-core/src/memory-budget.ts, 4 commits after 4c428153, latest fc0360dab2e",
        _oracle("memory_budget_compaction_matches_python"),
    ),
    PendingPort(
        "transcript and replay helpers (history-limit hysteresis, tool-use repair, runtime context "
        "prompt, assistant replay normalization, tool-result truncation, startup context)",
        "d5dee714c4f (#115281); session-transcript-repair.ts 17, runtime-context-prompt.ts 5, "
        "replay-history.ts 23, tool-result-truncation.ts 36 and startup-context.ts 2 commits "
        "after 4c428153",
        (
            *_oracle(
                "history_limit_helpers_match_python",
                "repair_tool_use_result_pairing_matches_python",
                "runtime_context_prompt_helpers_match_python",
                "normalize_assistant_replay_content_matches_python",
                "startup_context_matches_python[emoji-at-file-cap]",
            ),
            "test_openclaw_ts_oracle.py::test_real_openclaw_oracle_truncate_tool_result_text_matches_python[Line 1*",
        ),
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
    ),
    PendingPort(
        "bootstrap budget and truncation (USER.md fixed 4000-char cap, effectiveFileLimit in the "
        "budget analysis, Traditional Chinese AGENTS.md digest markers)",
        "28630a9a650 (#114819), dae1aea7117 (#136967), dfc9678a516 (#142915)",
        (
            *_oracle(
                "bootstrap_context_files_match_python[probe-head-tail]",
                "bootstrap_context_files_match_python[compact-marker]",
                "bootstrap_context_files_match_python[agents-policy-digest]",
                "bootstrap_context_files_match_python[agents-digest-tight]",
                "bootstrap_context_files_match_python[surrogate-split-cjk-turkish]",
                "bootstrap_context_files_match_python[total-budget-exhaustion]",
                "bootstrap_context_files_match_python[missing-marker-clamp-then-break]",
                "bootstrap_context_files_match_python[paths-and-js-whitespace]",
                "bootstrap_context_files_match_python[duplicate-names-report]",
                "bootstrap_warning_once_mode_matches_python",
            ),
            "test_openclaw_ts_oracle.py::test_bootstrap_constants_and_keyword_sets_equal_upstream_source",
        ),
    ),
    PendingPort(
        "workspace bootstrap map (AGENTS, SOUL, IDENTITY, USER, BOOTSTRAP, MEMORY: TOOLS.md "
        "retired into AGENTS.md ## Tools, HEARTBEAT.md into the monitor scratch; setup state in "
        "SQLite; root MEMORY.md dropped for shared sessions; new Project Context wording)",
        "669db2968fc (#113966), 3e2b3ea4d5e (#112967), d06fc25a0c5 (#119198), "
        "78d7a8489cd (#114436), #109147",
        _oracle(
            "workspace_bootstrap_files_match_python[all-files]",
            "workspace_bootstrap_files_match_python[missing-lowercase-memory]",
            "workspace_bootstrap_files_match_python[setup-completed-drops-bootstrap]",
            "workspace_bootstrap_files_match_python[guarded-reads]",
            "project_context_render_matches_python[all-full]",
            "project_context_render_matches_python[full-without-bootstrap-file]",
            "project_context_render_matches_python[dynamic-only]",
            "project_context_render_matches_python[empty]",
            "project_context_render_matches_python[soul-only]",
            "workspace_lifecycle_matches_python[fresh-seed-then-reconcile-deletes-bootstrap]",
            "workspace_lifecycle_matches_python[skip-optional-then-agent-deletes-bootstrap]",
            "workspace_lifecycle_matches_python[memory-dir-counts-as-configured]",
            "workspace_lifecycle_matches_python[memory-file-counts-as-configured]",
            "workspace_lifecycle_matches_python[workspace-skill-counts-as-configured]",
            "workspace_lifecycle_matches_python[git-dir-counts-as-configured]",
            "workspace_lifecycle_matches_python[customized-identity-counts-as-configured]",
            "workspace_lifecycle_matches_python[legacy-onboarding-state-migrates]",
            "workspace_lifecycle_matches_python[existing-bootstrap-marked-then-reconciled]",
            "workspace_lifecycle_matches_python[corrupt-state-file]",
        ),
    ),
    PendingPort(
        "heartbeat monitor scratch (prompts follow the scratch and reply NO_REPLY, the runner "
        "never reads HEARTBEAT.md, recurring tasks are cron jobs, heartbeat transcript filter)",
        "3e2b3ea4d5e (#112967), 07e3855b465 (#113131), b23c7bd0f84 (#113165); "
        "heartbeat-filter.ts 10 commits after 4c428153",
        _oracle(
            "heartbeat_constants_match_python",
            "heartbeat_prompt_config_matches_python",
            "heartbeat_run_prompt_matches_python",
            "heartbeat_session_filter_matches_python",
        ),
    ),
    PendingPort(
        "session-memory hook (transcripts from the SQLite session store, agentId-scoped slug run "
        "and entry rendering, new bare reset prompts)",
        "4273ca9dbd9 (#113233); handler.ts 16, llm-slug-generator.ts 6 and "
        "session-reset-prompt.ts 4 commits after 4c428153",
        (
            *_oracle(
                "session_memory_slug_matches_python",
                "session_memory_hook_matches_python[scenarios]",
                "session_memory_hook_matches_python[zone_sweep]",
            ),
            "test_session_reset_prompt_source.py::test_bare_session_reset_prompts_equal_upstream_source",
        ),
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
