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
    # Last bootstrap truncation warning line (OpenClaw
    # src/agents/bootstrap-budget.ts:312-314 names OpenClaw config keys).
    bootstrap_truncation_limits_line: str = (
        "If unintentional, raise the per-file and/or total bootstrap character limits."
    )
    # Prefix of the `<!-- <prefix><recall key> -->` marker written above each promoted
    # MEMORY.md entry (OpenClaw extensions/memory-core/src/short-term-promotion.ts:52
    # PROMOTION_MARKER_PREFIX). memory_core.consolidation reads every known prefix and writes
    # this one.
    promotion_marker_prefix: str = "memory-core-memory-promotion:"


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
    bootstrap_truncation_limits_line=(
        "If unintentional, raise the per-file and/or total bootstrap character limits."
    ),
    promotion_marker_prefix="memory-core-memory-promotion:",
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
    bootstrap_truncation_limits_line=(
        "If unintentional, raise agents.defaults.bootstrapMaxChars and/or "
        "agents.defaults.bootstrapTotalMaxChars."
    ),
    promotion_marker_prefix="openclaw-memory-promotion:",
)
