from __future__ import annotations

import errno
import os
import re
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from memory_core.bootstrap._js import js_trim
from memory_core.memory_paths import (
    SESSION_CORPUS_FILE_RE,
    MemoryPathNotAllowedError,
    MemoryReadPathError,
    UnsafeMemoryPathError,
    validate_daily_memory_path,
)
from memory_core.session_corpus import MemoryCoreSessionCorpus

if TYPE_CHECKING:
    from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver

# Root memory file name (OpenClaw src/memory/root-memory-files.ts
# CANONICAL_ROOT_MEMORY_FILENAME). The legacy lowercase `memory.md` is a
# doctor/repair concern upstream and is never indexed.
CANONICAL_ROOT_MEMORY_FILENAME = "MEMORY.md"
# Directory name memory discovery never descends into: OpenClaw's doctor
# writes repair copies there (packages/memory-host-sdk/src/host/internal.ts
# shouldDescendMemoryEntry). Kept under its upstream name so a workspace shared
# with OpenClaw never indexes repair artifacts.
OPENCLAW_REPAIR_DIRNAME = ".openclaw-repair"

# memory_get refusal messages, verbatim: readMemoryFile
# (packages/memory-host-sdk/src/host/read-file.ts:78,114,117) and fs-safe
# statRegularFile (symlinked or non-regular target).
MEMORY_PATH_REQUIRED_ERROR = "path required"
# read-file.ts memoryPathNotAllowed(): the gate refusal, with its error code.
MEMORY_PATH_NOT_ALLOWED_ERROR = "path is not an allowed Markdown memory file"
MEMORY_PATH_NOT_REGULAR_FILE_ERROR = "path must be a regular file"
_LEADING_DOTS_AND_SLASHES_RE = re.compile(r"^[./]+")


def is_memory_path(rel_path: str) -> bool:
    """Port of OpenClaw ``isMemoryPath`` + ``normalizeRelPath`` (host/internal.ts:96-170)."""
    normalized = _LEADING_DOTS_AND_SLASHES_RE.sub("", js_trim(rel_path)).replace("\\", "/")
    if not normalized:
        return False
    if (
        normalized in (CANONICAL_ROOT_MEMORY_FILENAME, "USER.md")
        or normalized.lower() == "dreams.md"
    ):
        return True
    return normalized.startswith("memory/")


def list_memory_files(workspace_dir: Path) -> list[Path]:
    """Default-root portion of OpenClaw ``listMemoryFiles`` (v2026.9.9).

    Returns paths in upstream order: the root ``MEMORY.md`` when it is a real
    file (exact name, not a symlink), root ``USER.md``, then every ``*.md`` under
    ``memory/`` sorted by JavaScript UTF-16 code units. Symlinked files and directories are
    skipped, a symlinked ``memory/`` is ignored, and ``.openclaw-repair``
    directories are not descended; hidden files and dot-directories such as
    ``memory/.dreams`` are walked like any other entry. Results are deduplicated
    by realpath. Missing entries are ignored; operational scan errors are
    reported instead of publishing an apparently successful partial scan.

    Not ported: ``extraPaths`` and multimodal files (memory-core has no config for
    them), and the ``shouldSkipRootMemoryAuxiliaryPath`` guard, which can only
    match for extra paths outside ``memory/``.
    """
    root = Path(workspace_dir)
    result: list[Path] = []
    memory_file = _resolve_canonical_root_memory_file(root)
    if memory_file is not None and _is_regular_markdown_file(memory_file):
        result.append(memory_file)
    user_file = root / "USER.md"
    if _is_regular_markdown_file(user_file):
        result.append(user_file)
    memory_dir = root / "memory"
    try:
        memory_dir_stat = os.lstat(memory_dir)
    except (FileNotFoundError, NotADirectoryError):
        memory_dir_stat = None
    except OSError as exc:
        raise MemorySourceScanError(memory_dir, exc) from exc
    if (
        memory_dir_stat is not None
        and not stat.S_ISLNK(memory_dir_stat.st_mode)
        and stat.S_ISDIR(memory_dir_stat.st_mode)
    ):
        _collect_memory_files_from_dir(memory_dir, result)
    if len(result) <= 1:
        return result
    seen: set[str] = set()
    deduped: list[Path] = []
    for entry in result:
        try:
            key = os.path.realpath(entry, strict=True)
        except OSError:
            key = str(entry)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


