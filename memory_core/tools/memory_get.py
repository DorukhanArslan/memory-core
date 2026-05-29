from __future__ import annotations

from memory_core.config import MemoryConfig
from memory_core.supplements import MemoryCorpusSupplement
from memory_core.workspace import MemoryWorkspace, UnsafeMemoryPathError


def _continuation_notice(*, next_from: int | None, suggest_read_fallback: bool) -> str:
    if next_from is not None:
        base = f"[More content available. Use from={next_from} to continue.]"
    else:
        base = "[More content available. Requested excerpt exceeded the default maxChars budget.]"
    fallback = " If you need the full raw line, use read on the source file." if suggest_read_fallback else ""
    return f"\n\n{base[:-1]}{fallback}]"


def _fit_lines_to_char_budget(lines: list[str], *, max_chars: int) -> tuple[str, int, bool]:
    if not lines:
        return "", 0, False

    included_lines = len(lines)
    text = "\n".join(lines)
    while included_lines > 1 and len(text) > max_chars:
        included_lines -= 1
        text = "\n".join(lines[:included_lines])

    if len(text) <= max_chars:
        return text, included_lines, False

    return text[:max_chars], 1, True


def memory_get(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None = None,
    lines: int | None = None,
    corpus: str = "memory",
    supplements: list[MemoryCorpusSupplement] | None = None,
) -> dict:
    workspace = MemoryWorkspace(config.workspace_dir)
    normalized_path = workspace.normalize_memory_path(path)
    if corpus == "wiki":
        return _memory_get_supplement(
            config,
            path=normalized_path,
            from_line=from_line,
            lines=lines,
            corpus=corpus,
            supplements=supplements or [],
        )
    try:
        memory_path = workspace.resolve_memory_path(path)
        rel_path = normalized_path
        content = memory_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"text": "", "path": workspace.normalize_memory_path(path)}
    except UnsafeMemoryPathError:
        return {"path": path, "text": "", "disabled": True, "error": "path required"}
    except Exception as exc:
        return {"path": path, "text": "", "disabled": True, "error": str(exc)}

    return _memory_get_text(
        config,
        path=rel_path,
        content=content,
        from_line=from_line,
        lines=lines,
    )


def _memory_get_supplement(
    config: MemoryConfig,
    *,
    path: str,
    from_line: int | None,
    lines: int | None,
    corpus: str,
    supplements: list[MemoryCorpusSupplement],
) -> dict:
    result = None
    for supplement in supplements:
        result = supplement.get(path=path, corpus=corpus)
        if result is not None:
            break
    if result is None:
        return {
            "path": path,
            "text": "",
            "disabled": True,
            "error": "wiki corpus result not found",
        }
    content = result.get("content") or result.get("snippet") or ""
    text_result = _memory_get_text(
        config,
        path=path,
        content=str(content),
        from_line=from_line,
        lines=lines,
    )
    text_result["corpus"] = result.get("corpus", corpus)
    return text_result


def _memory_get_text(
    config: MemoryConfig,
    *,
    path: str,
    content: str,
    from_line: int | None,
    lines: int | None,
) -> dict:
    file_lines = content.split("\n")
    start = max(1, from_line or 1)
    requested_count = max(1, lines if lines is not None else config.memory_get_default_lines)
    selected_lines = file_lines[start - 1 : start - 1 + requested_count]
    more_source_lines_remain = start - 1 + len(selected_lines) < len(file_lines)
    text, included_lines, hard_truncated_single_line = _fit_lines_to_char_budget(
        selected_lines,
        max_chars=max(1, config.memory_get_max_chars),
    )
    char_cap_truncated = hard_truncated_single_line or included_lines < len(selected_lines)
    next_from = (
        start + included_lines
        if not hard_truncated_single_line
        and (more_source_lines_remain or included_lines < len(selected_lines))
        else None
    )
    truncated = char_cap_truncated or more_source_lines_remain
    if truncated and text:
        text = f"{text}{_continuation_notice(next_from=next_from, suggest_read_fallback=hard_truncated_single_line)}"

    output = {
        "text": text,
        "path": path,
        "from": start,
        "lines": included_lines,
    }
    if truncated:
        output["truncated"] = True
    if next_from is not None:
        output["nextFrom"] = next_from
    return output
