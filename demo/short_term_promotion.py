from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import difflib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
from typing import Any, Iterator

from demo.memory_flush import ParsedFlushOutput
from memory_core.config import MemoryConfig
from memory_core.workspace import MemoryWorkspace

SHORT_TERM_STORE_RELATIVE_PATH = Path("memory") / ".dreams" / "short-term-recall.json"
SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH = Path("memory") / ".dreams" / "phase-signals.json"
SHORT_TERM_LOCK_RELATIVE_PATH = Path("memory") / ".dreams" / "short-term-promotion.lock"
_SHORT_TERM_LOCK_GUARD_RELATIVE_PATH = Path("memory") / ".dreams" / "short-term-promotion.lock.guard"
SHORT_TERM_LOCK_STALE_MS = 60_000
PROMOTION_MARKER_PREFIX = "openclaw-memory-promotion:"
DEFAULT_PROMOTION_MIN_SCORE = 0.75
DEFAULT_PROMOTION_MIN_RECALL_COUNT = 3
DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES = 2
DEFAULT_RECENCY_HALF_LIFE_DAYS = 14
DAY_MS = 24 * 60 * 60 * 1000
PHASE_SIGNAL_DECAY_MS = 30 * DAY_MS


@dataclass(frozen=True)
class ShortTermLockResult:
    acquired: bool
    path: Path
    reason: str | None = None
    stole_stale: bool = False


@dataclass(frozen=True)
class ShortTermAuditIssue:
    severity: str
    code: str
    message: str
    fixable: bool


@dataclass(frozen=True)
class ShortTermAuditSummary:
    exists: bool
    entry_count: int
    promoted_entry_count: int
    spaced_entry_count: int
    concept_tagged_entry_count: int
    invalid_entry_count: int
    issues: tuple[ShortTermAuditIssue, ...]


@dataclass(frozen=True)
class _ShortTermLockSnapshot:
    mtime_ns: int
    payload: bytes
    owner_token: str | None


@dataclass(frozen=True)
class PromotionCandidate:
    key: str
    path: str
    start_line: int
    end_line: int
    snippet: str
    recall_count: int
    daily_count: int
    grounded_count: int
    signal_count: int
    avg_score: float
    max_score: float
    unique_queries: int
    score: float
    first_recalled_at: str
    last_recalled_at: str
    promoted_at: str | None = None
    age_days: float = 0.0
    concept_tags: tuple[str, ...] = ()
    components: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PromotionEvaluation:
    key: str
    path: str
    start_line: int
    end_line: int
    snippet: str
    recall_count: int
    daily_count: int
    grounded_count: int
    signal_count: int
    avg_score: float
    max_score: float
    unique_queries: int
    context_diversity: int
    score: float
    reasons: tuple[str, ...]
    age_days: float = 0.0
    concept_tags: tuple[str, ...] = ()
    components: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryPromotionRun:
    target: str
    raw_text: str
    parsed: ParsedFlushOutput
    diff: str
    indexed_files: int
    chunks: int
    evaluated_candidates: list[PromotionEvaluation]
    reindex_error: str | None = None


@contextmanager
def acquire_short_term_promotion_lock(
    config: MemoryConfig, now_ms: int
) -> Iterator[ShortTermLockResult]:
    lock_path = config.workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stole_stale = False
    owner_token = secrets.token_hex(16)
    acquired = False
    with _short_term_promotion_guard(lock_path):
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                stale_snapshot = _read_short_term_lock_snapshot(lock_path)
                if stale_snapshot is None:
                    continue
                if not _lock_is_stale(lock_path, now_ms):
                    break
                if not _unlink_matching_short_term_lock(lock_path, stale_snapshot):
                    break
                stole_stale = True
                continue
            acquired = True
            break

        if acquired:
            payload = {"pid": os.getpid(), "createdAt": _iso(now_ms), "ownerToken": owner_token}
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")

    if not acquired:
        yield ShortTermLockResult(acquired=False, path=lock_path, reason="locked")
        return

    try:
        yield ShortTermLockResult(acquired=True, path=lock_path, stole_stale=stole_stale)
    finally:
        _release_short_term_promotion_lock(lock_path, owner_token)