class MemorySourceScanError(RuntimeError):
    """An operational failure while enumerating a memory source.

    The path and errno code mirror the native scan diagnostic. A missing source
    is intentionally not a scan failure and is handled by discovery itself.
    """

    def __init__(self, path: Path, cause: OSError):
        self.path = path
        self.code = errno.errorcode.get(cause.errno)
        code = f" ({self.code})" if self.code else ""
        super().__init__(f"memory source scan failed at {path}{code}: {cause}")


def _resolve_canonical_root_memory_file(root: Path) -> Path | None:
    # src/memory/root-memory-files.ts resolveCanonicalRootMemoryFile: an exact
    # directory entry (no case folding) that is a file and not a symlink.
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.name == CANONICAL_ROOT_MEMORY_FILENAME and entry.is_file(
                    follow_symlinks=False
                ):
                    return root / entry.name
    except (FileNotFoundError, NotADirectoryError):
        pass
    except OSError as exc:
        raise MemorySourceScanError(root, exc) from exc
    return None


def _is_regular_markdown_file(path: Path) -> bool:
    # listMemoryFiles addMarkdownFile: statRegularFile (lstat; symlinks and
    # non-regular files are rejected) plus the `.md` suffix check.
    try:
        file_stat = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:
        raise MemorySourceScanError(path, exc) from exc
    return stat.S_ISREG(file_stat.st_mode) and path.name.endswith(".md")


def _collect_memory_files_from_dir(directory: Path, files: list[Path]) -> None:
    # collectMemoryFilesFromDir over @openclaw/fs-safe walkDirectory with
    # `symlinks: "skip"`: each directory is visited once by realpath, entries
    # are pushed before descending. listMemoryFiles then sorts the complete
    # collected list using JavaScript's default UTF-16 string comparison.
    visited: set[str] = set()
    collected: list[Path] = []

    def visit(current: Path) -> None:
        try:
            if current != directory and stat.S_ISLNK(os.lstat(current).st_mode):
                return
            real_dir = os.path.realpath(current, strict=True)
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as exc:
            raise MemorySourceScanError(current, exc) from exc
        if real_dir in visited:
            return
        visited.add(real_dir)
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as exc:
            raise MemorySourceScanError(current, exc) from exc
        for entry in entries:
            if entry.is_symlink():
                continue
            full_path = current / entry.name
            if entry.is_file(follow_symlinks=False):
                if entry.name.endswith(".md"):
                    collected.append(full_path)
            elif entry.is_dir(follow_symlinks=False) and entry.name != OPENCLAW_REPAIR_DIRNAME:
                visit(full_path)

    visit(directory)
    files.extend(sorted(collected, key=lambda item: str(item).encode("utf-16-be", "surrogatepass")))



# One lock per (workspace root, file) for this process: curated writes and the memory flush's
# daily append read, check and write under it, so parallel tool calls never interleave.
_FILE_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def workspace_file_lock(root: Path, rel_path: str) -> threading.Lock:
    """The process-wide write lock of ``rel_path`` under the (resolved) workspace ``root``."""
    with _FILE_LOCKS_GUARD:
        return _FILE_LOCKS.setdefault((str(root), rel_path), threading.Lock())


