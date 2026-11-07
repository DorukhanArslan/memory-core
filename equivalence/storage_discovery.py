"""Paired default-root filesystem fixtures for the real discovery entry points.

The adapters arrange isolated filesystem inputs, inject named OS failures, and
serialize paths/error codes. They do not enumerate eligible files themselves.
Extra-path patterns and multimodal discovery remain uncovered by this subset.
"""
from __future__ import annotations

from contextlib import ExitStack
import errno
import os
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
from typing import Any


def build_storage_discovery_cases() -> list[dict[str, Any]]:
    cases = []
    scenarios: list[tuple[str, dict]] = [
        ("empty", {}),
        ("roots-and-case", {"files": {
            "MEMORY.md": "canonical", "USER.md": "profile", "memory.md": "legacy",
            "user.md": "case-sensitive profile", "DREAMS.md": "not a default root",
            "Memory.md": "wrong case", "memory/upper.MD": "wrong suffix",
            "memory/mixed.Md": "wrong suffix", "memory/note.md": "note",
            "memory/not-markdown.txt": "not indexed",
        }}),
        ("global-and-utf16-order", {"files": {
            "memory/a/nested.md": "nested", "memory/a.md": "sibling file",
            "memory/a-/note.md": "hyphen dir", "memory/a-.md": "hyphen file",
            "memory/\ue000.md": "private use", "memory/\U00010000.md": "supplementary",
            "memory/\U0001f600.md": "emoji", "memory/Z.md": "uppercase",
            "memory/z.md": "lowercase", "USER.md": "user", "MEMORY.md": "root",
        }}),
        ("hidden-and-repair", {"files": {
            "memory/.hidden.md": "hidden", "memory/.dreams/diary.md": "diary",
            "memory/.dreams/session-corpus/chat.txt": "not markdown",
            "memory/.openclaw-repair/copy.md": "repair",
            "memory/sub/.openclaw-repair/copy.md": "repair",
            "memory/.openclaw-repair.md": "file with repair-like name",
            "memory/.openclaw-repair-other/keep.md": "ordinary hidden directory",
            "memory/repair.md": "ordinary file",
        }}),
        ("symlink-files-and-directories", {"files": {
            "memory/real/note.md": "real", "outside.md": "outside default root",
        }, "symlinks": {
            "memory/alias.md": "memory/real/note.md",
            "memory/aliasdir": "memory/real",
            "memory/escape.md": "outside.md",
            "memory/broken.md": "missing.md",
        }}),
        ("symlink-root-memory", {"files": {"notes/root.md": "note"},
                                  "symlinks": {"MEMORY.md": "notes/root.md"}}),
        ("symlink-root-user", {"files": {"notes/user.md": "profile"},
                                "symlinks": {"USER.md": "notes/user.md"}}),
        ("symlink-memory-root", {"files": {"MEMORY.md": "root", "notes/note.md": "note"},
                                  "symlinks": {"memory": "notes"}}),
        ("nonregular-roots", {"dirs": ["MEMORY.md", "USER.md"],
                              "files": {"memory/note.md": "note"}}),
        ("nonregular-memory-root", {"files": {"MEMORY.md": "root", "memory": "file"}}),
        ("fifos", {"files": {"memory/note.md": "note"},
                    "fifos": ["MEMORY.md", "USER.md", "memory/pipe.md"]}),
        ("hard-links-are-distinct-paths", {"files": {"memory/a.md": "shared inode"},
                                          "hardlinks": {"memory/b.md": "memory/a.md"}}),
        ("disappearing-and-renamed-files", {"files": {
            "MEMORY.md": "root", "USER.md": "user", "memory/a.md": "a",
            "memory/nested/b.md": "b",
        }, "steps": [
            {"remove": ["USER.md", "memory/a.md"]},
            {"rename": {"memory/nested/b.md": "memory/renamed.md"}},
            {"remove": ["memory"]},
        ]}),
        ("disappearing-directory-during-scan", {"files": {
            "memory/disappears/note.md": "removed while scanning", "memory/keep.md": "keep",
        }, "removeOnScan": "memory/disappears"}),
        ("missing-workspace", {"workspaceKind": "missing"}),
        ("file-workspace", {"workspaceKind": "file"}),
        ("looped-workspace", {"workspaceKind": "symlink-loop"}),
        ("root-operational-error", {"files": {"MEMORY.md": "root"},
                                    "failure": {"operation": "scan", "path": ".", "code": "EACCES"}}),
        ("user-stat-operational-error", {"files": {"USER.md": "profile"},
                                         "failure": {"operation": "stat", "path": "USER.md", "code": "EIO"}}),
        ("nested-operational-error", {"files": {
            "memory/accessible.md": "keep", "memory/blocked/note.md": "blocked",
        }, "failure": {"operation": "scan", "path": "memory/blocked", "code": "EACCES"}}),
        ("memory-stat-operational-error", {"files": {"memory/note.md": "note"},
                                          "failure": {"operation": "stat", "path": "memory", "code": "EIO"}}),
    ]
    for name, value in scenarios:
        cases.append({
            "id": f"discovery-{name}", "requirement": "storage.discovery",
            "operation": "storage-discovery", "input": value,
            # Default-root behavior is proven by these cases, but the full
            # acceptance points also encompass unsupported extra-path sources.
            "covers": [],
        })
    return cases


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif os.path.lexists(path):
        path.unlink()


