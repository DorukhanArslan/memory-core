from __future__ import annotations

from dataclasses import dataclass

from memory_core._heartbeat_constants import INTERNAL_WAKE_TRANSCRIPT_PROMPTS
from memory_core.project_name import DISPLAY_NAME, DIST_NAME, PACKAGE_NAME, UPPER_NAME
from memory_core.index._index_identity_constants import (
    MEMORY_INDEX_NEWER_ACTION_TEMPLATE,
    MEMORY_INDEX_REBUILD_AGENT_CLAUSE,
    MEMORY_INDEX_REBUILD_COMMAND_TEMPLATE,
    MEMORY_INDEX_STALE_NEWER_ACTION_TEMPLATE,
    MEMORY_INDEX_VERSION_CHANGED_CAUSE_TEMPLATE,
)
from memory_core.tools._memory_tool_constants import (
    MEMORY_SEARCH_DEADLINE_AGENT_ACTION_TEMPLATE,
    MEMORY_SEARCH_MISSING_SQLITE_ACTION,
    MEMORY_SEARCH_MISSING_SQLITE_WARNING,
    SESSION_CANONICAL_KEY_MIGRATION_ACTION,
    SESSION_SEARCH_NOT_ENABLED_ACTION,
)

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
    # memory_search deadline action when the caller has an agent id (OpenClaw
    # extensions/memory-core/src/tools.shared.ts:111-113 names two CLI commands with
    # `--agent`; d46f9ebf2b2 #147702). A str.format template with ``{agent_id}``. The
    # memory-core wording names the store calls that inspect and rebuild the index (decision
    # D4 of docs/upstream_port_v2026_9_6.md, proposed, awaiting Doruk's approval).
    memory_search_deadline_agent_action: str = (
        "Retry memory_search after a short wait: a memory-corpus timeout pauses retries for up "
        "to a minute. If memory-corpus timeouts persist, check "
        "SQLiteMemoryStore.index_identity() for agent {agent_id}, and rebuild with "
        "SQLiteMemoryStore.reindex(workspace) only if it reports the index missing or mismatched"
    )
    # memory_search action for SESSION_CANONICAL_KEY_MIGRATION_REQUIRED (OpenClaw
    # tools.shared.ts:20-21 names the Gateway and `openclaw doctor --fix`). memory-core never
    # raises that code itself; the wording is a D4 proposal.
    memory_search_canonical_key_migration_action: str = (
        "Migrate the session catalog to canonical session keys, then retry memory_search."
    )
    # memory_search action when corpus=sessions is asked for but sessions are not searched
    # (OpenClaw extensions/memory-core/src/tools.ts:260-265 names the config keys
    # memory.search.experimental.sessionMemory and memory.search.sources). memory-core's knob is
    # the search_sources argument of execute_memory_search_tool (D4, proposed).
    session_search_not_enabled_action: str = (
        "If an exact session-history capability is available for this run, use it. Otherwise, "
        'ask the operator to enable semantic session search by adding "sessions" to the search '
        "sources memory_search runs with."
    )
    # Memory index rebuild command of the index search diagnostic (OpenClaw
    # packages/memory-host-sdk/src/host/types.ts:300-311 formatMemoryIndexRebuildGuidance names
    # `openclaw memory status --index` plus ` --agent <id>`). str.format templates: the command
    # with ``{agent_suffix}``, and the suffix with ``{agent_id}`` (used when an agent id is set).
    # memory-core names its one reindex call, which takes no agent (decision D4, proposed).
    memory_index_rebuild_command_template: str = "SQLiteMemoryStore.reindex(workspace){agent_suffix}"
    memory_index_rebuild_agent_clause: str = ""
    # Paused cause for an older index format (types.ts:343, `this OpenClaw version changed the
    # memory index format (${reason}); ...`), with ``{reason}`` (D4).
    memory_index_version_changed_cause_template: str = (
        f"this {DISPLAY_NAME} version changed the memory index format ({{reason}}); no "
        "configuration change is needed"
    )
    # Actions for an index written by a newer version (types.ts:349-350 and 355-356 tell the user
    # to upgrade OpenClaw), with ``{guidance}`` (D4).
    memory_index_newer_action_template: str = (
        f"Tell the user to upgrade {DISPLAY_NAME} or reindex explicitly: {{guidance}}"
    )
    memory_index_stale_newer_action_template: str = (
        f"Upgrade {DISPLAY_NAME} or reindex explicitly: {{guidance}}"
    )
    # How the stale-index warning names the owner of the index format (types.ts:354 prints the
    # identity's `owner`, the protocol value "openclaw"; the returned diagnostic keeps that
    # value, only the prose changes, D4).
    memory_index_owner_label: str = DIST_NAME
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
    memory_search_sqlite_unavailable_warning=MEMORY_SEARCH_MISSING_SQLITE_WARNING,
    memory_search_sqlite_unavailable_action=MEMORY_SEARCH_MISSING_SQLITE_ACTION,
    memory_search_deadline_agent_action=MEMORY_SEARCH_DEADLINE_AGENT_ACTION_TEMPLATE,
    memory_search_canonical_key_migration_action=SESSION_CANONICAL_KEY_MIGRATION_ACTION,
    session_search_not_enabled_action=SESSION_SEARCH_NOT_ENABLED_ACTION,
    memory_index_rebuild_command_template=MEMORY_INDEX_REBUILD_COMMAND_TEMPLATE,
    memory_index_rebuild_agent_clause=MEMORY_INDEX_REBUILD_AGENT_CLAUSE,
    memory_index_version_changed_cause_template=MEMORY_INDEX_VERSION_CHANGED_CAUSE_TEMPLATE,
    memory_index_newer_action_template=MEMORY_INDEX_NEWER_ACTION_TEMPLATE,
    memory_index_stale_newer_action_template=MEMORY_INDEX_STALE_NEWER_ACTION_TEMPLATE,
    memory_index_owner_label="openclaw",
    heartbeat_transcript_prompt=_OPENCLAW_WAKE_PROMPTS["heartbeat"],
    internal_wake_transcript_prompts=tuple(_OPENCLAW_WAKE_PROMPTS.values()),
    session_reset_transcript_prompt="[OpenClaw session {action}]",
)