def audit_short_term_promotion_artifacts(
    config: MemoryConfig, now_ms: int
) -> ShortTermAuditSummary:
    del now_ms
    store_path = config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH
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
        if not isinstance(entry, dict):
            invalid_entry_count += 1
            continue
        entry_count += 1
        if entry.get("promotedAt"):
            promoted_entry_count += 1
        recall_days = entry.get("recallDays")
        if isinstance(recall_days, list) and len({day for day in recall_days if isinstance(day, str)}) > 1:
            spaced_entry_count += 1
        concept_tags = entry.get("conceptTags")
        if isinstance(concept_tags, list) and any(isinstance(tag, str) and tag for tag in concept_tags):
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


def repair_short_term_promotion_artifacts(config: MemoryConfig, now_ms: int) -> dict[str, Any]:
    store_path = config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH
    lock_path = config.workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH
    removed_invalid_entries = 0
    rewrote_store = False
    removed_stale_lock = False

    if store_path.exists():
        try:
            raw = json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _write_store(store_path, {"version": 1, "updatedAt": _iso(now_ms), "entries": {}})
            rewrote_store = True
        else:
            entries = raw.get("entries") if isinstance(raw, dict) else None
            if not isinstance(raw, dict) or not isinstance(entries, dict):
                _write_store(store_path, {"version": 1, "updatedAt": _iso(now_ms), "entries": {}})
                rewrote_store = True
            else:
                valid_entries = {
                    key: entry for key, entry in entries.items() if isinstance(entry, dict)
                }
                removed_invalid_entries = len(entries) - len(valid_entries)
                if removed_invalid_entries:
                    raw["version"] = 1
                    raw["updatedAt"] = _iso(now_ms)
                    raw["entries"] = valid_entries
                    _write_store(store_path, raw)
                    rewrote_store = True

    if lock_path.exists() and _lock_is_stale(lock_path, now_ms):
        with _short_term_promotion_guard(lock_path):
            snapshot = _read_short_term_lock_snapshot(lock_path)
            if snapshot is not None and _lock_is_stale(lock_path, now_ms):
                removed_stale_lock = _unlink_matching_short_term_lock(lock_path, snapshot)

    return {
        "changed": bool(removed_invalid_entries or rewrote_store or removed_stale_lock),
        "removedInvalidEntries": removed_invalid_entries,
        "rewroteStore": rewrote_store,
        "removedStaleLock": removed_stale_lock,
    }


def record_short_term_recalls(
    *,
    config: MemoryConfig,
    query: str,
    results: list[dict[str, Any]],
    now_ms: int,
    signal_type: str = "recall",
) -> int:
    store_path = config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH
    store = _read_store(store_path, now_ms)
    now_iso = _iso(now_ms)
    query_hash = _hash(query.lower().strip())
    changed = 0
    for result in results:
        path = str(result.get("path") or "")
        if not path.startswith("memory/") or not path.endswith(".md"):
            continue
        start_line = _int(result.get("startLine"), 1)
        score = _clamp(float(result.get("score") or 0))
        for line_number, snippet in _candidate_lines(
            raw=str(result.get("snippet") or ""), start_line=start_line
        ):
            claim_hash = _hash(snippet)
            key = f"memory:{path}:{line_number}:{line_number}:{claim_hash}"
            entry = store["entries"].get(key)
            if entry is None:
                entry = {
                    "key": key,
                    "path": path,
                    "startLine": line_number,
                    "endLine": line_number,
                    "source": "memory",
                    "snippet": snippet,
                    "recallCount": 0,
                    "dailyCount": 0,
                    "groundedCount": 0,
                    "totalScore": 0.0,
                    "maxScore": 0.0,
                    "firstRecalledAt": now_iso,
                    "lastRecalledAt": now_iso,
                    "queryHashes": [],
                    "recallDays": [],
                    "conceptTags": _derive_concept_tags(path, snippet),
                    "claimHash": claim_hash,
                }
                store["entries"][key] = entry
            entry["totalScore"] = float(entry.get("totalScore") or 0) + score
            entry["maxScore"] = max(float(entry.get("maxScore") or 0), score)
            entry["lastRecalledAt"] = now_iso
            entry["conceptTags"] = entry.get("conceptTags") or _derive_concept_tags(path, snippet)
            entry["queryHashes"] = _append_distinct(
                list(entry.get("queryHashes") or []), query_hash, 32
            )
            entry["recallDays"] = _append_distinct(
                list(entry.get("recallDays") or []), now_iso[:10], 16
            )
            if signal_type == "daily":
                entry["dailyCount"] = _int(entry.get("dailyCount"), 0) + 1
            else:
                entry["recallCount"] = _int(entry.get("recallCount"), 0) + 1
            changed += 1
    if changed:
        store["updatedAt"] = now_iso
        _write_store(store_path, store)
    return changed