def check_writable_memory_file(root: Path, rel_path: str) -> None:
    """Refuse a memory write target that a plain append could redirect or share.

    Raises ``UnsafeMemoryPathError`` when a parent directory of ``rel_path`` under ``root`` is a
    symlink or not a directory, or when the target exists as a symlink, a non-regular file or a
    file with more than one hard link. Writes never follow or repair such entries.
    """
    current = root
    for part in rel_path.split("/")[:-1]:
        current = current / part
        if current.is_symlink():
            raise UnsafeMemoryPathError(f"{part}/ is a symlink; memory writes never follow symlinks")
        if os.path.lexists(current) and not current.is_dir():
            raise UnsafeMemoryPathError(f"{part} is not a directory")
    target = root / rel_path
    if not os.path.lexists(target):
        return
    info = os.lstat(target)
    if stat.S_ISLNK(info.st_mode):
        raise UnsafeMemoryPathError(f"{rel_path} is a symlink; memory writes never follow symlinks")
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeMemoryPathError(f"{rel_path} is not a regular file")
    if info.st_nlink > 1:
        raise UnsafeMemoryPathError(f"{rel_path} has more than one hard link")


def append_daily_memory_file(
    root: str | os.PathLike[str],
    rel_path: str,
    entry: str,
    *,
    provenance: MemoryWriteProvenanceObserver | None = None,
) -> Path:
    """:meth:`MemoryWorkspace.append_daily_memory` under the file's write lock.

    The shared daily append of the curated daily note and the memory flush's ``write`` tool:
    ``rel_path`` must be ``memory/YYYY-MM-DD.md`` and pass :func:`check_writable_memory_file`.
    ``provenance`` is the write observer of the flush (:mod:`memory_core.memory_write_provenance`).
    """
    resolved = Path(root).resolve()
    validate_daily_memory_path(rel_path)
    with workspace_file_lock(resolved, rel_path):
        check_writable_memory_file(resolved, rel_path)
        return MemoryWorkspace(resolved).append_daily_memory(rel_path, entry, provenance=provenance)


@dataclass(frozen=True)
class MemoryFile:
    rel_path: str
    abs_path: Path
    source: str = "memory"
    index_text: str | None = None


@dataclass(frozen=True)
class MemoryReadResult:
    path: str
    text: str
    start_line: int
    end_line: int


