"""Paired default-root filesystem fixtures for the real discovery entry points.

The adapters arrange isolated filesystem inputs, inject named OS failures, and
serialize paths/error codes. They do not enumerate eligible files themselves.
Extra-root options control filesystem discovery only; embeddings are not exercised.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import errno
import os
from pathlib import Path
import shutil
import tempfile
import traceback
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
    extra_files = {"MEMORY.md": "root", "USER.md": "user", "memory/base.md": "default",
                   "notes/a.md": "a", "notes/b.md": "b", "notes/sub/c.md": "c",
                   "notes/sub/.hidden.md": "hidden", "notes/.top.md": "hidden",
                   "notes/a.txt": "text", "notes/.openclaw-repair/repair.md": "repair"}
    scenarios.extend([
        ("extra-relative-directory", {"files": extra_files, "extraPaths": ["notes"]}),
        ("extra-absolute-outside-workspace", {"files": {**extra_files, "../outside/note.md": "outside"},
                                              "extraPaths": ["$FIXTURE/outside"]}),
        ("extra-explicit-file-ignores-pattern", {"files": extra_files,
            "extraPaths": [{"path": "notes/a.md", "pattern": "never-matches/**"}]}),
        ("extra-order-and-duplicate-roots", {"files": extra_files,
            "extraPaths": ["notes/b.md", " notes/a.md ", "notes", "notes", "./notes", "", {"path": "notes", "pattern": None}]}),
        ("extra-default-deduplication", {"files": extra_files, "extraPaths": [".", "memory", "MEMORY.md"]}),
        ("extra-root-legacy-and-repair-exclusions", {"files": {
            "MEMORY.md": "canonical", "memory.md": "legacy", ".openclaw-repair/root-memory/copy.md": "repair",
            ".openclaw-repair/unrelated.md": "unrelated", "notes/memory.md": "ordinary nested name",
        }, "extraPaths": ["memory.md", ".openclaw-repair/root-memory", ".openclaw-repair", "notes"]}),
        ("extra-home-roots", {"files": {**extra_files, "../home/notes/home.md": "home"}, "homeRoot": True,
                              "extraPaths": ["~/notes", "~\\notes", "~"]}),
        ("extra-missing-and-nonregular-roots", {"files": extra_files, "fifos": ["pipe.md"],
                                               "extraPaths": ["missing", "pipe.md", "notes/a.txt"]}),
        ("extra-symlink-roots-and-descendants", {"files": extra_files,
            "symlinks": {"alias": "notes", "alias.md": "notes/a.md", "notes/link.md": "notes/a.md"},
            "extraPaths": ["alias", "alias.md", "notes"], "captureSkippedSymlinkRoots": True}),
        ("extra-union-and-normalized-patterns", {"files": extra_files, "extraPaths": [
            {"path": " notes ", "pattern": " a.md "}, {"path": "notes", "pattern": "sub\\**\\*.md"},
            {"path": "./notes", "pattern": "b.md"}, {"path": "notes", "pattern": "a.md"}]}),
        ("extra-pattern-pruning-failure", {"files": extra_files,
            "extraPaths": [{"path": "notes", "pattern": "a.md"}],
            "failure": {"operation": "scan", "path": "notes/sub", "code": "EACCES"}}),
        ("extra-operational-failure", {"files": extra_files, "extraPaths": ["notes"],
            "failure": {"operation": "scan", "path": "notes/sub", "code": "EACCES"}}),
        ("extra-outside-operational-failure", {"files": {"../outside/note.md": "outside"},
            "extraPaths": ["../outside"], "failure": {"operation": "scan", "path": "../outside", "code": "EACCES"}}),
        ("extra-disappearing-directory", {"files": extra_files, "extraPaths": ["notes"], "removeOnScan": "notes/sub"}),
        ("extra-real-intermediate-symlink-loop", {"symlinks": {"loop": "loop"}, "extraPaths": ["loop/notes"]}),
        ("extra-real-overlong-component", {"extraPaths": ["x" * 260]}),
    ])
    for name, pattern in (("leaf", "*.md"), ("recursive", "**/*.md"), ("braces", "{a,b}.md"),
                          ("extglob", "@(a|b).md"), ("negative-extglob", "!(b).md"),
                          ("character-class", "[ab].md"), ("negated-class", "[!b].md"),
                          ("explicit-hidden", "**/.*.md"), ("directory-star", "sub/**"),
                          ("directory-recursion", "sub/**/*.md"), ("invalid-bracket", "[a.md"),
                          ("leading-negation-literal", "!*.md")):
        scenarios.append((f"extra-pattern-{name}", {"files": extra_files,
                          "extraPaths": [{"path": "notes", "pattern": pattern}]}))
    edge_files = {**extra_files, "notes/😀.md": "supplementary", "notes/𐀀.md": "supplementary letter",
                  "notes/é.md": "letter", "notes/α.md": "letter", "notes/𞛀.md": "Unicode 17 letter",
                  "notes/1.md": "digit", "notes/!.md": "punctuation", "notes/ .md": "blank",
                  "notes/\x01.md": "control", "notes/a1.md": "range one", "notes/a999.md": "range last"}
    for name, pattern in (("utf16-one-unit", "?.md"), ("utf16-two-units", "??.md"),
                          ("utf16-bracket", "[😀].md"), ("literal-parent", "sub/../*.md"),
                          ("globstar-parent", "sub/**/../deep/*.md"), ("leading-dot-segment", "./*.md"),
                          ("trailing-slash", "a.md/"), ("large-brace-range", "a{1..1100}.md")):
        scenarios.append((f"extra-pattern-{name}", {"files": edge_files,
                          "extraPaths": [{"path": "notes", "pattern": pattern}]}))
    for name in ("alnum", "alpha", "ascii", "blank", "cntrl", "digit", "graph", "lower", "print",
                 "punct", "space", "upper", "word", "xdigit"):
        scenarios.append((f"extra-pattern-posix-{name}", {"files": edge_files,
                          "extraPaths": [{"path": "notes", "pattern": f"[[:{name}:]].md"}]}))
    media_files = {"MEMORY.md": "root", "memory/default.png": "default remains markdown only",
                   "media/note.md": "markdown", "media/image.PNG": "image", "media/sound.MP3": "audio",
                   "media/sub/clip.flac": "audio", "media/video.mp4": "unsupported", "media/.image.jpg": "hidden"}
    for name, settings in (("disabled", {"enabled": False, "modalities": ["image", "audio"], "maxFileBytes": 1}),
                           ("image", {"enabled": True, "modalities": ["image"], "maxFileBytes": 1}),
                           ("audio", {"enabled": True, "modalities": ["audio"], "maxFileBytes": 1}),
                           ("all", {"enabled": True, "modalities": ["image", "audio"], "maxFileBytes": 1}),
                           ("empty", {"enabled": True, "modalities": [], "maxFileBytes": 1})):
        scenarios.append((f"extra-multimodal-{name}", {"files": media_files, "extraPaths": ["media"],
                                                    "multimodal": settings}))
    for name, value in scenarios:
        if "failure" in value:
            value["failure"]["message"] = "injected filesystem failure"
        cases.append({
            "id": f"discovery-{name}", "requirement": "storage.discovery",
            "operation": "storage-discovery", "input": deepcopy(value),
            # Coverage stays unclaimed until actual native comparison succeeds.
            "covers": [],
            "normalizationPolicy": (
                "Complete scan-error type/message/code/path/cause envelopes are compared. Only the exact "
                "owned fixture-base prefix maps to $FIXTURE; physical error paths are retained raw. "
                "Native and SDK fixtures raise the same literal injected Error name/message/code/path "
                "facts. Complete actual exception properties, stacks and OS details remain separate raw "
                "diagnostics. Adapters preserve actual production error messages. Standard OS errors "
                "cross the production Node-compatible IO bridge; original Python exceptions remain raw."
            ),
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


def _scan_error_envelope(error: BaseException) -> dict:
    code = getattr(error, "code", None)
    if code is None and isinstance(error, OSError):
        code = errno.errorcode.get(error.errno)
    path = getattr(error, "path", getattr(error, "filename", None))
    cause = getattr(error, "cause", error.__cause__)
    return {"type": getattr(error, "name", type(error).__name__), "message": str(error),
            "code": code, "path": str(path) if path is not None else None,
            "cause": _scan_error_envelope(cause) if cause is not None else None}


def _raw_scan_error(error: BaseException) -> dict:
    def value(item):
        if isinstance(item, BaseException):
            return _raw_scan_error(item)
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, (tuple, list)):
            return [value(entry) for entry in item]
        if isinstance(item, dict):
            return {key: value(entry) for key, entry in item.items()}
        return repr(item)

    properties = {key: value(item) for key, item in vars(error).items()}
    for field in ("errno", "strerror", "filename", "filename2", "winerror"):
        if hasattr(error, field):
            properties[field] = value(getattr(error, field))
    return {"type": type(error).__name__, "module": type(error).__module__,
            "qualifiedType": type(error).__qualname__, "name": getattr(error, "name", type(error).__name__),
            "message": str(error),
            "args": value(error.args), "properties": properties,
            "stack": "".join(traceback.format_exception(error)),
            "cause": _raw_scan_error(error.__cause__) if error.__cause__ is not None else None,
            "context": _raw_scan_error(error.__context__) if error.__context__ is not None
                       and error.__context__ is not error.__cause__ else None,
            "suppressContext": error.__suppress_context__}


def run_storage_discovery(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict:
    from equivalence.get_contract import map_get_fixture_paths
    from memory_core.workspace import MemorySourceScanError, list_memory_files

    with tempfile.TemporaryDirectory(prefix="memory-core-discovery-") as directory:
        root = Path(directory) / "workspace"
        _fixture(root, arguments)
        failure = arguments.get("failure")
        remove_on_scan = arguments.get("removeOnScan")
        original_scan, original_stat = os.scandir, os.lstat
        raw = {"kind": "storage-discovery", "fixtureBase": directory, "workspaceRoot": str(root),
               "input": deepcopy(arguments), "snapshots": []}

        class FixtureFilesystemError(OSError):
            """The same literal Error facts supplied at the native IO boundary."""

            name = "Error"

            def __init__(self, message, code, path):
                super().__init__(message)
                self.code, self.path = code, str(path)

        def injected(operation: str, path: str | os.PathLike) -> None:
            if isinstance(path, int):
                return
            absolute = Path(os.path.abspath(path))
            if operation == "scan" and remove_on_scan and absolute == Path(os.path.abspath(root / remove_on_scan)):
                _remove(absolute)
            if (failure and operation == failure["operation"]
                    and absolute == Path(os.path.abspath(root / failure["path"]))):
                raise FixtureFilesystemError(failure["message"], failure["code"], absolute)

        def scan(path):
            injected("scan", path)
            return original_scan(path)

        def file_stat(path, *args, **kwargs):
            injected("stat", path)
            return original_stat(path, *args, **kwargs)

        def snapshot() -> dict:
            try:
                skipped = []
                extra_paths = []
                for entry in arguments.get("extraPaths", []):
                    if isinstance(entry, str):
                        extra_paths.append(entry.replace("$FIXTURE", directory))
                    else:
                        extra_paths.append({**entry, "path": entry["path"].replace("$FIXTURE", directory)})
                callback = skipped.append if arguments.get("captureSkippedSymlinkRoots") else None
                files = list_memory_files(root, extra_paths, arguments.get("multimodal"), callback)
                result = {"files": [os.path.relpath(path, root).replace(os.sep, "/") for path in files],
                        **({"skippedSymlinkRoots": [os.path.relpath(path, root).replace(os.sep, "/") for path in skipped]}
                           if callback else {})}
                raw["snapshots"].append({"result": deepcopy(result)})
                return result
            except MemorySourceScanError as exc:
                result = {"error": _scan_error_envelope(exc)}
                raw["snapshots"].append({"result": deepcopy(result), "exception": _raw_scan_error(exc)})
                return result

        with ExitStack() as stack:
            if arguments.get("homeRoot"):
                stack.enter_context(patch.object(Path, "home", return_value=Path(directory) / "home"))
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
        result = {"snapshots": snapshots}
        raw["result"] = deepcopy(result)
        if evidence_directory is not None:
            import json

            evidence_directory = Path(evidence_directory)
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(json.dumps([raw], indent=2) + "\n")

        return map_get_fixture_paths(result, directory)
