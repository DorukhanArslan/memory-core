"""Short-term recall store, phase-signal store and promotion lock.

Workspace JSON contract of ``extensions/memory-core/src/short-term-promotion.ts``
(OpenClaw pin 4c42815348): recall entries live in
``memory/.dreams/short-term-recall.json``, dreaming phase signals in
``memory/.dreams/phase-signals.json`` and the promotion lock in
``memory/.dreams/short-term-promotion.lock``.

Documented deviation (decision Q14, 2026-09-26): the pin keeps this state in
SQLite-backed plugin state; memory-core keeps the JSON files as its contract and
the oracle runner bridges them into the pin's plugin state. The retention caps
(512 entries, 800-char snippets) and the 60 s stale-lock window are the pin's.
"""

from __future__ import annotations

import contextvars
import json
import os
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_trim_end, utf16_len
from memory_core.config import MemoryConfig
from memory_core.project_name import PACKAGE_NAME
from memory_core.index.cjk_chars import truncate_utf16_safe
from memory_core.consolidation._util import (
    DAY_MS,
    iso_ms,
    parse_ms,
    to_int,
    write_json_atomic,
)
from memory_core.workspace import workspace_file_lock

SHORT_TERM_STORE_RELATIVE_PATH = Path("memory") / ".dreams" / "short-term-recall.json"
SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH = Path("memory") / ".dreams" / "phase-signals.json"
SHORT_TERM_LOCK_RELATIVE_PATH = Path("memory") / ".dreams" / "short-term-promotion.lock"
# Python-only guard file serialising lock steal/release across processes.
_SHORT_TERM_LOCK_GUARD_RELATIVE_PATH = (
    Path("memory") / ".dreams" / "short-term-promotion.lock.guard"
)
SHORT_TERM_LOCK_STALE_MS = 60_000
SHORT_TERM_RECALL_MAX_ENTRIES = 512
SHORT_TERM_RECALL_MAX_SNIPPET_CHARS = 800
PHASE_SIGNAL_DECAY_MS = 30 * DAY_MS


@dataclass(frozen=True)
class ShortTermLockResult:
    """Outcome of :func:`acquire_short_term_promotion_lock`.

    ``reason`` is ``"locked"`` when another owner holds a fresh lock;
    ``stole_stale`` is True when a stale lock (older than 60 s) was replaced.
    """

    acquired: bool
    path: Path
    reason: str | None = None
    stole_stale: bool = False


@dataclass(frozen=True)
class _ShortTermLockSnapshot:
    mtime_ns: int
    payload: bytes
    owner_token: str | None


def recall_store_path(workspace_dir: Path) -> Path:
    """Absolute path of the short-term recall store under ``workspace_dir``."""
    return workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH


def recall_store_lock(workspace_dir: Path) -> threading.Lock:
    """The process-wide lock that every read-modify-write of the recall store holds.

    Recording, the promotion's ``promotedAt`` marks and repair each read and rewrite the whole
    file under it, so parallel ``memory_search`` recordings lose no update. Upstream holds its
    workspace lock for them (``withMemoryWorkspaceLock``, short-term-promotion-record.ts:193),
    which also spans processes; this one does not.
    """
    return workspace_file_lock(
        workspace_dir.resolve(), SHORT_TERM_STORE_RELATIVE_PATH.as_posix()
    )


def phase_signal_store_path(workspace_dir: Path) -> Path:
    """Absolute path of the dreaming phase-signal store under ``workspace_dir``."""
    return workspace_dir / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH


def promotion_lock_path(workspace_dir: Path) -> Path:
    """Absolute path of the short-term promotion lock under ``workspace_dir``."""
    return workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH


def acquire_short_term_promotion_lock(
    config: MemoryConfig, now_ms: int
) -> AbstractContextManager[ShortTermLockResult]:
    """Hold the workspace promotion lock for the ``with`` block (see :func:`_acquire_workspace_lock`)."""
    return _acquire_workspace_lock(Path(config.workspace_dir), now_ms)