def record_short_term_phase_signals(
    *,
    config: MemoryConfig,
    keys: list[str],
    phase: str,
    now_ms: int,
) -> int:
    if phase not in {"light", "rem"}:
        raise ValueError(f"unsupported dreaming phase: {phase}")
    path = config.workspace_dir / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH
    store = _read_phase_signal_store(path, now_ms)
    now_iso = _iso(now_ms)
    changed = 0
    for key in keys:
        if not key:
            continue
        entry = _normalize_phase_signal_entry(key, store["entries"].get(key))
        if phase == "light":
            entry["lightHits"] += 1
            entry["lastLightAt"] = now_iso
        else:
            entry["remHits"] += 1
            entry["lastRemAt"] = now_iso
        entry["updatedAt"] = now_iso
        store["entries"][key] = entry
        changed += 1
    if changed:
        store["updatedAt"] = now_iso
        _write_json_atomic(path, store)
    return changed


def record_daily_memory_flush(
    *,
    config: MemoryConfig,
    target: str,
    entry: str,
    now_ms: int,
) -> int:
    if not target.startswith("memory/") or not target.endswith(".md"):
        return 0
    path = config.workspace_dir / target
    if not path.exists():
        return 0
    file_lines = path.read_text(encoding="utf-8").splitlines()
    results = []
    for _, snippet in _candidate_lines(entry, 1):
        line_number = _find_line_number(file_lines, snippet)
        if line_number is None:
            continue
        results.append(
            {
                "path": target,
                "startLine": line_number,
                "endLine": line_number,
                "snippet": snippet,
                "score": 1,
            }
        )
    return record_short_term_recalls(
        config=config,
        query=entry,
        results=results,
        now_ms=now_ms,
        signal_type="daily",
    )


def run_short_term_promotion(
    *,
    config: MemoryConfig,
    store: Any,
    now_ms: int,
    timezone: str,
    limit: int = 5,
    min_score: float = DEFAULT_PROMOTION_MIN_SCORE,
    min_recall_count: int = DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    min_unique_queries: int = DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
) -> MemoryPromotionRun:
    with acquire_short_term_promotion_lock(config=config, now_ms=now_ms) as lock:
        if not lock.acquired:
            target = "MEMORY.md"
            return MemoryPromotionRun(
                target=target,
                raw_text="short-term promotion skipped: locked",
                parsed=ParsedFlushOutput(
                    should_write=False,
                    target=target,
                    entry="",
                    reason="promotion locked",
                ),
                diff="",
                indexed_files=0,
                chunks=store.count_chunks(),
                evaluated_candidates=[],
            )
        return _run_short_term_promotion_unlocked(
            config=config,
            store=store,
            now_ms=now_ms,
            timezone=timezone,
            limit=limit,
            min_score=min_score,
            min_recall_count=min_recall_count,
            min_unique_queries=min_unique_queries,
        )


