from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from memory_core.transcript_tree import select_session_transcript_leaf_controlled_path


@dataclass(frozen=True)
class SessionCorpusFile:
    rel_path: str
    abs_path: Path
    source: str = "sessions"


class MemoryCoreSessionCorpus:
    def __init__(self, state_dir: Path, *, agent_id: str = "main"):
        self.state_dir = state_dir.resolve()
        self.agent_id = agent_id

    @property
    def sessions_dir(self) -> Path:
        return self.state_dir / "agents" / self.agent_id / "sessions"

    def discover_files(self) -> list[SessionCorpusFile]:
        sessions = self._read_session_store()
        files: list[SessionCorpusFile] = []
        for file_name in sorted(_session_file_names(sessions)):
            if "/" in file_name or "\\" in file_name or not file_name.endswith(".jsonl"):
                continue
            path = (self.sessions_dir / file_name).resolve()
            if not path.is_file() or not _is_inside(path, self.sessions_dir.resolve()):
                continue
            session_id = file_name[: -len(".jsonl")]
            files.append(
                SessionCorpusFile(
                    rel_path=f"sessions/{self.agent_id}/{session_id}.jsonl",
                    abs_path=path,
                )
            )
        return files

    def read_index_text(self, file: SessionCorpusFile) -> str:
        entries = _read_jsonl(file.abs_path)
        # OpenClaw readers resolve the active leaf path once navigation
        # controls exist; legacy transcripts keep flat file-order rendering
        # (src/agents/cli-runner/session-history.ts).
        selected = select_session_transcript_leaf_controlled_path(entries)
        lines: list[str] = []
        for entry in entries if selected is None else selected:
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = _message_text(message.get("content")).strip()
            if not text:
                continue
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {text}")
        return "\n".join(lines).rstrip() + ("\n" if lines else "")

    def _read_session_store(self) -> dict[str, Any]:
        path = self.sessions_dir / "sessions.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def _session_file_names(store: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for value in store.values():
        if isinstance(value, dict) and isinstance(value.get("sessionFile"), str):
            names.append(value["sessionFile"])
    return names


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts)


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