def _fixture(root: Path, arguments: dict) -> None:
    kind = arguments.get("workspaceKind", "directory")
    if kind == "missing":
        return
    if kind == "file":
        root.write_text("not a directory", encoding="utf-8")
        return
    if kind == "symlink-loop":
        root.symlink_to(root)
        return
    root.mkdir()
    for name in arguments.get("dirs", []):
        (root / name).mkdir(parents=True, exist_ok=True)
    for name, text in arguments.get("files", {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for name in arguments.get("fifos", []):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
    for field, operation in (("symlinks", os.symlink), ("hardlinks", os.link)):
        for name, target in arguments.get(field, {}).items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            operation(root / target, path)


def run_storage_discovery(arguments: dict[str, Any]) -> dict:
    from memory_core.workspace import MemorySourceScanError, list_memory_files

    with tempfile.TemporaryDirectory(prefix="memory-core-discovery-") as directory:
        root = Path(directory) / "workspace"
        _fixture(root, arguments)
        failure = arguments.get("failure")
        remove_on_scan = arguments.get("removeOnScan")
        original_scan, original_stat = os.scandir, os.lstat

        def injected(operation: str, path: str | os.PathLike) -> None:
            if isinstance(path, int):
                return
            absolute = Path(path)
            if operation == "scan" and remove_on_scan and absolute == root / remove_on_scan:
                _remove(absolute)
            if (failure and operation == failure["operation"]
                    and absolute == root / failure["path"]):
                raise OSError(getattr(errno, failure["code"]), "injected filesystem failure", str(absolute))

        def scan(path):
            injected("scan", path)
            return original_scan(path)

        def file_stat(path, *args, **kwargs):
            injected("stat", path)
            return original_stat(path, *args, **kwargs)

        def snapshot() -> dict:
            try:
                return {"files": [path.relative_to(root).as_posix()
                                  for path in list_memory_files(root)]}
            except MemorySourceScanError as exc:
                return {"error": {"type": type(exc).__name__, "code": exc.code,
                                  "path": exc.path.relative_to(root).as_posix()}}

        with ExitStack() as stack:
            stack.enter_context(patch("os.scandir", scan))
            stack.enter_context(patch("os.lstat", file_stat))
            snapshots = [snapshot()]
            for step in arguments.get("steps", []):
                for name in step.get("remove", []):
                    _remove(root / name)
                for previous, current in step.get("rename", {}).items():
                    (root / current).parent.mkdir(parents=True, exist_ok=True)
                    (root / previous).rename(root / current)
                snapshots.append(snapshot())
        return {"snapshots": snapshots}