def _run_short_term_promotion_unlocked(
    *,
    config: MemoryConfig,
    store: Any,
    now_ms: int,
    timezone: str,
    limit: int = 5,
    min_score: float = DEFAULT_PROMOTION_MIN_SCORE,
    min_recall_count: int = DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    min_unique_queries: int = DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
) -> MemoryPromotionRun:
    workspace = MemoryWorkspace(config.workspace_dir)
    target = "MEMORY.md"
    target_path = workspace.resolve_memory_path(target)
    before = _read_text_if_exists(target_path)
    evaluations = evaluate_short_term_promotion_candidates(
        config=config,
        now_ms=now_ms,
        min_score=min_score,
        min_recall_count=min_recall_count,
        min_unique_queries=min_unique_queries,
    )
    candidates = [
        _evaluation_to_candidate(evaluation)
        for evaluation in evaluations
        if not evaluation.reasons
    ][:limit]
    candidates = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    raw_text = (
        f"ranked {len(candidates)} short-term promotion candidate(s); "
        f"evaluated {len(evaluations)} candidate(s)"
    )
    indexed_files = 0
    reindex_error = None
    if candidates:
        entry = _build_promotion_section(candidates, now_ms, timezone)
        _append_to_memory(target_path, entry)
        _mark_promoted(config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH, candidates, now_ms)
        try:
            indexed_files = store.reindex(workspace)
        except Exception as exc:
            reindex_error = _exception_message(exc)
        parsed = ParsedFlushOutput(
            should_write=True,
            target=target,
            entry=entry.strip(),
            reason="short-term promotion",
        )
    else:
        parsed = ParsedFlushOutput(
            should_write=False,
            target=target,
            entry="",
            reason="no promotion candidates",
        )
    after = _read_text_if_exists(target_path)
    return MemoryPromotionRun(
        target=target,
        raw_text=raw_text,
        parsed=parsed,
        diff=_unified_diff(before, after, target),
        indexed_files=indexed_files,
        chunks=store.count_chunks(),
        evaluated_candidates=evaluations,
        reindex_error=reindex_error,
    )


def rank_short_term_promotion_candidates(
    *,
    config: MemoryConfig,
    now_ms: int,
    limit: int,
    min_score: float,
    min_recall_count: int,
    min_unique_queries: int,
) -> list[PromotionCandidate]:
    candidates = [
        _evaluation_to_candidate(evaluation)
        for evaluation in evaluate_short_term_promotion_candidates(
            config=config,
            now_ms=now_ms,
            min_score=min_score,
            min_recall_count=min_recall_count,
            min_unique_queries=min_unique_queries,
        )
        if not evaluation.reasons
    ]
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:limit]


def evaluate_short_term_promotion_candidates(
    *,
    config: MemoryConfig,
    now_ms: int,
    min_score: float,
    min_recall_count: int,
    min_unique_queries: int,
) -> list[PromotionEvaluation]:
    store = _read_store(config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH, now_ms)
    phase_signals = _read_phase_signal_store(
        config.workspace_dir / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
        now_ms,
    )
    phase_entries = phase_signals.get("entries", {})
    memory_text = _read_text_if_exists(config.workspace_dir / "MEMORY.md")
    markers = set(_extract_promotion_markers(memory_text))
    evaluations = []
    for raw in store["entries"].values():
        key = str(raw.get("key") or "")
        if not key or key in markers or raw.get("promotedAt"):
            continue
        recall_count = _int(raw.get("recallCount"), 0)
        daily_count = _int(raw.get("dailyCount"), 0)
        grounded_count = _int(raw.get("groundedCount"), 0)
        signal_count = recall_count + daily_count + grounded_count
        if signal_count <= 0:
            continue
        query_hashes = [value for value in raw.get("queryHashes", []) if isinstance(value, str)]
        unique_queries = len(set(query_hashes))
        total_score = float(raw.get("totalScore") or 0)
        avg_score = _clamp(total_score / signal_count)
        max_score = _clamp(float(raw.get("maxScore") or 0))
        last_recalled_at = str(raw.get("lastRecalledAt") or _iso(now_ms))
        age_days = max(0.0, (now_ms - _parse_ms(last_recalled_at, now_ms)) / DAY_MS)
        recall_days = [value for value in raw.get("recallDays", []) if isinstance(value, str)]
        context_diversity = max(unique_queries, len(set(recall_days)))
        concept_tags = tuple(
            value for value in raw.get("conceptTags", []) if isinstance(value, str) and value
        )
        components = _candidate_components(
            entry=raw,
            now_ms=now_ms,
            phase_entries=phase_entries if isinstance(phase_entries, dict) else {},
        )
        score = _clamp(sum(components.values()))
        reasons = []
        if score < min_score:
            reasons.append(f"score {score:.3f} < {min_score:.3f}")
        if signal_count < min_recall_count:
            reasons.append(f"signals {signal_count} < {min_recall_count}")
        if context_diversity < min_unique_queries:
            reasons.append(f"unique queries/days {context_diversity} < {min_unique_queries}")
        evaluations.append(
            PromotionEvaluation(
                key=key,
                path=str(raw.get("path") or ""),
                start_line=_int(raw.get("startLine"), 1),
                end_line=_int(raw.get("endLine"), _int(raw.get("startLine"), 1)),
                snippet=str(raw.get("snippet") or ""),
                recall_count=recall_count,
                daily_count=daily_count,
                grounded_count=grounded_count,
                signal_count=signal_count,
                avg_score=avg_score,
                max_score=max_score,
                unique_queries=unique_queries,
                context_diversity=context_diversity,
                score=score,
                reasons=tuple(reasons),
                age_days=age_days,
                concept_tags=concept_tags,
                components=components,
            )
        )
    return sorted(evaluations, key=lambda evaluation: evaluation.score, reverse=True)


