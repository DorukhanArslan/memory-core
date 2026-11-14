"""Owned filesystem notifications for the managed memory publication policy.

Linux watches directories through inotify. Other systems, or an unavailable
inotify backend, reconcile actual source statistics periodically. Notifications
never decide source admission: the index's ordinary discovery remains authoritative.
"""
from __future__ import annotations

from collections.abc import Callable
import ctypes
import errno
import os
from pathlib import Path
import select
import stat
import struct
import sys
import threading
import time


_IGNORED = frozenset({".git", "node_modules", ".pnpm-store", ".venv", "venv", ".tox", "__pycache__"})
_MAX_PATHS = 1024
_IS_DIRECTORY = 0x40000000
_OVERFLOW = 0x00004000
_IGNORED_WATCH = 0x00008000
_EVENT = struct.Struct("iIII")
_MASK = 0x00000002 | 0x00000004 | 0x00000008 | 0x00000040 | 0x00000080 | 0x00000100 | 0x00000200 | 0x00000400 | 0x00000800


def _directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    return (info.st_dev, info.st_ino) if stat.S_ISDIR(info.st_mode) else None


def _inventory(root: Path) -> tuple[dict[str, tuple[int, ...]], dict[Path, tuple[int, int]]]:
    """Observe eligible files and directory identity without following symlinks."""
    signature: dict[str, tuple[int, ...]] = {}
    directories: dict[Path, tuple[int, int]] = {}
    parent = root.parent
    while (identity := _directory_identity(parent)) is None and parent != parent.parent:
        parent = parent.parent
    if identity is not None:
        directories[parent] = identity
    root_identity = _directory_identity(root)
    if root_identity is None:
        return signature, directories
    directories[root] = root_identity
    signature["directory:"] = root_identity

    def file(path: Path, relative: str) -> None:
        try:
            info = path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return
        if stat.S_ISREG(info.st_mode):
            signature["file:" + relative] = (info.st_dev, info.st_ino, info.st_size,
                                              info.st_mtime_ns, info.st_ctime_ns)

    for name in ("MEMORY.md", "USER.md"):
        file(root / name, name)

    def directory(path: Path, relative: str) -> None:
        identity = _directory_identity(path)
        if identity is None:
            return
        directories[path] = identity
        signature["directory:" + relative] = identity
        try:
            with os.scandir(path) as iterator:
                entries = list(iterator)
        except (FileNotFoundError, NotADirectoryError):
            return
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                child = path / entry.name
                child_relative = relative + "/" + entry.name
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in _IGNORED and entry.name != ".openclaw-repair":
                        directory(child, child_relative)
                elif entry.name.endswith(".md") and entry.is_file(follow_symlinks=False):
                    file(child, child_relative)
            except (FileNotFoundError, NotADirectoryError):
                continue

    directory(root / "memory", "memory")
    return signature, directories


