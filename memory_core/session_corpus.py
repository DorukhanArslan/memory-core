from __future__ import annotations

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
    ):
        self.state_dir = state_dir.resolve()
        self.agent_id = agent_id
        # Decides which heartbeat transcript row (HEARTBEAT_TRANSCRIPT_PROMPT) is
        # dropped; transcripts written by an OpenClaw runtime need
        # OPENCLAW_COMPAT_RUNTIME_IDENTITY.
        self.runtime_identity = runtime_identity

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
        # Indexing follows OpenClaw memory ingestion
        # (packages/memory-host-sdk/src/host/session-files.ts buildSessionEntry):
        # every user/assistant message row is rendered in file order, including
        # abandoned and side-append branches; ingestion never calls the
        # transcript-tree helpers. Readers that want the active branch use
        # memory_core.transcript_tree.select_session_transcript_leaf_controlled_path
        # (the src/agents/cli-runner/session-history.ts pattern).
        # Heartbeat prompt rows, silent replies (isSilentReplyPayloadText: NO_REPLY,
        # the canonical quiet heartbeat answer at v2026.9.6) and bare HEARTBEAT_OK
        # replies are dropped like sanitizeSessionText (session-files.ts:529-560 at
        # v2026.9.6). Not ported from that function: inbound-metadata and
        # internal-runtime-context stripping before the checks, whitespace
        # normalisation of the indexed text, the system-wrapper, cron-prompt and
        # exec-completion drops, redaction and 800-char line wrapping.
        lines: list[str] = []
        for entry in _read_jsonl(file.abs_path):
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            raw_text = _message_text(message.get("content"))
            text = raw_text.strip()
            if not text:
                continue
            if self._is_heartbeat_row(raw_text, role):
                continue
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {text}")
        return "\n".join(lines).rstrip() + ("\n" if lines else "")

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
