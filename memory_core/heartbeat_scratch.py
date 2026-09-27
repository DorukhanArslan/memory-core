"""Heartbeat monitor scratch: the per-agent checklist that replaced HEARTBEAT.md.

v2026.9.6 keeps an agent's heartbeat instructions as the private scratch of its system-owned
heartbeat automation job, in the shared state database (3e2b3ea4d5e, #112967; the runtime
fallback to HEARTBEAT.md went in 07e3855b465, #113131). This module ports the observable part
of that storage contract:

- ``src/cron/scratch-contract.ts``: :data:`CRON_JOB_SCRATCH_MAX_BYTES` (256 KiB of UTF-8) and
  :func:`assert_heartbeat_scratch_content` (``assertCronJobScratchContent``);
- ``src/cron/scratch-store.ts``: the value shapes (``CronJobScratchState``: a revision plus
  optional content; an unset leaves a revision tombstone so a stale compare-and-swap writer
  cannot resurrect old content), the write rule of ``writeCronJobScratch`` (content check,
  compare-and-swap on ``expected_revision``, no-op unset of an absent row, full-row replace
  that keeps a trimmed ``source_sha256`` only with content) as the pure
  :func:`apply_heartbeat_scratch_write`, the guarded delete of ``deleteCronJobScratch``
  (:func:`apply_heartbeat_scratch_delete`) and ``hashCronScratchSource``.

The host owns storage. :class:`HeartbeatScratchStore` is the small interface memory-core's
heartbeat helpers read and write through; :class:`memory_core.automation.FileAutomationStore` is
the default file-backed implementation under ``<root>/.memory-core/``. Deviation (documented in
docs/parity_matrix.md): upstream keys scratch by the monitor job's id and refuses a write once
that job is deleted (``revision-conflict``); memory-core keys it by agent id and has no job rows for
monitors, so a host that removes an agent's heartbeat calls ``delete_scratch`` itself.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from memory_core._heartbeat_constants import CRON_JOB_SCRATCH_MAX_BYTES, CRON_JOB_SCRATCH_TOO_LARGE
from memory_core.bootstrap._js import js_trim

__all__ = [
    "CRON_JOB_SCRATCH_MAX_BYTES",
    "HeartbeatScratch",
    "HeartbeatScratchState",
    "HeartbeatScratchStore",
    "HeartbeatScratchTooLargeError",
    "HeartbeatScratchWrite",
    "apply_heartbeat_scratch_delete",
    "apply_heartbeat_scratch_write",
    "assert_heartbeat_scratch_content",
    "hash_heartbeat_scratch_source",
]

REVISION_CONFLICT = "revision-conflict"


class HeartbeatScratchTooLargeError(ValueError):
    """Scratch content over :data:`CRON_JOB_SCRATCH_MAX_BYTES` (upstream's thrown ``Error``)."""


def _utf8_length(content: str) -> int:
    # Buffer.byteLength(content, "utf8"): a lone surrogate encodes as U+FFFD (3 bytes), which
    # is also the length of its surrogatepass encoding.
    return len(content.encode("utf-8", errors="surrogatepass"))


def assert_heartbeat_scratch_content(content: str) -> None:
    """Port of ``assertCronJobScratchContent``: refuse more than 256 KiB of UTF-8."""
    size_bytes = _utf8_length(content)
    if size_bytes > CRON_JOB_SCRATCH_MAX_BYTES:
        raise HeartbeatScratchTooLargeError(
            CRON_JOB_SCRATCH_TOO_LARGE.format(
                max_bytes=CRON_JOB_SCRATCH_MAX_BYTES, size_bytes=size_bytes
            )
        )


def hash_heartbeat_scratch_source(content: str) -> str:
    """Port of ``hashCronScratchSource``: SHA-256 hex of the UTF-8 text."""
    return hashlib.sha256(content.encode("utf-8", errors="surrogatepass")).hexdigest()


@dataclass(frozen=True)
class HeartbeatScratch:
    """Present scratch content (upstream ``CronJobScratch``)."""

    content: str
    revision: int
    updated_at_ms: int
    source_sha256: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"content": self.content, "revision": self.revision}
        if self.source_sha256:
            out["sourceSha256"] = self.source_sha256
        out["updatedAtMs"] = self.updated_at_ms
        return out


