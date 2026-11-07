"""Filesystem fixtures for the read surface of storage.path-safety.

Only fixture construction and transport live here. Admission and excerpt results
come from the installed engine, paired with readMemoryFile in the real reference.
Configured extra roots and concurrent path replacement are not covered here.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


def build_storage_path_cases() -> list[dict[str, Any]]:
    files = [
        {"kind": "file", "path": "workspace/MEMORY.md", "text": "one\ntwo\n"},
        {"kind": "file", "path": "workspace/USER.md", "text": "user"},
        {"kind": "file", "path": "workspace/DREAMS.md", "text": "dream"},
        {"kind": "file", "path": "workspace/dreams.md", "text": "lower dream"},
        {"kind": "file", "path": "workspace/memory.md", "text": "legacy"},
        {"kind": "file", "path": "workspace/AGENTS.md", "text": "agent"},
        {"kind": "file", "path": "workspace/memory/note.md", "text": "note"},
        {"kind": "file", "path": "workspace/memory/not-markdown.txt", "text": "text"},
        {"kind": "file", "path": "workspace/memory/UPPER.MD", "text": "upper"},
        {"kind": "file", "path": "outside/secret.md", "text": "outside"},
    ]
    definitions: list[tuple[str, list[dict], list[str]]] = [
        ("root-and-relative", files, [
            "MEMORY.md", "./MEMORY.md", "USER.md", "DREAMS.md", "dreams.md", "memory.md",
            "AGENTS.md", "memory/note.md", "memory/UPPER.MD", "memory/not-markdown.txt",
            " memory/note.md\t", "\ufeffMEMORY.md\u00a0", "", " \t", ".", "memory/",
        ]),
        ("absolute-and-traversal", files, [
            "@workspace/MEMORY.md", "@workspace/memory/note.md", "@outside/secret.md",
            "../outside/secret.md", "memory/../../outside/secret.md", "memory/../MEMORY.md",
            "memory/../AGENTS.md", "memory/./note.md", "memory/sub/../note.md",
            "memory//note.md", "memory\\note.md", "MEMORY.md/../MEMORY.md",
        ]),
        ("encoded-and-missing", files, [
            "memory/%2e%2e/AGENTS.md", "memory/%2f../AGENTS.md", "memory/%6eote.md",
            "memory/missing.md", "memory/note.md/child.md", "memory/missing/child.md",
            "sessions/main/session.jsonl", "memory/.dreams/session-corpus/a.txt",
            "MEMORY.md\x00.md",
        ]),
        ("symlink-and-special-files", [*files,
            {"kind": "symlink", "path": "workspace/memory/file-link.md", "target": "note.md"},
            {"kind": "symlink", "path": "workspace/memory/outside-link.md", "target": "../../outside/secret.md"},
            {"kind": "symlink", "path": "workspace/memory/broken.md", "target": "gone.md"},
            {"kind": "symlink", "path": "workspace/memory/inside", "target": "."},
            {"kind": "symlink", "path": "workspace/memory/outside", "target": "../../outside"},
            {"kind": "symlink", "path": "workspace/memory/loop", "target": "loop"},
            {"kind": "symlink", "path": "workspace/memory/broken-parent", "target": "gone"},
            {"kind": "symlink", "path": "workspace/memory/file-parent", "target": "note.md"},
            {"kind": "directory", "path": "workspace/memory/directory.md"},
            {"kind": "fifo", "path": "workspace/memory/pipe.md"},
            {"kind": "hardlink", "path": "workspace/memory/hardlink.md", "target": "workspace/memory/note.md"},
        ], [
            "memory/file-link.md", "memory/outside-link.md", "memory/broken.md",
            "memory/inside/note.md", "memory/outside/secret.md", "memory/loop/note.md",
            "memory/outside/missing.md", "memory/outside/dir.md", "memory/broken-parent/note.md",
            "memory/file-parent/note.md", "memory/directory.md", "memory/pipe.md", "memory/hardlink.md",
        ]),
        ("missing-workspace", [], ["MEMORY.md", "memory/missing.md", "../outside/secret.md"]),
        ("workspace-is-file", [{"kind": "file", "path": "workspace", "text": "file"}], [
            "MEMORY.md", "memory/missing.md",
        ]),
    ]
    cases = []
    for name, entries, requests in definitions:
        cases.append({
            "id": f"storage-read-paths-{name}", "requirement": "storage.path-safety",
            "operation": "storage-read-paths", "input": {"entries": entries, "requests": requests},
            # The fixed acceptance also includes write admission. Keep it open:
            # these are real but explicitly read-only partial contract probes.
            "covers": [],
        })
    return cases


def _snapshot(base: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for directory, subdirs, filenames in os.walk(base, followlinks=False):
        for name in [*subdirs, *filenames]:
            target = Path(directory) / name
            info = target.lstat()
            key = target.relative_to(base).as_posix()
            if stat.S_ISLNK(info.st_mode):
                snapshot[key] = f"symlink:{os.readlink(target)}"
            elif stat.S_ISREG(info.st_mode):
                snapshot[key] = "file:" + hashlib.sha256(target.read_bytes()).hexdigest()
            elif stat.S_ISDIR(info.st_mode):
                snapshot[key] = "directory"
            elif stat.S_ISFIFO(info.st_mode):
                snapshot[key] = "fifo"
            else:
                snapshot[key] = f"special:{stat.S_IFMT(info.st_mode)}"
    return snapshot


def run_storage_paths(arguments: dict[str, Any]) -> dict[str, Any]:
    from memory_core.config import MemoryConfig
    from memory_core.tools.memory_get import _read_builtin

    with tempfile.TemporaryDirectory(prefix="memory-core-read-paths-") as temporary:
        base = Path(temporary)
        root = base / "workspace"
        for entry in arguments["entries"]:
            target = base / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            kind = entry["kind"]
            if kind == "file":
                target.write_text(entry["text"], encoding="utf-8")
            elif kind == "directory":
                target.mkdir(exist_ok=True)
            elif kind == "symlink":
                target.symlink_to(entry["target"])
            elif kind == "fifo":
                os.mkfifo(target)
            elif kind == "hardlink":
                target.hardlink_to(base / entry["target"])
            else:
                raise ValueError(f"Unsupported read fixture kind: {kind}")
        before = _snapshot(base)
        reads = []
        config = MemoryConfig(workspace_dir=root)
        for request in arguments["requests"]:
            raw_path = request.replace("@workspace", str(root)).replace("@outside", str(base / "outside"))
            try:
                value = _read_builtin(config, path=raw_path, from_line=None, lines=None)
                reads.append({"ok": True, "result": value})
            except Exception as error:
                reads.append({"ok": False, "error": {
                    "message": str(error).replace(str(base), "@fixture"),
                    "code": getattr(error, "code", None),
                }})
        return {"reads": reads, "filesUnchanged": before == _snapshot(base)}
