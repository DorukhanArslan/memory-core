"""Scored short-term promotion into MEMORY.md.

Port of the ranking and apply halves of
``extensions/memory-core/src/short-term-promotion.ts`` at OpenClaw pin
4c42815348:

- :func:`evaluate_short_term_promotion_candidates` and
  :func:`rank_short_term_promotion_candidates` score every live recall entry
  with the upstream component weights (frequency 0.24, relevance 0.30,
  diversity 0.15, recency 0.15, consolidation 0.10, conceptual 0.06, plus the
  light/REM phase boost) and apply the score / signal / diversity / age gates
  (``rankShortTermPromotionCandidates``);
- :func:`run_short_term_promotion` ranks, rehydrates each candidate against its
  live daily note, reconciles existing promotion markers and appends one
  ``## Promoted From Short-Term Memory (<date>)`` section under the budget of
  :mod:`memory_core.memory_budget` (``applyShortTermPromotions``).

This is the only product path that changes MEMORY.md on its own (AGENTS.md
parity rules): candidates must pass the gates, so nothing is promoted by
keyword. Structural deviation: memory-core ranks and applies in one call under
one lock, where upstream's CLI passes ranked candidates to a separate apply.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_core.bootstrap._js import js_trim
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import (
    DAY_MS,
    clamp_score,
    exception_message,
    iso_ms,
    normalize_snippet,
    parse_day_ms,
    parse_ms,
    read_text_if_exists,
    to_int,
    unified_diff,
)
from memory_core.consolidation.markers import (
    extract_promotion_markers,
    format_promotion_marker,
    line_range_overlaps_dreaming_fence,
)
from memory_core.consolidation.policy import (
    DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
)
from memory_core.consolidation.recall import is_contaminated_dreaming_snippet
from memory_core.consolidation.store import (
    acquire_short_term_promotion_lock,
    phase_signal_store_path,
    read_phase_signal_store,
    read_recall_store,
    recall_store_path,
    write_recall_store,
)
from memory_core.memory_budget import DEFAULT_MEMORY_FILE_MAX_CHARS, compact_memory_for_budget
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.workspace import MemoryWorkspace

PROMOTION_TARGET = "MEMORY.md"
PROMOTION_SECTION_TITLE = "Promoted From Short-Term Memory"
LONG_TERM_MEMORY_HEADER = "# Long-Term Memory"
PROMOTION_COMPONENT_WEIGHTS = {
    "frequency": 0.24,
    "relevance": 0.30,
    "diversity": 0.15,
    "recency": 0.15,
    "consolidation": 0.10,
    "conceptual": 0.06,
}
_PROMOTED_SNIPPET_CHARS_PER_TOKEN_ESTIMATE = 4


class ReindexableStore(Protocol):
    """The index surface promotion needs: a full reindex and a chunk count."""

    def reindex(self, workspace: MemoryWorkspace) -> int: ...

    def count_chunks(self) -> int: ...


@dataclass(frozen=True)
class PromotionCandidate:
    """A recall entry that passed the gates (upstream ``PromotionCandidate`` subset)."""

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
    """Score, components and gate failures (``reasons``) of one live recall entry."""

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
class PromotionWriteOutcome:
    """Whether a promotion run wrote MEMORY.md, the written section and why."""

    should_write: bool
    target: str
    entry: str
    reason: str
    error: str | None = None


@dataclass(frozen=True)
class MemoryPromotionRun:
    """Result of :func:`run_short_term_promotion`.

    ``parsed`` holds the write outcome (field name kept from the demo flush
    result it mirrors); ``diff`` is a unified diff of MEMORY.md;
    ``evaluated_candidates`` lists every live entry with its gate reasons.
    ``applied_candidates``, ``appended``, ``reconciled_existing`` and
    ``compacted_dates`` mirror upstream ``ApplyShortTermPromotionsResult``
    (``applied`` is ``len(applied_candidates)``, ``compactedSections`` is
    ``len(compacted_dates)``).
    """

    target: str
    raw_text: str
    parsed: PromotionWriteOutcome
    diff: str
    indexed_files: int
    chunks: int
    evaluated_candidates: list[PromotionEvaluation]
    reindex_error: str | None = None
    applied_candidates: tuple[PromotionCandidate, ...] = ()
    appended: int = 0
    reconciled_existing: int = 0
    compacted_dates: tuple[str, ...] = ()


def run_short_term_promotion(
    *,
    config: MemoryConfig,
    store: ReindexableStore,
    now_ms: int,
    timezone: str,
    limit: int = 5,
    min_score: float = DEFAULT_PROMOTION_MIN_SCORE,
    min_recall_count: int = DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    min_unique_queries: int = DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    max_age_days: int = -1,
    recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
    memory_file_max_chars: int = DEFAULT_MEMORY_FILE_MAX_CHARS,
    max_promoted_snippet_tokens: int = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> MemoryPromotionRun:
    """Promote the top gated recall entries into ``MEMORY.md`` and reindex.

    Under the workspace promotion lock: evaluate every live entry, keep the
    ``limit`` best that pass the gates, rehydrate each against its current
    daily note (entries whose text is gone, or now inside a dreaming fence,
    are dropped), skip keys that already have a promotion marker
    (reconciled), append one dated section for the rest (dated in
    ``timezone``), compact older promotion sections to fit
    ``memory_file_max_chars``, mark every rehydrated entry ``promotedAt`` and
    reindex ``store`` when MEMORY.md changed. A held lock returns a
    ``"promotion locked"`` no-op result.

    New markers use ``identity.promotion_marker_prefix`` (the neutral
    ``memory-core-memory-promotion:`` by default; pass
    ``OPENCLAW_COMPAT_RUNTIME_IDENTITY`` for upstream's bytes); existing
    markers of either prefix reconcile.
    """
    with acquire_short_term_promotion_lock(config=config, now_ms=now_ms) as lock:
        if not lock.acquired:
            return MemoryPromotionRun(
                target=PROMOTION_TARGET,
                raw_text="short-term promotion skipped: locked",
                parsed=PromotionWriteOutcome(
                    should_write=False,
                    target=PROMOTION_TARGET,
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
            max_age_days=max_age_days,
            recency_half_life_days=recency_half_life_days,
            memory_file_max_chars=memory_file_max_chars,
            max_promoted_snippet_tokens=max_promoted_snippet_tokens,
            identity=identity,
        )


def rank_short_term_promotion_candidates(
    *,
    config: MemoryConfig,
    now_ms: int,
    limit: int,
    min_score: float,
    min_recall_count: int,
    min_unique_queries: int,
    max_age_days: int = -1,
    recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
) -> list[PromotionCandidate]:
    """Return up to ``limit`` gated candidates, best score first.

    ``max_age_days < 0`` disables the age gate. Entries already promoted or
    with contaminated snippets are never candidates.
    """
    candidates = [
        _evaluation_to_candidate(evaluation)
        for evaluation in evaluate_short_term_promotion_candidates(
            config=config,
            now_ms=now_ms,
            min_score=min_score,
            min_recall_count=min_recall_count,
            min_unique_queries=min_unique_queries,
            max_age_days=max_age_days,
            recency_half_life_days=recency_half_life_days,
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
    max_age_days: int = -1,
    recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
) -> list[PromotionEvaluation]:
    """Score every live recall entry and list the gates it fails, best score first."""
    store = read_recall_store(recall_store_path(config.workspace_dir), now_ms)
    phase_signals = read_phase_signal_store(phase_signal_store_path(config.workspace_dir), now_ms)
    phase_entries = phase_signals.get("entries", {})
    evaluations = []
    for raw in store["entries"].values():
        key = str(raw.get("key") or "")
        if not key or raw.get("promotedAt"):
            continue
        if is_contaminated_dreaming_snippet(str(raw.get("snippet") or "")):
            continue
        recall_count = to_int(raw.get("recallCount"), 0)
        daily_count = to_int(raw.get("dailyCount"), 0)
        grounded_count = to_int(raw.get("groundedCount"), 0)
        signal_count = recall_count + daily_count + grounded_count
        if signal_count <= 0:
            continue
        query_hashes = [value for value in raw.get("queryHashes", []) if isinstance(value, str)]
        unique_queries = len(set(query_hashes))
        total_score = float(raw.get("totalScore") or 0)
        avg_score = clamp_score(total_score / signal_count)
        max_score = clamp_score(float(raw.get("maxScore") or 0))
        last_recalled_at = str(raw.get("lastRecalledAt") or iso_ms(now_ms))
        age_days = max(0.0, (now_ms - parse_ms(last_recalled_at, now_ms)) / DAY_MS)
        recall_days = [value for value in raw.get("recallDays", []) if isinstance(value, str)]
        context_diversity = max(unique_queries, len(set(recall_days)))
        concept_tags = tuple(
            value for value in raw.get("conceptTags", []) if isinstance(value, str) and value
        )
        components = _candidate_components(
            entry=raw,
            now_ms=now_ms,
            phase_entries=phase_entries if isinstance(phase_entries, dict) else {},
            recency_half_life_days=recency_half_life_days,
        )
        score = _candidate_score(components)
        reasons = []
        if score < min_score:
            reasons.append(f"score {score:.3f} < {min_score:.3f}")
        if signal_count < min_recall_count:
            reasons.append(f"signals {signal_count} < {min_recall_count}")
        if context_diversity < min_unique_queries:
            reasons.append(f"unique queries/days {context_diversity} < {min_unique_queries}")
        if max_age_days >= 0 and age_days > max_age_days:
            reasons.append(f"age {age_days:.3f} > {max_age_days}")
        evaluations.append(
            PromotionEvaluation(
                key=key,
                path=str(raw.get("path") or ""),
                start_line=to_int(raw.get("startLine"), 1),
                end_line=to_int(raw.get("endLine"), to_int(raw.get("startLine"), 1)),
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


def format_memory_dreaming_day(now_ms: int, timezone: str | None = None) -> str:
    """``YYYY-MM-DD`` of ``now_ms`` in ``timezone`` (upstream ``formatMemoryDreamingDay``).

    An unknown timezone falls back to the host's local time.
    """
    if timezone:
        try:
            return datetime.fromtimestamp(now_ms / 1000, tz=ZoneInfo(timezone)).strftime(
                "%Y-%m-%d"
            )
        except ZoneInfoNotFoundError:
            pass
    return datetime.fromtimestamp(now_ms / 1000).strftime("%Y-%m-%d")


def _run_short_term_promotion_unlocked(
    *,
    config: MemoryConfig,
    store: ReindexableStore,
    now_ms: int,
    timezone: str,
    limit: int,
    min_score: float,
    min_recall_count: int,
    min_unique_queries: int,
    max_age_days: int,
    recency_half_life_days: float,
    memory_file_max_chars: int,
    max_promoted_snippet_tokens: int,
    identity: RuntimeIdentity,
) -> MemoryPromotionRun:
    workspace = MemoryWorkspace(config.workspace_dir)
    target = PROMOTION_TARGET
    target_path = workspace.resolve_memory_path(target)
    before = read_text_if_exists(target_path)
    evaluations = evaluate_short_term_promotion_candidates(
        config=config,
        now_ms=now_ms,
        min_score=min_score,
        min_recall_count=min_recall_count,
        min_unique_queries=min_unique_queries,
        max_age_days=max_age_days,
        recency_half_life_days=recency_half_life_days,
    )
    candidates = [
        _evaluation_to_candidate(evaluation) for evaluation in evaluations if not evaluation.reasons
    ][:limit]
    candidates = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    rehydrated_candidates = [
        rehydrated
        for candidate in candidates
        if (rehydrated := _rehydrate_promotion_candidate(config.workspace_dir, candidate))
        is not None
    ]
    existing_markers = set(extract_promotion_markers(before))
    to_append = [
        candidate for candidate in rehydrated_candidates if candidate.key not in existing_markers
    ]
    raw_text = (
        f"ranked {len(candidates)} short-term promotion candidate(s); "
        f"evaluated {len(evaluations)} candidate(s); "
        f"rehydrated {len(rehydrated_candidates)}; "
        f"appending {len(to_append)}; reconciled {len(rehydrated_candidates) - len(to_append)}"
    )
    indexed_files = 0
    reindex_error = None
    compacted_dates: tuple[str, ...] = ()
    if rehydrated_candidates:
        entry = (
            _build_promotion_section(
                to_append, now_ms, timezone, max_promoted_snippet_tokens, identity
            )
            if to_append
            else ""
        )
        if to_append:
            compacted_dates = _append_to_memory(
                target_path, entry, memory_file_max_chars=memory_file_max_chars
            )
        _mark_promoted(recall_store_path(config.workspace_dir), rehydrated_candidates, now_ms)
        if to_append:
            try:
                indexed_files = store.reindex(workspace)
            except Exception as exc:
                reindex_error = exception_message(exc)
        parsed = PromotionWriteOutcome(
            should_write=bool(to_append),
            target=target,
            entry=entry.strip(),
            reason="short-term promotion" if to_append else "short-term promotion reconciled",
        )
    else:
        parsed = PromotionWriteOutcome(
            should_write=False,
            target=target,
            entry="",
            reason="no live promotion candidates" if candidates else "no promotion candidates",
        )
    after = read_text_if_exists(target_path)
    return MemoryPromotionRun(
        target=target,
        raw_text=raw_text,
        parsed=parsed,
        diff=unified_diff(before, after, target),
        indexed_files=indexed_files,
        chunks=store.count_chunks(),
        evaluated_candidates=evaluations,
        reindex_error=reindex_error,
        applied_candidates=tuple(rehydrated_candidates),
        appended=len(to_append),
        reconciled_existing=len(rehydrated_candidates) - len(to_append),
        compacted_dates=compacted_dates,
    )


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
    recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
) -> dict[str, float]:
    recall_count = to_int(entry.get("recallCount"), 0)
    daily_count = to_int(entry.get("dailyCount"), 0)
    grounded_count = to_int(entry.get("groundedCount"), 0)
    signal_count = recall_count + daily_count + grounded_count
    total_score = float(entry.get("totalScore") or 0)
    avg_score = total_score / max(1, signal_count)
    query_hashes = [value for value in entry.get("queryHashes", []) if isinstance(value, str)]
    recall_days = [value for value in entry.get("recallDays", []) if isinstance(value, str)]
    context_diversity = max(len(set(query_hashes)), len(set(recall_days)))
    last_recalled_at = str(entry.get("lastRecalledAt") or iso_ms(now_ms))
    age_days = max(0.0, (now_ms - parse_ms(last_recalled_at, now_ms)) / DAY_MS)
    half_life_days = (
        recency_half_life_days
        if math.isfinite(recency_half_life_days) and recency_half_life_days > 0
        else DEFAULT_RECENCY_HALF_LIFE_DAYS
    )
    recency = math.exp(-(math.log(2) / half_life_days) * age_days)
    concept_tags = [value for value in entry.get("conceptTags", []) if isinstance(value, str)]
    consolidation = max(
        _calculate_consolidation_component(recall_days),
        clamp_score(max(0, grounded_count) / 3),
    )
    key = str(entry.get("key") or "")
    return {
        "frequency": clamp_score(math.log1p(max(0, signal_count)) / math.log1p(10)),
        "relevance": clamp_score(avg_score),
        "diversity": clamp_score(max(0, context_diversity) / 5),
        "recency": clamp_score(recency),
        "consolidation": consolidation,
        "conceptual": clamp_score(len(concept_tags) / 6),
        "phaseBoost": _phase_signal_boost(phase_entries.get(key)),
    }


def _candidate_score(components: dict[str, float]) -> float:
    # Left-to-right float addition like the upstream expression
    # (short-term-promotion.ts rankShortTermPromotionCandidates). Python 3.12's
    # built-in sum() compensates rounding and can differ in the last ulp.
    weighted = 0.0
    for key, weight in PROMOTION_COMPONENT_WEIGHTS.items():
        weighted += weight * float(components.get(key) or 0)
    return clamp_score(weighted + float(components.get("phaseBoost") or 0))


def _phase_signal_boost(entry: Any) -> float:
    if not isinstance(entry, dict):
        return 0.0
    light_hits = to_int(entry.get("lightHits"), 0)
    rem_hits = to_int(entry.get("remHits"), 0)
    light = min(0.06, max(0, light_hits) * 0.02)
    rem = min(0.09, max(0, rem_hits) * 0.03)
    return min(0.09, light + rem)


def _calculate_consolidation_component(recall_days: list[str]) -> float:
    if not recall_days:
        return 0.0
    if len(recall_days) == 1:
        return 0.2
    parsed = sorted(
        value for value in (parse_day_ms(day) for day in recall_days) if value is not None
    )
    if len(parsed) <= 1:
        return 0.2
    span_days = max(0.0, (parsed[-1] - parsed[0]) / DAY_MS)
    spacing = clamp_score(math.log1p(len(parsed) - 1) / math.log1p(4))
    span = clamp_score(span_days / 7)
    return clamp_score(0.55 * spacing + 0.45 * span)


def _build_promotion_section(
    candidates: list[PromotionCandidate],
    now_ms: int,
    timezone: str,
    max_promoted_snippet_tokens: int = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> str:
    section_date = format_memory_dreaming_day(now_ms, timezone)
    lines = ["", f"## {PROMOTION_SECTION_TITLE} ({section_date})", ""]
    for candidate in candidates:
        source = f"{candidate.path}:{candidate.start_line}-{candidate.end_line}"
        lines.append(format_promotion_marker(candidate.key, identity))
        # Cap only the visible MEMORY.md text; the recall store keeps the full
        # rehydrated snippet for ranking and provenance.
        snippet = _format_promoted_snippet_for_memory(
            candidate.snippet, max_promoted_snippet_tokens
        )
        lines.append(
            "- "
            + snippet
            + (
                f" [score={candidate.score:.3f} recalls={candidate.recall_count} "
                f"avg={candidate.avg_score:.3f} source={source}]"
            )
        )
    lines.append("")
    return "\n".join(lines)


def _resolve_promoted_snippet_char_limit(max_tokens: int) -> int:
    try:
        token_limit = math.floor(float(max_tokens))
    except (TypeError, ValueError):
        token_limit = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS
    if not math.isfinite(float(max_tokens)) or token_limit < 0:
        token_limit = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS
    # Inexpensive display-size guard, not a tokenizer contract.
    return token_limit * _PROMOTED_SNIPPET_CHARS_PER_TOKEN_ESTIMATE


def _truncate_promoted_snippet(snippet: str, max_tokens: int) -> str:
    limit = _resolve_promoted_snippet_char_limit(max_tokens)
    if limit == 0 or len(snippet) <= limit:
        return snippet
    hard_limit = snippet[:limit]
    sentence_boundary = max(
        hard_limit.rfind(". "),
        hard_limit.rfind("! "),
        hard_limit.rfind("? "),
    )
    word_boundary = hard_limit.rfind(" ")
    if sentence_boundary >= math.floor(limit * 0.55):
        cut_at = sentence_boundary + 1
    elif word_boundary >= math.floor(limit * 0.65):
        cut_at = word_boundary
    else:
        cut_at = limit
    return f"{hard_limit[:cut_at].rstrip()}..."


def _format_promoted_snippet_for_memory(raw_snippet: str, max_tokens: int) -> str:
    normalized = re.sub(
        r"^[-*+] +", "", normalize_snippet(raw_snippet or "(no snippet captured)")
    ).strip()
    return _truncate_promoted_snippet(normalized or "(no snippet captured)", max_tokens)


def _mark_promoted(path: Path, candidates: list[PromotionCandidate], now_ms: int) -> None:
    store = read_recall_store(path, now_ms)
    now_iso = iso_ms(now_ms)
    for candidate in candidates:
        entry = store["entries"].get(candidate.key)
        if isinstance(entry, dict):
            # The store keeps the full rehydrated snippet and relocated range;
            # only the MEMORY.md presentation is token-capped.
            entry["startLine"] = candidate.start_line
            entry["endLine"] = candidate.end_line
            entry["snippet"] = candidate.snippet
            entry["promotedAt"] = now_iso
    store["updatedAt"] = now_iso
    write_recall_store(path, store)


def _append_to_memory(
    path: Path, section: str, memory_file_max_chars: int = DEFAULT_MEMORY_FILE_MAX_CHARS
) -> tuple[str, ...]:
    """Write ``section`` below the budget-compacted MEMORY.md; returns dropped section dates.

    Mirrors the write in upstream ``applyShortTermPromotions``: older promotion
    sections are dropped until the file fits ``memory_file_max_chars``, an
    empty (or whitespace-only) result gets the ``# Long-Term Memory`` header,
    and the section (which starts with a blank line) follows the kept text.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_text_if_exists(path)
    budget_chars = (
        max(0, math.floor(memory_file_max_chars))
        if isinstance(memory_file_max_chars, int | float) and math.isfinite(memory_file_max_chars)
        else DEFAULT_MEMORY_FILE_MAX_CHARS
    )
    compaction = compact_memory_for_budget(
        existing_memory=existing, new_section=section, budget_chars=budget_chars
    )
    base = compaction.compacted
    header = "" if js_trim(base) else f"{LONG_TERM_MEMORY_HEADER}\n\n"
    base_with_newline = base if not base or base.endswith("\n") else f"{base}\n"
    path.write_text(f"{header}{base_with_newline}{section}", encoding="utf-8")
    return compaction.dropped_dates


def _normalize_memory_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def _resolve_short_term_source_path_candidates(
    workspace_dir: Path, candidate_path: str
) -> list[Path]:
    normalized = _normalize_memory_path(candidate_path)
    basenames = [normalized]
    if not normalized.startswith("memory/"):
        basenames.append((Path("memory") / Path(normalized).name).as_posix())
    seen = set()
    resolved = []
    for relative_path in basenames:
        source_path = (workspace_dir / relative_path).resolve()
        if source_path in seen:
            continue
        seen.add(source_path)
        resolved.append(source_path)
    return resolved


def _normalize_range_snippet(lines: list[str], start_line: int, end_line: int) -> str:
    start_index = max(0, start_line - 1)
    end_index = min(len(lines), end_line)
    if start_index >= end_index:
        return ""
    return normalize_snippet(" ".join(lines[start_index:end_index]))


def _compare_candidate_window(target_snippet: str, window_snippet: str) -> tuple[bool, int]:
    if not target_snippet or not window_snippet:
        return False, 0
    if window_snippet == target_snippet:
        return True, 3
    if target_snippet in window_snippet:
        return True, 2
    if window_snippet in target_snippet:
        return True, 1
    return False, 0


def _relocate_candidate_range(
    lines: list[str], candidate: PromotionCandidate
) -> tuple[int, int, str] | None:
    target_snippet = normalize_snippet(candidate.snippet)
    preferred_span = max(1, candidate.end_line - candidate.start_line + 1)
    if not target_snippet:
        fallback_snippet = _normalize_range_snippet(lines, candidate.start_line, candidate.end_line)
        if not fallback_snippet:
            return None
        return candidate.start_line, candidate.end_line, fallback_snippet

    exact_snippet = _normalize_range_snippet(lines, candidate.start_line, candidate.end_line)
    if exact_snippet == target_snippet:
        return candidate.start_line, candidate.end_line, exact_snippet

    max_span = min(len(lines), max(preferred_span + 3, 8))
    best_match: tuple[int, int, str, int, int] | None = None
    for start_index in range(len(lines)):
        for span in range(1, max_span + 1):
            if start_index + span > len(lines):
                break
            start_line = start_index + 1
            end_line = start_index + span
            snippet = _normalize_range_snippet(lines, start_line, end_line)
            matched, quality = _compare_candidate_window(target_snippet, snippet)
            if not matched:
                continue
            distance = abs(start_line - candidate.start_line)
            if best_match is None:
                best_match = (start_line, end_line, snippet, quality, distance)
                continue
            best_start, best_end, _, best_quality, best_distance = best_match
            best_span_delta = abs(best_end - best_start + 1 - preferred_span)
            span_delta = abs(span - preferred_span)
            if (
                quality > best_quality
                or (quality == best_quality and distance < best_distance)
                or (
                    quality == best_quality
                    and distance == best_distance
                    and span_delta < best_span_delta
                )
            ):
                best_match = (start_line, end_line, snippet, quality, distance)

    if best_match is None:
        return None
    start_line, end_line, snippet, _, _ = best_match
    return start_line, end_line, snippet


def _rehydrate_promotion_candidate(
    workspace_dir: Path, candidate: PromotionCandidate
) -> PromotionCandidate | None:
    for source_path in _resolve_short_term_source_path_candidates(workspace_dir, candidate.path):
        try:
            raw_source = source_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        lines = raw_source.splitlines()
        relocated = _relocate_candidate_range(lines, candidate)
        if relocated is None:
            continue
        start_line, end_line, snippet = relocated
        if line_range_overlaps_dreaming_fence(lines, start_line, end_line):
            continue
        return replace(
            candidate,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
        )
    return None
