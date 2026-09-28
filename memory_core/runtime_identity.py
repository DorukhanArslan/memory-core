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
    # memory_search paused-index action (OpenClaw extensions/memory-core/src/tools.ts
    # PAUSED_MEMORY_INDEX_ACTION names two CLI commands that both reindex; memory-core
    # names its one reindex call, since index_identity() only reports).
    memory_search_paused_action: str = (
        "Tell the user to run: SQLiteMemoryStore.reindex(workspace)."
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
    memory_search_paused_action=(
        "Tell the user to run: openclaw memory status --index or openclaw memory index --force."
    ),
    heartbeat_transcript_prompt=_OPENCLAW_WAKE_PROMPTS["heartbeat"],
    internal_wake_transcript_prompts=tuple(_OPENCLAW_WAKE_PROMPTS.values()),
    session_reset_transcript_prompt="[OpenClaw session {action}]",
)
