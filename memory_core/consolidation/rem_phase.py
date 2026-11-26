"""REM reflections, stage consumption, and diary publication in the ordinary host sweep."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Literal

from memory_core.bootstrap._js import locale_sort_key
from memory_core.consolidation._util import iso_ms, js_to_fixed, parse_ms, write_json_atomic
from memory_core.consolidation.concepts import _normalize_concept_token
from memory_core.consolidation.dream_narrative import run_rem_narrative
from memory_core.consolidation.light_phase import (
    dedupe_dreaming_entries, entry_average_score, filter_live_short_term_recall_entries,
    publish_daily_dreaming_phase_block,
)
from memory_core.consolidation.promotion import format_memory_dreaming_day, is_promotion_origin_blocked
from memory_core.consolidation.recall import is_short_term_memory_path
from memory_core.consolidation.store import (
    memory_workspace_lock, phase_signal_store_path, read_canonical_phase_signal_store,
    read_canonical_recall_store, recall_store_path,
)
from memory_core.index._js_log1p import log1p


@dataclass(frozen=True)
class RemDreamingOptions:
    """Resolved REM settings and optional awaited narrative provider."""
    enabled: bool = True
    min_pattern_strength: float = 0.75
    storage_mode: Literal["inline", "separate", "both"] = "separate"
    separate_reports: bool = False
    model: str | None = None
    complete: Callable[[dict], Mapping[str, Any]] | None = None

    def __post_init__(self):
        if self.storage_mode not in {"inline", "separate", "both"}:
            raise ValueError("unknown REM dreaming storage mode")
        if not 0 <= self.min_pattern_strength <= 1:
            raise ValueError("min_pattern_strength must be a fraction between 0 and 1")


def _is_pending(signal: dict) -> bool:
    if signal["lightHits"] <= 0:
        return False
    light = parse_ms(signal.get("lastLightAt") or "", -math.inf)
    if light == -math.inf:
        return not signal.get("lastRemAt")
    return light > max(parse_ms(signal.get(field) or "", -math.inf)
                       for field in ("lastRemAt", "lastRemConsideredAt"))


def _evidence(entry):
    return f"{entry['path']}:{entry['startLine']}-{entry['endLine']}"


def _candidate_truths(entries, limit):
    candidates = []
    for entry in dedupe_dreaming_entries([e for e in entries if not e.get("promotedAt")], 0.88):
        recall = min(1, log1p(entry["recallCount"]) / log1p(6))
        days = min(1, len(entry["recallDays"]) / 3)
        concepts = min(1, len(entry["conceptTags"]) / 6)
        confidence = max(0, min(1, entry_average_score(entry) * 0.45 + recall * 0.25 + days * 0.2 + concepts * 0.1))
        if confidence >= 0.45:
            candidates.append((entry["key"], entry["snippet"] or "(no snippet captured)", confidence, _evidence(entry)))
    candidates.sort(key=lambda candidate: (-candidate[2], locale_sort_key(candidate[1])))
    return candidates[:max(1, min(3, limit))]


def _reflections(entries, limit, minimum):
    counts = {}
    evidence = {}
    for entry in entries:
        # One memory contributes to a normalized topic at most once.
        for tag in dict.fromkeys(map(_normalize_concept_token, entry["conceptTags"])):
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
                evidence.setdefault(tag, {})[_evidence(entry)] = None
    strength = {tag: min(1, count / len(entries) * 2) for tag, count in counts.items()}
    ranked = sorted((tag for tag in counts if strength[tag] >= minimum),
                    key=lambda tag: (-strength[tag], -counts[tag], locale_sort_key(tag)))
    lines = []
    themes = []
    for tag in ranked[:limit]:
        themes.append(f"- Theme: `{tag}` kept surfacing across {counts[tag]} memories.")
        lines.extend((themes[-1], f"  - confidence: {js_to_fixed(strength[tag], 2)}",
                      f"  - evidence: {', '.join(list(evidence[tag])[:3])}", "  - note: reflection"))
    return themes, lines or ["- No strong patterns surfaced."]


def _update_signals(workspace: Path, keys, now_ms, now_iso, *, considered):
    """Update each set from a fresh store read while holding the phase's workspace lock."""
    if not keys:
        return 0
    known = read_canonical_recall_store(recall_store_path(workspace), now_ms, for_publication=True)["entries"]
    signal_path = phase_signal_store_path(workspace)
    store = read_canonical_phase_signal_store(signal_path, now_ms)
    records = store["entries"]
    recorded = 0
    for key in dict.fromkeys(keys):
        if key in known:
            record = records.setdefault(key, {"key": key, "lightHits": 0, "remHits": 0})
            if considered:
                record["lastRemConsideredAt"] = now_iso
            else:
                record["lastRemAt"] = now_iso
                record["remHits"] = min(9999, record["remHits"] + 1)
            recorded += 1
    store["entries"] = {k: v for k, v in records.items() if k in known and (v["lightHits"] > 0 or v["remHits"] > 0)}
    store["updatedAt"] = now_iso
    write_json_atomic(signal_path, store)
    return recorded


