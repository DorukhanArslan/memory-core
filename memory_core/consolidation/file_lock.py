"""The sidecar file lock of the deep promotion phase (the second of upstream's two locks).

Port of the ``withFileLock`` call in ``applyShortTermPromotions``
(extensions/memory-core/src/short-term-promotion-apply.ts, OpenClaw v2026.9.6) and of the
sidecar lock contract it uses (``src/plugin-sdk/file-lock.ts`` over ``@openclaw/fs-safe``):

- the lock target is ``<state dir>/locks/memory-promotion-<sha256 of the canonical workspace
  path>`` (``resolveMemoryPromotionLockTarget``; the directory is created with mode 0700, the
  workspace path is ``realpath``-ed, falling back to the absolute path);
- the held lock is the sidecar ``<target>.lock``, created exclusively with mode 0600 and holding
  ``JSON.stringify({pid, createdAt, starttime?}, null, 2)`` plus a newline, the ownership token
  (eight tabs and 128 tab/space bits) and a newline;
- contention retries with the policy of ``MEMORY_WRITE_LOCK_OPTIONS`` (100 retries, factor 1.2,
  25 ms to 250 ms) and then fails with ``file lock timeout for <target>``;
- recovery is ``fail-closed``: a sidecar whose owner is provably gone (dead PID, or a PID whose
  process start time changed) is NOT removed, acquisition fails with
  ``file lock stale for <target>``; a live or unreadable owner is waited for.

Upstream's other lock, the workspace lock (``withMemoryWorkspaceLock``), is
:func:`memory_core.consolidation.store.memory_workspace_lock`. The deep phase takes this one
first and the workspace lock inside it.

The state directory is host-supplied (upstream: ``resolveStateDir()``); memory-core has no
state directory of its own for this.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

FILE_LOCK_TIMEOUT_ERROR_CODE = "file_lock_timeout"
FILE_LOCK_STALE_ERROR_CODE = "file_lock_stale"
_TOKEN_PREFIX = "\t" * 8
_TOKEN_BITS = 128


class FileLockError(OSError):
    """A file lock could not be acquired; ``code`` is upstream's stable discriminator."""

    code = ""

    def __init__(self, message: str, lock_path: Path) -> None:
        super().__init__(message)
        self.lock_path = lock_path


class FileLockTimeoutError(FileLockError):
    code = FILE_LOCK_TIMEOUT_ERROR_CODE


class FileLockStaleError(FileLockError):
    code = FILE_LOCK_STALE_ERROR_CODE


@dataclass(frozen=True)
class FileLockOptions:
    """``FileLockOptions`` (retry policy, stale window, stale recovery)."""

    retries: int = 100
    factor: float = 1.2
    min_timeout_ms: float = 25
    max_timeout_ms: float = 250
    stale_ms: int = 120_000
    stale_recovery: Literal["fail-closed", "remove-if-unchanged"] = "fail-closed"


# ``MEMORY_WRITE_LOCK_OPTIONS`` of short-term-promotion-apply.ts.
MEMORY_WRITE_LOCK_OPTIONS = FileLockOptions()


def process_start_time(pid: int) -> int | None:
    """``getFileLockProcessStartTime``: field 22 of ``/proc/<pid>/stat`` (Linux), else ``None``."""
    if pid <= 0 or not sys.platform.startswith("linux"):
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    end = stat.rfind(")")
    if end < 0:
        return None
    fields = stat[end + 1 :].split()
    try:
        value = int(fields[19])
    except (IndexError, ValueError):
        return None
    return value if value >= 0 else None


def _is_zombie(pid: int) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return False
    state = re.search(r"^State:\s+(\S)", status, re.M)
    return bool(state and state.group(1) == "Z" and re.search(r"^Threads:[ \t]+1[ \t]*$", status, re.M))


def pid_definitely_dead(pid: int) -> bool:
    """``isPidDefinitelyDead``: invalid, missing (``ESRCH``) or a single-threaded zombie."""
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return _is_zombie(pid)


@dataclass(frozen=True)
class StaleLockOwner:
    """``StaleLockOwner``: the bounded facts of one stale decision."""

    reason: Literal["owner-starttime-changed", "owner-process-exited"]
    pid: int
    recorded_starttime: int | None
    observed_starttime: int | None

    def detail(self) -> str:
        recorded = "unknown" if self.recorded_starttime is None else self.recorded_starttime
        observed = "unknown" if self.observed_starttime is None else self.observed_starttime
        return f" [{self.reason} pid={self.pid} recorded-start={recorded} observed-start={observed}]"


