from __future__ import annotations

from dataclasses import dataclass

from memory_core._heartbeat_constants import INTERNAL_WAKE_TRANSCRIPT_PROMPTS
from memory_core.project_name import DISPLAY_NAME, DIST_NAME, PACKAGE_NAME, UPPER_NAME

# OpenClaw src/auto-reply/heartbeat.ts INTERNAL_WAKE_TRANSCRIPT_PROMPTS (generated).
_OPENCLAW_WAKE_PROMPTS = dict(INTERNAL_WAKE_TRANSCRIPT_PROMPTS)


@dataclass(frozen=True)
class RuntimeIdentity:
    runtime_context_begin: str
    runtime_context_end: str
    runtime_context_custom_type: str
    runtime_context_source: str
    next_turn_runtime_context_header: str
    runtime_event_header: str
    runtime_event_user_prompt: str
    # Intro line under "## Workspace Files (injected)" (OpenClaw
    # src/agents/system-prompt.ts:1132 at v2026.9.6 names the runtime).
    workspace_files_injected_line: str = (
        f"User-editable; {DISPLAY_NAME} loads below as Project Context."
    )
    # Last bootstrap truncation warning line (OpenClaw
    # src/agents/bootstrap-budget.ts:312-314 names OpenClaw config keys).
    bootstrap_truncation_limits_line: str = (
        "If unintentional, raise the per-file and/or total bootstrap character limits."
    )
    # Prefix of the `<!-- <prefix><recall key> -->` marker written above each promoted
    # MEMORY.md entry (OpenClaw extensions/memory-core/src/short-term-promotion.ts:52
    # PROMOTION_MARKER_PREFIX). memory_core.consolidation reads every known prefix and writes
    # this one.
    promotion_marker_prefix: str = f"{DIST_NAME}-memory-promotion:"
    # memory_search unavailable guidance when the failure reason names a
    # missing SQLite runtime (OpenClaw extensions/memory-core/src/tools.shared.ts
    # buildMemorySearchUnavailableResult names its Node runtime).
    memory_search_sqlite_unavailable_warning: str = (
        f"Memory search is unavailable because this {DISPLAY_NAME} Python runtime does not "
        "provide SQLite support."
    )
    memory_search_sqlite_unavailable_action: str = (
        f"Run {DISPLAY_NAME} with a Python build that includes the sqlite3 module, then retry "
        "memory_search."
    )
    # The product named by a paused-index warning for an index another version wrote (OpenClaw
    # packages/memory-host-sdk/src/host/types.ts resolveMemoryIndexSearchDiagnostic).
    memory_index_product_name: str = DISPLAY_NAME
    # `formatMemoryIndexRebuildGuidance`: how to rebuild the index. `{agent}` is
    # " --agent <id>" or empty. OpenClaw names its CLI and discloses whether the rebuild calls an
    # embedding provider; memory-core names its one reindex call, since index_identity() only
    # reports and never lifts the pause.
    memory_index_rebuild_guidance: str = "SQLiteMemoryStore.reindex(workspace)."
    memory_index_rebuild_guidance_keyword_only: str = "SQLiteMemoryStore.reindex(workspace)."
    memory_index_repair_failed_guidance: str = (
        "Inspect this agent's memory sync failure before retrying the search."
    )
    # memory_search deadline guidance (OpenClaw extensions/memory-core/src/tools.shared.ts
    # buildMemorySearchUnavailableResult `deadlineAction`, which names two CLI commands);
    # `{agent_id}` is the agent in the second form.
    memory_search_deadline_action: str = (
        "Retry memory_search after a short wait. If memory-corpus timeouts persist, inspect "
        "this agent's memory index before rebuilding it."
    )
    memory_search_deadline_action_for_agent: str = (
        "Retry memory_search after a short wait: a memory-corpus timeout pauses retries for "
        "up to a minute. If memory-corpus timeouts persist, inspect the memory index "
        "(SQLiteMemoryStore.index_identity()) of agent {agent_id}, and rebuild it with "
        "SQLiteMemoryStore.reindex(workspace) only if it reports the index stale or incomplete"
    )
    # memory_search refusal for corpus=sessions when session search is off (OpenClaw
    # extensions/memory-core/src/tools.ts names its config keys).
    memory_search_sessions_disabled_action: str = (
        "If an exact session-history capability is available for this run, use it. Otherwise, "
        "ask the host to enable session search (MemoryConfig.session_search)."
    )
    memory_search_session_migration_action: str = (
        "Stop the host and migrate its session catalog to canonical keys, then restart it "
        "and retry memory_search."
    )
    # Transcript row recorded for a heartbeat turn instead of the full heartbeat
    # prompt (OpenClaw src/auto-reply/heartbeat.ts INTERNAL_WAKE_TRANSCRIPT_PROMPTS.heartbeat,
    # the pin's HEARTBEAT_TRANSCRIPT_PROMPT; cdda5825f8b, #143866).
    heartbeat_transcript_prompt: str = f"[{DISPLAY_NAME} heartbeat poll]"
    # Every internal-wake transcript row the heartbeat transcript filter drops (OpenClaw
    # src/auto-reply/heartbeat-filter.ts isHeartbeatUserMessage over
    # INTERNAL_WAKE_TRANSCRIPT_PROMPTS). memory-core writes only the heartbeat row; exec-completion,
    # cron-wake and session-event turns are not ported, so the memory-core identity lists no
    # markers for them.
    internal_wake_transcript_prompts: tuple[str, ...] = (f"[{DISPLAY_NAME} heartbeat poll]",)
    # Transcript row recorded for a bare /new or /reset turn instead of the reset prompt
    # (OpenClaw src/auto-reply/reply/prompt-prelude.ts:233-234 `[OpenClaw session ${action}]`);
    # ``{action}`` is "new" or "reset".
    session_reset_transcript_prompt: str = f"[{DISPLAY_NAME} session {{action}}]"


