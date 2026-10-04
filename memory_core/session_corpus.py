from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim
from memory_core.heartbeat import (
    HEARTBEAT_PROMPT,
    HEARTBEAT_TOKEN,
    is_heartbeat_user_message,
    is_silent_reply_payload_text,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_entry import build_session_entry, parse_jsonl_records

_NEWLINE_RUN_RE = re.compile(f"[{JS_SPACE_CLASS}]*\n+[{JS_SPACE_CLASS}]*")
_WHITESPACE_RUN_RE = re.compile(f"[{JS_SPACE_CLASS}]+")


@dataclass(frozen=True)
class SessionCorpusFile:
    rel_path: str
    abs_path: Path
    source: str = "sessions"


class MemoryCoreSessionCorpus:
    def __init__(
        self,
        state_dir: Path,
        *,
        agent_id: str = "main",
        runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
        redact_text: Callable[[str], str] | None = None,
    ):
        self.state_dir = state_dir.resolve()
        self.agent_id = agent_id
        # Decides which heartbeat transcript row (HEARTBEAT_TRANSCRIPT_PROMPT) is
        # dropped; transcripts written by an OpenClaw runtime need
        # OPENCLAW_COMPAT_RUNTIME_IDENTITY.
        self.runtime_identity = runtime_identity
        # Host redaction of every indexed text (upstream: redactSensitiveText, mode tools).
        self.redact_text = redact_text

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
        # Indexing follows OpenClaw memory ingestion (buildSessionEntry, ported in
        # memory_core.session_entry): every user/assistant message row in file order, including
        # abandoned and side-append branches (ingestion never calls the transcript-tree helpers),
        # rendered as "User:"/"Assistant:" lines with whitespace normalised, long lines wrapped
        # at 800 characters, and heartbeat, cron, exec-completion, silent-reply, inter-session,
        # recalled-memory and dreaming-narrative rows dropped. Not ported: redaction (pass
        # ``redact_text`` to build_session_entry from a host), see session_entry's docstring.
        try:
            mtime_ms = file.abs_path.stat().st_mtime * 1000
        except OSError:
            mtime_ms = 0
        entry = build_session_entry(
            records=parse_jsonl_records(file.abs_path.read_text(encoding="utf-8")),
            mtime_ms=mtime_ms,
            session_key=None,
            runtime_identity=self.runtime_identity,
            redact_text=self.redact_text,
        )
        return entry.content + ("\n" if entry.content else "")

    def _is_heartbeat_row(self, raw_text: str, role: str) -> bool:
        # Checks run on normalizeSessionText output (sanitizeSessionText at v2026.9.6), so
        # a heartbeat prompt followed by a newline and more text no longer matches.
        normalized = _normalize_session_text(raw_text)
        if role == "user" and is_heartbeat_user_message(
            {"role": role, "content": normalized},
            HEARTBEAT_PROMPT,
            runtime_identity=self.runtime_identity,
        ):
            return True
        if is_silent_reply_payload_text(normalized):
            return True
        return role == "assistant" and normalized == HEARTBEAT_TOKEN

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


def _normalize_session_text(value: str) -> str:
    return js_trim(_WHITESPACE_RUN_RE.sub(" ", _NEWLINE_RUN_RE.sub(" ", value)))


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
