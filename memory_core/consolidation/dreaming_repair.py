"""Repair the canonical recall rows used by a managed deep dreaming sweep."""
from copy import deepcopy
import json

from memory_core.consolidation._util import iso_ms, write_json_atomic
from memory_core.consolidation.concepts import derive_concept_tags
from memory_core.consolidation.light_phase import filter_live_short_term_recall_entries
from memory_core.consolidation.recall import MAX_RECALL_DAYS, merge_recent_distinct, normalize_iso_day
from memory_core.consolidation.store import (
    _enforce_short_term_recall_store_retention, lock_is_stale, memory_workspace_lock, phase_signal_store_path,
    promotion_lock_path, read_canonical_phase_signal_store, read_canonical_recall_store, recall_store_path,
    remove_stale_lock,
)


def repair_dreaming_recall(workspace, now_ms):
    """Return the original report's action summary after pruning or normalizing its persisted rows."""
    timestamp = iso_ms(now_ms)
    lock = promotion_lock_path(workspace)
    removed_lock = lock.exists() and lock_is_stale(lock, now_ms) and remove_stale_lock(lock, now_ms)
    actions = []
    path = recall_store_path(workspace)
    with memory_workspace_lock(workspace, now_ms=now_ms):
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            store = read_canonical_recall_store(path, now_ms)
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
                detail = ", ".join(f"-{count} {label}" for label, count in (
                    ("invalid", invalid), ("dangling", len(dangling)), ("overflow", overflow)) if count)
                actions.append("rewrote recall store" + (f" ({detail})" if detail else ""))
    if removed_lock:
        actions.append("removed stale promotion lock")
    return ", ".join(actions)