@dataclass(frozen=True)
class HeartbeatScratchState:
    """``CronJobScratchState``: the persisted revision plus content when it is set.

    ``current_revision == 0`` with no ``scratch`` is "no scratch" (the heartbeat runs the
    generic prompt); ``current_revision > 0`` with no ``scratch`` is an explicit unset.
    """

    current_revision: int = 0
    scratch: HeartbeatScratch | None = None

    @property
    def content(self) -> str | None:
        return self.scratch.content if self.scratch is not None else None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"currentRevision": self.current_revision}
        if self.scratch is not None:
            out["scratch"] = self.scratch.to_json()
        return out

    @classmethod
    def from_json(cls, data: Any) -> HeartbeatScratchState:
        if not isinstance(data, dict):
            return cls()
        revision = data.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            return cls()
        content = data.get("content")
        if not isinstance(content, str):
            return cls(current_revision=revision)
        sha = data.get("sourceSha256")
        updated = data.get("updatedAtMs")
        return cls(
            current_revision=revision,
            scratch=HeartbeatScratch(
                content=content,
                revision=revision,
                updated_at_ms=updated if isinstance(updated, int) else 0,
                source_sha256=sha if isinstance(sha, str) and sha else None,
            ),
        )

    def to_row(self) -> dict[str, Any] | None:
        """The stored row (``None``: no row), the inverse of :meth:`from_json`."""
        if self.current_revision == 0 and self.scratch is None:
            return None
        if self.scratch is None:
            return {"content": None, "revision": self.current_revision}
        return self.scratch.to_json()


@dataclass(frozen=True)
class HeartbeatScratchWrite:
    """``CronJobScratchWriteResult``: ``ok`` with the new revision, or a revision conflict."""

    ok: bool
    current_revision: int
    scratch: HeartbeatScratch | None = None
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if not self.ok:
            out["reason"] = self.reason
        out["currentRevision"] = self.current_revision
        if self.scratch is not None:
            out["scratch"] = self.scratch.to_json()
        return out


def apply_heartbeat_scratch_write(
    state: HeartbeatScratchState,
    content: str | None,
    *,
    now_ms: int,
    expected_revision: int | None = None,
    source_sha256: str | None = None,
) -> tuple[HeartbeatScratchState, HeartbeatScratchWrite]:
    """The write rule of ``writeCronJobScratch`` on one agent's current state.

    ``content=None`` unsets. Content over 256 KiB raises :class:`HeartbeatScratchTooLargeError`
    before anything else. A mismatching ``expected_revision`` is a ``revision-conflict``. An
    unset of an absent row is a no-op; every other write bumps the revision and replaces the
    whole row, so a write without ``source_sha256`` clears a stale migration hash and an unset
    leaves a tombstone. Returns the new state and the result.
    """
    if content is not None:
        assert_heartbeat_scratch_content(content)
    current_revision = state.current_revision
    if expected_revision is not None and expected_revision != current_revision:
        return state, HeartbeatScratchWrite(
            ok=False, current_revision=current_revision, reason=REVISION_CONFLICT
        )
    if content is None and current_revision == 0:
        return state, HeartbeatScratchWrite(ok=True, current_revision=0)
    revision = current_revision + 1
    sha = js_trim(source_sha256) if content is not None and source_sha256 is not None else None
    if content is None:
        return HeartbeatScratchState(current_revision=revision), HeartbeatScratchWrite(
            ok=True, current_revision=revision
        )
    scratch = HeartbeatScratch(
        content=content, revision=revision, updated_at_ms=int(now_ms), source_sha256=sha or None
    )
    return HeartbeatScratchState(current_revision=revision, scratch=scratch), HeartbeatScratchWrite(
        ok=True, current_revision=revision, scratch=scratch
    )


def apply_heartbeat_scratch_delete(
    state: HeartbeatScratchState, *, expected_revision: int | None = None
) -> tuple[HeartbeatScratchState, bool]:
    """``deleteCronJobScratch``: remove the row (back to "no scratch", revision 0).

    With ``expected_revision`` the delete happens only while the stored revision still equals
    it (doctor's atomic rollback of its own migration write); returns ``False`` otherwise.
    """
    if expected_revision is not None and state.current_revision != expected_revision:
        return state, False
    return HeartbeatScratchState(), True


class HeartbeatScratchStore(Protocol):
    """Where a host keeps each agent's heartbeat monitor scratch.

    Implementations apply :func:`apply_heartbeat_scratch_write` and
    :func:`apply_heartbeat_scratch_delete` atomically per agent.
    """

    def read_scratch(self, agent_id: str) -> HeartbeatScratchState: ...

    def write_scratch(
        self,
        agent_id: str,
        content: str | None,
        *,
        expected_revision: int | None = None,
        source_sha256: str | None = None,
        now_ms: int | None = None,
    ) -> HeartbeatScratchWrite: ...

    def delete_scratch(self, agent_id: str, *, expected_revision: int | None = None) -> bool: ...