def _evaluation_to_candidate(evaluation: PromotionEvaluation) -> PromotionCandidate:
    return PromotionCandidate(
        key=evaluation.key,
        path=evaluation.path,
        start_line=evaluation.start_line,
        end_line=evaluation.end_line,
        snippet=evaluation.snippet,
        recall_count=evaluation.recall_count,
        daily_count=evaluation.daily_count,
        grounded_count=evaluation.grounded_count,
        signal_count=evaluation.signal_count,
        avg_score=evaluation.avg_score,
        max_score=evaluation.max_score,
        unique_queries=evaluation.unique_queries,
        score=evaluation.score,
        first_recalled_at="",
        last_recalled_at="",
        age_days=evaluation.age_days,
        concept_tags=evaluation.concept_tags,
        components=dict(evaluation.components),
    )


def _candidate_components(
    *,
    entry: dict[str, Any],
    now_ms: int,
    phase_entries: dict[str, Any],
) -> dict[str, float]:
    recall_count = _int(entry.get("recallCount"), 0)
    daily_count = _int(entry.get("dailyCount"), 0)
    grounded_count = _int(entry.get("groundedCount"), 0)
    signal_count = recall_count + daily_count + grounded_count
    total_score = float(entry.get("totalScore") or 0)
    avg_score = total_score / max(1, signal_count)
    query_hashes = [value for value in entry.get("queryHashes", []) if isinstance(value, str)]
    recall_days = [value for value in entry.get("recallDays", []) if isinstance(value, str)]
    context_diversity = max(len(set(query_hashes)), len(set(recall_days)))
    last_recalled_at = str(entry.get("lastRecalledAt") or _iso(now_ms))
    age_days = max(0.0, (now_ms - _parse_ms(last_recalled_at, now_ms)) / DAY_MS)
    recency = math.exp(-(math.log(2) / DEFAULT_RECENCY_HALF_LIFE_DAYS) * age_days)
    concept_tags = [value for value in entry.get("conceptTags", []) if isinstance(value, str)]
    consolidation = max(
        _calculate_consolidation_component(recall_days),
        _clamp(max(0, grounded_count) / 3),
    )
    key = str(entry.get("key") or "")
    return {
        "frequency": 0.24 * _clamp(math.log1p(max(0, signal_count)) / math.log1p(10)),
        "relevance": 0.30 * _clamp(avg_score),
        "diversity": 0.15 * _clamp(max(0, context_diversity) / 5),
        "recency": 0.15 * _clamp(recency),
        "consolidation": 0.10 * consolidation,
        "conceptual": 0.06 * _clamp(len(concept_tags) / 6),
        "phaseBoost": _phase_signal_boost(phase_entries.get(key)),
    }


def _phase_signal_boost(entry: Any) -> float:
    if not isinstance(entry, dict):
        return 0.0
    light_hits = _int(entry.get("lightHits"), 0)
    rem_hits = _int(entry.get("remHits"), 0)
    light = min(0.06, max(0, light_hits) * 0.02)
    rem = min(0.09, max(0, rem_hits) * 0.03)
    return min(0.09, light + rem)


