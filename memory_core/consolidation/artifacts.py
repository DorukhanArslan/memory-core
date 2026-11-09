"""Consolidation preimages and the DREAMS.md consolidation-history summaries.

Port of OpenClaw v2026.9.6 ``extensions/memory-core/src/dreaming-consolidation-artifacts.ts``
(``storeMemoryPreimage``, ``appendConsolidationSummary``, ``appendConsolidationSkippedSummary``)
and the DREAMS.md read/replace helpers of ``dreaming-dreams-file.ts`` they sit on
(``resolveDreamsPath``, ``readDreamsFile``, ``writeDreamsFileAtomic``, ``updateDreamsFile``).

Differences from upstream, all forced by the package's host-injected design:

- preimages are the JSON file ``memory/.dreams/consolidation-preimages.json`` (upstream: a keyed
  SQLite plugin-state namespace); the entry shape is ``{createdAt, content, contentHash}``;
- rotation prunes the origins ledger (:mod:`memory_core.consolidation.origins`) only when the
  host passes one;
- the workspace lock the DREAMS.md writers take is the file lock of
  :func:`memory_core.consolidation.store.memory_workspace_lock` (upstream: a plugin-state lease).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable, Collection, Iterable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from memory_core.bootstrap._js import js_trim, js_trim_end
from memory_core.consolidation._util import iso_ms, write_json_atomic
from memory_core.consolidation.markers import extract_promotion_markers
from memory_core.consolidation.origins import (
    MemoryEntryOriginLedger,
    prune_memory_entry_origins,
)
from memory_core.consolidation.store import memory_workspace_lock
from memory_core.runtime_identity import RuntimeIdentity

CONSOLIDATION_BACKUP_LIMIT = 8
PREIMAGE_FILE = "consolidation-preimages.json"
DREAMS_FILENAMES = ("DREAMS.md", "dreams.md")
CONSOLIDATION_HISTORY_HEADING = "## Memory Consolidation History"

T = TypeVar("T")


def preimage_path(workspace: str | Path) -> Path:
    return Path(workspace) / "memory" / ".dreams" / PREIMAGE_FILE


def read_memory_preimages(workspace: str | Path) -> list[dict[str, Any]]:
    """``readMemoryPreimages``: stored MEMORY.md snapshots, oldest first (an unreadable store is empty)."""
    try:
        entries = json.loads(preimage_path(workspace).read_text(encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []


def store_memory_preimage(
    workspace: str | Path,
    content: str,
    now_ms: int,
    *,
    agent_ids: Iterable[str] = (),
    retained_entry_keys: Collection[str] = frozenset(),
    ledger: MemoryEntryOriginLedger | None = None,
    identity: RuntimeIdentity | None = None,
) -> set[str]:
    """``storeMemoryPreimage``: keep the last :data:`CONSOLIDATION_BACKUP_LIMIT` MEMORY.md snapshots.

    Returns the promotion keys of the snapshots kept. With a ``ledger``, rotation then prunes the
    origins of the keys the previous snapshots held that neither a kept snapshot nor
    ``retained_entry_keys`` (nor a diary or index, see :func:`prune_memory_entry_origins`) retains:
    only expired backup references are released.
    """
    current = read_memory_preimages(workspace)
    created_at = iso_ms(now_ms)
    digest = hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()
    entry = {"createdAt": created_at, "content": content, "contentHash": digest}
    # Entries are keyed ``<createdAt>:<first 12 hash digits>``; a repeat replaces its predecessor.
    by_key = {
        f"{item.get('createdAt')}:{str(item.get('contentHash', ''))[:12]}": item for item in current
    }
    by_key[f"{created_at}:{digest[:12]}"] = entry
    entries = sorted(by_key.values(), key=lambda item: str(item.get("createdAt", "")))
    kept = entries[-CONSOLIDATION_BACKUP_LIMIT:]
    write_json_atomic(preimage_path(workspace), {"version": 1, "entries": kept})
    retained = {key for item in kept for key in extract_promotion_markers(str(item.get("content", "")), identity=identity)}
    if ledger is not None:
        prune_memory_entry_origins(
            ledger,
            workspace_dir=workspace,
            agent_ids=agent_ids,
            entry_keys=[
                key for item in current for key in extract_promotion_markers(str(item.get("content", "")), identity=identity)
            ],
            retained_entry_keys={*retained, *retained_entry_keys},
            identity=identity,
        )
    return retained


# --- DREAMS.md -------------------------------------------------------------------------


def resolve_dreams_path(workspace: str | Path) -> Path:
    """``resolveDreamsPath``: the first existing of ``DREAMS.md`` / ``dreams.md``, else ``DREAMS.md``."""
    root = Path(workspace)
    for name in DREAMS_FILENAMES:
        target = root / name
        if os.path.lexists(target):
            return target
    return root / DREAMS_FILENAMES[0]


def read_dreams_file(path: Path) -> str:
    """``readDreamsFile``: a missing file, a symlink or a non-file reads as empty."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return ""
    if not stat.S_ISREG(mode):
        return ""
    return path.read_text(encoding="utf-8")