class MemoryWorkspace:
    def __init__(
        self,
        root: Path,
        *,
        openclaw_state_dir: Path | None = None,
        agent_id: str = "main",
        is_session_forgotten: Callable[[str], bool] | None = None,
    ):
        # ``is_session_forgotten(session_id)``: forgotten sessions leave the index and stay out
        # (the origins ledger's tombstones, ``MemoryEntryOriginLedger.list_session_tombstones``).
        self.is_session_forgotten = is_session_forgotten
        self.root = root.resolve()
        self.openclaw_state_dir = openclaw_state_dir.resolve() if openclaw_state_dir else None
        self.agent_id = agent_id

    def discover_memory_files(self) -> list[MemoryFile]:
        # Same file list as OpenClaw's memory index (listMemoryFiles); the
        # relative path mirrors buildFileEntry (path.relative + "/" separators).
        return [
            MemoryFile(path.relative_to(self.root).as_posix(), path)
            for path in list_memory_files(self.root)
        ]

    def discover_session_transcript_files(self) -> list[MemoryFile]:
        files: list[MemoryFile] = []
        session_dir = self.root / "memory" / ".dreams" / "session-corpus"
        if session_dir.is_dir():
            for path in sorted(session_dir.iterdir()):
                resolved_path = path.resolve()
                if SESSION_CORPUS_FILE_RE.fullmatch(path.name) and self.is_path_inside_root(
                    resolved_path
                ):
                    files.append(
                        MemoryFile(
                            path.relative_to(self.root).as_posix(),
                            resolved_path,
                            source="sessions",
                        )
                    )
        if self.openclaw_state_dir is not None:
            corpus = MemoryCoreSessionCorpus(
                self.openclaw_state_dir, agent_id=self.agent_id, is_forgotten=self.is_session_forgotten
            )
            files.extend(
                MemoryFile(
                    item.rel_path,
                    item.abs_path,
                    item.source,
                    index_text=corpus.read_index_text(item),
                )
                for item in corpus.discover_files()
            )
        return files

    def discover_indexable_files(self) -> list[MemoryFile]:
        # memory-core extension: files under memory/.dreams/session-corpus/ are
        # indexed once, as source "sessions" (the lab writes its chat corpus
        # there as YYYY-MM-DD.md). Upstream has no sessions scan of that
        # directory; its recursive memory walk would index such a `.md` as a
        # memory file, and upstream's own corpus files are `.txt`, which the
        # memory walk never picks up.
        session_files = self.discover_session_transcript_files()
        session_paths = {file.rel_path for file in session_files}
        memory_files = [
            file for file in self.discover_memory_files() if file.rel_path not in session_paths
        ]
        return [*memory_files, *session_files]

    def normalize_memory_path(self, rel_path: str) -> str:
        return rel_path.replace("\\", "/").lstrip("/")

    def is_allowed_memory_path(self, rel_path: str) -> bool:
        normalized = self.normalize_memory_path(rel_path)
        if normalized in {"MEMORY.md", "memory.md", "DREAMS.md"}:
            return True
        if not normalized.startswith("memory/"):
            return False
        return normalized.endswith(".md")

    def is_path_inside_root(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents

    def resolve_memory_path(self, rel_path: str) -> Path:
        normalized = self.normalize_memory_path(rel_path)
        if not self.is_allowed_memory_path(normalized):
            raise UnsafeMemoryPathError(f"path is not an allowed memory file: {rel_path}")
        candidate = (self.root / normalized).resolve()
        if not self.is_path_inside_root(candidate):
            raise UnsafeMemoryPathError(f"memory path escapes workspace: {rel_path}")
        return candidate

    def resolve_memory_read_path(self, raw_path: str) -> tuple[str, Path | None]:
        """Port of OpenClaw ``readMemoryFile``'s workspace gate (host/read-file.ts:67-134).

        Returns ``(rel_path, abs_path)``, with ``abs_path`` None when the file
        (or the workspace) does not exist. Raises ``UnsafeMemoryPathError`` with
        upstream's message: ``path required`` for a blank path, a path outside
        the workspace, a non-memory path (anything but ``MEMORY.md``,
        ``dreams.md`` in any case, or ``memory/...``) or a non-``.md`` file,
        such as session-corpus ``.txt`` files and ``sessions/<agent>/*.jsonl``
        state-dir transcripts. Non-regular leaves raise ``path must be a regular
        file``; final symlinks and parent symlinks escaping the root retain the
        reference filesystem policy code. Parent symlinks within the root are
        admitted. Paths are resolved lexically first, so ``memory/../AGENTS.md``
        is refused. Not ported: ``extraPaths`` or the reference's descriptor and
        concurrent path-identity checks.
        """
        path = js_trim(raw_path)
        if not path:
            raise UnsafeMemoryPathError(MEMORY_PATH_REQUIRED_ERROR)
        abs_path = Path(
            os.path.normpath(path if os.path.isabs(path) else os.path.join(self.root, path))
        )
        rel_path = os.path.relpath(abs_path, self.root).replace("\\", "/")
        if rel_path == ".":
            rel_path = ""
        in_workspace = bool(rel_path) and not rel_path.startswith("..") and not os.path.isabs(
            rel_path
        )
        if not in_workspace or not is_memory_path(rel_path) or not str(abs_path).endswith(".md"):
            raise MemoryPathNotAllowedError(MEMORY_PATH_NOT_ALLOWED_ERROR)
        if not self.root.exists():
            # fs-safe root(): "root dir not found" counts as a missing file.
            return rel_path, None
        if not self.root.is_dir():
            raise MemoryReadPathError("invalid-path", "root dir is not a directory")
        # Authorize parents before observing the leaf. Otherwise an outside
        # symlink with a missing leaf would be misreported as an ordinary miss.
        parent = self.root
        for part in abs_path.relative_to(self.root).parts[:-1]:
            parent = parent / part
            try:
                parent_stat = os.lstat(parent)
                if stat.S_ISLNK(parent_stat.st_mode):
                    try:
                        resolved_parent = parent.resolve(strict=True)
                    except (FileNotFoundError, NotADirectoryError) as error:
                        raise MemoryReadPathError(
                            "outside-workspace", "file is outside workspace root"
                        ) from error
                    if not self.is_path_inside_root(resolved_parent) or not resolved_parent.is_dir():
                        raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
                elif not stat.S_ISDIR(parent_stat.st_mode):
                    raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
            except FileNotFoundError:
                return rel_path, None
            except (OSError, RuntimeError) as error:
                # pathlib reports a symlink loop as RuntimeError on older
                # supported Python versions and as ELOOP on newer versions.
                if isinstance(error, RuntimeError) or getattr(error, "errno", None) == errno.ELOOP:
                    raise MemoryReadPathError("symlink", "symlink path could not be resolved") from error
                raise
        try:
            file_stat = os.lstat(abs_path)
        except FileNotFoundError:
            return rel_path, None
        except NotADirectoryError as error:
            # fs-safe's parent admission refuses a non-directory ancestor;
            # it is not a missing leaf and must remain a visible read failure.
            raise MemoryReadPathError("outside-workspace", "file is outside workspace root") from error
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise MemoryReadPathError("symlink", "symlink path could not be resolved") from error
            raise
        if stat.S_ISLNK(file_stat.st_mode):
            raise MemoryReadPathError("symlink", "symlink path component not allowed")
        if not stat.S_ISREG(file_stat.st_mode):
            raise UnsafeMemoryPathError(MEMORY_PATH_NOT_REGULAR_FILE_ERROR)
        if not self.is_path_inside_root(abs_path.resolve()):
            raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
        return rel_path, abs_path

    def append_daily_memory(
        self,
        rel_path: str,
        entry: str,
        *,
        provenance: MemoryWriteProvenanceObserver | None = None,
    ) -> Path:
        """Append ``entry`` to the daily note ``rel_path`` (``memory/YYYY-MM-DD.md``).

        With a ``provenance`` observer (the flush's trust record, upstream's
        ``createMemoryWriteProvenanceObserver``) the file's trust is recorded before the append
        (the text before and the text the append produces) and rolled back when the append fails.
        """
        validate_daily_memory_path(rel_path)
        lexical_path = self.root / rel_path
        if lexical_path.is_symlink():
            raise UnsafeMemoryPathError(f"memory path is a symlink: {rel_path}")
        path = lexical_path.resolve()
        if not self.is_path_inside_root(path):
            raise UnsafeMemoryPathError(f"memory path escapes workspace: {rel_path}")

        path.parent.mkdir(parents=True, exist_ok=True)
        if not entry.strip():
            return path
        text = entry.rstrip("\r\n")
        needs_separator = False
        if path.exists() and path.stat().st_size > 0:
            with path.open("rb") as existing:
                existing.seek(-1, 2)
                needs_separator = existing.read(1) != b"\n"

        def commit() -> None:
            with path.open("a", encoding="utf-8") as handle:
                if needs_separator:
                    handle.write("\n")
                handle.write(f"{text}\n")

        if provenance is None:
            commit()
            return path
        from memory_core.memory_write_provenance import read_text_or_empty

        before = read_text_or_empty(path)
        after = f"{before}{chr(10) if needs_separator else ''}{text}\n"
        provenance.write(absolute_path=path, content_before=before, content_after=after, commit=commit)
        return path

    def read_text(
        self,
        rel_path: str,
        *,
        from_line: int | None = None,
        line_count: int | None = None,
    ) -> MemoryReadResult:
        path = self.resolve_memory_path(rel_path)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start = max(1, from_line or 1)
        if line_count is None:
            selected = lines[start - 1 :]
        else:
            selected = lines[start - 1 : start - 1 + max(0, line_count)]
        end = start + len(selected) - 1 if selected else start - 1
        return MemoryReadResult(self.normalize_memory_path(rel_path), "".join(selected), start, end)