def _build_promotion_section(
    candidates: list[PromotionCandidate], now_ms: int, timezone: str
) -> str:
    del timezone
    section_date = datetime.fromtimestamp(now_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
    lines = ["", f"## Promoted From Short-Term Memory ({section_date})", ""]
    for candidate in candidates:
        source = f"{candidate.path}:{candidate.start_line}-{candidate.end_line}"
        lines.append(f"<!-- {PROMOTION_MARKER_PREFIX}{candidate.key} -->")
        lines.append(
            "- "
            + candidate.snippet
            + (
                f" [score={candidate.score:.3f} recalls={candidate.recall_count} "
                f"avg={candidate.avg_score:.3f} source={source}]"
            )
        )
    lines.append("")
    return "\n".join(lines)


def _read_store(path: Path, now_ms: int) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updatedAt": _iso(now_ms), "entries": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "updatedAt": _iso(now_ms), "entries": {}}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return {
        "version": 1,
        "updatedAt": str(raw.get("updatedAt") or _iso(now_ms)) if isinstance(raw, dict) else _iso(now_ms),
        "entries": entries if isinstance(entries, dict) else {},
    }


def _read_phase_signal_store(path: Path, now_ms: int) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updatedAt": _iso(now_ms), "entries": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"version": 1, "updatedAt": _iso(now_ms), "entries": {}}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        entries = {}
    active_entries = {}
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if _phase_signal_is_expired(entry, now_ms):
            continue
        active_entries[key] = _normalize_phase_signal_entry(key, entry)
    return {
        "version": 1,
        "updatedAt": str(raw.get("updatedAt") or _iso(now_ms)) if isinstance(raw, dict) else _iso(now_ms),
        "entries": active_entries,
    }


def _normalize_phase_signal_entry(key: str, entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}
    return {
        "key": key,
        "lightHits": _int(entry.get("lightHits"), 0),
        "remHits": _int(entry.get("remHits"), 0),
        "lastLightAt": entry.get("lastLightAt") if isinstance(entry.get("lastLightAt"), str) else None,
        "lastRemAt": entry.get("lastRemAt") if isinstance(entry.get("lastRemAt"), str) else None,
        "updatedAt": entry.get("updatedAt") if isinstance(entry.get("updatedAt"), str) else None,
    }


def _phase_signal_is_expired(entry: dict[str, Any], now_ms: int) -> bool:
    timestamps = [
        _parse_ms(value, -1)
        for value in (
            entry.get("updatedAt"),
            entry.get("lastLightAt"),
            entry.get("lastRemAt"),
        )
        if isinstance(value, str)
    ]
    latest = max(timestamps, default=-1)
    return latest >= 0 and now_ms - latest > PHASE_SIGNAL_DECAY_MS


def _lock_is_stale(lock_path: Path, now_ms: int) -> bool:
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        raw = None
    if isinstance(raw, dict):
        created_at = raw.get("createdAt")
        if isinstance(created_at, str):
            created_at_ms = _parse_ms(created_at, -1)
            if created_at_ms >= 0:
                return now_ms - created_at_ms > SHORT_TERM_LOCK_STALE_MS
    try:
        lock_mtime_ms = int(lock_path.stat().st_mtime * 1000)
    except FileNotFoundError:
        return False
    return now_ms - lock_mtime_ms > SHORT_TERM_LOCK_STALE_MS


def _read_short_term_lock_snapshot(lock_path: Path) -> _ShortTermLockSnapshot | None:
    try:
        stat = lock_path.stat()
        payload = lock_path.read_bytes()
    except (FileNotFoundError, OSError):
        return None
    owner_token = None
    try:
        raw = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raw = None
    if isinstance(raw, dict):
        raw_owner_token = raw.get("ownerToken")
        if isinstance(raw_owner_token, str):
            owner_token = raw_owner_token
    return _ShortTermLockSnapshot(
        mtime_ns=stat.st_mtime_ns,
        payload=payload,
        owner_token=owner_token,
    )