def inspect_stale_lock_owner(payload: dict[str, Any] | None) -> StaleLockOwner | None:
    """``inspectStaleLockOwner``: why the owner is provably gone, else ``None``.

    An ownerless payload is never stale (it can belong to a suspended writer); age alone proves
    nothing. A live PID with a different recorded start time is PID reuse.
    """
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    recorded = payload.get("starttime")
    if not isinstance(recorded, int) or isinstance(recorded, bool) or recorded < 0:
        recorded = None
    observed = process_start_time(pid) if recorded is not None else None
    if observed is not None and observed != recorded:
        return StaleLockOwner("owner-starttime-changed", pid, recorded, observed)
    if pid_definitely_dead(pid):
        return StaleLockOwner("owner-process-exited", pid, recorded, observed)
    return None


def _should_remove_dead_owner_or_expired(payload: dict[str, Any] | None, stale_ms: int) -> bool:
    if isinstance(payload, dict):
        pid = payload.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            return inspect_stale_lock_owner(payload) is not None
        created = payload.get("createdAt")
        if isinstance(created, str):
            from memory_core.consolidation._util import parse_ms

            created_ms = parse_ms(created, -1)
            return created_ms < 0 or time.time() * 1000 - created_ms > stale_ms
    return False


def retry_delay_ms(options: FileLockOptions, attempt: int) -> int | None:
    """``sidecarLockRetryDelay``: the wait before retry ``attempt`` (0-based), ``None`` when spent."""
    if attempt >= options.retries:
        return None
    scaled = 0 if options.min_timeout_ms == 0 else options.min_timeout_ms * options.factor**attempt
    base = min(options.max_timeout_ms, max(options.min_timeout_ms, scaled))
    return int(math.floor(min(options.max_timeout_ms, base) + 0.5))


def _ownership_token() -> str:
    token = _TOKEN_PREFIX
    bits = secrets.randbits(_TOKEN_BITS)
    for index in range(_TOKEN_BITS - 1, -1, -1):
        token += "\t" if bits >> index & 1 else " "
    return token


_TOKEN_TAIL_RE = re.compile(r"\n" + _TOKEN_PREFIX + r"[ \t]{" + str(_TOKEN_BITS) + r"}\n$")


def _parse_payload(raw: str) -> dict[str, Any] | None:
    tail = _TOKEN_TAIL_RE.search(raw)
    try:
        parsed = json.loads(raw[: tail.start()] if tail else raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _read_raw(lock_path: Path) -> str | None:
    try:
        return lock_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def lock_payload_raw() -> str:
    """The sidecar's content for the current process (what ``serializeSidecarLockPayload`` writes)."""
    from memory_core.consolidation._util import iso_ms

    payload: dict[str, Any] = {"pid": os.getpid(), "createdAt": iso_ms(int(time.time() * 1000))}
    starttime = process_start_time(os.getpid())
    if starttime is not None:
        payload["starttime"] = starttime
    return f"{json.dumps(payload, indent=2)}\n{_ownership_token()}\n"


def lock_sidecar_path(target: str | Path) -> Path:
    return Path(f"{target}.lock")


@contextmanager
def with_file_lock(
    target: str | Path,
    options: FileLockOptions = MEMORY_WRITE_LOCK_OPTIONS,
    *,
    sleep: Callable[[float], None] = time.sleep,
    observer: Callable[[str, Path], None] | None = None,
) -> Iterator[Path]:
    """``withFileLock``: hold the sidecar of ``target`` for the block; yields the sidecar path.

    ``observer`` (host or test hook) is told ``"acquired"`` and ``"released"``.
    """
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = lock_sidecar_path(target_path)
    raw = lock_payload_raw()
    attempt = 0
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            holder = _read_raw(lock_path)
            payload = _parse_payload(holder) if holder is not None else None
            if options.stale_recovery == "fail-closed":
                stale_owner = inspect_stale_lock_owner(payload)
                if stale_owner is not None:
                    raise FileLockStaleError(
                        f"file lock stale for {target_path}{stale_owner.detail()}", lock_path
                    ) from None
            elif _should_remove_dead_owner_or_expired(payload, options.stale_ms) and holder is not None:
                if _read_raw(lock_path) == holder:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
            delay = retry_delay_ms(options, attempt)
            if delay is None:
                raise FileLockTimeoutError(f"file lock timeout for {target_path}", lock_path) from None
            sleep(delay / 1000)
            attempt += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(raw)
        break
    if observer is not None:
        observer("acquired", lock_path)
    try:
        yield lock_path
    finally:
        if _read_raw(lock_path) == raw:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
        if observer is not None:
            observer("released", lock_path)


def resolve_memory_promotion_lock_target(state_dir: str | Path, workspace_dir: str | Path) -> Path:
    """``resolveMemoryPromotionLockTarget``: ``<state dir>/locks/memory-promotion-<sha256>``."""
    lock_dir = Path(state_dir) / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        canonical = os.path.realpath(workspace_dir, strict=True)
    except OSError:
        canonical = os.path.abspath(workspace_dir)
    digest = hashlib.sha256(canonical.encode("utf-8", "surrogatepass")).hexdigest()
    return lock_dir / f"memory-promotion-{digest}"
