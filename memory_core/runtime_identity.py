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
    heartbeat_transcript_prompt="[OpenClaw heartbeat poll]",
)