@contextmanager
def _short_term_promotion_guard(lock_path: Path) -> Iterator[None]:
    guard_path = lock_path.with_name(_SHORT_TERM_LOCK_GUARD_RELATIVE_PATH.name)
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    with guard_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _unlink_matching_short_term_lock(
    lock_path: Path, snapshot: _ShortTermLockSnapshot
) -> bool:
    current = _read_short_term_lock_snapshot(lock_path)
    if current is None:
        return True
    if current != snapshot:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    return True


def _release_short_term_promotion_lock(lock_path: Path, owner_token: str) -> None:
    with _short_term_promotion_guard(lock_path):
        try:
            raw = json.loads(lock_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
            return
        if not isinstance(raw, dict) or raw.get("ownerToken") != owner_token:
            return
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _write_store(path: Path, store: dict[str, Any]) -> None:
    _write_json_atomic(path, store)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _mark_promoted(path: Path, candidates: list[PromotionCandidate], now_ms: int) -> None:
    store = _read_store(path, now_ms)
    now_iso = _iso(now_ms)
    for candidate in candidates:
        entry = store["entries"].get(candidate.key)
        if isinstance(entry, dict):
            entry["promotedAt"] = now_iso
    store["updatedAt"] = now_iso
    _write_store(path, store)


def _append_to_memory(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    before = _read_text_if_exists(path)
    separator = "" if not before or before.endswith("\n") else "\n"
    path.write_text(f"{before}{separator}{content.strip()}\n", encoding="utf-8")


def _extract_promotion_markers(memory_text: str) -> list[str]:
    markers = []
    for line in memory_text.splitlines():
        marker = f"<!-- {PROMOTION_MARKER_PREFIX}"
        if line.startswith(marker) and line.endswith(" -->"):
            markers.append(line[len(marker) : -4].strip())
    return markers


def _normalize_snippet(raw: str) -> str:
    return " ".join(raw.strip().split())


def _candidate_lines(raw: str, start_line: int) -> list[tuple[int, str]]:
    candidates = []
    for offset, line in enumerate(raw.splitlines()):
        snippet = _normalize_snippet(line)
        if not snippet or snippet.startswith("#"):
            continue
        if snippet.startswith("- "):
            snippet = snippet[2:].strip()
        if snippet:
            candidates.append((start_line + offset, snippet))
    if candidates:
        return candidates
    snippet = _normalize_snippet(raw)
    return [(start_line, snippet)] if snippet else []


def _find_line_number(lines: list[str], snippet: str) -> int | None:
    normalized = _normalize_snippet(snippet)
    for index, line in enumerate(lines, start=1):
        candidate = _normalize_snippet(line)
        if candidate.startswith("- "):
            candidate = candidate[2:].strip()
        if candidate == normalized:
            return index
    return None


def _calculate_consolidation_component(recall_days: list[str]) -> float:
    if not recall_days:
        return 0.0
    if len(recall_days) == 1:
        return 0.2
    parsed = sorted(
        value
        for value in (_parse_day_ms(day) for day in recall_days)
        if value is not None
    )
    if len(parsed) <= 1:
        return 0.2
    span_days = max(0.0, (parsed[-1] - parsed[0]) / DAY_MS)
    spacing = _clamp(math.log1p(len(parsed) - 1) / math.log1p(4))
    span = _clamp(span_days / 7)
    return _clamp(0.55 * spacing + 0.45 * span)


def _derive_concept_tags(path: str, snippet: str, limit: int = 6) -> list[str]:
    words = []
    source = f"{Path(path).name} {snippet}".lower()
    for raw in source.replace("_", " ").replace("-", " ").split():
        token = "".join(char for char in raw if char.isalnum())
        if len(token) < 3 or token.isdigit() or token in words:
            continue
        words.append(token)
        if len(words) >= limit:
            break
    return words


def _hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _append_distinct(values: list[str], value: str, limit: int) -> list[str]:
    next_values = [item for item in values if item]
    if value and value not in next_values:
        next_values.append(value)
    return next_values[-limit:]


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _iso(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def _parse_ms(value: str, fallback: int) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return fallback


def _parse_day_ms(value: str) -> int | None:
    try:
        return int(datetime.fromisoformat(f"{value}T00:00:00+00:00").timestamp() * 1000)
    except ValueError:
        return None


def _exception_message(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _unified_diff(before: str, after: str, target: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
        )
    )
