"""The memory-write provenance observer: trust records for the files the flush writes.

Port of ``createMemoryWriteProvenanceObserver`` and ``withMemoryWriteProvenance``
(``src/agents/memory-write-provenance.ts``, OpenClaw v2026.9.6), the observer the agent tools
(``agent-tools.ts:255``, the flush's ``write``) and the session-memory hook
(``hooks/bundled/session-memory/handler.ts:256``) attach to their file writes.

Every write to a memory file of the workspace (``MEMORY.md``, ``USER.md``, ``memory/*.md`` and the
other files of :func:`~memory_core.consolidation.artifact_provenance.normalize_memory_artifact_relative_path`)
first records its trust in the host's :class:`~memory_core.consolidation.artifact_provenance.MemoryArtifactProvenanceStore`
(``agent`` for a trusted writer on a file that was still the way a trusted write left it, ``untrusted``
for an untrusted turn, an edit in between, or a file that was already untrusted: the record is sticky),
then commits the write; an ordinary commit error rolls the record back. The SDK host integration
keeps quarantine when a checked publisher reports a genuinely dispatched uncertain/committed
mutation, and can gate producer entry with its durable intent. The dreaming daily ingestion and the
promotion's daily-file quarantine read the records
(:mod:`memory_core.consolidation.daily_ingestion`, ``with_daily_file_quarantine``).

Paths are canonicalized with the owner's rule (``canonicalPathFromExistingAncestor``: the real path of
the nearest existing ancestor plus the missing tail), so an alias or a symlinked directory does not
escape the quarantine; a path outside the mutation root is not classified and written untracked.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Literal

from memory_core.atomic_publication import MemoryAtomicPublicationError
from memory_core.consolidation.artifact_provenance import (
    MemoryArtifactProvenanceStore,
    normalize_memory_artifact_relative_path,
)

LOGGER = logging.getLogger(__name__)

OriginClass = Literal["agent", "untrusted"]
_write_entry: ContextVar[Callable[[], None] | None] = ContextVar("memory_write_entry", default=None)


@contextmanager
def _observe_memory_write_entry(callback: Callable[[], None] | None):
    """Bind a trusted host observer to this synchronous source invocation."""
    token = _write_entry.set(callback)
    try:
        yield
    finally:
        _write_entry.reset(token)


def canonical_path_from_existing_ancestor(file_path: str | os.PathLike[str]) -> str:
    """``canonicalPathFromExistingAncestor``: realpath of the nearest existing ancestor plus the rest."""
    resolved = os.path.abspath(file_path)
    ancestor: str | None = None
    current = resolved
    while True:
        try:
            os.lstat(current)
            ancestor = current
            break
        except FileNotFoundError:
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    if ancestor is None:
        return resolved
    canonical_ancestor = ancestor
    try:
        canonical_ancestor = os.path.realpath(ancestor, strict=True)
    except OSError:
        pass  # keep the lexical path when the existing ancestor cannot be canonicalized
    relative = os.path.relpath(resolved, ancestor)
    return canonical_ancestor if relative == "." else os.path.join(canonical_ancestor, relative)


class MemoryWriteProvenanceObserver:
    """``MemoryWriteProvenanceObserver``: records the trust of a memory file before it is written."""

    def __init__(
        self,
        *,
        store: MemoryArtifactProvenanceStore,
        mutation_root: str | os.PathLike[str],
        workspace_dir: str | os.PathLike[str],
        resolve_origin_class: Callable[[], OriginClass],
        session_id: str | None = None,
        session_key: str | None = None,
        now: Callable[[], int] | None = None,
        resolve_path: Callable[[str], str] | None = None,
    ) -> None:
        self._store = store
        self._mutation_root = str(mutation_root)
        self._workspace_dir = str(workspace_dir)
        self._resolve_origin_class = resolve_origin_class
        self._session_id = session_id
        self._session_key = session_key
        self._now = now or (lambda: time.time_ns() // 1_000_000)
        self._resolve_path = resolve_path or canonical_path_from_existing_ancestor

    def _relative_path(self, absolute_path: str | os.PathLike[str]) -> str | None:
        # Both paths are canonicalized by the same owner: aliases must keep the memory quarantine.
        root = self._resolve_path(self._mutation_root)
        target = self._resolve_path(os.fspath(absolute_path))
        relative = os.path.relpath(target, root)
        if not relative or relative == "." or os.path.isabs(relative) or relative == ".." or relative.startswith(f"..{os.sep}"):
            return None
        return normalize_memory_artifact_relative_path(relative.replace(os.sep, "/"))

    def classifies(self, absolute_path: str | os.PathLike[str]) -> bool:
        """True when the path is a memory file whose writes carry a trust record."""
        return self._relative_path(absolute_path) is not None

    def write(
        self,
        *,
        absolute_path: str | os.PathLike[str],
        content_before: str,
        content_after: str,
        commit: Callable[[], None],
    ) -> None:
        """Record trust, retaining checked publisher states and rolling back other failures."""
        before_write = _write_entry.get()
        if before_write is not None:
            before_write()
        relative_path = self._relative_path(absolute_path)
        if relative_path is None:
            commit()
            return
        rollback = self._store.record_write(
            workspace_dir=self._workspace_dir,
            relative_path=relative_path,
            content_before=content_before,
            content_after=content_after,
            origin_class=self._resolve_origin_class(),
            observed_at=self._now(),
            session_id=self._session_id,
            session_key=self._session_key,
        )
        try:
            commit()
        except BaseException as error:
            # A dispatched publisher can no longer promise that no write took
            # place. Keep the original sticky quarantine; its content hash
            # still prevents it from blessing an external replacement.
            if (isinstance(error, MemoryAtomicPublicationError)
                    and error.publication in {"committed", "uncertain"}):
                raise
            if rollback is not None:
                try:
                    rollback()
                except Exception as rollback_error:
                    raise RuntimeError(
                        f"File write failed and memory provenance rollback also failed: {error}"
                    ) from rollback_error
            raise

    def clear_after_delete(self, absolute_path: str | os.PathLike[str], content_before: str) -> None:
        """Forget the record of a deleted file (a cleanup failure keeps the stale quarantine)."""
        relative_path = self._relative_path(absolute_path)
        if relative_path is None:
            return
        try:
            self._store.clear(
                workspace_dir=self._workspace_dir, relative_path=relative_path, content_before=content_before
            )
        except Exception as error:
            # The file is already gone; a stale quarantine is safer than reporting the delete failed.
            LOGGER.warning("memory provenance cleanup failed for %s: %s", relative_path, error)


def read_text_or_empty(path: str | os.PathLike[str]) -> str:
    """The text of a file as upstream reads ``contentBefore`` (a missing file is empty)."""
    try:
        return Path(path).read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
