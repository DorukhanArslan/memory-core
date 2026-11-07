"""Paired filesystem source snapshots used by incremental indexing.

These fixtures compare the production immutable source reader with the pinned
native buildFileEntry operation. They do not claim to execute native sync plans,
query admission, the embedding provider, or index transaction publication.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


_MTIME_MS = 1_700_000_000_000


def _file(path: str, data: bytes) -> dict:
    return {"kind": "file", "path": path,
            "dataBase64": base64.b64encode(data).decode("ascii")}


def build_incremental_index_cases() -> list[dict[str, Any]]:
    """Return source-entry cases; full incremental lifecycle remains uncovered."""
    scenarios: list[tuple[str, dict]] = []
    for name, data in (
        ("empty", b""),
        ("ascii", b"A durable preference.\n"),
        ("crlf", b"one\r\ntwo\r\n"),
        ("bare-cr", b"one\rtwo\r"),
        ("utf8-multilingual", "café İstanbul 我喜欢咖啡 😀\n".encode()),
        ("utf8-bom", b"\xef\xbb\xbfsource retains BOM\n"),
        ("utf8-combining", "cafe\u0301\n".encode()),
        ("invalid-single-bytes", b"caf\xe9\xff\x80\n"),
        ("invalid-truncated-sequence", b"prefix\xf0\x9f\x98"),
        ("invalid-surrogate-encoding", b"\xed\xa0\x80"),
        ("all-byte-values", bytes(range(256))),
        ("nul-and-controls", b"alpha\x00beta\t\r\n\x1a"),
    ):
        scenarios.append((name, {"entries": [_file("memory/note.md", data)],
                                 "requests": ["memory/note.md"]}))
    scenarios.extend([
        ("root-profile-and-memory", {
            "entries": [_file("MEMORY.md", b"# Long-term\n"),
                        _file("USER.md", b"Prefer short replies.\n")],
            "requests": ["MEMORY.md", "USER.md"],
        }),
        ("content-changes-with-fixed-size-and-time", {
            "entries": [_file("memory/note.md", b"first\n")],
            "requests": ["memory/note.md"],
            "steps": [{"write": [_file("memory/note.md", b"other\n")]},
                      {"write": [_file("memory/note.md", b"other\n")]}],
        }),
        ("newline-changes-with-fixed-size-and-time", {
            "entries": [_file("memory/note.md", b"one\r\ntwo")],
            "requests": ["memory/note.md"],
            "steps": [{"write": [_file("memory/note.md", b"one\n\ntwo")]}],
        }),
        ("invalid-bytes-same-decoded-content", {
            "entries": [_file("memory/note.md", b"A\xffB")],
            "requests": ["memory/note.md"],
            "steps": [{"write": [_file("memory/note.md", b"A\xfeB")]}],
        }),
        ("rename-and-delete", {
            "entries": [_file("memory/old.md", b"same source\n")],
            "requests": ["memory/old.md", "memory/new.md"],
            "steps": [{"rename": {"memory/old.md": "memory/new.md"}},
                      {"remove": ["memory/new.md"]}],
        }),
        ("regular-to-directory-to-missing", {
            "entries": [_file("memory/note.md", b"was regular")],
            "requests": ["memory/note.md"],
            "steps": [{"remove": ["memory/note.md"],
                       "mkdir": ["memory/note.md"]},
                      {"remove": ["memory/note.md"]}],
        }),
        ("symlink-and-hardlink-leaves", {
            "entries": [_file("memory/note.md", b"same inode source\n"),
                        {"kind": "symlink", "path": "memory/link.md", "target": "note.md"},
                        {"kind": "symlink", "path": "memory/broken.md", "target": "missing.md"},
                        {"kind": "hardlink", "path": "memory/hard.md", "target": "memory/note.md"}],
            "requests": ["memory/note.md", "memory/link.md", "memory/broken.md", "memory/hard.md"],
        }),
        ("fifo-and-directory-leaves", {
            "entries": [{"kind": "fifo", "path": "memory/pipe.md"},
                        {"kind": "directory", "path": "memory/folder.md"}],
            "requests": ["memory/pipe.md", "memory/folder.md", "memory/missing.md"],
        }),
    ])
    return [{
        "id": f"source-snapshot-{name}", "requirement": "indexing.incremental-sync",
        "operation": "incremental-index", "input": {"mtimeMs": _MTIME_MS, **arguments},
        # Source fingerprinting is one input to sync decisions. It does not
        # establish unchanged-file handling, chunk publication or session sync.
        "covers": [],
    } for name, arguments in scenarios]


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif os.path.lexists(path):
        path.unlink()


def _arrange(root: Path, entries: list[dict], mtime_ms: int) -> None:
    for entry in entries:
        destination = root / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        kind = entry["kind"]
        if kind == "file":
            destination.write_bytes(base64.b64decode(entry["dataBase64"], validate=True))
            os.utime(destination, ns=(mtime_ms * 1_000_000, mtime_ms * 1_000_000))
        elif kind == "directory":
            destination.mkdir()
        elif kind == "symlink":
            destination.symlink_to(entry["target"])
        elif kind == "hardlink":
            os.link(root / entry["target"], destination)
        elif kind == "fifo":
            os.mkfifo(destination)
        else:
            raise ValueError(f"Unsupported source fixture entry: {kind}")


def run_incremental_index(arguments: dict[str, Any]) -> dict:
    """Translate the production source reader's immutable snapshot into JSON."""
    from memory_core.index.sqlite_store import read_index_source
    from memory_core.workspace import MemoryFile

    # Fixture execution must not add bookkeeping fields to registered inputs.
    inputs = deepcopy(arguments)
    with tempfile.TemporaryDirectory(prefix="memory-core-source-snapshot-") as directory:
        root = Path(directory)
        _arrange(root, inputs["entries"], inputs["mtimeMs"])

        def snapshot() -> dict:
            entries = []
            for relative in inputs["requests"]:
                source = read_index_source(MemoryFile(relative, root / relative))
                entry = None if source is None else {
                    "path": source.path, "hash": source.hash, "size": source.size,
                    "mtimeMs": source.mtime, "kind": source.kind,
                }
                entries.append({"request": relative, "entry": entry})
            return {"entries": entries}

        snapshots = [snapshot()]
        for step in inputs.get("steps", []):
            for relative in step.get("remove", []):
                _remove(root / relative)
            for previous, current in step.get("rename", {}).items():
                (root / current).parent.mkdir(parents=True, exist_ok=True)
                (root / previous).rename(root / current)
            for relative in step.get("mkdir", []):
                (root / relative).mkdir(parents=True)
            _arrange(root, step.get("write", []), inputs["mtimeMs"])
            snapshots.append(snapshot())
        return {"snapshots": snapshots}
