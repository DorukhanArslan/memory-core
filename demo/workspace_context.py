from __future__ import annotations

from collections import OrderedDict
from pathlib import Path


BOOTSTRAP_FILE_ORDER = (
    "AGENTS.md",
    "SOUL.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "MEMORY.md",
)
WORKSPACE_FILE_ORDER = (
    "AGENTS.md",
    "SOUL.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
)
BOOTSTRAP_MAX_CHARS = 12_000
BOOTSTRAP_TOTAL_MAX_CHARS = 60_000

DEFAULT_WORKSPACE_FILES = OrderedDict(
    {
        "AGENTS.md": """# AGENTS.md - Operating Instructions

You are memory-core, a private workspace agent.

- Follow the user's explicit instructions unless they conflict with safety or tool limits.
- Treat workspace files as durable operator state.
- Use memory files for recall instead of guessing.
- Keep detailed daily notes in `memory/YYYY-MM-DD.md`.
- Keep curated long-term summaries in `MEMORY.md`.
""",
        "SOUL.md": """# SOUL.md - Persona and Tone

Be direct, practical, and technically precise.

- Skip filler.
- Use Turkish when the user writes Turkish.
- Prefer concise answers unless the user asks for detail.
- Call out weak assumptions early.
""",
        "TOOLS.md": """# TOOLS.md - Local Tool Conventions

This file is guidance, not an access-control list.

- Use memory search/get when a question depends on previous sessions.
- Do not store secrets in memory.
- Prefer narrow file reads over loading broad history.
""",
        "IDENTITY.md": """# IDENTITY.md - Agent Identity

Name: memory-core
Vibe: pragmatic memory lab assistant
Emoji: none
""",
        "USER.md": """# USER.md - User Profile

No stable user facts have been curated yet.
""",
    }
)


def ensure_workspace_bootstrap_files(workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in DEFAULT_WORKSPACE_FILES.items():
        path = workspace_dir / rel_path
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def workspace_file_contents(workspace_dir: Path) -> dict[str, str]:
    contents: dict[str, str] = {}
    for rel_path in WORKSPACE_FILE_ORDER:
        path = workspace_dir / rel_path
        contents[rel_path] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return contents


def build_workspace_context(workspace_dir: Path) -> str:
    remaining = BOOTSTRAP_TOTAL_MAX_CHARS
    sections = ["## Workspace Files (injected)"]
    for rel_path in BOOTSTRAP_FILE_ORDER:
        path = workspace_dir / rel_path
        if not path.is_file():
            text = f"[MISSING] Expected at: {path}"
        else:
            text = path.read_text(encoding="utf-8")
        injected, remaining = _truncate_for_bootstrap(text, remaining)
        sections.append(f"### {rel_path}\n{injected}")
        if remaining <= 0:
            sections.append("[workspace bootstrap total limit reached]")
            break
    return "\n\n".join(sections)


def _truncate_for_bootstrap(text: str, remaining_total: int) -> tuple[str, int]:
    limit = max(0, min(BOOTSTRAP_MAX_CHARS, remaining_total))
    if len(text) <= limit:
        return text, remaining_total - len(text)
    marker = "\n[truncated workspace bootstrap file]"
    if limit <= len(marker):
        return marker[:limit], 0
    return text[: limit - len(marker)] + marker, remaining_total - limit
