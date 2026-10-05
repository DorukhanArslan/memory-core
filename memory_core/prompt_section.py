"""``## Memory Recall``, the memory tools' prompt section.

Port of OpenClaw ``extensions/memory-core/src/memory-tool-contract.ts``
``buildMemoryPromptSection`` at v2026.9.6. Besides ``memory_search`` and ``memory_get`` the
section knows the session-history tools: a session hit is a search reference, not a readable
memory-file path, so the section points the model at ``sessions_search`` / ``sessions_history``
when the host offers them and says exact history is unavailable when it does not.
"""

from __future__ import annotations

_PRIOR_WORK = "prior work, decisions, dates, people, preferences, or todos"


def build_prompt_section(available_tools: set[str], *, citations_mode: str) -> list[str]:
    if citations_mode not in {"on", "off"}:
        raise ValueError("citations_mode must be 'on' or 'off'")

    has_memory_search = "memory_search" in available_tools
    has_memory_get = "memory_get" in available_tools
    if not has_memory_search and not has_memory_get:
        return []

    # Code mode may defer tool descriptions; recall and disclosure policy must stay here.
    if has_memory_search:
        get_hint = (
            "; for memory-file hits, use memory_get to pull only the needed lines"
            if has_memory_get
            else ""
        )
        guidance = (
            f"Before answering anything about {_PRIOR_WORK}: run memory_search{get_hint}. "
            "If low confidence after search, say you checked."
        )
    else:
        guidance = (
            f"Before answering anything about {_PRIOR_WORK} that point to a specific memory "
            "file: run memory_get to pull only the needed lines. If low confidence after "
            "reading, say you checked."
        )
    session_guidance: list[str] = []
    if has_memory_search:
        if "sessions_search" in available_tools:
            history = (
                ", then sessions_history with the returned sessionKey, messageId, and "
                "sessionId for a bounded sanitized excerpt"
                if "sessions_history" in available_tools
                else "; exact session history is unavailable with the enabled tools"
            )
            session_hint = (
                "For session hits, use sessions_search with distinctive snippet text (and "
                f"sessionKey set to the transcript ID when known){history}."
            )
        elif "sessions_history" in available_tools:
            session_hint = (
                "For session hits, use sessions_history with a known session key or transcript "
                "ID and a small limit; paginate its returned history metadata to locate the "
                "excerpt."
            )
        else:
            session_hint = (
                "Session hits are search snippets only; exact session history is unavailable "
                "with the enabled tools."
            )
        session_guidance = [
            session_hint,
            "Session search line numbers are not history offsets. Never read raw transcript "
            "files to expand session hits.",
        ]
    outcome_guidance = (
        "Report partial, unavailable, or stale recall to the user, including returned "
        "warning and action guidance."
    )
    if citations_mode == "off":
        citation_guidance = (
            "Citations are disabled: do not mention file paths or line numbers in replies "
            "unless the user explicitly asks."
        )
    else:
        citation_guidance = (
            "Citations: include Source: <path#line> when it helps the user verify memory "
            "snippets."
        )
    return ["## Memory Recall", guidance, *session_guidance, outcome_guidance, citation_guidance, ""]
