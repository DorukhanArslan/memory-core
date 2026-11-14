"""Owned filesystem notifications for the managed memory publication policy.

Linux watches directories through inotify. Other systems, or an unavailable
inotify backend, reconcile actual source statistics periodically. Notifications
never decide source admission: the index's ordinary discovery remains authoritative.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection
from copy import deepcopy
import ctypes
import errno
import math
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
_DELIVERY_HISTORY = 4096
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

    def reconcile(self, directories: dict[Path, tuple[int, int]]) -> bool:
        changed = False
        for path, (descriptor, identity) in list(self.paths.items()):
            if directories.get(path) != identity:
                self._remove(self.fd, descriptor)
                self.paths.pop(path, None)
                self.descriptors.pop(descriptor, None)
                changed = True
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
            changed = True
        return changed

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
        self._condition = threading.Condition(self._lock)
        self._callback_local = threading.local()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._backend: _Inotify | None = None
        self._pipe: tuple[int, int] | None = None
        self._closed = False
        self._finished = False
        self._signature: dict[str, tuple[int, ...]] | None = None
        self._pending = False
        self._active = False
        self._changes = 0
        self._completed_callbacks = 0
        self._settled_generation = 0
        self._delivered_generation = 0
        self._deliveries: deque[dict[str, object]] = deque(maxlen=_DELIVERY_HISTORY)
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
                    while not self._stop.is_set() and backend.reconcile(directories):
                        # Files born between enumeration and attachment belong
                        # to the startup baseline, rather than a lost event.
                        self._signature, directories = _inventory(self.root)
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
            delivery = getattr(self._callback_local, "delivery", None)
            settling = getattr(self._callback_local, "settling", None)
            self._callback_local.delivery = self._callback_local.settling = None
            try:
                self._on_unavailable(error)
            except Exception:
                pass
            finally:
                self._callback_local.delivery, self._callback_local.settling = delivery, settling

    def _dirty(self, generation: int | None = None) -> None:
        self._callback_local.delivery = generation
        try:
            self._on_dirty()
        except Exception as error:
            self._unavailable(error)
        finally:
            self._callback_local.delivery = None

    @property
    def delivery_generation(self) -> int | None:
        """The actual accepted generation only inside its on_dirty callback."""
        return getattr(self._callback_local, "delivery", None)

    @property
    def settling_generation(self) -> int | None:
        """The actual accepted generation only inside its on_change callback."""
        return getattr(self._callback_local, "settling", None)

    def _owned_file(self, value: str | Path, *, absolute: bool = False) -> Path:
        if not isinstance(value, (str, Path)):
            raise ValueError("A memory watch target must name an owned eligible file")
        path = Path(value)
        if ".." in path.parts or absolute and (not path.is_absolute() or str(path) != value):
            raise ValueError("A memory watch target must be canonical and owned")
        if not path.is_absolute():
            path = self.root / path
        try:
            relative = path.relative_to(self.root)
        except ValueError as error:
            raise ValueError("A memory watch target is outside its owned workspace") from error
        parts = relative.parts
        if parts in {("MEMORY.md",), ("USER.md",)}:
            return path
        if (len(parts) < 2 or parts[0] != "memory" or not parts[-1].endswith(".md")
                or any(part.lower() in _IGNORED or part == ".openclaw-repair" for part in parts[1:-1])):
            raise ValueError("A memory watch target is not an eligible memory file")
        return path

    @staticmethod
    def _version(values: tuple[int, ...] | None) -> dict[str, object] | None:
        if values is None:
            return None
        device, inode, size, mtime, ctime = values
        return {"device": str(device), "inode": str(inode), "size": size,
                "mtimeNs": str(mtime), "ctimeNs": str(ctime)}

    def capture_versions(self, paths: Collection[str | Path]) -> list[dict[str, object]]:
        """Capture physical versions without delivering an event or starting work."""
        if isinstance(paths, (str, bytes)) or not isinstance(paths, Collection) or not paths:
            raise ValueError("At least one owned memory watch target is required")
        targets = []
        for value in paths:
            path = self._owned_file(value)
            relative = path.relative_to(self.root)
            current = self.root
            for part in (None, *relative.parts[:-1]):
                if part is not None:
                    current /= part
                try:
                    info = current.lstat()
                except (FileNotFoundError, NotADirectoryError):
                    continue
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError("A memory watch target has a symlink or non-directory ancestor")
            try:
                info = path.lstat()
            except (FileNotFoundError, NotADirectoryError):
                version = None
            else:
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("A memory watch target must be a regular file, never a symlink")
                version = self._version((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            targets.append({"path": str(path), "exists": version is not None, "version": version})
        return targets

    def _retained_targets(self, versions: Collection[dict[str, object]]) -> list[dict[str, object]]:
        if isinstance(versions, (str, bytes, dict)) or not isinstance(versions, Collection) or not versions:
            raise ValueError("At least one retained memory watch version is required")
        targets = []
        fields = {"device", "inode", "size", "mtimeNs", "ctimeNs"}
        for target in versions:
            if not isinstance(target, dict) or set(target) != {"path", "exists", "version"}:
                raise ValueError("A retained watch version has an invalid shape")
            self._owned_file(target["path"], absolute=True)
            if type(target["exists"]) is not bool:
                raise ValueError("A retained watch version must preserve actual existence")
            version = target["version"]
            if target["exists"]:
                if not isinstance(version, dict) or set(version) != fields:
                    raise ValueError("A retained watch file version is invalid")
                if type(version["size"]) is not int or version["size"] < 0:
                    raise ValueError("A retained watch file size is invalid")
                for name in ("device", "inode", "mtimeNs", "ctimeNs"):
                    value = version[name]
                    if not isinstance(value, str):
                        raise ValueError("Retained watch metadata must use exact decimal strings")
                    try:
                        number = int(value)
                    except ValueError as error:
                        raise ValueError("Retained watch metadata is not a decimal integer") from error
                    if str(number) != value or name in {"device", "inode"} and number < 0:
                        raise ValueError("Retained watch metadata is not canonical")
            elif version is not None:
                raise ValueError("An absent retained watch target cannot carry a file version")
            targets.append(deepcopy(target))
        return targets

    def wait_for_versions(self, versions: Collection[dict[str, object]], *, timeout: float | None = None) -> dict[str, object]:
        """Wait only for retained delivery witnesses and completed callbacks.

        This method performs no filesystem I/O, recapture, notification, scan,
        publication or timer modification. Initial baseline membership is never
        a delivery witness. Evicted or never observed versions remain unproved.
        """
        targets = self._retained_targets(versions)
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("The watch version timeout must be finite and nonnegative")
        if self.owns_current_thread():
            raise RuntimeError("A memory watcher cannot wait for its own callback settlement")
        deadline = time.monotonic() + timeout if timeout is not None else None
        with self._condition:
            while True:
                if self._closed or self._finished or self._thread is None or not self._thread.is_alive():
                    raise RuntimeError("The memory watcher is closed or is not observing versions")
                matches = []
                for target in targets:
                    delivery = next((row for row in reversed(self._deliveries)
                        if row["path"] == target["path"] and row["exists"] == target["exists"]
                        and row["version"] == target["version"]
                        and (target["exists"] or row["previousVersion"] is not None)), None)
                    if delivery is None or delivery["generation"] > self._settled_generation:
                        break
                    matches.append(delivery)
                if len(matches) == len(targets):
                    return {"targets": deepcopy(targets), "deliveries": deepcopy(matches),
                            "settledGeneration": self._settled_generation}
                remaining = deadline - time.monotonic() if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("The retained memory file versions were not delivered and settled")
                self._condition.wait(remaining)

    def _deliver(self, previous: dict[str, tuple[int, ...]] | None, current: dict[str, tuple[int, ...]]) -> int:
        with self._condition:
            self._pending = True
            self._changes += 1
            generation = self._changes
            if previous is not None:
                observed = str(time.monotonic_ns())
                backend = "inotify" if self._backend is not None else "stat"
                for key in sorted(previous.keys() | current.keys()):
                    if key.startswith("file:") and previous.get(key) != current.get(key):
                        version = self._version(current.get(key))
                        self._deliveries.append({"path": str(self.root / key.removeprefix("file:")),
                            "exists": version is not None, "version": version,
                            "previousVersion": self._version(previous.get(key)), "generation": generation,
                            "backend": backend, "observedAtNs": observed})
                        self._delivered_generation = generation
            self._condition.notify_all()
            return generation

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
                    while not self._stop.is_set():
                        current, directories = _inventory(self.root)
                        coverage_changed = False
                        if self._backend is not None:
                            try:
                                coverage_changed = self._backend.reconcile(directories)
                            except OSError as error:
                                self._backend.close()
                                self._backend = None
                                self._unavailable(error)
                        previous = self._signature
                        changed = previous is None or current != previous or overflow
                        self._signature = current
                        overflow = False
                        if changed:
                            generation = self._deliver(previous, current)
                            self._dirty(generation)
                            deadline, baseline = time.monotonic() + self._debounce, None
                        if not coverage_changed:
                            break
                        # Watch additions/replacements leave an enumeration /
                        # attachment gap. Observe each real intervening version
                        # immediately, before accepting stable coverage.
                    if self._stop.is_set():
                        break
                    now = time.monotonic()
                except OSError as error:
                    self._unavailable(error)
                    if deadline is None:
                        with self._lock:
                            self._pending = True
                        self._dirty()
                    deadline, baseline = now + self._poll, None
                    continue
                if deadline is not None and now >= deadline:
                    if baseline is None or baseline != current:
                        baseline, deadline = current, now + self._settle
                    else:
                        deadline, baseline = None, None
                        with self._lock:
                            self._pending = False
                            self._active = True
                            settling_generation = self._changes
                        self._callback_local.settling = settling_generation
                        try:
                            if not self._stop.is_set():
                                self._on_change()
                                with self._condition:
                                    self._completed_callbacks += 1
                                    self._settled_generation = max(self._settled_generation, settling_generation)
                                    self._condition.notify_all()
                        except Exception as error:
                            self._unavailable(error)
                        finally:
                            self._callback_local.settling = None
                            with self._lock:
                                self._active = False
        except Exception as error:
            self._unavailable(error)
        finally:
            if self._backend is not None:
                self._backend.close()
            with self._condition:
                self._pending = False
                self._active = False
                self._finished = True
                self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"started": self._thread is not None, "closed": self._closed,
                    "alive": self._thread is not None and self._thread.is_alive(),
                    "backend": "inotify" if self._backend is not None else "stat",
                    "pending": self._pending, "active": self._active, "changes": self._changes,
                    "completedCallbacks": self._completed_callbacks, "overflows": self._overflows,
                    "lastError": self._last_error, "deliveredGeneration": self._delivered_generation,
                    "settledGeneration": self._settled_generation, "deliveries": deepcopy(list(self._deliveries))}

    def status(self) -> dict[str, object]:
        with self._lock:
            return {"started": self._thread is not None, "closed": self._closed,
                    "backend": "inotify" if self._backend is not None else "stat",
                    "threadId": self._thread.ident if self._thread is not None else None,
                    "alive": self._thread is not None and self._thread.is_alive(),
                    "pendingChange": self._pending, "acceptedChanges": self._changes,
                    "deliveredGeneration": self._delivered_generation, "settledGeneration": self._settled_generation}

    def owns_current_thread(self) -> bool:
        return self._thread is threading.current_thread()

    def close(self) -> None:
        with self._lock:
            thread = self._thread
            if thread is threading.current_thread():
                raise RuntimeError("A watcher callback cannot close its own watcher")
            self._closed = True
            self._stop.set()
            self._condition.notify_all()
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