MEMORY_CORE_RUNTIME_IDENTITY = RuntimeIdentity(
    runtime_context_begin=f"<<<BEGIN_{UPPER_NAME}_INTERNAL_CONTEXT>>>",
    runtime_context_end=f"<<<END_{UPPER_NAME}_INTERNAL_CONTEXT>>>",
    runtime_context_custom_type=f"{PACKAGE_NAME}.runtime-context",
    runtime_context_source=f"{DIST_NAME}-runtime-context",
    next_turn_runtime_context_header=(
        f"{DISPLAY_NAME} runtime context for the immediately preceding user message."
    ),
    runtime_event_header=f"{DISPLAY_NAME} runtime event.",
    runtime_event_user_prompt=f"Continue the {DISPLAY_NAME} runtime event.",
)

OPENCLAW_COMPAT_RUNTIME_IDENTITY = RuntimeIdentity(
    runtime_context_begin="<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>",
    runtime_context_end="<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
    runtime_context_custom_type="openclaw.runtime-context",
    runtime_context_source="openclaw-runtime-context",
    next_turn_runtime_context_header="OpenClaw runtime context for the immediately preceding user message.",
    runtime_event_header="OpenClaw runtime event.",
    runtime_event_user_prompt="Continue the OpenClaw runtime event.",
    workspace_files_injected_line="User-editable; OpenClaw loads below as Project Context.",
    bootstrap_truncation_limits_line=(
        "If unintentional, raise agents.defaults.bootstrapMaxChars and/or "
        "agents.defaults.bootstrapTotalMaxChars."
    ),
    promotion_marker_prefix="openclaw-memory-promotion:",
    memory_search_sqlite_unavailable_warning=(
        "Memory search is unavailable because this OpenClaw Node runtime does not provide "
        "SQLite support."
    ),
    memory_search_sqlite_unavailable_action=(
        "Run OpenClaw with a Node runtime that includes node:sqlite, then retry memory_search."
    ),
    memory_index_product_name="OpenClaw",
    memory_index_rebuild_guidance=(
        "openclaw memory status --index{agent}. Rebuilding may call the configured embedding "
        "provider and can incur provider cost."
    ),
    memory_index_rebuild_guidance_keyword_only=(
        "openclaw memory status --index{agent}. Rebuilding uses keyword indexing only and does "
        "not call an embedding provider."
    ),
    memory_index_repair_failed_guidance=(
        "openclaw memory status --deep{agent}. Resolve the reported sync failure before retrying the search."
    ),
    memory_search_deadline_action_for_agent=(
        "Retry memory_search after a short wait: a memory-corpus timeout pauses retries for "
        "up to a minute. If memory-corpus timeouts persist, run: openclaw memory status --deep "
        "--agent {agent_id}, and rebuild with openclaw memory index --force --agent {agent_id} "
        "only if it reports the index dirty or incomplete"
    ),
    memory_search_sessions_disabled_action=(
        "If an exact session-history capability is available for this run, use it. Otherwise, "
        "ask the operator to enable semantic session search by enabling "
        "memory.search.experimental.sessionMemory and adding \"sessions\" to "
        "memory.search.sources."
    ),
    memory_search_session_migration_action=(
        "Stop the Gateway and run openclaw doctor --fix, then restart the Gateway and retry memory_search."
    ),
    heartbeat_transcript_prompt=_OPENCLAW_WAKE_PROMPTS["heartbeat"],
    internal_wake_transcript_prompts=tuple(_OPENCLAW_WAKE_PROMPTS.values()),
    session_reset_transcript_prompt="[OpenClaw session {action}]",
)
