from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from memory_core import MemoryChatTurn, MemoryCoreMemory


def prepare_chatbot_turn(
    memory: MemoryCoreMemory,
    user_message: str,
    *,
    system_prompt: str | None = None,
) -> MemoryChatTurn:
    if system_prompt is None:
        return memory.prepare_turn(user_message)
    return memory.prepare_turn(user_message, system_prompt=system_prompt)


def answer_with_memory(
    memory: MemoryCoreMemory,
    user_message: str,
    chat: Callable[[list[dict[str, str]]], str],
    *,
    system_prompt: str | None = None,
) -> str:
    turn = prepare_chatbot_turn(memory, user_message, system_prompt=system_prompt)
    return chat(turn.messages)


def seed_demo_memory(workspace_dir: str | Path) -> None:
    root = Path(workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "MEMORY.md").write_text(
        "# MEMORY.md\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )
