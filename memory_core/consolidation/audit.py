"""Audit and repair short-term promotion state for the selected runtime identity."""


from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from memory_core.config import MemoryConfig
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.consolidation._util import iso_ms
from memory_core.consolidation.store import (
    empty_recall_store,
    is_valid_short_term_recall_entry,
    lock_is_stale,
    promotion_lock_path,
    recall_store_lock,
    recall_store_path,
    remove_stale_lock,
    write_recall_store,
)


@dataclass(frozen=True)
class ShortTermAuditIssue:
    """One audit finding; ``fixable`` issues are resolved by the repair pass."""

    severity: str
    code: str
    message: str
    fixable: bool


@dataclass(frozen=True)
class ShortTermAuditSummary:
    """Counts over the recall store plus any issues found."""

    exists: bool
    entry_count: int
    promoted_entry_count: int
    spaced_entry_count: int
    concept_tagged_entry_count: int
    invalid_entry_count: int
    issues: tuple[ShortTermAuditIssue, ...]
    store_path: str | None = None
    lock_path: str | None = None
    updated_at: str | None = None
    concept_tag_scripts: dict[str, int] | None = None
    dangling_entry_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists, "entryCount": self.entry_count, "promotedCount": self.promoted_entry_count,
            "spacedEntryCount": self.spaced_entry_count, "conceptTaggedEntryCount": self.concept_tagged_entry_count,
            "invalidEntryCount": self.invalid_entry_count, "danglingEntryCount": self.dangling_entry_count,
            "issues": [asdict(issue) for issue in self.issues],
            **{key: value for key, value in (("storePath", self.store_path), ("lockPath", self.lock_path),
                ("updatedAt", self.updated_at), ("conceptTagScripts", self.concept_tag_scripts)) if value is not None},
        }


@dataclass(frozen=True)
class ShortTermRepairResult:
    """What :func:`repair_short_term_promotion_artifacts` changed."""

    changed: bool
    removed_invalid_entries: int
    rewrote_store: bool
    removed_stale_lock: bool
    removed_dangling_entries: int | None = None
    removed_overflow_entries: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the result with upstream camelCase keys."""
        return {
            **{key: value for key, value in (("removedDanglingEntries", self.removed_dangling_entries),
                ("removedOverflowEntries", self.removed_overflow_entries)) if value is not None},
            "changed": self.changed,
            "removedInvalidEntries": self.removed_invalid_entries,
            "rewroteStore": self.rewrote_store,
            "removedStaleLock": self.removed_stale_lock,
        }


def audit_short_term_promotion_artifacts(
    config: MemoryConfig, now_ms: int, *, identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY
) -> ShortTermAuditSummary:
    """Summarize the recall store under ``config.workspace_dir`` (read-only).

    An entry is valid when it is an object with ``key``, ``path`` and
    ``snippet``. ``now_ms`` is accepted for signature parity and unused.
    """
    if identity == OPENCLAW_COMPAT_RUNTIME_IDENTITY:
        from memory_core.consolidation.dreaming_repair import audit_workspace_recall
        return audit_workspace_recall(config.workspace_dir, now_ms)
    del now_ms
    store_path = recall_store_path(config.workspace_dir)
    if not store_path.exists():
        return ShortTermAuditSummary(
            exists=False,
            entry_count=0,
            promoted_entry_count=0,
            spaced_entry_count=0,
            concept_tagged_entry_count=0,
            invalid_entry_count=0,
            issues=(),
        )
    try:
        raw = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ShortTermAuditSummary(
            exists=True,
            entry_count=0,
            promoted_entry_count=0,
            spaced_entry_count=0,
            concept_tagged_entry_count=0,
            invalid_entry_count=0,
            issues=(
                ShortTermAuditIssue(
                    severity="error",
                    code="recall-store-unreadable",
                    message="Short-term recall store could not be read.",
                    fixable=True,
                ),
            ),
        )

    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        entries = {}
    entry_count = 0
    promoted_entry_count = 0
    spaced_entry_count = 0
    concept_tagged_entry_count = 0
    invalid_entry_count = 0
    for entry in entries.values():
        if not is_valid_short_term_recall_entry(entry):
            invalid_entry_count += 1
            continue
        entry_count += 1
        if entry.get("promotedAt"):
            promoted_entry_count += 1
        recall_days = entry.get("recallDays")
        if (
            isinstance(recall_days, list)
            and len({day for day in recall_days if isinstance(day, str)}) > 1
        ):
            spaced_entry_count += 1
        concept_tags = entry.get("conceptTags")
        if isinstance(concept_tags, list) and any(
            isinstance(tag, str) and tag for tag in concept_tags
        ):
            concept_tagged_entry_count += 1
        if not entry.get("key") or not entry.get("path") or not entry.get("snippet"):
            invalid_entry_count += 1
    return ShortTermAuditSummary(
        exists=True,
        entry_count=entry_count,
        promoted_entry_count=promoted_entry_count,
        spaced_entry_count=spaced_entry_count,
        concept_tagged_entry_count=concept_tagged_entry_count,
        invalid_entry_count=invalid_entry_count,
        issues=(),
    )


def repair_short_term_promotion_artifacts(
    config: MemoryConfig, now_ms: int, *, identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY
) -> ShortTermRepairResult:
    """Repair the recall store and lock under ``config.workspace_dir``.

    An unreadable or malformed store is replaced by an empty one; invalid
    entries are dropped (store ``updatedAt`` becomes ``now_ms``); a lock older
    than the stale window is removed if it did not change meanwhile.
    """
    if identity == OPENCLAW_COMPAT_RUNTIME_IDENTITY:
        from memory_core.consolidation.dreaming_repair import repair_workspace_recall
        return repair_workspace_recall(config.workspace_dir, now_ms)
    store_path = recall_store_path(config.workspace_dir)
    lock_path = promotion_lock_path(config.workspace_dir)
    removed_invalid_entries = 0
    rewrote_store = False
    removed_stale_lock = False

    with recall_store_lock(config.workspace_dir):
        if store_path.exists():
            try:
                raw = json.loads(store_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                write_recall_store(store_path, empty_recall_store(now_ms))
                rewrote_store = True
            else:
                entries = raw.get("entries") if isinstance(raw, dict) else None
                if not isinstance(raw, dict) or not isinstance(entries, dict):
                    write_recall_store(store_path, empty_recall_store(now_ms))
                    rewrote_store = True
                else:
                    valid_entries = {
                        key: entry
                        for key, entry in entries.items()
                        if is_valid_short_term_recall_entry(entry)
                    }
                    removed_invalid_entries = len(entries) - len(valid_entries)
                    if removed_invalid_entries:
                        raw["version"] = 1
                        raw["updatedAt"] = iso_ms(now_ms)
                        raw["entries"] = valid_entries
                        write_recall_store(store_path, raw)
                        rewrote_store = True

    if lock_path.exists() and lock_is_stale(lock_path, now_ms):
        removed_stale_lock = remove_stale_lock(lock_path, now_ms)

    return ShortTermRepairResult(
        changed=bool(removed_invalid_entries or rewrote_store or removed_stale_lock),
        removed_invalid_entries=removed_invalid_entries,
        rewrote_store=rewrote_store,
        removed_stale_lock=removed_stale_lock,
    )
