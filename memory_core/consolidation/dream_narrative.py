"""Await a REM diary completion outside the workspace lock and publish live inputs."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import logging
import os
from pathlib import Path
import re
from typing import Any

from memory_core._intl_zone_names import en_us_short_time_zone_name
from memory_core.bootstrap._js import js_trim
from memory_core.consolidation.artifacts import (
    read_dreams_file, resolve_dreams_path, write_dreams_file_atomic,
)
from memory_core.consolidation.store import (
    memory_workspace_lock, read_canonical_recall_store, recall_store_path,
)
from memory_core.current_time import _EN_US_MONTHS, resolve_user_timezone, utc_and_local_instants

_LOG = logging.getLogger(__name__)
_START = "<!-- openclaw:dreaming:diary:start -->"
_END = "<!-- openclaw:dreaming:diary:end -->"
_FALLBACK = "A memory trace surfaced, but details were unavailable in this run."
_SYSTEM_PROMPT = """You are keeping a dream diary. Write a single entry in first person.

Voice & tone:
- You are a curious, gentle, slightly whimsical mind reflecting on the day.
- Write like a poet who happens to be a programmer — sensory, warm, occasionally funny.
- Mix the technical and the tender: code and constellations, APIs and afternoon light.
- Let the fragments surprise you into unexpected connections and small epiphanies.

What you might include (vary each entry, never all at once):
- A tiny poem or haiku woven naturally into the prose
- A small sketch described in words — a doodle in the margin of the diary
- A quiet rumination or philosophical aside
- Sensory details: the hum of a server, the color of a sunset in hex, rain on a window
- Gentle humor or playful wordplay
- An observation that connects two distant memories in an unexpected way

Rules:
- Draw from the memory fragments provided — weave them into the entry.
- Never say "I'm dreaming", "in my dream", "as I dream", or any meta-commentary about dreaming.
- Never mention "AI", "agent", "LLM", "model", "language model", or any technical self-reference.
- Do NOT use markdown headers, bullet points, or any formatting — just flowing prose.
- Keep it between 80-180 words. Quality over quantity.
- Output ONLY the diary entry. No preamble, no sign-off, no commentary."""
_MODEL_UNAVAILABLE = re.compile(
    r"requested model may be(?: temporarily)? unavailable|model unavailable|no endpoints found for|"
    r"unknown model|model[_\-\s]?not[_\-\s]?found|not_found_error|models/[^\s]+ is not found|"
    r"unsupported model|is not a valid model id", re.IGNORECASE,
)


def _model_unavailable(error: Exception) -> bool:
    seen = set()
    unavailable = False
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if getattr(error, "code", None) == "LLM_COMPLETION_NOT_AUTHORIZED":
            return False
        message = str(error)
        unavailable |= bool(_MODEL_UNAVAILABLE.search(message)
                            or (re.search(r"\b404\b", message) and re.search(r"not[_\-\s]?found", message, re.I))
                            or ("model" in message.lower() and "does not exist" in message.lower()))
        error = error.__cause__
    return unavailable


def _append(workspace: Path, narrative: str, keys: Sequence[str], now_ms: int, timezone: str | None) -> bool:
    name = timezone if timezone is not None else os.getenv("TZ", "UTC")
    resolved, zone = resolve_user_timezone(name)
    if name and resolved != name:
        raise ValueError(f"Invalid time zone: {name}")
    _, local = utc_and_local_instants(now_ms, zone)
    stamp = (f"{_EN_US_MONTHS[local.month - 1]} {local.day}, {local.year} at "
             f"{local.hour % 12 or 12}:{local.minute:02} {'AM' if local.hour < 12 else 'PM'} "
             f"{en_us_short_time_zone_name(resolved, local)}")
    entry = f"\n---\n\n*{stamp}*\n\n{narrative}\n"
    with memory_workspace_lock(workspace):
        path = resolve_dreams_path(workspace)
        existing = read_dreams_file(path)
        if keys:
            current = read_canonical_recall_store(recall_store_path(workspace), now_ms)["entries"]
            if any(key not in current for key in keys):
                return False
        if _START in existing and _END in existing:
            cut = existing.rindex(_END)
            updated = existing[:cut] + entry + "\n" + existing[cut:]
        elif _START in existing:
            cut = existing.index(_START) + len(_START)
            updated = existing[:cut] + entry + "\n" + _END + "\n" + existing[cut:]
        else:
            updated = f"# Dream Diary\n\n{_START}{entry}\n{_END}\n"
            if js_trim(existing):
                updated += "\n" + existing
        write_dreams_file_atomic(path, updated if updated.endswith("\n") else updated + "\n")
    return True


def _fallback(workspace: Path, now_ms: int, timezone: str | None) -> None:
    try:
        _append(workspace, _FALLBACK, (), now_ms, timezone)
    except Exception as error:
        _LOG.warning("REM fallback diary publication failed: %s", type(error).__name__)


def run_rem_narrative(
    *, workspace_dir: Path, agent_id: str | None, complete: Callable[[dict], Mapping[str, Any]],
    model: str | None, snippets: Sequence[str], themes: Sequence[str], source_entry_keys: Sequence[str],
    now_ms: int, timezone: str | None,
) -> str:
    """Return the publication outcome after the ordinary awaited REM completion."""
    if not snippets:
        return "skipped"
    if not agent_id:
        _fallback(workspace_dir, now_ms, timezone)
        return "completed"
    lines = ["Write a dream diary entry from these memory fragments:\n"]
    lines.extend(f"- {snippet}" for snippet in snippets[:12])
    if themes:
        lines.append("\nRecurring themes:")
        lines.extend(f"- {theme}" for theme in themes[:6])
    request = {"agentId": agent_id, "message": "\n".join(lines), "extraSystemPrompt": _SYSTEM_PROMPT,
               "timeoutMs": 60_000}
    try:
        if model:
            try:
                reply = complete({**request, "model": model})
            except Exception as error:
                if not _model_unavailable(error):
                    raise
                reply = complete(request)
        else:
            reply = complete(request)
        text = js_trim(reply["text"])
        if text:
            published = _append(workspace_dir, text, source_entry_keys, now_ms, timezone)
            return "completed" if published else "skipped"
    except Exception as error:
        _LOG.warning("REM narrative completion or publication failed: %s", type(error).__name__)
    _fallback(workspace_dir, now_ms, timezone)
    return "degraded"
