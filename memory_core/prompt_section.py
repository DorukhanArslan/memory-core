from __future__ import annotations


def build_prompt_section(available_tools: set[str], *, citations_mode: str) -> list[str]:
    if citations_mode not in {"on", "off"}:
        raise ValueError("citations_mode must be 'on' or 'off'")

    has_memory_search = "memory_search" in available_tools
    has_memory_get = "memory_get" in available_tools
    if not has_memory_search and not has_memory_get:
        return []
    if has_memory_search and has_memory_get:
        tool_guidance = (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos: run memory_search on MEMORY.md + memory/*.md; then use memory_get to "
            "pull only the needed lines. If low confidence after search, say you checked."
        )
    elif has_memory_search:
        tool_guidance = (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos: run memory_search on MEMORY.md + memory/*.md and answer from the matching "
            "results. If low confidence after search, say you checked."
        )
    else:
        tool_guidance = (
            "Before answering anything about prior work, decisions, dates, people, preferences, "
            "or todos that already point to a specific memory file or note: run memory_get to pull "
            "only the needed lines. If low confidence after reading them, say you checked."
        )
    lines = ["## Memory Recall", tool_guidance]
    if citations_mode == "off":
        lines.append(
            "Citations are disabled: do not mention file paths or line numbers in replies unless the user explicitly asks."
        )
    else:
        lines.append("Citations: include Source: <path#line> when it helps the user verify memory snippets.")
    lines.append("")
    return lines
