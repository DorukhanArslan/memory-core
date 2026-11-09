from __future__ import annotations

import errno
import os
import re
import stat
import threading
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from memory_core.bootstrap._js import js_trim, js_utf8_encode
from memory_core._memory_scan_io import bridge_memory_read_io_error
from memory_core.memory_paths import (
    SESSION_CORPUS_FILE_RE,
    MemoryPathNotAllowedError,
    MemoryReadPathError,
    UnsafeMemoryPathError,
    validate_daily_memory_path,
)
from memory_core.session_corpus import MemoryCoreSessionCorpus, is_memory_session_indexable

if TYPE_CHECKING:
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver
    from memory_core.session_entry import SessionEntry

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


def list_memory_files(
    workspace_dir: Path, extra_paths: Sequence[str | Mapping[str, str]] | None = None,
    multimodal: Mapping[str, object] | None = None,
    on_skipped_symlink_root: Callable[[Path], None] | None = None,
) -> list[Path]:
    """OpenClaw ``listMemoryFiles`` filesystem discovery (v2026.9.9).

    Returns paths in upstream order: the root ``MEMORY.md`` when it is a real
    file (exact name, not a symlink), root ``USER.md``, then every ``*.md`` under
    ``memory/`` sorted by JavaScript UTF-16 code units. Symlinked files and directories are
    skipped, a symlinked ``memory/`` is ignored, and ``.openclaw-repair``
    directories are not descended; hidden files and dot-directories such as
    ``memory/.dreams`` are walked like any other entry. Results are deduplicated
    by realpath. Missing entries are ignored; operational scan errors are
    reported instead of publishing an apparently successful partial scan.

    Extra roots retain their configured order and union their glob patterns.
    Image/audio extension discovery is an explicit extra-root opt-in; discovery
    does not imply support for multimodal embeddings or binary-file reads.
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
        raise MemorySourceScanError(memory_dir, exc, operation="lstat") from exc
    if (
        memory_dir_stat is not None
        and not stat.S_ISLNK(memory_dir_stat.st_mode)
        and stat.S_ISDIR(memory_dir_stat.st_mode)
    ):
        _collect_memory_files_from_dir(memory_dir, result)
    for extra_root, entries in _extra_memory_paths(root, extra_paths).items():
        if _skip_root_auxiliary(root, extra_root):
            continue
        try:
            extra_stat = os.lstat(extra_root)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            raise MemorySourceScanError(extra_root, exc, operation="lstat") from exc
        if stat.S_ISLNK(extra_stat.st_mode):
            if on_skipped_symlink_root is not None:
                on_skipped_symlink_root(extra_root)
        elif stat.S_ISDIR(extra_stat.st_mode):
            _collect_memory_files_from_dir(
                extra_root, result, multimodal=multimodal,
                should_skip_path=lambda path: _skip_root_auxiliary(root, path), extra_path_entries=entries,
            )
        elif stat.S_ISREG(extra_stat.st_mode) and _allowed_memory_file(extra_root, multimodal):
            result.append(extra_root)
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


def _extra_memory_paths(
    workspace: Path, configured: Sequence[str | Mapping[str, str]] | None,
) -> dict[Path, list[tuple[Path, str | None]]]:
    normalized = {}
    for entry in configured or ():
        path = js_trim(entry if isinstance(entry, str) else entry["path"])
        raw_pattern = None if isinstance(entry, str) else entry.get("pattern")
        pattern = js_trim(raw_pattern) or None if raw_pattern is not None else None
        if path:
            normalized[(path, pattern)] = (path, pattern)
    grouped: dict[Path, list[tuple[Path, str | None]]] = {}
    for path, pattern in normalized.values():
        if path == "~":
            path = str(Path.home())
        elif path.startswith(("~/", "~\\")):
            path = str(Path.home() / path[2:])
        absolute = Path(os.path.abspath(os.path.join(workspace, path)))
        grouped.setdefault(absolute, []).append((absolute, pattern.replace("\\", "/") if pattern else None))
    return grouped


def _skip_root_auxiliary(workspace: Path, path: Path) -> bool:
    relative = os.path.relpath(path, workspace).replace(os.sep, "/")
    return relative == "memory.md" or relative == ".openclaw-repair/root-memory" or relative.startswith(
        ".openclaw-repair/root-memory/"
    )


def _allowed_memory_file(path: Path, multimodal: Mapping[str, object] | None) -> bool:
    if path.name.endswith(".md"):
        return True
    if not multimodal or multimodal.get("enabled") is not True:
        return False
    extensions = {
        "image": (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"),
        "audio": (".mp3", ".wav", ".ogg", ".opus", ".m4a", ".m2a", ".aac", ".flac"),
    }
    return any(str(path).lower().endswith(extensions[modality]) for modality in multimodal.get("modalities", ())
               if modality in extensions)


def _matches_extra_path(entry: tuple[Path, str | None], candidate: Path, *, directory: bool = False) -> bool:
    root, pattern = entry
    if not pattern:
        return True
    relative = os.path.relpath(candidate, root)
    if relative == ".":
        return True
    if relative == ".." or relative.startswith(".." + os.sep):
        return False
    relative = relative.replace(os.sep, "/")
    from memory_core._memory_glob import matches_posix_glob

    def matches(value: str) -> bool:
        return matches_posix_glob(relative, value)

    try:
        if not directory:
            return matches(pattern)
        segments = pattern.split("/")
        if re.search(r"[\{\[\(]", pattern) or any(segment in {".", ".."} for segment in segments):
            return True
        parents = len(segments) if segments[-1] == "**" else len(segments) - 1
        return any(matches("/".join(segments[:count])) for count in range(1, parents + 1))
    except Exception:
        return False


class MemorySourceScanError(RuntimeError):
    """An operational failure while enumerating a memory source.

    The path, string code and unmodified public cause mirror the native scan
    diagnostic. Standard system errors cross the actual IO bridge; its original
    Python exception remains available separately. Missing sources are handled
    by discovery itself rather than becoming scan failures.
    """

    def __init__(self, path: Path, cause: OSError, *, operation: str | None = None):
        from memory_core._memory_scan_io import bridge_scan_io_error

        cause = bridge_scan_io_error(cause, operation, path)
        self.path = path
        supplied_code = getattr(cause, "code", None)
        self.code = supplied_code if isinstance(supplied_code, str) else errno.errorcode.get(getattr(cause, "errno", None))
        self.cause = cause
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
        raise MemorySourceScanError(root, exc, operation="scandir") from exc
    return None


def _is_regular_markdown_file(path: Path) -> bool:
    # listMemoryFiles addMarkdownFile: statRegularFile (lstat; symlinks and
    # non-regular files are rejected) plus the `.md` suffix check.
    try:
        file_stat = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:
        raise MemorySourceScanError(path, exc, operation="lstat") from exc
    return stat.S_ISREG(file_stat.st_mode) and path.name.endswith(".md")


def _collect_memory_files_from_dir(
    directory: Path, files: list[Path], *, multimodal: Mapping[str, object] | None = None,
    should_skip_path: Callable[[Path], bool] | None = None,
    extra_path_entries: Sequence[tuple[Path, str | None]] | None = None,
) -> None:
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
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as exc:
            raise MemorySourceScanError(current, exc, operation="lstat") from exc
        try:
            real_dir = os.path.realpath(current, strict=True)
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as exc:
            raise MemorySourceScanError(current, exc, operation="realpath") from exc
        if real_dir in visited:
            return
        visited.add(real_dir)
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as exc:
            raise MemorySourceScanError(current, exc, operation="scandir") from exc
        for entry in entries:
            if entry.is_symlink():
                continue
            full_path = current / entry.name
            if should_skip_path is not None and should_skip_path(full_path):
                continue
            if entry.is_file(follow_symlinks=False):
                if _allowed_memory_file(full_path, multimodal) and (extra_path_entries is None or any(
                    _matches_extra_path(item, full_path) for item in extra_path_entries
                )):
                    collected.append(full_path)
            elif entry.is_dir(follow_symlinks=False) and entry.name != OPENCLAW_REPAIR_DIRNAME:
                if extra_path_entries is None or any(
                    _matches_extra_path(item, full_path, directory=True) for item in extra_path_entries
                ):
                    visit(full_path)

    visit(directory)
    files.extend(sorted(collected, key=lambda item: str(item).encode("utf-16-be", "surrogatepass")))



# One lock per (workspace root, file) for this process: curated writes and the memory flush's
# daily append read, check and write under it, so parallel tool calls never interleave.
_FILE_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()
_INDEX_LOCKS: dict[str, threading.RLock] = {}


def workspace_file_lock(root: Path, rel_path: str) -> threading.Lock:
    """The process-wide write lock of ``rel_path`` under the (resolved) workspace ``root``."""
    with _FILE_LOCKS_GUARD:
        return _FILE_LOCKS.setdefault((str(root), rel_path), threading.Lock())


def workspace_index_lock(root: Path) -> threading.RLock:
    """Serialize cooperating index refreshes and curated write/refresh pairs.

    Reentrancy lets a committed curated write refresh its index, and permits
    same-thread host callbacks. External processes and raw filesystem writers
    remain subject to the source and database generation checks.
    """
    key = str(root.resolve())
    with _FILE_LOCKS_GUARD:
        return _INDEX_LOCKS.setdefault(key, threading.RLock())


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
    assert_current: Callable[[], None] | None = None,
) -> Path:
    """:meth:`MemoryWorkspace.append_daily_memory` under the file's write lock.

    The curated daily note append: ``rel_path`` must be ``memory/YYYY-MM-DD.md`` and pass
    :func:`check_writable_memory_file`. The flush tool uses :func:`append_memory_flush_file`
    to preserve its exact content. ``provenance`` is the optional memory write observer.
    ``assert_current`` is a prompt synchronous raising check, run under the file lock and again
    before the append commits, including after provenance callbacks.
    """
    resolved = Path(root).resolve()
    validate_daily_memory_path(rel_path)
    with workspace_file_lock(resolved, rel_path):
        if assert_current is not None:
            assert_current()
        check_writable_memory_file(resolved, rel_path)
        return MemoryWorkspace(resolved).append_daily_memory(
            rel_path, entry, provenance=provenance, assert_current=assert_current
        )


def append_memory_flush_file(
    root: str | os.PathLike[str],
    rel_path: str,
    content: str,
    *,
    provenance: MemoryWriteProvenanceObserver | None = None,
    assert_current: Callable[[], None] | None = None,
) -> Path:
    """Append a flush tool's exact UTF-8 content under its file write lock.

    Unlike the curated daily-note append, empty strings, whitespace and ``NO_REPLY``
    are ordinary tool content. No trailing newline is added. The native fs-safe
    append separates nonempty content only when neither side supplies a newline.
    Path admission retains the SDK's stricter refusal of symlinks and hard links.

    Provenance follows the original flush wrapper's precommit text projection,
    including its empty-content edge: a non-newline-terminated existing file gets
    a projected separator even though fs-safe's empty append changes no bytes.
    """
    if not isinstance(content, str):
        raise TypeError("flush content must be a string")
    validate_daily_memory_path(rel_path)
    resolved = Path(root).resolve()
    target = resolved / rel_path
    encoded = js_utf8_encode(content)

    def check_current() -> None:
        if assert_current is not None:
            assert_current()

    with workspace_file_lock(resolved, rel_path):
        check_current()
        check_writable_memory_file(resolved, rel_path)
        check_current()
        target.parent.mkdir(parents=True, exist_ok=True)
        check_current()
        try:
            before = target.read_bytes().decode("utf-8", errors="replace")
        except FileNotFoundError:
            before = ""
        provenance_separator = "\n" if before and not before.endswith("\n") and not content.startswith("\n") else ""

        def commit() -> None:
            check_current()
            check_writable_memory_file(resolved, rel_path)
            flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_BINARY", 0)
            created = False
            try:
                descriptor = os.open(target, flags | os.O_EXCL, 0o666)
                created = True
            except FileExistsError:
                descriptor = os.open(target, flags, 0o666)
            dispatched = False
            identity = None
            try:
                identity = os.fstat(descriptor)

                def check_handle() -> None:
                    check_current()
                    check_writable_memory_file(resolved, rel_path)
                    current = os.stat(target, follow_symlinks=False)
                    if (not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1
                            or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)):
                        raise UnsafeMemoryPathError(f"memory flush target changed during append: {rel_path}")

                check_handle()
                separator = b""
                if encoded and identity.st_size > 0 and not encoded.startswith(b"\n"):
                    os.lseek(descriptor, -1, os.SEEK_END)
                    if os.read(descriptor, 1) != b"\n":
                        separator = b"\n"
                payload = separator + encoded
                offset = 0
                while offset < len(payload):
                    check_handle()
                    dispatched = True
                    written = os.write(descriptor, payload[offset:offset + 512 * 1024])
                    if written <= 0:
                        raise OSError(errno.EIO, "file write made no progress")
                    offset += written
                # Empty appends still create a missing file and settle successfully.
                dispatched = True
                os.fsync(descriptor)
            finally:
                try:
                    os.close(descriptor)
                finally:
                    if created and not dispatched and identity is not None:
                        try:
                            current = os.stat(target, follow_symlinks=False)
                            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                                target.unlink()
                        except FileNotFoundError:
                            pass
            if created:
                directory_descriptor = None
                try:
                    directory_descriptor = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    os.fsync(directory_descriptor)
                except OSError:
                    pass  # native fs-safe syncs a newly created file's parent best-effort
                finally:
                    if directory_descriptor is not None:
                        try:
                            os.close(directory_descriptor)
                        except OSError:
                            pass

        if provenance is None:
            commit()
        else:
            check_current()
            provenance.write(
                absolute_path=target,
                content_before=before,
                content_after=before + provenance_separator + encoded.decode("utf-8"),
                commit=commit,
            )
    return target


@dataclass(frozen=True)
class MemoryFile:
    rel_path: str
    abs_path: Path
    source: str = "memory"
    index_text: str | None = None
    # An authoritative host projection includes source hash, line mapping and
    # per-line provenance. Plain index_text remains supported for legacy hosts.
    index_entry: SessionEntry | None = None
    # Authoritative non-file transcript state, supplied by a session catalog.
    index_mtime_ms: float | None = None
    index_size: int | None = None


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
        session_catalog: MemorySessionCatalog | None = None,
        index_sources: Sequence[str] | None = None,
    ):
        # ``is_session_forgotten(session_id)``: forgotten sessions leave the index and stay out
        # (the origins ledger's tombstones, ``MemoryEntryOriginLedger.list_session_tombstones``).
        self.is_session_forgotten = is_session_forgotten
        self.root = root.resolve()
        self.openclaw_state_dir = openclaw_state_dir.resolve() if openclaw_state_dir else None
        self.agent_id = agent_id
        self.session_catalog = session_catalog
        self.index_sources = tuple(index_sources) if index_sources is not None else None

    def discover_memory_files(
        self, *, extra_paths: Sequence[str | Mapping[str, str]] | None = None,
        multimodal: Mapping[str, object] | None = None,
        on_skipped_symlink_root: Callable[[Path], None] | None = None,
    ) -> list[MemoryFile]:
        # Same file list as OpenClaw's memory index (listMemoryFiles); the
        # relative path mirrors buildFileEntry (path.relative + "/" separators).
        files = (list_memory_files(self.root) if extra_paths is None and multimodal is None
                 and on_skipped_symlink_root is None else
                 list_memory_files(self.root, extra_paths, multimodal, on_skipped_symlink_root))
        return [
            MemoryFile(os.path.relpath(path, self.root).replace(os.sep, "/"), path)
            for path in files
        ]

    def discover_session_transcript_files(self, *, paths: Collection[str] | None = None) -> list[MemoryFile]:
        files: list[MemoryFile] = []
        session_dir = self.root / "memory" / ".dreams" / "session-corpus"
        if session_dir.is_dir():
            for path in sorted(session_dir.iterdir()):
                if paths is not None and path.relative_to(self.root).as_posix() not in paths:
                    continue
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
        if self.openclaw_state_dir is not None or self.session_catalog is not None:
            corpus = MemoryCoreSessionCorpus(
                self.openclaw_state_dir or self.session_catalog.store_path.parent,
                agent_id=self.agent_id, is_forgotten=self.is_session_forgotten,
                catalog=self.session_catalog,
            )
            for item in corpus.discover_files():
                if paths is not None and item.rel_path not in paths:
                    continue
                entry = corpus.read_index_entry(item)
                if entry is None:
                    continue
                if not is_memory_session_indexable({
                    "generatedByDreamingNarrative": entry.generated_by_dreaming_narrative,
                    "generatedByCronRun": entry.generated_by_cron_run,
                    "sessionKind": entry.session_kind, "lineProvenance": entry.line_provenance,
                }):
                    continue
                files.append(MemoryFile(
                    item.rel_path, item.abs_path, item.source,
                    index_text=entry.content, index_entry=entry,
                    index_mtime_ms=item.updated_at_ms, index_size=item.index_size,
                ))
        return files

    def discover_indexable_files(self, *, sources: Collection[str] | None = None,
                                 paths: Collection[str] | None = None) -> list[MemoryFile]:
        # memory-core extension: files under memory/.dreams/session-corpus/ are
        # indexed once, as source "sessions" (the lab writes its chat corpus
        # there as YYYY-MM-DD.md). Upstream has no sessions scan of that
        # directory; its recursive memory walk would index such a `.md` as a
        # memory file, and upstream's own corpus files are `.txt`, which the
        # memory walk never picks up.
        configured = set(self.index_sources) if self.index_sources is not None else {"memory", "sessions"}
        selected = configured if sources is None else configured.intersection(sources)
        session_files = (self.discover_session_transcript_files() if paths is None else
                         self.discover_session_transcript_files(paths=paths)) if "sessions" in selected else []
        session_paths = {file.rel_path for file in session_files}
        def selected_memory(file: MemoryFile) -> bool:
            if paths is not None and file.rel_path not in paths:
                return False
            # The lab's legacy session-corpus files retain their existing
            # source classification even when only memory is being refreshed.
            if "sessions" in configured and "sessions" not in selected:
                relative = Path(file.rel_path)
                if (relative.parent.as_posix() == "memory/.dreams/session-corpus"
                        and SESSION_CORPUS_FILE_RE.fullmatch(relative.name)):
                    return False
            return file.rel_path not in session_paths
        memory_files = [
            file for file in self.discover_memory_files() if selected_memory(file)
        ] if "memory" in selected else [
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
        is refused. Extra roots are owned by ``tools.get_paths``; the actual
        descriptor read and final identity fences are owned by ``memory_read``.
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
                        resolved_parent = Path(os.path.realpath(parent, strict=True))
                    except (FileNotFoundError, NotADirectoryError):
                        # fs-safe retains the unresolved owned target, then
                        # observes its directory type. Outside targets are
                        # refused before this subsequent target observation.
                        resolved_parent = Path(os.path.realpath(parent))
                    except OSError as error:
                        cause = bridge_memory_read_io_error(error, "realpath", parent)
                        if error.errno == errno.ELOOP:
                            raise MemoryReadPathError("symlink", "symlink path could not be resolved") from cause
                        raise cause from None
                    if not self.is_path_inside_root(resolved_parent):
                        raise MemoryReadPathError(
                            "outside-workspace", "file is outside workspace root"
                        ) from ValueError(f"Symlink escapes root ({self.root}): {parent}")
                    try:
                        resolved_stat = os.stat(resolved_parent)
                    except OSError as error:
                        raise MemoryReadPathError(
                            "outside-workspace", "file is outside workspace root",
                        ) from bridge_memory_read_io_error(error, "stat", resolved_parent)
                    if not stat.S_ISDIR(resolved_stat.st_mode):
                        raise MemoryReadPathError(
                            "outside-workspace", "file is outside workspace root",
                        ) from MemoryReadPathError(
                            "ENOTDIR", f"Path component is not a directory: {resolved_parent}",
                        )
                elif not stat.S_ISDIR(parent_stat.st_mode):
                    raise MemoryReadPathError(
                        "outside-workspace", "file is outside workspace root",
                    ) from MemoryReadPathError(
                        "ENOTDIR", f"Path component is not a directory: {parent}",
                    )
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
            raise UnsafeMemoryPathError(MEMORY_PATH_NOT_REGULAR_FILE_ERROR) from MemoryReadPathError(
                "not-file", "not a file",
            )
        if not self.is_path_inside_root(abs_path.resolve()):
            raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
        return rel_path, abs_path

    def append_daily_memory(
        self,
        rel_path: str,
        entry: str,
        *,
        provenance: MemoryWriteProvenanceObserver | None = None,
        assert_current: Callable[[], None] | None = None,
    ) -> Path:
        """Append ``entry`` to the daily note ``rel_path`` (``memory/YYYY-MM-DD.md``).

        With a ``provenance`` observer (the flush's trust record, upstream's
        ``createMemoryWriteProvenanceObserver``) the file's trust is recorded before the append
        (the text before and the text the append produces) and rolled back when the append fails.
        ``assert_current`` checks the host's authority before filesystem mutations and before
        reserving provenance; a cancellation after reservation rolls the provenance back.
        """
        validate_daily_memory_path(rel_path)
        lexical_path = self.root / rel_path
        if lexical_path.is_symlink():
            raise UnsafeMemoryPathError(f"memory path is a symlink: {rel_path}")
        path = lexical_path.resolve()
        if not self.is_path_inside_root(path):
            raise UnsafeMemoryPathError(f"memory path escapes workspace: {rel_path}")

        if assert_current is not None:
            assert_current()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not entry.strip():
            return path
        text = entry.rstrip("\r\n")
        needs_separator = False
        if not text.startswith("\n") and path.exists() and path.stat().st_size > 0:
            with path.open("rb") as existing:
                existing.seek(-1, 2)
                needs_separator = existing.read(1) != b"\n"

        def commit() -> None:
            from memory_core.atomic_publication import append_memory_content

            if assert_current is not None:
                assert_current()
            append_memory_content(path, text + "\n", prepend_newline_if_needed=True, before_write=assert_current)

        if provenance is None:
            commit()
            return path
        from memory_core.memory_write_provenance import read_text_or_empty

        before = read_text_or_empty(path)
        after = f"{before}{chr(10) if needs_separator else ''}{text}\n"
        if assert_current is not None:
            assert_current()
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
