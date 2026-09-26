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

import fcntl
import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_trim_end, utf16_len, utf16_slice
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import (
    DAY_MS,
    iso_ms,
    parse_ms,
    to_int,
    write_json_atomic,
)

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


def phase_signal_store_path(workspace_dir: Path) -> Path:
    """Absolute path of the dreaming phase-signal store under ``workspace_dir``."""
    return workspace_dir / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH


def promotion_lock_path(workspace_dir: Path) -> Path:
    """Absolute path of the short-term promotion lock under ``workspace_dir``."""
    return workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH


@contextmanager
def acquire_short_term_promotion_lock(
    config: MemoryConfig, now_ms: int
) -> Iterator[ShortTermLockResult]:
    """Hold the workspace promotion lock for the duration of the ``with`` block.

    Port of upstream ``withShortTermLock``: the lock file carries ``pid``,
    ``createdAt`` and an owner token; a lock older than
    ``SHORT_TERM_LOCK_STALE_MS`` is stolen, a fresh one yields
    ``acquired=False``. Only the owner that created the file removes it.
    """
    lock_path = promotion_lock_path(config.workspace_dir)
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

    Upstream ``truncateShortTermSnippet`` counts and slices UTF-16 code units and
    trims with ``trimEnd``; a cut inside a surrogate pair keeps the lone surrogate,
    which the store's JSON write escapes like ``JSON.stringify``.
    """
    if utf16_len(snippet) <= SHORT_TERM_RECALL_MAX_SNIPPET_CHARS:
        return snippet
    return js_trim_end(utf16_slice(snippet, 0, SHORT_TERM_RECALL_MAX_SNIPPET_CHARS))


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
    guard_path = lock_path.with_name(_SHORT_TERM_LOCK_GUARD_RELATIVE_PATH.name)
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    with guard_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