def write_dreams_file_atomic(path: Path, content: str) -> None:
    """``writeDreamsFileAtomic``: refuses a symlink or non-file target, replaces atomically (0600 for new files)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode: int | None = os.lstat(path).st_mode
    except FileNotFoundError:
        mode = None
    if mode is not None:
        if stat.S_ISLNK(mode):
            raise OSError("Refusing to write symlinked DREAMS.md")
        if not stat.S_ISREG(mode):
            raise OSError("Refusing to write non-file DREAMS.md")
    temporary = path.with_name(f"{path.name}.dreams.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        if mode is not None:
            os.chmod(temporary, stat.S_IMODE(mode))
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def update_dreams_file(workspace: str | Path, updater: Callable[[str, Path], tuple[str, T]]) -> T:
    """``updateDreamsFile``: read, let ``updater`` return ``(content, result)``, write with a final newline.

    Takes the workspace lock (``withMemoryWorkspaceLock``), re-entering it when the caller, such
    as the deep phase, already holds it; waits up to 10 s for another holder.
    """
    with memory_workspace_lock(workspace):
        path = resolve_dreams_path(workspace)
        content, result = updater(read_dreams_file(path), path)
        write_dreams_file_atomic(path, content if content.endswith("\n") else f"{content}\n")
        return result


# --- consolidation history -------------------------------------------------------------


def _history_base(existing: str) -> str:
    if CONSOLIDATION_HISTORY_HEADING in existing:
        return js_trim_end(existing)
    separator = "\n\n" if js_trim(existing) else ""
    return f"{js_trim_end(existing)}{separator}{CONSOLIDATION_HISTORY_HEADING}"


def append_consolidation_summary(
    workspace: str | Path,
    *,
    added: int,
    merged: int,
    superseded: int,
    highlights: Sequence[str],
    now_ms: int,
) -> Path:
    """``appendConsolidationSummary``: one ``### <ISO time>`` block under ``## Memory Consolidation History``."""
    lines = [
        f"### {iso_ms(now_ms)}",
        "",
        f"- Added: {added}",
        f"- Merged: {merged}",
        f"- Superseded: {superseded}",
        *highlights,
        "",
    ]
    return update_dreams_file(
        workspace,
        lambda existing, path: (f"{_history_base(existing)}\n\n" + "\n".join(lines), path),
    )


def append_consolidation_skipped_summary(
    workspace: str | Path, *, now_ms: int, reason: str
) -> None:
    """``appendConsolidationSkippedSummary``: the "rewrite skipped" block with the append-only fallback."""
    block = (
        f"### {iso_ms(now_ms)}\n\n- Rewrite skipped: {reason}.\n- Fallback: append-only promotion.\n"
    )
    update_dreams_file(
        workspace, lambda existing, _path: (f"{_history_base(existing)}\n\n{block}", None)
    )
