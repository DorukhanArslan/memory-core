"""Lab event bus and workspace file snapshots (demo-only glue, no memory logic).

Two pieces the Lab UI builds on:

- :class:`LabEventBus`: a ring of the last 1,000 :data:`LabEvent` dicts with
  increasing ids. ``GET /api/lab/events`` streams them as Server-Sent Events;
  a reconnecting client sends ``Last-Event-ID`` and gets every buffered event
  after it (a ``lab.resync`` event says when the gap is older than the ring).
- :class:`WorkspaceSnapshots`: content snapshots of the Lab workspace (path ->
  sha256 plus text for files up to 2 MiB) taken before and after every
  mutating operation. Each difference becomes a ``file.changed`` event with the
  operation's ``source`` (curation, flush, lifecycle, editor, ...) so writes by
  any package module show up, including BOOTSTRAP.md deleted by
  ``initialize_agent_workspace``. Named baselines (``turn:<id>``, ``session``,
  ``reset``, ``mark:<id>``) back the Diff tab.

The Lab is single-user and in-process: nothing here is persisted.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import stat
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_core.project_name import STATE_DIRNAME

EVENT_RING_CAPACITY = 1_000
SSE_HEARTBEAT_SECONDS = 15.0
SNAPSHOT_MAX_FILE_BYTES = 2 * 1024 * 1024
BASELINE_TURN_HISTORY = 50

# Category ids of the Zaman tab (the frontend translates them).
_CATEGORY_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("chat.", "sohbet"),
    ("prompt.", "sohbet"),
    ("session.", "sohbet"),
    ("tool.", "sohbet"),
    ("index.", "bellek"),
    ("recall.", "bellek"),
    ("search.", "bellek"),
    ("embedding.", "bellek"),
    ("curation.", "bellek"),
    ("session_memory.", "bellek"),
    ("startup_context.", "bellek"),
    ("file.", "dosya"),
    ("workspace.", "dosya"),
    ("flush.", "flush"),
    ("bootstrap.", "bootstrap"),
    ("heartbeat.", "heartbeat"),
    ("clock.", "heartbeat"),
    ("promotion.", "konsolidasyon"),
    ("dreaming.", "konsolidasyon"),
    ("audit.", "konsolidasyon"),
    ("repair.", "konsolidasyon"),
    ("live.", "canlı"),
    ("settings.", "ayar"),
    ("provider.", "ayar"),
    ("error", "hata"),
)


def event_category(event_type: str) -> str:
    for prefix, category in _CATEGORY_BY_PREFIX:
        if event_type == prefix.rstrip(".") or event_type.startswith(prefix):
            return category
    return "lab"


class LabEventBus:
    """Thread-safe ring buffer of Lab events with monotonically increasing ids."""

    def __init__(self, capacity: int = EVENT_RING_CAPACITY) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._next_id = 1
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._next_id - 1

    def emit(
        self,
        event_type: str,
        *,
        summary: str = "",
        data: Any = None,
        turn_id: int | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            event: dict[str, Any] = {
                "id": self._next_id,
                "ts": int(time.time() * 1000),
                "type": event_type,
                "category": category or event_category(event_type),
                "summary": summary or event_type,
                "data": data if data is not None else {},
            }
            if turn_id is not None:
                event["turnId"] = turn_id
            self._next_id += 1
            self._events.append(event)
            listeners = list(self._listeners)
        for listener in listeners:
            listener(event)
        return event

    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def since(self, last_id: int) -> tuple[list[dict[str, Any]], bool]:
        """Buffered events after ``last_id`` and whether older ones were dropped."""
        with self._lock:
            events = [event for event in self._events if event["id"] > last_id]
            oldest = self._events[0]["id"] if self._events else self._next_id
        gap = last_id > 0 and last_id + 1 < oldest
        return events, gap

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def sse_frame(data: dict[str, Any], *, event: str | None = None, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def parse_last_event_id(value: str | None) -> int:
    if value is None:
        return 0
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return 0
    return max(0, parsed)


async def stream_lab_events(
    bus: LabEventBus,
    *,
    last_event_id: int,
    is_disconnected: Callable[[], Any] | None = None,
    once: bool = False,
    poll_seconds: float = 0.25,
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """SSE frames for ``GET /api/lab/events``.

    Frames carry no ``event:`` line: every LabEvent arrives as a default
    ``message`` whose JSON has the ``type``, so clients need no per-type
    listeners. ``once`` replays the buffered events after ``last_event_id``
    and ends (tests and debugging); otherwise the stream stays open with a
    comment heartbeat every 15 s.
    """
    events, gap = bus.since(last_event_id)
    if gap:
        yield sse_frame(
            {
                "type": "lab.resync",
                "category": "lab",
                "summary": "events after Last-Event-ID were dropped from the ring; refetch state",
                "data": {"lastEventId": last_event_id},
                "ts": int(time.time() * 1000),
            }
        )
    last_sent = last_event_id
    for event in events:
        yield sse_frame(event, event_id=event["id"])
        last_sent = event["id"]
    if once:
        return
    idle = 0.0
    while True:
        if is_disconnected is not None:
            disconnected = is_disconnected()
            if asyncio.iscoroutine(disconnected):
                disconnected = await disconnected
            if disconnected:
                return
        pending, _ = bus.since(last_sent)
        if pending:
            for event in pending:
                yield sse_frame(event, event_id=event["id"])
                last_sent = event["id"]
            idle = 0.0
        else:
            await asyncio.sleep(poll_seconds)
            idle += poll_seconds
            if idle >= heartbeat_seconds:
                yield ": ping\n\n"
                idle = 0.0


# --- workspace snapshots ------------------------------------------------------------------


@dataclass(frozen=True)
class FileSnapshot:
    sha256: str
    size: int
    mtime_ms: int
    text: str | None  # None for binary or oversized files


Snapshot = dict[str, FileSnapshot]


def _is_excluded(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if parts[0] in {STATE_DIRNAME, ".git", ".openclaw"}:
        return True
    name = parts[-1]
    return ".sqlite" in name or name.endswith(".lock") or name.endswith(".tmp")


def take_snapshot(root: Path) -> Snapshot:
    """Regular files under ``root`` (no symlinks followed), minus index/state files."""
    snapshot: Snapshot = {}
    if not root.is_dir():
        return snapshot
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else Path(rel_dir).as_posix()
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not _is_excluded(f"{rel_dir}/{name}".lstrip("/"))
            and not os.path.islink(os.path.join(dirpath, name))
        )
        for name in sorted(filenames):
            rel_path = f"{rel_dir}/{name}".lstrip("/")
            if _is_excluded(rel_path):
                continue
            full = os.path.join(dirpath, name)
            try:
                info = os.lstat(full)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            try:
                raw = Path(full).read_bytes() if info.st_size <= SNAPSHOT_MAX_FILE_BYTES else None
            except OSError:
                continue
            if raw is None:
                digest = f"size:{info.st_size}:mtime:{info.st_mtime_ns}"
                snapshot[rel_path] = FileSnapshot(digest, info.st_size, info.st_mtime_ns // 1_000_000, None)
                continue
            try:
                text: str | None = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            snapshot[rel_path] = FileSnapshot(
                hashlib.sha256(raw).hexdigest(), info.st_size, info.st_mtime_ns // 1_000_000, text
            )
    return snapshot


def unified_diff(before: str | None, after: str | None, path: str, *, context: int = 3) -> str:
    return "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=f"a/{path}" if before is not None else "/dev/null",
            tofile=f"b/{path}" if after is not None else "/dev/null",
            n=context,
        )
    )


def _count_lines(diff: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old is not None and new is not None and old.sha256 == new.sha256:
            continue
        status = "added" if old is None else "deleted" if new is None else "modified"
        if (old is not None and old.text is None) or (new is not None and new.text is None):
            diff = ""
            binary = True
        else:
            diff = unified_diff(
                old.text if old is not None else None, new.text if new is not None else None, path
            )
            binary = False
        added, removed = _count_lines(diff)
        changes.append(
            {
                "path": path,
                "status": status,
                "diff": diff,
                "added": added,
                "removed": removed,
                "binary": binary,
                # Stores under dot-directories (memory/.dreams/) are demo-only state.
                "hidden": any(part.startswith(".") for part in path.split("/")),
                "sha256Before": old.sha256 if old is not None else None,
                "sha256After": new.sha256 if new is not None else None,
            }
        )
    return changes


@dataclass
class ChangeRecord:
    path: str
    status: str
    source: str
    turn_id: int | None
    ts: int
    event_id: int | None


@dataclass
class WorkspaceSnapshots:
    """Before/after snapshots, named baselines and a change log for one workspace root."""

    root: Path
    bus: LabEventBus
    baselines: dict[str, Snapshot] = field(default_factory=dict)
    baseline_times: dict[str, int] = field(default_factory=dict)
    changes: list[ChangeRecord] = field(default_factory=list)
    _marks: int = 0
    _turn_baselines: deque[str] = field(default_factory=deque)

    def take(self) -> Snapshot:
        return take_snapshot(self.root)

    def record(
        self,
        before: Snapshot,
        after: Snapshot,
        *,
        source: str,
        turn_id: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Diff two snapshots, emit one ``file.changed`` per difference, log the sources."""
        changes = diff_snapshots(before, after)
        for change in changes:
            event = self.bus.emit(
                "file.changed",
                summary=f"{change['path']} {change['status']} ({source})",
                data={
                    "path": change["path"],
                    "status": change["status"],
                    "source": source,
                    "turnId": turn_id,
                    "added": change["added"],
                    "removed": change["removed"],
                    **(extra or {}),
                },
                turn_id=turn_id,
            )
            change["source"] = source
            self.changes.append(
                ChangeRecord(
                    change["path"], change["status"], source, turn_id, event["ts"], event["id"]
                )
            )
        if len(self.changes) > 5_000:
            del self.changes[: len(self.changes) - 5_000]
        return changes

    def set_baseline(self, name: str, snapshot: Snapshot | None = None) -> None:
        self.baselines[name] = snapshot if snapshot is not None else self.take()
        self.baseline_times[name] = int(time.time() * 1000)
        if name.startswith("turn:"):
            self._turn_baselines.append(name)
            while len(self._turn_baselines) > BASELINE_TURN_HISTORY:
                dropped = self._turn_baselines.popleft()
                self.baselines.pop(dropped, None)
                self.baseline_times.pop(dropped, None)

    def mark(self) -> str:
        self._marks += 1
        mark_id = f"m{self._marks}"
        self.set_baseline(f"mark:{mark_id}")
        return mark_id

    def baseline(self, name: str) -> Snapshot | None:
        return self.baselines.get(name)

    def sources_since(self, path: str, since_ts: int | None) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        for record in self.changes:
            if record.path != path or (since_ts is not None and record.ts < since_ts):
                continue
            seen.append(
                {
                    "source": record.source,
                    "turnId": record.turn_id,
                    "ts": record.ts,
                    "eventId": record.event_id,
                    "status": record.status,
                }
            )
        return seen

    def last_turn_changed(self, path: str) -> int | None:
        for record in reversed(self.changes):
            if record.path == path and record.turn_id is not None:
                return record.turn_id
        return None

    def reset(self) -> None:
        self.baselines.clear()
        self.baseline_times.clear()
        self.changes.clear()
        self._turn_baselines.clear()


def snapshot_texts(snapshot: Snapshot, paths: Iterable[str]) -> dict[str, str | None]:
    return {path: snapshot[path].text if path in snapshot else None for path in paths}