class _Inotify:
    """One nonblocking descriptor and one kernel watch per real directory."""

    def __init__(self) -> None:
        if not sys.platform.startswith("linux"):
            raise NotImplementedError("inotify is unavailable on this platform")
        library = ctypes.CDLL(None, use_errno=True)
        self._add = library.inotify_add_watch
        self._add.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32)
        self._add.restype = ctypes.c_int
        self._remove = library.inotify_rm_watch
        self._remove.argtypes = (ctypes.c_int, ctypes.c_int)
        self._remove.restype = ctypes.c_int
        initialize = library.inotify_init1
        initialize.argtypes = (ctypes.c_int,)
        initialize.restype = ctypes.c_int
        self.fd = initialize(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        self.paths: dict[Path, tuple[int, tuple[int, int]]] = {}
        self.descriptors: dict[int, Path] = {}

    def reconcile(self, directories: dict[Path, tuple[int, int]]) -> None:
        for path, (descriptor, identity) in list(self.paths.items()):
            if directories.get(path) != identity:
                self._remove(self.fd, descriptor)
                self.paths.pop(path, None)
                self.descriptors.pop(descriptor, None)
        for path, identity in directories.items():
            if path in self.paths:
                continue
            descriptor = self._add(self.fd, os.fsencode(path), _MASK | 0x01000000 | 0x02000000)
            if descriptor < 0:
                code = ctypes.get_errno()
                if code in {errno.ENOENT, errno.ENOTDIR}:
                    continue
                raise OSError(code, os.strerror(code), str(path))
            self.paths[path] = (descriptor, identity)
            self.descriptors[descriptor] = path

    def read(self) -> tuple[dict[Path, bool], bool]:
        paths: dict[Path, bool] = {}
        overflow = False
        # Bound one drain so close remains responsive during a sustained burst.
        for _ in range(16):
            try:
                payload = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not payload:
                raise OSError("The inotify descriptor closed unexpectedly")
            position = 0
            while position + _EVENT.size <= len(payload):
                descriptor, mask, _, length = _EVENT.unpack_from(payload, position)
                name = payload[position + _EVENT.size:position + _EVENT.size + length].split(b"\0", 1)[0]
                position += _EVENT.size + length
                if mask & _OVERFLOW:
                    overflow = True
                parent = self.descriptors.get(descriptor)
                if parent is None:
                    continue
                if mask & _IGNORED_WATCH:
                    self.descriptors.pop(descriptor, None)
                    self.paths.pop(parent, None)
                if not overflow:
                    paths[parent / os.fsdecode(name) if name else parent] = bool(mask & _IS_DIRECTORY)
                    if len(paths) > _MAX_PATHS:
                        paths.clear()
                        overflow = True
        return paths, overflow

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        self.paths.clear()
        self.descriptors.clear()


class MemoryFileWatcher:
    """Observe real memory files, settle bursts, and own callback shutdown.

    Startup establishes coverage before returning and does not publish initial
    files. The optional small intervals are useful for embedded hosts and tests;
    defaults retain native's 1500 ms debounce and 100 ms unknown-baseline settle.
    """

    def __init__(self, root: Path, *, on_dirty: Callable[[], None], on_change: Callable[[], None],
                 on_unavailable: Callable[[Exception], None] | None = None, debounce_ms: float = 1500,
                 poll_interval_ms: float = 100, settle_ms: float = 100) -> None:
        if debounce_ms < 0 or poll_interval_ms <= 0 or settle_ms <= 0:
            raise ValueError("Watcher debounce must be nonnegative and intervals must be positive")
        self.root = Path(root).absolute()
        self._on_dirty, self._on_change, self._on_unavailable = on_dirty, on_change, on_unavailable
        self._debounce, self._poll, self._settle = debounce_ms / 1000, poll_interval_ms / 1000, settle_ms / 1000
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._backend: _Inotify | None = None
        self._pipe: tuple[int, int] | None = None
        self._closed = False
        self._signature: dict[str, tuple[int, ...]] | None = None
        self._pending = False
        self._active = False
        self._changes = 0
        self._completed_callbacks = 0
        self._overflows = 0
        self._last_error: str | None = None
        self._startup_errors: list[Exception] = []

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("The memory file watcher is closed")
            if self._thread is not None:
                return
            try:
                self._signature, directories = _inventory(self.root)
            except OSError as error:
                self._signature, directories = None, {}
                self._startup_errors.append(error)
            try:
                backend = _Inotify()
                try:
                    backend.reconcile(directories)
                except BaseException:
                    backend.close()
                    raise
                self._backend = backend
            except (OSError, AttributeError, NotImplementedError) as error:
                if not isinstance(error, NotImplementedError):
                    self._startup_errors.append(error)
            try:
                self._pipe = os.pipe()
                for descriptor in self._pipe:
                    os.set_blocking(descriptor, False)
                    os.set_inheritable(descriptor, False)
                self._thread = threading.Thread(target=self._run, name="memory-file-watcher", daemon=True)
                self._thread.start()
            except BaseException:
                self._thread = None
                if self._backend is not None:
                    self._backend.close()
                    self._backend = None
                if self._pipe is not None:
                    for descriptor in self._pipe:
                        os.close(descriptor)
                    self._pipe = None
                raise

    def _candidate(self, path: Path, directory: bool) -> bool:
        if path == self.root or path in {self.root / "MEMORY.md", self.root / "USER.md", self.root / "memory"}:
            return True
        try:
            relative = path.relative_to(self.root / "memory")
        except ValueError:
            # An ancestor watch must also notice the birth of a missing root.
            return path in self.root.parents
        if any(part.lower() in _IGNORED or part == ".openclaw-repair" for part in relative.parts):
            return False
        return directory or path.name.endswith(".md")

    def _unavailable(self, error: Exception) -> None:
        with self._lock:
            self._last_error = str(error)
        if self._on_unavailable is not None and not self._stop.is_set():
            try:
                self._on_unavailable(error)
            except Exception:
                pass

    def _dirty(self) -> None:
        try:
            self._on_dirty()
        except Exception as error:
            self._unavailable(error)

    def _run(self) -> None:
        deadline: float | None = None
        baseline: dict[str, tuple[int, ...]] | None = None
        next_poll = time.monotonic()
        initial = True
        try:
            for error in self._startup_errors:
                self._unavailable(error)
            while not self._stop.is_set():
                now = time.monotonic()
                backend = self._backend
                scan = initial or backend is None and now >= next_poll
                initial = False
                overflow = False
                timeout = max(0, min(self._poll, (deadline - now) if deadline is not None else self._poll))
                descriptors = [self._pipe[0]] if self._pipe is not None else []
                if backend is not None:
                    descriptors.append(backend.fd)
                ready, _, _ = select.select(descriptors, [], [], 0 if scan else timeout)
                if self._stop.is_set():
                    break
                if backend is not None and backend.fd in ready:
                    try:
                        paths, overflow = backend.read()
                        scan = scan or overflow or any(self._candidate(path, directory) for path, directory in paths.items())
                    except OSError as error:
                        backend.close()
                        self._backend = None
                        self._unavailable(error)
                        scan, overflow = True, True
                if overflow:
                    with self._lock:
                        self._overflows += 1
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    scan = True
                if not scan:
                    continue
                next_poll = now + self._poll
                try:
                    current, directories = _inventory(self.root)
                    if self._backend is not None:
                        try:
                            self._backend.reconcile(directories)
                        except OSError as error:
                            self._backend.close()
                            self._backend = None
                            self._unavailable(error)
                    changed = self._signature is None or current != self._signature or overflow
                    self._signature = current
                except OSError as error:
                    self._unavailable(error)
                    if deadline is None:
                        with self._lock:
                            self._pending = True
                        self._dirty()
                    deadline, baseline = now + self._poll, None
                    continue
                if changed:
                    with self._lock:
                        self._pending = True
                        self._changes += 1
                    self._dirty()
                    deadline, baseline = now + self._debounce, None
                if deadline is not None and now >= deadline:
                    if baseline is None or baseline != current:
                        baseline, deadline = current, now + self._settle
                    else:
                        deadline, baseline = None, None
                        with self._lock:
                            self._pending = False
                            self._active = True
                        try:
                            if not self._stop.is_set():
                                self._on_change()
                                with self._lock:
                                    self._completed_callbacks += 1
                        except Exception as error:
                            self._unavailable(error)
                        finally:
                            with self._lock:
                                self._active = False
        except Exception as error:
            self._unavailable(error)
        finally:
            if self._backend is not None:
                self._backend.close()
            with self._lock:
                self._pending = False
                self._active = False

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"started": self._thread is not None, "closed": self._closed,
                    "alive": self._thread is not None and self._thread.is_alive(),
                    "backend": "inotify" if self._backend is not None else "stat",
                    "pending": self._pending, "active": self._active, "changes": self._changes,
                    "completedCallbacks": self._completed_callbacks, "overflows": self._overflows,
                    "lastError": self._last_error}

    def status(self) -> dict[str, object]:
        with self._lock:
            return {"started": self._thread is not None, "closed": self._closed,
                    "backend": "inotify" if self._backend is not None else "stat",
                    "threadId": self._thread.ident if self._thread is not None else None,
                    "alive": self._thread is not None and self._thread.is_alive(),
                    "pendingChange": self._pending, "acceptedChanges": self._changes}

    def owns_current_thread(self) -> bool:
        return self._thread is threading.current_thread()

    def close(self) -> None:
        with self._lock:
            thread = self._thread
            if thread is threading.current_thread():
                raise RuntimeError("A watcher callback cannot close its own watcher")
            self._closed = True
            self._stop.set()
            if self._pipe is not None:
                try:
                    os.write(self._pipe[1], b"x")
                except BlockingIOError:
                    pass
        if thread is not None:
            thread.join()
        with self._lock:
            if self._pipe is not None:
                for descriptor in self._pipe:
                    os.close(descriptor)
                self._pipe = None