def prepare_rem_phase(*, config, now_ms, timezone, limit, lookback_days, options: RemDreamingOptions,
                      agent_id=None, on_event=None, dispatch_narrative=None):
    from memory_core.consolidation.dreaming import filter_recall_entries_within_lookback

    workspace = config.workspace_dir
    now_iso = iso_ms(now_ms)
    with memory_workspace_lock(workspace, now_ms=now_ms):
        store = read_canonical_recall_store(recall_store_path(workspace), now_ms, for_publication=True)
        recent = filter_recall_entries_within_lookback(
            entries=[entry for entry in store["entries"].values() if is_short_term_memory_path(entry["path"])],
            now_ms=now_ms, lookback_days=lookback_days,
        )
        available = [e for e in filter_live_short_term_recall_entries(workspace, recent)
                     if not is_promotion_origin_blocked(e.get("provenance"))]
        signals = read_canonical_phase_signal_store(phase_signal_store_path(workspace), now_ms)
        pending = {key for key, signal in signals["entries"].items() if _is_pending(signal)}
        staged = [entry for entry in available if entry["key"] in pending]
        entries = staged or available
        truths = _candidate_truths(entries, limit)
        themes, reflections = _reflections(entries, limit, options.min_pattern_strength)
        lines = [f"- {snippet} [confidence={js_to_fixed(score, 2)} evidence={evidence}]"
                 for _, snippet, score, evidence in truths]
        body = ["### Reflections", *reflections, "", "### Possible Lasting Truths",
                *(lines or ["- No strong candidate truths surfaced."])]
        changed = publish_daily_dreaming_phase_block(
            workspace=workspace, phase="rem", day=format_memory_dreaming_day(now_ms, timezone),
            lines=body, has_content=bool(entries), now_iso=now_iso,
            storage_mode=options.storage_mode, separate_reports=options.separate_reports, on_event=on_event,
        )
        _update_signals(workspace, [e["key"] for e in staged], now_ms, now_iso, considered=True)
        recorded = _update_signals(workspace, [key for key, *_ in truths], now_ms, now_iso, considered=False)
        if staged or truths:
            changed.append(phase_signal_store_path(workspace).relative_to(workspace).as_posix())

    status = "skipped"
    if options.complete is not None and entries:
        snippets = [snippet for _, snippet, _, _ in truths] or [e["snippet"] for e in entries[:8] if e["snippet"]]
        def narrate():
            return run_rem_narrative(
                workspace_dir=workspace, agent_id=agent_id, complete=options.complete, model=options.model,
                snippets=snippets, themes=themes, source_entry_keys=[e["key"] for e in entries],
                now_ms=now_ms, timezone=timezone,
            )

        if snippets:
            status = dispatch_narrative(narrate) if dispatch_narrative else narrate()
        if status in ("completed", "degraded") and (workspace / "DREAMS.md").is_file():
            changed.append("DREAMS.md")
    return changed, recorded, status
