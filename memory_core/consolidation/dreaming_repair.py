"""Repair the canonical recall rows used by a managed deep dreaming sweep."""
from copy import deepcopy
import json
from pathlib import Path

from memory_core.consolidation._util import iso_ms, write_json_atomic
from memory_core.consolidation.concepts import _classify_concept_tag_script, derive_concept_tags
from memory_core.consolidation.light_phase import filter_live_short_term_recall_entries
from memory_core.consolidation.recall import MAX_RECALL_DAYS, merge_recent_distinct, normalize_iso_day
from memory_core.consolidation.store import (
    SHORT_TERM_RECALL_MAX_ENTRIES, _enforce_short_term_recall_store_retention, lock_is_stale, memory_workspace_lock, phase_signal_store_path,
    promotion_lock_path, read_canonical_phase_signal_store, recall_store_path,
    remove_stale_lock,
)


from memory_core.consolidation.store_normalization import normalize_short_term_recall_store


def _read_raw_recall(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"entries": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        raise ValueError("Short-term recall store does not contain a readable entries object.")
    return payload


def audit_workspace_recall(workspace: Path, now_ms: int):
    from memory_core.consolidation.audit import ShortTermAuditIssue, ShortTermAuditSummary

    path, lock = recall_store_path(workspace), promotion_lock_path(workspace)
    issues = []

    def warn(code, message):
        issues.append(ShortTermAuditIssue("warn", code, message, True))

    try:
        raw = _read_raw_recall(path)
    except (OSError, UnicodeError, ValueError):
        return ShortTermAuditSummary(True, 0, 0, 0, 0, 0, (
            ShortTermAuditIssue("error", "recall-store-unreadable",
                                "Short-term recall store could not be read.", False),),
            store_path=str(path), lock_path=str(lock))
    store = normalize_short_term_recall_store(raw, now_ms)
    entries = list(store["entries"].values())
    exists = bool(raw["entries"])
    invalid = len(raw["entries"]) - len(entries)
    dangling = len(entries) - len(filter_live_short_term_recall_entries(workspace, entries))
    if invalid:
        noun = "entry" if invalid == 1 else "entries"
        warn("recall-store-invalid", f"Short-term recall store contains {invalid} invalid {noun}.")
    if dangling:
        noun = "entry" if dangling == 1 else "entries"
        warn("recall-store-dangling", f"Short-term recall store contains {dangling} {noun} "
             "whose source file is missing or not a regular file.")
    if len(entries) > SHORT_TERM_RECALL_MAX_ENTRIES:
        warn("recall-store-over-limit", f"Short-term recall store contains {len(entries)} entries; "
             f"only the newest {SHORT_TERM_RECALL_MAX_ENTRIES} are kept at runtime.")
    if lock.exists() and lock_is_stale(lock, now_ms):
        warn("recall-lock-stale", "Short-term promotion lock appears stale.")
    tagged = [entry["conceptTags"] for entry in entries if entry["conceptTags"]]
    scripts = dict.fromkeys(("latinEntryCount", "cjkEntryCount", "mixedEntryCount", "otherEntryCount"), 0)
    for tags in tagged:
        scripts[_classify_concept_tag_script(" ".join(tags)) + "EntryCount"] += 1
    return ShortTermAuditSummary(
        exists, len(entries), sum(bool(e.get("promotedAt")) for e in entries),
        sum(len(e["recallDays"]) > 1 for e in entries), len(tagged), invalid, tuple(issues),
        store_path=str(path), lock_path=str(lock), updated_at=store["updatedAt"] if exists else None,
        concept_tag_scripts=scripts if exists else None, dangling_entry_count=dangling,
    )


def repair_workspace_recall(workspace: Path, now_ms: int):
    """Prune individual recoverable rows while preserving unreadable store bytes."""
    from memory_core.consolidation.audit import ShortTermRepairResult
    timestamp = iso_ms(now_ms)
    lock = promotion_lock_path(workspace)
    removed_lock = lock.exists() and lock_is_stale(lock, now_ms) and remove_stale_lock(lock, now_ms)
    invalid = overflow = 0
    dangling = set()
    rewrote = False
    path = recall_store_path(workspace)
    with memory_workspace_lock(workspace, now_ms=now_ms):
        if path.exists():
            payload = _read_raw_recall(path)
            store = normalize_short_term_recall_store(payload, now_ms)
            original = deepcopy(store["entries"])
            invalid = max(0, len(payload.get("entries", {})) - len(original))
            for entry in store["entries"].values():
                tags = derive_concept_tags(entry["path"], entry["snippet"])
                if tags:
                    entry["conceptTags"] = tags
                day = normalize_iso_day(entry["lastRecalledAt"]) or timestamp[:10]
                entry["recallDays"] = merge_recent_distinct(entry["recallDays"], day, MAX_RECALL_DAYS)
            live = filter_live_short_term_recall_entries(workspace, list(store["entries"].values()))
            dangling = store["entries"].keys() - {e["key"] for e in live}
            for key in dangling:
                del store["entries"][key]
            overflow = _enforce_short_term_recall_store_retention(store)
            if invalid or dangling or overflow or store["entries"] != original:
                if dangling:
                    signal_path = phase_signal_store_path(workspace)
                    signals = read_canonical_phase_signal_store(signal_path, now_ms)
                    for key in dangling:
                        signals["entries"].pop(key, None)
                    signals["updatedAt"] = timestamp
                    write_json_atomic(signal_path, signals)
                store["updatedAt"] = timestamp
                write_json_atomic(path, store)
                rewrote = True
    return ShortTermRepairResult(rewrote or removed_lock, invalid, rewrote, removed_lock, len(dangling), overflow)


def repair_dreaming_recall(workspace, now_ms):
    """Summarize the completed workspace repair for the managed dreaming report."""
    result = repair_workspace_recall(workspace, now_ms)
    actions = []
    if result.rewrote_store:
        detail = ", ".join(f"-{count} {label}" for label, count in (
            ("invalid", result.removed_invalid_entries), ("dangling", result.removed_dangling_entries),
            ("overflow", result.removed_overflow_entries)) if count)
        actions.append("rewrote recall store" + (f" ({detail})" if detail else ""))
    if result.removed_stale_lock:
        actions.append("removed stale promotion lock")
    return ", ".join(actions)