@contextmanager
def _acquire_workspace_lock(workspace_dir: Path, now_ms: int) -> Iterator[ShortTermLockResult]:
    """Hold the workspace promotion lock for the duration of the ``with`` block.

    Port of upstream ``withShortTermLock``: the lock file carries ``pid``,
    ``createdAt`` and an owner token; a lock older than
    ``SHORT_TERM_LOCK_STALE_MS`` is stolen, a fresh one yields
    ``acquired=False``. Only the owner that created the file removes it.
    """
    lock_path = promotion_lock_path(workspace_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stole_stale = False
    owner_token = secrets.token_hex(16)
    acquired = False
    with _short_term_promotion_guard(lock_path):
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                stale_snapshot = _read_short_term_lock_snapshot(lock_path)
                if stale_snapshot is None:
                    continue
                if not _lock_is_stale(lock_path, now_ms):
                    break
                if not _unlink_matching_short_term_lock(lock_path, stale_snapshot):
                    break
                stole_stale = True
                continue
            acquired = True
            break

        if acquired:
            payload = {"pid": os.getpid(), "createdAt": iso_ms(now_ms), "ownerToken": owner_token}
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")

    if not acquired:
        yield ShortTermLockResult(acquired=False, path=lock_path, reason="locked")
        return

    try:
        yield ShortTermLockResult(acquired=True, path=lock_path, stole_stale=stole_stale)
    finally:
        _release_short_term_promotion_lock(lock_path, owner_token)


# Upstream's ``withMemoryWorkspaceLock`` is reentrant within one async call chain (an AsyncLocalStorage
# of owned workspaces): the DREAMS.md writers re-enter the lock the deep phase already holds.
_HELD_WORKSPACES: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar(
    f"{PACKAGE_NAME}_held_workspace_locks", default=frozenset()
)
MEMORY_WORKSPACE_LOCK_WAIT_TIMEOUT_MS = 10_000
MEMORY_WORKSPACE_LOCK_RETRY_DELAY_MS = 40


class MemoryWorkspaceLockHeldError(OSError):
    """``MEMORY_WORKSPACE_LOCK_HELD``: the workspace lock stayed held for the whole wait."""

    code = "MEMORY_WORKSPACE_LOCK_HELD"


def _workspace_key(workspace_dir: Path) -> str:
    return os.path.realpath(workspace_dir)


@contextmanager
def hold_workspace_lock_marker(workspace_dir: Path) -> Iterator[None]:
    """Record that this call chain owns the workspace lock (so :func:`memory_workspace_lock` re-enters)."""
    held = _HELD_WORKSPACES.get()
    token = _HELD_WORKSPACES.set(held | {_workspace_key(workspace_dir)})
    try:
        yield
    finally:
        _HELD_WORKSPACES.reset(token)


def workspace_lock_held(workspace_dir: Path) -> bool:
    """True inside a block that owns the workspace lock (the current call chain)."""
    return _workspace_key(workspace_dir) in _HELD_WORKSPACES.get()


@contextmanager
def memory_workspace_lock(
    workspace_dir: str | Path,
    *,
    now_ms: int | None = None,
    timeout_ms: float = MEMORY_WORKSPACE_LOCK_WAIT_TIMEOUT_MS,
    retry_delay_ms: float = MEMORY_WORKSPACE_LOCK_RETRY_DELAY_MS,
) -> Iterator[None]:
    """``withMemoryWorkspaceLock``: wait for the workspace promotion lock, re-entering one this chain holds.

    Waits ``retry_delay_ms`` between attempts for up to ``timeout_ms`` and then raises
    :class:`MemoryWorkspaceLockHeldError` (upstream: 10 s and 40 ms). The lock is the same file
    :func:`acquire_short_term_promotion_lock` takes.
    """
    workspace_dir = Path(workspace_dir)
    if workspace_lock_held(workspace_dir):
        yield
        return
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        stamp = int(time.time() * 1000) if now_ms is None else now_ms
        with _acquire_workspace_lock(workspace_dir, stamp) as lock:
            if lock.acquired:
                with hold_workspace_lock_marker(workspace_dir):
                    yield
                return
        if time.monotonic() >= deadline:
            raise MemoryWorkspaceLockHeldError(
                f"Timed out waiting for memory workspace lock at {lock.path}"
            )
        time.sleep(retry_delay_ms / 1000)


def empty_recall_store(now_ms: int) -> dict[str, Any]:
    return {"version": 1, "updatedAt": iso_ms(now_ms), "entries": {}}


def read_recall_store(path: Path, now_ms: int) -> dict[str, Any]:
    """Read the recall store; a missing or unparsable file reads as empty."""
    if not path.exists():
        return empty_recall_store(now_ms)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_recall_store(now_ms)
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return {
        "version": 1,
        "updatedAt": str(raw.get("updatedAt") or iso_ms(now_ms))
        if isinstance(raw, dict)
        else iso_ms(now_ms),
        "entries": entries if isinstance(entries, dict) else {},
    }


def write_recall_store(path: Path, store: dict[str, Any]) -> None:
    """Write the recall store after applying the snippet cap and entry retention."""
    _enforce_short_term_recall_snippet_cap(store)
    _enforce_short_term_recall_store_retention(store)
    write_json_atomic(path, store)


def read_phase_signal_store(path: Path, now_ms: int) -> dict[str, Any]:
    """Read the phase-signal store, dropping entries idle for more than 30 days."""
    if not path.exists():
        return {"version": 1, "updatedAt": iso_ms(now_ms), "entries": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"version": 1, "updatedAt": iso_ms(now_ms), "entries": {}}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        entries = {}
    active_entries = {}
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if _phase_signal_is_expired(entry, now_ms):
            continue
        active_entries[key] = normalize_phase_signal_entry(key, entry)
    return {
        "version": 1,
        "updatedAt": str(raw.get("updatedAt") or iso_ms(now_ms))
        if isinstance(raw, dict)
        else iso_ms(now_ms),
        "entries": active_entries,
    }


def normalize_phase_signal_entry(key: str, entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}
    return {
        "key": key,
        "lightHits": to_int(entry.get("lightHits"), 0),
        "remHits": to_int(entry.get("remHits"), 0),
        "lastLightAt": _optional_str(entry.get("lastLightAt")),
        "lastRemAt": _optional_str(entry.get("lastRemAt")),
        "updatedAt": _optional_str(entry.get("updatedAt")),
    }


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def truncate_short_term_snippet(snippet: str) -> str:
    """Cap a stored snippet at ``SHORT_TERM_RECALL_MAX_SNIPPET_CHARS`` (trailing space trimmed).

    Upstream ``truncateShortTermSnippet`` counts UTF-16 code units, cuts with
    ``truncateUtf16Safe`` (a cut inside a surrogate pair drops the pair, v2026.9.6) and trims
    with ``trimEnd``.
    """
    if utf16_len(snippet) <= SHORT_TERM_RECALL_MAX_SNIPPET_CHARS:
        return snippet
    return js_trim_end(truncate_utf16_safe(snippet, SHORT_TERM_RECALL_MAX_SNIPPET_CHARS))


def is_valid_short_term_recall_entry(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and bool(entry.get("key"))
        and bool(entry.get("path"))
        and bool(entry.get("snippet"))
    )


def lock_is_stale(lock_path: Path, now_ms: int) -> bool:
    """True when the lock's ``createdAt`` (or mtime) is older than the stale window."""
    return _lock_is_stale(lock_path, now_ms)


def remove_stale_lock(lock_path: Path, now_ms: int) -> bool:
    """Remove ``lock_path`` if it is still stale under the guard; True when removed."""
    with _short_term_promotion_guard(lock_path):
        snapshot = _read_short_term_lock_snapshot(lock_path)
        if snapshot is not None and _lock_is_stale(lock_path, now_ms):
            return _unlink_matching_short_term_lock(lock_path, snapshot)
    return False


def _phase_signal_is_expired(entry: dict[str, Any], now_ms: int) -> bool:
    timestamps = [
        parse_ms(value, -1)
        for value in (
            entry.get("updatedAt"),
            entry.get("lastLightAt"),
            entry.get("lastRemAt"),
        )
        if isinstance(value, str)
    ]
    latest = max(timestamps, default=-1)
    return latest >= 0 and now_ms - latest > PHASE_SIGNAL_DECAY_MS


def _lock_is_stale(lock_path: Path, now_ms: int) -> bool:
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        raw = None
    if isinstance(raw, dict):
        created_at = raw.get("createdAt")
        if isinstance(created_at, str):
            created_at_ms = parse_ms(created_at, -1)
            if created_at_ms >= 0:
                return now_ms - created_at_ms > SHORT_TERM_LOCK_STALE_MS
    try:
        lock_mtime_ms = int(lock_path.stat().st_mtime * 1000)
    except FileNotFoundError:
        return False
    return now_ms - lock_mtime_ms > SHORT_TERM_LOCK_STALE_MS


def _read_short_term_lock_snapshot(lock_path: Path) -> _ShortTermLockSnapshot | None:
    try:
        stat = lock_path.stat()
        payload = lock_path.read_bytes()
    except (FileNotFoundError, OSError):
        return None
    owner_token = None
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raw = None
    if isinstance(raw, dict):
        raw_owner_token = raw.get("ownerToken")
        if isinstance(raw_owner_token, str):
            owner_token = raw_owner_token
    return _ShortTermLockSnapshot(
        mtime_ns=stat.st_mtime_ns,
        payload=payload,
        owner_token=owner_token,
    )


@contextmanager
def _short_term_promotion_guard(lock_path: Path) -> Iterator[None]:
    """Serialise lock steal/release: ``flock`` on POSIX, ``msvcrt.locking`` on Windows.

    Imported lazily so ``import memory_core`` works where ``fcntl`` is missing; with
    neither module the ``O_EXCL`` lock file alone guards the promotion.
    """
    guard_path = lock_path.with_name(_SHORT_TERM_LOCK_GUARD_RELATIVE_PATH.name)
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    with guard_path.open("a+b") as handle:
        release = _lock_guard_file(handle)
        try:
            yield
        finally:
            release()


def _lock_guard_file(handle: Any) -> Callable[[], None]:
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    try:
        import msvcrt  # type: ignore[import-not-found]
    except ImportError:
        return lambda: None
    handle.seek(0)
    while True:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            break
        except OSError:  # LK_LOCK gives up after ~10 s; keep waiting like flock.
            continue

    def release() -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    return release


def _unlink_matching_short_term_lock(lock_path: Path, snapshot: _ShortTermLockSnapshot) -> bool:
    current = _read_short_term_lock_snapshot(lock_path)
    if current is None:
        return True
    if current != snapshot:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    return True


def _release_short_term_promotion_lock(lock_path: Path, owner_token: str) -> None:
    with _short_term_promotion_guard(lock_path):
        try:
            raw = json.loads(lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
            return
        if not isinstance(raw, dict) or raw.get("ownerToken") != owner_token:
            return
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _entry_total_signal_count(entry: dict[str, Any]) -> int:
    return (
        max(0, to_int(entry.get("recallCount"), 0))
        + max(0, to_int(entry.get("dailyCount"), 0))
        + max(0, to_int(entry.get("groundedCount"), 0))
    )


def _store_timestamp_ms(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return float("-inf")
    parsed = parse_ms(value, -1)
    return float(parsed) if parsed >= 0 else float("-inf")


def _retention_sort_key(item: tuple[str, dict[str, Any]]) -> tuple[Any, ...]:
    key, entry = item
    return (
        -_store_timestamp_ms(entry.get("lastRecalledAt")),
        -_entry_total_signal_count(entry),
        -float(entry.get("totalScore") or 0),
        -float(entry.get("maxScore") or 0),
        -_store_timestamp_ms(entry.get("promotedAt")),
        key,
    )


def _enforce_short_term_recall_store_retention(store: dict[str, Any]) -> int:
    entries = store.get("entries")
    if not isinstance(entries, dict) or len(entries) <= SHORT_TERM_RECALL_MAX_ENTRIES:
        return 0
    valid = [(key, entry) for key, entry in entries.items() if isinstance(entry, dict)]
    retained = sorted(valid, key=_retention_sort_key)[:SHORT_TERM_RECALL_MAX_ENTRIES]
    store["entries"] = dict(sorted(retained, key=lambda item: item[0]))
    return len(entries) - len(store["entries"])


def _enforce_short_term_recall_snippet_cap(store: dict[str, Any]) -> None:
    entries = store.get("entries")
    if not isinstance(entries, dict):
        return
    for entry in entries.values():
        if isinstance(entry, dict) and isinstance(entry.get("snippet"), str):
            entry["snippet"] = truncate_short_term_snippet(entry["snippet"])
