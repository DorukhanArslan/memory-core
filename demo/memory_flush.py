from __future__ import annotations

from dataclasses import dataclass
import difflib
import json
from pathlib import Path
from typing import Protocol

from demo.chat_engine import ChatEngine, ChatMessage
from memory_core.config import MemoryConfig
from memory_core.memory_flush import (
    SILENT_REPLY_TOKEN,
    UnsafeMemoryFlushTargetError,
    build_memory_flush_plan,
    validate_daily_memory_target,
)
from memory_core.workspace import MemoryWorkspace


class MemoryStore(Protocol):
    def reindex(self, workspace: MemoryWorkspace) -> int:
        raise NotImplementedError

    def count_chunks(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class ParsedFlushOutput:
    should_write: bool
    target: str
    entry: str
    reason: str
    error: str | None = None


@dataclass(frozen=True)
class MemoryFlushRun:
    target: str
    raw_text: str
    parsed: ParsedFlushOutput
    diff: str
    indexed_files: int
    chunks: int


def parse_flush_output(raw_text: str, *, target: str) -> ParsedFlushOutput:
    text = raw_text.strip()
    if text.startswith(SILENT_REPLY_TOKEN):
        return ParsedFlushOutput(
            should_write=False,
            target=target,
            entry="",
            reason="silent reply",
        )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return ParsedFlushOutput(
            should_write=False,
            target=target,
            entry="",
            reason="invalid JSON",
            error=f"invalid JSON flush output: {exc.msg}",
        )

    if not isinstance(payload, dict):
        return ParsedFlushOutput(
            should_write=False,
            target=target,
            entry="",
            reason="invalid payload",
            error="flush output must be a JSON object",
        )

    output_target = _string_field(payload, "target") or target
    reason = _string_field(payload, "reason")
    entry = _string_field(payload, "entry")
    should_write = bool(payload.get("shouldWrite", payload.get("should_write", False)))

    if output_target != target:
        return ParsedFlushOutput(
            should_write=False,
            target=output_target,
            entry="",
            reason=reason,
            error=f"flush target mismatch: expected {target}, got {output_target}",
        )

    try:
        validate_daily_memory_target(output_target)
    except UnsafeMemoryFlushTargetError as exc:
        return ParsedFlushOutput(
            should_write=False,
            target=output_target,
            entry="",
            reason=reason,
            error=str(exc),
        )

    if should_write and not entry.strip():
        return ParsedFlushOutput(
            should_write=False,
            target=output_target,
            entry="",
            reason=reason,
            error="flush output requested a write with an empty entry",
        )

    return ParsedFlushOutput(
        should_write=should_write,
        target=output_target,
        entry=entry if should_write else "",
        reason=reason,
    )


def run_memory_flush(
    *,
    config: MemoryConfig,
    store: MemoryStore,
    engine: ChatEngine,
    transcript: list[ChatMessage],
    now_ms: int | None = None,
    timezone: str = "UTC",
) -> MemoryFlushRun:
    plan = build_memory_flush_plan(
        workspace_dir=config.workspace_dir,
        now_ms=now_ms,
        timezone=timezone,
    )
    workspace = MemoryWorkspace(config.workspace_dir)
    target_path = workspace.resolve_memory_path(plan.relative_path)
    before = _read_text_if_exists(target_path)

    output = engine.flush(
        system_prompt=plan.system_prompt,
        prompt=plan.prompt,
        transcript=transcript,
        target=plan.relative_path,
    )
    parsed = parse_flush_output(output.raw_text, target=plan.relative_path)

    indexed_files = 0
    if parsed.should_write and parsed.error is None:
        workspace.append_daily_memory(parsed.target, parsed.entry)
        indexed_files = store.reindex(workspace)

    after = _read_text_if_exists(target_path)
    return MemoryFlushRun(
        target=plan.relative_path,
        raw_text=output.raw_text,
        parsed=parsed,
        diff=_unified_diff(before, after, plan.relative_path),
        indexed_files=indexed_files,
        chunks=store.count_chunks(),
    )


def _string_field(payload: dict, name: str) -> str:
    value = payload.get(name)
    return value if isinstance(value, str) else ""


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _unified_diff(before: str, after: str, target: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
        )
    )
