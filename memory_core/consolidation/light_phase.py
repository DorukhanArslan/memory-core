"""Light dreaming selection, publication, and staged signals at OpenClaw v2026.9.9."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
import math
from pathlib import Path
import re
import stat
from typing import Any, Literal

from memory_core.atomic_publication import commit_memory_content
from memory_core.bootstrap._js import JS_SPACE, js_trim, js_trim_end, truncate_utf16_safe, utf16_len
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import iso_ms, js_to_fixed, parse_ms, write_json_atomic
from memory_core.consolidation.artifacts import read_dreams_file, resolve_dreams_path
from memory_core.consolidation.promotion import (
    _resolve_short_term_source_path_candidates,
    format_memory_dreaming_day,
    is_promotion_origin_blocked,
)
from memory_core.consolidation.recall import is_short_term_memory_path
from memory_core.consolidation.store import (
    memory_workspace_lock,
    phase_signal_store_path,
    read_canonical_phase_signal_store,
    read_canonical_recall_store,
    recall_store_path,
)
from memory_core.index.mmr import jaccard_similarity, tokenize
from memory_core.workspace import check_writable_memory_file


@dataclass(frozen=True)
class LightDreamingOptions:
    """Resolved light phase settings, for the ordinary host sweep without a narrative subagent."""

    enabled: bool = True
    dedupe_similarity: float = 0.9
    storage_mode: Literal["inline", "separate", "both"] = "separate"
    separate_reports: bool = False
    model: str | None = None
    complete: Callable[[dict], dict] | None = None

    def __post_init__(self):
        if self.storage_mode not in {"inline", "separate", "both"}:
            raise ValueError("unknown light dreaming storage mode")
        if not 0 <= self.dedupe_similarity <= 1:
            raise ValueError("dedupe_similarity must be a fraction between 0 and 1")


def _similarity(left, right):
    a, b = tokenize(left), tokenize(right)
    if not a and not b:
        return float(js_trim(left).lower() == js_trim(right).lower())
    return jaccard_similarity(a, b)


def _recent_diary(workspace):
    try:
        content = read_dreams_file(resolve_dreams_path(workspace))
    except PermissionError:
        return []
    return diary_context_entries(content)[-4:][::-1]


def diary_context_entries(content):
    start = "<!-- openclaw:dreaming:diary:start -->"
    end = "<!-- openclaw:dreaming:diary:end -->"
    if start not in content or content.find(end) < content.index(start):
        return []
    blocks = content.partition(start)[2].partition(end)[0].split("\n---\n")
    entries = []
    for block in blocks:
        lines = [js_trim(line) for line in block.split("\n")]
        body = " ".join(
            line
            for line in lines
            if line
            and not line.startswith(("#", "<!--"))
            and not (len(line) > 2 and line.startswith("*") and line.endswith("*"))
        )
        body = js_trim(re.sub(JS_SPACE + "+", " ", body))
        if body:
            entries.append(
                js_trim_end(truncate_utf16_safe(body, 360)) + "..."
                if utf16_len(body) > 360
                else body
            )
    return entries


def _fresh(entry, signal):
    if not signal or signal["lightHits"] <= 0:
        return True
    last_light = parse_ms(signal.get("lastLightAt") or "", -math.inf)
    return last_light == -math.inf or parse_ms(entry["lastRecalledAt"], -math.inf) > last_light


def dedupe_dreaming_entries(entries, threshold):
    """Group similar entries at the same path, preserving the first entry and all source keys."""
    groups = []
    for entry in entries:
        group = next(
            (
                item
                for item in groups
                if item["path"] == entry["path"]
                and _similarity(item["snippet"], entry["snippet"]) >= threshold
            ),
            None,
        )
        if group is None:
            groups.append({**deepcopy(entry), "sourceEntryKeys": [entry["key"]]})
            continue
        group["sourceEntryKeys"].append(entry["key"])
        for key in ("recallCount", "totalScore", "maxScore"):
            group[key] = max(group[key], entry[key])
        for key in ("queryHashes", "userQueryHashes", "conceptTags"):
            group[key] = list(dict.fromkeys([*group.get(key, []), *entry.get(key, [])]))
        group["recallDays"] = sorted(set(group["recallDays"]) | set(entry["recallDays"]))
        if parse_ms(entry["lastRecalledAt"], -math.inf) > parse_ms(
            group["lastRecalledAt"], -math.inf
        ):
            group["lastRecalledAt"] = entry["lastRecalledAt"]
    return groups


def entry_average_score(entry):
    count = sum(entry.get(key, 0) for key in ("recallCount", "dailyCount", "groundedCount"))
    return max(0, min(1, entry["totalScore"] / count)) if count > 0 else 0


def _managed_phase_block(original, heading, phase, body):
    start, end = (
        f"<!-- openclaw:dreaming:{phase}:start -->",
        f"<!-- openclaw:dreaming:{phase}:end -->",
    )
    block = "\n".join((heading, start, body, end))
    pattern = re.compile(
        re.escape(heading)
        + r"(?:[ \t]*(?:\r\n|\n|\r))+[ \t]*"
        + re.escape(start)
        + r"[\s\S]*?"
        + re.escape(end)
    )
    matches = list(pattern.finditer(original))
    if not matches:
        previous = js_trim_end(original)
        return (previous + "\n\n" if previous else "") + block + "\n"
    result = original[: matches[0].start()] + block
    for left, right in zip(matches, matches[1:]):
        between = original[left.end() : right.start()]
        if between.strip(" \t\r\n"):
            result += between
    result += original[matches[-1].end() :]
    return result if result.endswith("\n") else result + "\n"


def _publish(workspace, relative, content):
    target = workspace / relative
    check_writable_memory_file(workspace, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    commit_memory_content(target, content=content, temp_prefix=target.name + ".dreaming")


def publish_daily_dreaming_phase_block(
    *,
    workspace: Path,
    phase: Literal["light", "rem"],
    day: str,
    lines: list[str],
    has_content: bool,
    now_iso: str,
    storage_mode: str,
    separate_reports: bool,
    on_event: Callable[[dict[str, Any]], None] | None,
) -> list[str]:
    """Publish the daily phase Markdown, emit its outcome, and return written paths."""
    title = {"light": "Light Sleep", "rem": "REM Sleep"}[phase]
    body = "\n".join(lines) if lines else "- No notable updates."
    changed = []
    event = {
        "type": "memory.dream.completed",
        "timestamp": now_iso,
        "phase": phase,
        "outcome": "completed",
        "lineCount": len(lines),
        "storageMode": storage_mode,
    }
    if storage_mode in {"inline", "both"}:
        relative = f"memory/{day}.md"
        check_writable_memory_file(workspace, relative)
        try:
            original = (workspace / relative).read_bytes().decode("utf-8", errors="replace")
        except FileNotFoundError:
            original = None
        if has_content or original is not None:
            _publish(
                workspace,
                relative,
                _managed_phase_block(original or "", f"## {title}", phase, body),
            )
            changed.append(relative)
            event["inlinePath"] = str(workspace / relative)
    if has_content and (storage_mode in {"separate", "both"} or separate_reports):
        relative = f"memory/dreaming/{phase}/{day}.md"
        _publish(workspace, relative, f"# {title}\n\n{body}\n")
        changed.append(relative)
        event["reportPath"] = str(workspace / relative)
    if on_event is not None:
        on_event(event)
    return changed


def filter_live_short_term_recall_entries(workspace: Path, entries: list[dict]) -> list[dict]:
    """Keep entries with a regular source file, resolving each shared file once per sweep."""

    @cache
    def source_is_file(path: Path) -> bool:
        try:
            return stat.S_ISREG(path.stat().st_mode)
        except FileNotFoundError:
            return False

    return [
        entry
        for entry in entries
        if any(
            source_is_file(path)
            for path in _resolve_short_term_source_path_candidates(workspace, entry["path"])
        )
    ]


def prepare_light_phase(
    *,
    config: MemoryConfig,
    now_ms: int,
    timezone: str,
    limit: int,
    lookback_days: float,
    options: LightDreamingOptions,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    recent_diary: list[str] | None = None,
):
    """Publish the selected group leaders, then mark their keys under the same workspace lock."""
    from memory_core.consolidation.dreaming import filter_recall_entries_within_lookback

    root = config.workspace_dir
    now_iso = iso_ms(now_ms)
    with memory_workspace_lock(root, now_ms=now_ms):
        store = read_canonical_recall_store(recall_store_path(root), now_ms)
        signals_path = phase_signal_store_path(root)
        signals = read_canonical_phase_signal_store(signals_path, now_ms)
        entries = filter_recall_entries_within_lookback(
            entries=list(store["entries"].values()), now_ms=now_ms, lookback_days=lookback_days
        )
        fresh_entries = [
            entry
            for entry in entries
            if is_short_term_memory_path(entry["path"])
            and _fresh(entry, signals["entries"].get(entry["key"]))
        ]
        entries = [
            entry
            for entry in filter_live_short_term_recall_entries(root, fresh_entries)
            if not is_promotion_origin_blocked(entry.get("provenance"))
        ]
        entries.sort(
            key=lambda e: (parse_ms(e["lastRecalledAt"], -math.inf), e["recallCount"]), reverse=True
        )
        groups = dedupe_dreaming_entries(entries, options.dedupe_similarity)
        diary = _recent_diary(root)
        if recent_diary is not None:
            recent_diary.extend(diary)

        def covered(entry):
            snippet = js_trim(re.sub(JS_SPACE + "+", " ", entry["snippet"].lower()))
            return bool(snippet) and any(
                snippet in text.lower() or _similarity(entry["snippet"], text) >= 0.35
                for text in diary
            )

        selected = sorted(groups, key=covered)[:limit]
        lines = []
        for entry in selected:
            lines.extend(
                (
                    f"- Candidate: {entry['snippet'] or '(no snippet captured)'}",
                    f"  - confidence: {js_to_fixed(entry_average_score(entry), 2)}",
                    f"  - evidence: {entry['path']}:{entry['startLine']}-{entry['endLine']}",
                    f"  - recalls: {entry['recallCount']}",
                    "  - status: staged",
                )
            )
        if not lines:
            lines = ["- No notable updates."]
        changed = publish_daily_dreaming_phase_block(
            workspace=root,
            phase="light",
            day=format_memory_dreaming_day(now_ms, timezone),
            lines=lines,
            has_content=bool(selected),
            now_iso=now_iso,
            storage_mode=options.storage_mode,
            separate_reports=options.separate_reports,
            on_event=on_event,
        )
        recorded = 0
        if selected:
            # Publication may invoke a host callback which updates memory under this reentrant lock.
            store = read_canonical_recall_store(recall_store_path(root), now_ms)
            signals = read_canonical_phase_signal_store(signals_path, now_ms)
            for entry in selected:
                key = entry["key"]
                if key not in store["entries"]:
                    continue
                signal = signals["entries"].setdefault(
                    key, {"key": key, "lightHits": 0, "remHits": 0}
                )
                signal["lightHits"] = min(9999, signal["lightHits"] + 1)
                signal["lastLightAt"] = now_iso
                recorded += 1
            signals["entries"] = {
                k: s
                for k, s in signals["entries"].items()
                if k in store["entries"] and (s["lightHits"] > 0 or s["remHits"] > 0)
            }
            signals["updatedAt"] = now_iso
            write_json_atomic(signals_path, signals)
            changed.append(str(signals_path.relative_to(root)))
        return selected, changed, recorded
