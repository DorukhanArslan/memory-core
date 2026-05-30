from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryBranding:
    runtime_context_begin: str
    runtime_context_end: str
    runtime_context_custom_type: str
    runtime_context_source: str
    next_turn_runtime_context_header: str
    runtime_event_header: str
    runtime_event_user_prompt: str


MEMORY_CORE_BRANDING = MemoryBranding(
    runtime_context_begin="<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>",
    runtime_context_end="<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>",
    runtime_context_custom_type="memory_core.runtime-context",
    runtime_context_source="memory-core-runtime-context",
    next_turn_runtime_context_header="memory-core runtime context for the immediately preceding user message.",
    runtime_event_header="memory-core runtime event.",
    runtime_event_user_prompt="Continue the memory-core runtime event.",
)

OPENCLAW_COMPAT_BRANDING = MemoryBranding(
    runtime_context_begin="<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>",
    runtime_context_end="<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
    runtime_context_custom_type="openclaw.runtime-context",
    runtime_context_source="openclaw-runtime-context",
    next_turn_runtime_context_header="OpenClaw runtime context for the immediately preceding user message.",
    runtime_event_header="OpenClaw runtime event.",
    runtime_event_user_prompt="Continue the OpenClaw runtime event.",
)
