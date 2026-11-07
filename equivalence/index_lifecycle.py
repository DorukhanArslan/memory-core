"""Filesystem/session refresh fixtures for the actual production index owners.

The native counterpart loads the authenticated published MemoryIndexManager,
not a reimplementation of its sync planner. Actual chunk identifiers are
retained; execution-clock write times compare their relationships. Session source
hashes compare their complete SessionEntry snapshot suffix; the durable SQLite
revision prefix and serialized byte counts are private host representations.
Raw native states may additionally be saved by the release runner as evidence.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
from typing import Any

_TIME = 1_700_000_000_000


def _message(role: str, text: str, offset: int = 0) -> dict:
    return {"role": role, "content": [{"type": "text", "text": text}],
            "timestamp": _TIME + offset}


def build_index_lifecycle_cases() -> list[dict[str, Any]]:
    definitions = [
        ("memory-create-update-rename-delete-reopen", {
            "files": {"memory/note.md": "Alpha durable note.", "USER.md": "Use short replies."},
            "steps": [
                {"label": "initial"}, {"label": "unchanged"},
                {"label": "created", "write": {"memory/second.md": "Beta new note."}},
                {"label": "changed", "write": {"memory/note.md": "Gamma revised note."}},
                {"label": "renamed", "rename": {"memory/second.md": "memory/renamed.md"}},
                {"label": "reopened-unchanged", "reopen": True},
                {"label": "deleted", "remove": ["memory/note.md", "memory/renamed.md"]},
            ],
        }),
        ("same-size-time-content-change", {
            "files": {"memory/note.md": "First durable note."},
            "steps": [{"label": "initial"},
                      {"label": "same-size-new-content", "write": {"memory/note.md": "Other durable note."}},
                      {"label": "unchanged"}, {"label": "reopened-unchanged", "reopen": True}],
        }),
        ("empty-and-whitespace-sources", {
            "files": {"memory/empty.md": "", "memory/whitespace.md": " \n\t", "memory/note.md": "Alpha note."},
            "steps": [{"label": "initial"}, {"label": "unchanged"},
                      {"label": "emptied", "write": {"memory/note.md": ""}},
                      {"label": "deleted", "remove": ["memory/empty.md", "memory/whitespace.md"]}],
        }),
        ("recognized-memory-provenance", {
            "files": {"MEMORY.md": "# Preferences\n\nPrefer glacier tea.",
                      "memory/dreaming/note.md": "Dreaming system note.",
                      "memory/.dreams/note.md": "Dreaming hidden note.",
                      "DREAMS.md": "Dreaming root note."},
            "steps": [{"label": "initial"}, {"label": "unchanged"}],
        }),
        ("session-create-append-delete-reopen", {
            "files": {"memory/note.md": "Alpha workspace note."},
            "sessions": {"session-a": [_message("user", "Remember glacier tea.")]},
            "steps": [{"label": "initial"}, {"label": "unchanged"},
                      {"label": "session-appended", "appendSessions": {
                          "session-a": [_message("assistant", "I will remember glacier tea.", 1000)]}},
                      {"label": "session-renamed", "renameSessions": {"session-a": "session-renamed"}},
                      {"label": "session-created", "createSessions": {
                          "session-b": [_message("user", "Use concise replies.", 2000)]}},
                      {"label": "reopened-unchanged", "reopen": True},
                      {"label": "session-deleted", "deleteSessions": ["session-renamed"]}],
        }),
        ("chunk-write-failure-retains-published-state", {
            "files": {"memory/note.md": "Alpha published note."},
            "steps": [{"label": "initial"},
                      {"label": "failed-change", "write": {"memory/note.md": "Beta replacement note."},
                       "failChunkWrite": True},
                      {"label": "retry"}, {"label": "reopened-unchanged", "reopen": True}],
        }),
    ]
    return [{"id": f"lifecycle-{name}", "requirement": "indexing.incremental-sync",
             "operation": "index-lifecycle-runtime", "input": {"mtimeMs": _TIME, **deepcopy(value)},
             "driverScope": "Real native CLI MemoryIndexManager with fixture-driven existing watcher/reconciliation dirty notifications. Session rename is a public host transfer: read stored messages, delete the old identity, upsert a new identity, append in order, then one complete reconciliation. OS watcher scheduling, embedding orchestration and binary transcript interchange are separate contracts.",
             "normalizationPolicy": "Actual chunk IDs, public paths and source mtimes are retained; execution clocks compare retained/rewritten; SQLite session revision prefixes compare complete SessionEntry hashes and retention. Session transport byte counts compare zero/nonzero, retention and change direction; memory byte counts remain exact. Absolute raw states and all host meta keys are retained separately; semantic meta is the full memory_index_meta_v1 identity.",
             "covers": ["indexing.incremental-sync.outcomes", "indexing.incremental-sync.boundaries"]}
            for name, value in definitions]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _normalize(raw: dict, previous: dict | None) -> dict:
    """Translate only private storage encodings; keep every semantic row."""
    keys = {chunk["id"]: _canonical([chunk["source"], chunk["path"], chunk["startLine"],
                                    chunk["endLine"], chunk["text"]]) for chunk in raw["chunks"]}
    old_keys = {} if previous is None else {
        _canonical([c["source"], c["path"], c["startLine"], c["endLine"], c["text"]]): c
        for c in previous["chunks"]}

    chunks = []
    clocks = {}
    for row in raw["chunks"]:
        row = deepcopy(row)
        key = keys[row["id"]]
        before = old_keys.get(key)
        clocks[row["id"]] = "new" if before is None else (
            "retained" if before.get("updatedAt") == row.get("updatedAt") else "rewritten")
        row["updatedAt"] = clocks[row["id"]]
        row["identityRetained"] = before is not None and before["id"] == row["id"]
        chunks.append(row)
    sources = []
    old_sources = {} if previous is None else {(s["source"], s["path"]): s for s in previous["sources"]}
    for row in raw["sources"]:
        row = deepcopy(row)
        before = old_sources.get((row["source"], row["path"]))
        row["hashRetained"] = before is not None and before["hash"] == row["hash"]
        if row["source"] == "sessions":
            # Native durable-session revisions precede the complete snapshot
            # hash. JSONL is the Python host transport, not a SQLite replica.
            if row["hash"].startswith("sqlite:"):
                row["hash"] = row["hash"].split(":", 2)[2]
            size = row["size"]
            row["size"] = {
                "empty": size == 0,
                "retained": before is not None and before["size"] == size,
                "direction": None if before is None else (
                    (size > before["size"]) - (size < before["size"])),
            }
        sources.append(row)
    result = {"sources": sources, "chunks": chunks, "paths": deepcopy(raw["paths"])}
    for collection, field in (("fts", "id"), ("details", "chunkId"),
                              ("provenance", "chunkId"), ("recall", "chunkId")):
        rows = []
        for original in raw[collection]:
            row = deepcopy(original)
            if "updatedAt" in row:
                row["updatedAt"] = clocks.get(row[field], "orphan")
            rows.append(row)
        result[collection] = rows
    # Store-private sync counters and wall clock values are not index identity.
    result["meta"] = [{"key": row["key"], "value": json.loads(row["value"])} for row in raw["meta"]
                      if row["key"] == "memory_index_meta_v1"]
    for collection in result:
        result[collection].sort(key=_canonical)
    return result


def run_index_lifecycle(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict:
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.workspace import MemoryWorkspace

    inputs = deepcopy(arguments)
    with tempfile.TemporaryDirectory(prefix="memory-core-index-lifecycle-") as directory:
        root = Path(directory)
        workspace, state = root / "workspace", root / "state"
        workspace.mkdir()
        session_dir = state / "agents" / "main" / "sessions"
        session_dir.mkdir(parents=True)
        metadata: dict[str, dict] = {}

        def write_files(files):
            for relative, text in files.items():
                filename = workspace / relative
                filename.parent.mkdir(parents=True, exist_ok=True)
                filename.write_text(text, encoding="utf-8", newline="")
                os.utime(filename, ns=(inputs["mtimeMs"] * 1_000_000,) * 2)

        def append_session(identifier, messages, create=False):
            filename = session_dir / f"{identifier}.jsonl"
            if create:
                filename.write_text(_canonical({"type": "session", "id": identifier}) + "\n")
            with filename.open("a", encoding="utf-8") as stream:
                for message in messages:
                    stream.write(_canonical({"type": "message", "message": message}) + "\n")
            if create:
                timestamp = max((message["timestamp"] for message in messages), default=inputs["mtimeMs"])
                metadata[f"agent:main:{identifier}"] = {
                    "sessionId": identifier, "sessionFile": filename.name,
                    "updatedAt": timestamp, "chatType": "direct"}
            # The native durable append API changes transcript revision/bytes,
            # while its session-store activity timestamp remains unchanged.
            # Arrange the corresponding JSONL timestamp explicitly too.
            timestamp = metadata[f"agent:main:{identifier}"]["updatedAt"]
            os.utime(filename, ns=(timestamp * 1_000_000,) * 2)
            (session_dir / "sessions.json").write_text(_canonical(metadata), encoding="utf-8")

        write_files(inputs.get("files", {}))
        for identifier, messages in inputs.get("sessions", {}).items():
            append_session(identifier, messages, create=True)
        host = MemoryWorkspace(workspace, openclaw_state_dir=state)
        config = MemoryConfig(workspace_dir=workspace, store_path=root / "index.sqlite",
                              flags=FeatureFlags(vector_search=False))
        store = SQLiteMemoryStore(config, None)
        previous = None
        snapshots = []
        raw_snapshots = []
        for step in inputs["steps"]:
            write_files(step.get("write", {}))
            for source, destination in step.get("rename", {}).items():
                (workspace / destination).parent.mkdir(parents=True, exist_ok=True)
                (workspace / source).rename(workspace / destination)
            for relative in step.get("remove", []):
                (workspace / relative).unlink()
            for identifier, messages in step.get("createSessions", {}).items():
                append_session(identifier, messages, create=True)
            for identifier, messages in step.get("appendSessions", {}).items():
                append_session(identifier, messages)
            for identifier, renamed in step.get("renameSessions", {}).items():
                original = metadata[f"agent:main:{identifier}"]
                records = [json.loads(line) for line in (session_dir / f"{identifier}.jsonl").read_text().splitlines()]
                del metadata[f"agent:main:{identifier}"]
                (session_dir / f"{identifier}.jsonl").unlink()
                append_session(renamed, [row["message"] for row in records if row.get("type") == "message"], create=True)
                metadata[f"agent:main:{renamed}"]["updatedAt"] = original["updatedAt"]
                os.utime(session_dir / f"{renamed}.jsonl", ns=(original["updatedAt"] * 1_000_000,) * 2)
                (session_dir / "sessions.json").write_text(_canonical(metadata), encoding="utf-8")
            for identifier in step.get("deleteSessions", []):
                del metadata[f"agent:main:{identifier}"]
                (session_dir / f"{identifier}.jsonl").unlink()
                (session_dir / "sessions.json").write_text(_canonical(metadata), encoding="utf-8")
            if step.get("reopen"):
                store = SQLiteMemoryStore(config, None)
            if step.get("failChunkWrite"):
                with closing(store.connect()) as db:
                    db.execute("CREATE TRIGGER lifecycle_failure BEFORE INSERT ON chunks "
                               "BEGIN SELECT RAISE(ABORT,'injected lifecycle chunk failure'); END")
                    db.commit()
            error = None
            try:
                store.reindex(host)
            except Exception as exc:
                if "injected lifecycle chunk failure" not in str(exc):
                    raise
                error = {"kind": "injected-chunk-write-failure"}
            finally:
                if step.get("failChunkWrite"):
                    with closing(store.connect()) as db:
                        db.execute("DROP TRIGGER lifecycle_failure")
                        db.commit()
            raw = store.read_published_index()
            snapshots.append({"label": step["label"], "error": error,
                              "state": _normalize(raw, previous)})
            raw_snapshots.append({"label": step["label"], "raw": raw})
            previous = raw
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(_canonical(raw_snapshots), encoding="utf-8")
        return {"snapshots": snapshots, "provider": "none"}
