"""The ``## Memory Recall`` system-prompt section.

Port of ``buildMemoryPromptSection`` (``extensions/memory-core/src/memory-tool-contract.ts:108-145``
at OpenClaw v2026.9.6; the session-hit lines came with 67f55de5553 #144669). The texts are
script-extracted into ``memory_core.tools._memory_tool_constants``.

The section depends only on which tools the turn offers: with ``memory_search`` it tells the
model to search first (and to read memory-file hits with ``memory_get`` when that tool is
offered), then how to follow up session hits with the offered session tools (``sessions_search``,
``sessions_history``; memory-core's host kit offers neither), then to report partial,
unavailable or stale recall, then the citation rule. Upstream prints the "on" citation line for
any mode but ``"off"``; memory-core has only ``on``/``off`` (``MemoryConfig.citation_mode``), so
another value raises (the ``auto`` mode is not ported).
"""

from __future__ import annotations

from collections.abc import Collection

from memory_core.tools._memory_tool_constants import (
    MEMORY_RECALL_CITATIONS_OFF,
    MEMORY_RECALL_CITATIONS_ON,
    MEMORY_RECALL_GET_ONLY,
    MEMORY_RECALL_HEADING,
    MEMORY_RECALL_OUTCOME,
    MEMORY_RECALL_SEARCH_GET_CLAUSE,
    MEMORY_RECALL_SEARCH_TEMPLATE,
    MEMORY_RECALL_SESSION_LINE_NUMBERS,
    MEMORY_RECALL_SESSIONS_HISTORY_CLAUSE,
    MEMORY_RECALL_SESSIONS_HISTORY_ONLY,
    MEMORY_RECALL_SESSIONS_NO_HISTORY_CLAUSE,
    MEMORY_RECALL_SESSIONS_SEARCH_TEMPLATE,
    MEMORY_RECALL_SESSIONS_SNIPPETS_ONLY,
    SESSIONS_HISTORY_TOOL_NAME,
    SESSIONS_SEARCH_TOOL_NAME,
)


def build_prompt_section(available_tools: Collection[str], *, citations_mode: str) -> list[str]:
    """The section's lines, ending with ``""``; ``[]`` without ``memory_search``/``memory_get``."""
    if citations_mode not in {"on", "off"}:
        raise ValueError("citations_mode must be 'on' or 'off'")

    has_memory_search = "memory_search" in available_tools
    has_memory_get = "memory_get" in available_tools
    if not has_memory_search and not has_memory_get:
        return []
    guidance = (
        MEMORY_RECALL_SEARCH_TEMPLATE.format(
            memory_get_clause=MEMORY_RECALL_SEARCH_GET_CLAUSE if has_memory_get else ""
        )
        if has_memory_search
        else MEMORY_RECALL_GET_ONLY
    )
    session_guidance: list[str] = []
    if has_memory_search:
        if SESSIONS_SEARCH_TOOL_NAME in available_tools:
            session_hits = MEMORY_RECALL_SESSIONS_SEARCH_TEMPLATE.format(
                history_clause=(
                    MEMORY_RECALL_SESSIONS_HISTORY_CLAUSE
                    if SESSIONS_HISTORY_TOOL_NAME in available_tools
                    else MEMORY_RECALL_SESSIONS_NO_HISTORY_CLAUSE
                )
            )
        elif SESSIONS_HISTORY_TOOL_NAME in available_tools:
            session_hits = MEMORY_RECALL_SESSIONS_HISTORY_ONLY
        else:
            session_hits = MEMORY_RECALL_SESSIONS_SNIPPETS_ONLY
        session_guidance = [session_hits, MEMORY_RECALL_SESSION_LINE_NUMBERS]
    citation_guidance = (
        MEMORY_RECALL_CITATIONS_OFF if citations_mode == "off" else MEMORY_RECALL_CITATIONS_ON
    )
    return [
        MEMORY_RECALL_HEADING,
        guidance,
        *session_guidance,
        MEMORY_RECALL_OUTCOME,
        citation_guidance,
        "",
    ]
