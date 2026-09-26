from __future__ import annotations

from dataclasses import dataclass


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
    # src/agents/system-prompt.ts:1232 names the runtime).
    workspace_files_injected_line: str = (
        "These user-editable files are loaded by memory-core and included below in Project Context."
    )
    # memory_search unavailable guidance when the failure reason names a
    # missing SQLite runtime (OpenClaw extensions/memory-core/src/tools.shared.ts
    # buildMemorySearchUnavailableResult names its Node runtime).
    memory_search_sqlite_unavailable_warning: str = (
        "Memory search is unavailable because this memory-core Python runtime does not provide "
        "SQLite support."
    )
    memory_search_sqlite_unavailable_action: str = (
        "Run memory-core with a Python build that includes the sqlite3 module, then retry "
        "memory_search."
    )
    # memory_search paused-index action (OpenClaw extensions/memory-core/src/tools.ts
    # PAUSED_MEMORY_INDEX_ACTION names two CLI commands that both reindex; memory-core
    # names its one reindex call, since index_identity() only reports).
    memory_search_paused_action: str = (
        "Tell the user to run: SQLiteMemoryStore.reindex(workspace)."
    )
    # Transcript row recorded for a heartbeat turn instead of the full heartbeat
    # prompt (OpenClaw src/auto-reply/heartbeat.ts:23 HEARTBEAT_TRANSCRIPT_PROMPT,
    # written by src/auto-reply/reply/prompt-prelude.ts:231-232).
    heartbeat_transcript_prompt: str = "[memory-core heartbeat poll]"


MEMORY_CORE_RUNTIME_IDENTITY = RuntimeIdentity(
    runtime_context_begin="<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>",
    runtime_context_end="<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>",
    runtime_context_custom_type="memory_core.runtime-context",
    runtime_context_source="memory-core-runtime-context",
    next_turn_runtime_context_header="memory-core runtime context for the immediately preceding user message.",
    runtime_event_header="memory-core runtime event.",
    runtime_event_user_prompt="Continue the memory-core runtime event.",
    workspace_files_injected_line=(
        "These user-editable files are loaded by memory-core and included below in Project Context."
    ),
    memory_search_sqlite_unavailable_warning=(
        "Memory search is unavailable because this memory-core Python runtime does not provide "
        "SQLite support."
    ),
    memory_search_sqlite_unavailable_action=(
        "Run memory-core with a Python build that includes the sqlite3 module, then retry "
        "memory_search."
    ),
    memory_search_paused_action=(
        "Tell the user to run: SQLiteMemoryStore.reindex(workspace)."
    ),
    heartbeat_transcript_prompt="[memory-core heartbeat poll]",
)

OPENCLAW_COMPAT_RUNTIME_IDENTITY = RuntimeIdentity(
    runtime_context_begin="<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>",
    runtime_context_end="<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
    runtime_context_custom_type="openclaw.runtime-context",
    runtime_context_source="openclaw-runtime-context",
    next_turn_runtime_context_header="OpenClaw runtime context for the immediately preceding user message.",
    runtime_event_header="OpenClaw runtime event.",
    runtime_event_user_prompt="Continue the OpenClaw runtime event.",
    workspace_files_injected_line=(
        "These user-editable files are loaded by OpenClaw and included below in Project Context."
    ),
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
    heartbeat_transcript_prompt="[OpenClaw heartbeat poll]",
)
