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

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_core.bootstrap._js import (
    js_json_stringify,
    js_to_well_formed,
    js_trim_end,
    locale_sort_key,
    utf16_len,
    utf16_slice,
)
from memory_core.config import MemoryConfig
from memory_core.project_name import DISPLAY_NAME
from memory_core.index.cjk_chars import truncate_utf16_safe
from memory_core.consolidation._util import (
    DAY_MS,
    clamp_score,
    exception_message,
    iso_ms,
    js_to_fixed,
    normalize_snippet,
    parse_day_ms,
    parse_ms,
    read_text_if_exists,
    to_int,
    unified_diff,
)
from memory_core.consolidation.artifact_provenance import (
    MemoryArtifactProvenance,
    MemoryArtifactProvenanceStore,
    daily_file_quarantine_by_path,
    with_daily_file_quarantine,
)
from memory_core.consolidation.artifacts import read_memory_preimages
from memory_core.consolidation.file_lock import (
    MEMORY_WRITE_LOCK_OPTIONS,
    resolve_memory_promotion_lock_target,
    with_file_lock,
)
from memory_core.consolidation.host_events import truncate_utf8 as _truncate_utf8
from memory_core.consolidation.host_events import utf8_len as _utf8_len
from memory_core.consolidation.markers import (
    extract_promotion_markers,
    format_promotion_marker,
    line_range_overlaps_dreaming_fence,
)
from memory_core.consolidation.origins import MemoryEntryOriginLedger, prune_memory_entry_origins
from memory_core.consolidation.policy import (
    DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT,
    DEFAULT_DEEP_DREAMING_MAX_PRIOR_ENTRY_LOSS_FRACTION,
    DEFAULT_DEEP_DREAMING_MIN_SCORE,
    DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
)
from memory_core.consolidation.recall import (
    is_contaminated_dreaming_snippet,
    is_short_term_session_corpus_path,
    is_workspace_contained_path,
    normalize_memory_path,
)
from memory_core.consolidation.store import (
    acquire_short_term_promotion_lock,
    hold_workspace_lock_marker,
    phase_signal_store_path,
    read_phase_signal_store,
    read_recall_store,
    recall_store_lock,
    recall_store_path,
    write_recall_store,
)
from memory_core.memory_budget import DEFAULT_MEMORY_FILE_MAX_CHARS, build_budgeted_memory_append
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.workspace import MemoryWorkspace

if TYPE_CHECKING:
    from memory_core.consolidation.llm_consolidation import (
        DeepConsolidation,
        MemoryConsolidationResult,
    )

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
    recall_days: tuple[str, ...] = ()
    claim_hash: str | None = None
    project_key: str | None = None
    provenance: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        """The candidate in upstream's ``PromotionCandidate`` JSON shape (camelCase, optional keys omitted)."""
        out: dict[str, Any] = {
            "key": self.key,
            "path": self.path,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "source": "memory",
            "snippet": self.snippet,
            "recallCount": self.recall_count,
            "dailyCount": self.daily_count,
            "groundedCount": self.grounded_count,
            "signalCount": self.signal_count,
            "avgScore": self.avg_score,
            "maxScore": self.max_score,
            "uniqueQueries": self.unique_queries,
        }
        if self.claim_hash:
            out["claimHash"] = self.claim_hash
        if self.project_key:
            out["projectKey"] = self.project_key
        if self.promoted_at:
            out["promotedAt"] = self.promoted_at
        out.update(
            {
                "firstRecalledAt": self.first_recalled_at,
                "lastRecalledAt": self.last_recalled_at,
                "ageDays": self.age_days,
                "score": self.score,
                "recallDays": list(self.recall_days),
                "conceptTags": list(self.concept_tags),
                "components": dict(self.components),
            }
        )
        if self.provenance is not None:
            out["provenance"] = self.provenance
        return out

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> PromotionCandidate:
        """Read a candidate ranked elsewhere (the host's own ranking, or upstream's ``rankShortTermPromotionCandidates``)."""
        return cls(
            key=str(raw["key"]),
            path=str(raw["path"]),
            start_line=int(raw["startLine"]),
            end_line=int(raw["endLine"]),
            snippet=str(raw.get("snippet") or ""),
            recall_count=int(raw.get("recallCount") or 0),
            daily_count=int(raw.get("dailyCount") or 0),
            grounded_count=int(raw.get("groundedCount") or 0),
            signal_count=int(raw.get("signalCount") or 0),
            avg_score=float(raw.get("avgScore") or 0),
            max_score=float(raw.get("maxScore") or 0),
            unique_queries=int(raw.get("uniqueQueries") or 0),
            score=float(raw.get("score") or 0),
            first_recalled_at=str(raw.get("firstRecalledAt") or ""),
            last_recalled_at=str(raw.get("lastRecalledAt") or ""),
            promoted_at=raw.get("promotedAt") or None,
            age_days=float(raw.get("ageDays") or 0),
            concept_tags=tuple(raw.get("conceptTags") or ()),
            components={k: float(v) for k, v in (raw.get("components") or {}).items()},
            recall_days=tuple(raw.get("recallDays") or ()),
            claim_hash=raw.get("claimHash") or None,
            project_key=raw.get("projectKey") or None,
            provenance=raw.get("provenance") if isinstance(raw.get("provenance"), dict) else None,
        )


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
    first_recalled_at: str = ""
    last_recalled_at: str = ""
    recall_days: tuple[str, ...] = ()
    claim_hash: str | None = None
    project_key: str | None = None
    provenance: dict[str, Any] | None = None


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

    ``summary`` is a one-line account of the run, ``outcome`` the write
    outcome; ``diff`` is a unified diff of MEMORY.md;
    ``evaluated_candidates`` lists every live entry with its gate reasons.
    ``applied_candidates``, ``appended``, ``reconciled_existing`` and
    ``compacted_dates`` mirror upstream ``ApplyShortTermPromotionsResult``
    (``applied`` is ``len(applied_candidates)``, ``compactedSections`` is
    ``len(compacted_dates)``).
    """

    target: str
    summary: str
    outcome: PromotionWriteOutcome
    diff: str
    indexed_files: int
    chunks: int
    evaluated_candidates: list[PromotionEvaluation]
    reindex_error: str | None = None
    applied_candidates: tuple[PromotionCandidate, ...] = ()
    appended: int = 0
    reconciled_existing: int = 0
    compacted_dates: tuple[str, ...] = ()
    # Candidates the "memory budget" category deferred: the write would have exceeded
    # ``memory_file_max_chars`` within ``max_prior_entry_loss_fraction``, so MEMORY.md is unchanged.
    deferred_candidates: tuple[PromotionCandidate, ...] = ()
    deferred_reason: str | None = None
    # Set when an LLM consolidation rewrote MEMORY.md (``outcome.reason`` is then
    # "short-term promotion consolidated"), or the reason a planned rewrite was skipped.
    consolidation: MemoryConsolidationResult | None = None
    consolidation_skipped_reason: str | None = None
    # Every ranked candidate that did not reach MEMORY.md, with upstream's category and reason
    # (``rejectedCandidates``). ``host_event`` is the ``memory.promotion.applied`` event of the run.
    rejected_candidates: tuple[PromotionRejection, ...] = ()
    host_event: dict[str, Any] | None = None


def run_short_term_promotion(
    *,
    config: MemoryConfig,
    store: ReindexableStore,
    now_ms: int,
    timezone: str,
    limit: int = 5,
    min_score: float = DEFAULT_DEEP_DREAMING_MIN_SCORE,
    min_recall_count: int = DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT,
    min_unique_queries: int = DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES,
    max_age_days: int = -1,
    recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
    memory_file_max_chars: int = DEFAULT_MEMORY_FILE_MAX_CHARS,
    max_promoted_snippet_tokens: int = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    max_prior_entry_loss_fraction: float = DEFAULT_DEEP_DREAMING_MAX_PRIOR_ENTRY_LOSS_FRACTION,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
    consolidation: DeepConsolidation | None = None,
    candidates: Sequence[PromotionCandidate] | None = None,
    agent_id: str | None = None,
    workspace_agent_ids: Sequence[str] = (),
    origins: MemoryEntryOriginLedger | None = None,
    artifact_provenance: MemoryArtifactProvenanceStore | None = None,
    state_dir: str | Path | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    lock_observer: Callable[[str, Path], None] | None = None,
) -> MemoryPromotionRun:
    """Promote the top gated recall entries into ``MEMORY.md`` and reindex.

    Port of ``rankShortTermPromotionCandidates`` plus ``applyShortTermPromotions``: ranks (or takes
    the host's ``candidates``, upstream's CLI path), applies the apply-stage gates and reports every
    candidate that did not reach MEMORY.md in ``rejected_candidates`` with upstream's category
    (``origin``, ``consolidation origin/session``, ``contamination``, ``already promoted``,
    ``score threshold``, ``signal threshold``, ``query threshold``, ``age threshold``,
    ``selection limit``, ``source rehydration``, ``source changed``, ``memory budget``,
    ``candidate changed``). Each selected candidate is rehydrated against its current daily note
    (entries whose text is gone, or now inside a dreaming fence, are rejected), keys that already
    have a promotion marker are reconciled, one dated section is appended for the rest (dated in
    ``timezone``), older promotion sections are compacted to fit ``memory_file_max_chars``, every
    committed entry is marked ``promotedAt`` and ``store`` is reindexed when MEMORY.md changed.

    Locks, in upstream's order: the sidecar file lock
    ``<state_dir>/locks/memory-promotion-<sha256 of the workspace path>.lock``
    (:mod:`memory_core.consolidation.file_lock`; ``state_dir`` defaults to
    ``<workspace>/memory/.dreams``) and inside it the workspace promotion lock, which the DREAMS.md
    writers re-enter. A held workspace lock returns a ``"promotion locked"`` no-op result (upstream
    waits 10 s and throws). A held or stale file lock raises
    :class:`~memory_core.consolidation.file_lock.FileLockError`.

    ``on_event`` receives the stored form of the ``memory.promotion.applied`` host event
    (:func:`build_promotion_applied_event`) after the locks are released, once per run that
    rehydrated a candidate; nothing is sent over a network. With ``agent_id`` and an ``origins``
    ledger, consolidation reserves the origins of merged entries and the commit prunes the origins
    nothing retains any more (``workspace_agent_ids`` are the sibling agents of the workspace).

    ``artifact_provenance`` (upstream: the plugin-state store behind ``listMemoryArtifactProvenance``)
    carries the daily-file quarantine: a candidate whose daily file the flush recorded as
    ``untrusted`` is itself ``untrusted`` and is rejected by the ``origin`` gate, whatever the recall
    store says (:func:`~memory_core.consolidation.artifact_provenance.with_daily_file_quarantine`).
    Without a store no file is quarantined.

    New markers use ``identity.promotion_marker_prefix`` (the neutral
    ``memory-core-memory-promotion:`` by default; pass
    ``OPENCLAW_COMPAT_RUNTIME_IDENTITY`` for upstream's bytes); existing
    markers of either prefix reconcile.

    ``consolidation`` (a :class:`~memory_core.consolidation.llm_consolidation.DeepConsolidation`)
    stands for upstream's ``options.consolidation``: any object turns on the consolidation
    origin/session filter and the lock-time candidate rules; with ``options.enabled`` and a host
    model the model also plans a MEMORY.md rewrite *before* the locks are taken, and under the
    locks the plan is re-checked (same candidates, MEMORY.md unchanged), applied, preimaged
    (``memory/.dreams/consolidation-preimages.json``), committed and summarized in DREAMS.md. Any
    failed step falls back to the deterministic append below, so no eligible candidate is lost.
    """
    from memory_core.consolidation.llm_consolidation import plan_deep_consolidation

    active = consolidation if consolidation is not None and consolidation.active else None
    gates: dict[str, Any] = {
        "limit": limit,
        "min_score": min_score,
        "min_recall_count": min_recall_count,
        "min_unique_queries": min_unique_queries,
        "max_age_days": max_age_days,
    }
    ranked = (
        list(candidates)
        if candidates is not None
        else rank_short_term_promotion_candidates(
            config=config,
            now_ms=now_ms,
            recency_half_life_days=recency_half_life_days,
            **gates,
        )
    )
    evaluations = evaluate_short_term_promotion_candidates(
        config=config,
        now_ms=now_ms,
        min_score=min_score,
        min_recall_count=min_recall_count,
        min_unique_queries=min_unique_queries,
        max_age_days=max_age_days,
        recency_half_life_days=recency_half_life_days,
    )
    plan = _plan_apply_stage(
        config=config,
        ranked=ranked,
        now_ms=now_ms,
        consolidation=consolidation is not None,
        daily_provenance=daily_file_quarantine_by_path(
            artifact_provenance.list(config.workspace_dir) if artifact_provenance is not None else []
        ),
        **gates,
    )
    preplan: _PrePlan | None = None
    if active is not None:
        preplan = _plan_before_lock(
            config=config,
            consolidation=active,
            plan=plan,
            now_ms=now_ms,
            memory_file_max_chars=memory_file_max_chars,
            max_promoted_snippet_tokens=max_promoted_snippet_tokens,
            max_prior_entry_loss_fraction=max_prior_entry_loss_fraction,
            identity=identity,
            plan_fn=plan_deep_consolidation,
        )
    lock_target = resolve_memory_promotion_lock_target(
        state_dir if state_dir is not None else Path(config.workspace_dir) / "memory" / ".dreams",
        config.workspace_dir,
    )
    with (
        with_file_lock(lock_target, MEMORY_WRITE_LOCK_OPTIONS, observer=lock_observer),
        acquire_short_term_promotion_lock(config=config, now_ms=now_ms) as lock,
    ):
        if not lock.acquired:
            return MemoryPromotionRun(
                target=PROMOTION_TARGET,
                summary="short-term promotion skipped: locked",
                outcome=PromotionWriteOutcome(
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
        with hold_workspace_lock_marker(Path(config.workspace_dir)):
            run, commit = _commit_promotion(
                config=config,
                store=store,
                now_ms=now_ms,
                timezone=timezone,
                memory_file_max_chars=memory_file_max_chars,
                max_promoted_snippet_tokens=max_promoted_snippet_tokens,
                max_prior_entry_loss_fraction=max_prior_entry_loss_fraction,
                identity=identity,
                consolidation=consolidation,
                plan=plan,
                preplan=preplan,
                ranked=ranked,
                evaluations=evaluations,
                agent_id=agent_id,
                origin_agent_ids=_origin_agent_ids(agent_id, workspace_agent_ids),
                origins=origins,
            )
    if commit is not None and commit.result is None and commit.skipped_reason and consolidation is not None:
        from memory_core.consolidation.llm_consolidation import record_deep_consolidation_history

        # Upstream writes the "rewrite skipped" note after releasing both locks.
        record_deep_consolidation_history(consolidation, config.workspace_dir, commit, now_ms=now_ms)
    if plan.rehydrated:
        event = build_promotion_applied_event(
            memory_path=str(Path(config.workspace_dir) / PROMOTION_TARGET),
            applied_candidates=run.applied_candidates,
            now_ms=now_ms,
        )
        run = replace(run, host_event=event)
        if on_event is not None:
            on_event(event)
    return run


def _origin_agent_ids(agent_id: str | None, workspace_agent_ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys([agent_id, *workspace_agent_ids])) if agent_id else []


@dataclass(frozen=True)
class _PrePlan:
    """A rewrite planned before the lock, with what the lock-time re-check compares against."""

    plan: Any
    base_hash: str
    fingerprints: dict[str, str]


@dataclass
class _ApplyPlan:
    """What the pre-lock half of ``applyShortTermPromotions`` decided."""

    current: list[PromotionCandidate]
    rejections: dict[str, tuple[PromotionRejectionCategory, str]]
    rehydrated: list[PromotionCandidate]
    store_fingerprints: dict[str, str]
    source_fingerprints: dict[str, str]

    def reject(self, key: str, category: PromotionRejectionCategory, reason: str) -> None:
        self.rejections[key] = (category, reason)

    def describe(self, candidate: PromotionCandidate) -> PromotionRejection:
        # Late revalidation has several causes; no more specific gate is attributed.
        category, reason = self.rejections.get(
            candidate.key, ("candidate changed", "candidate changed during apply")
        )
        return PromotionRejection(candidate=candidate, reason=reason, category=category)


def is_promotion_origin_blocked(provenance: dict[str, Any] | None) -> bool:
    """``isPromotionOriginBlocked``: untrusted and system origins never promote on any path."""
    return isinstance(provenance, dict) and provenance.get("originClass") in ("untrusted", "system")


def _js_number_text(value: float) -> str:
    """``String(value)`` of a finite JavaScript number, for the gate values in rejection reasons."""
    if float(value).is_integer() and abs(value) < 1e21:
        return str(int(value))
    return format(Decimal(repr(float(value))), "f")


def _to_finite_score(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) and 0 <= number <= 1 else fallback


def _to_finite_non_negative_int(value: Any, fallback: int) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    floored = math.floor(number)
    return fallback if floored < 0 else floored


def _with_authoritative_provenance(
    candidate: PromotionCandidate, provenance: dict[str, Any] | None
) -> PromotionCandidate:
    if is_promotion_origin_blocked(candidate.provenance):
        return candidate
    return replace(candidate, provenance=provenance if provenance else None)


def _readable_store_entries(store: dict[str, Any]) -> dict[str, Any]:
    """The recall entries upstream's ``readStore`` keeps: it drops rows without a memory source or a
    path and line range, and rows whose snippet is pipeline scaffolding."""
    kept: dict[str, Any] = {}
    for key, entry in store["entries"].items():
        if not isinstance(entry, dict):
            continue
        path = normalize_memory_path(str(entry.get("path") or ""))
        lines_ok = all(
            isinstance(entry.get(name), int | float)
            and not isinstance(entry.get(name), bool)
            and float(entry[name]).is_integer()
            for name in ("startLine", "endLine")
        )
        if not path or not lines_ok or entry.get("source") != "memory":
            continue
        snippet = normalize_snippet(str(entry.get("snippet") or ""))
        if snippet and is_contaminated_dreaming_snippet(
            snippet, allow_transcript_turn_snippet=is_short_term_session_corpus_path(path)
        ):
            continue
        kept[key] = entry
    return kept


def _store_entry_fingerprint(entry: Any) -> str:
    return json.dumps(entry if isinstance(entry, dict) else None, sort_keys=True, default=str)


def _promotion_source_fingerprint(workspace_dir: Path, candidate: PromotionCandidate) -> str:
    for source_path in _resolve_short_term_source_path_candidates(workspace_dir, candidate.path):
        try:
            content = source_path.read_bytes()
        except FileNotFoundError:
            continue
        return hashlib.sha256(content).hexdigest()
    return "missing"


def _plan_apply_stage(
    *,
    config: MemoryConfig,
    ranked: Sequence[PromotionCandidate],
    now_ms: int,
    consolidation: bool,
    daily_provenance: Mapping[str, MemoryArtifactProvenance],
    limit: int,
    min_score: float,
    min_recall_count: int,
    min_unique_queries: int,
    max_age_days: int,
) -> _ApplyPlan:
    """The pre-lock half of ``applyShortTermPromotions``: authoritative copies, gates, limit, rehydration."""
    from memory_core.consolidation.llm_consolidation import is_consolidation_candidate_eligible

    workspace_dir = Path(config.workspace_dir)
    store = read_recall_store(recall_store_path(workspace_dir), now_ms)
    entries = _readable_store_entries(store)
    min_score = _to_finite_score(min_score, DEFAULT_DEEP_DREAMING_MIN_SCORE)
    min_recall_count = _to_finite_non_negative_int(min_recall_count, 3)
    min_unique_queries = _to_finite_non_negative_int(min_unique_queries, 2)
    max_age = _to_finite_non_negative_int(max_age_days, -1)
    selection_limit = (
        max(0, math.floor(limit))
        if isinstance(limit, int | float) and math.isfinite(limit)
        else len(ranked)
    )

    current: list[PromotionCandidate] = []
    for candidate in ranked:
        entry = entries.get(candidate.key)
        if isinstance(entry, dict):
            candidate = _with_authoritative_provenance(
                replace(
                    candidate,
                    path=str(entry.get("path") or ""),
                    start_line=to_int(entry.get("startLine"), 1),
                    end_line=to_int(entry.get("endLine"), to_int(entry.get("startLine"), 1)),
                    snippet=str(entry.get("snippet") or ""),
                ),
                entry.get("provenance") if isinstance(entry.get("provenance"), dict) else None,
            )
        # Flush quarantine is sticky at the daily-file boundary: a trusted line of a mixed file
        # cannot promote either.
        current.append(with_daily_file_quarantine(candidate, daily_provenance))

    plan = _ApplyPlan(current, {}, [], {}, {})

    def passes(candidate: PromotionCandidate) -> bool:
        latest = entries.get(candidate.key)
        latest = latest if isinstance(latest, dict) else None
        key = candidate.key
        if is_promotion_origin_blocked(candidate.provenance):
            origin = (candidate.provenance or {}).get("originClass")
            plan.reject(key, "origin", f"origin filter ({origin})")
        elif consolidation and (latest is None or not is_consolidation_candidate_eligible(candidate)):
            if latest is not None:
                plan.reject(
                    key, "consolidation origin/session", "consolidation origin/session filter"
                )
        elif is_contaminated_dreaming_snippet(candidate.snippet):
            plan.reject(key, "contamination", "contamination filter")
        elif candidate.promoted_at or (latest is not None and latest.get("promotedAt")):
            plan.reject(key, "already promoted", "already promoted")
        elif candidate.score < min_score:
            plan.reject(
                key,
                "score threshold",
                f"score threshold ({js_to_fixed(candidate.score, 3)} < {_js_number_text(min_score)})",
            )
        elif candidate.signal_count < min_recall_count:
            plan.reject(
                key,
                "signal threshold",
                f"signal threshold ({candidate.signal_count} < {min_recall_count})",
            )
        elif candidate.unique_queries < min_unique_queries:
            plan.reject(
                key,
                "query threshold",
                f"query threshold ({candidate.unique_queries} < {min_unique_queries})",
            )
        elif max_age >= 0 and candidate.age_days > max_age:
            plan.reject(
                key,
                "age threshold",
                f"age threshold ({js_to_fixed(candidate.age_days, 1)}d > {max_age}d)",
            )
        else:
            return True
        return False

    eligible = [candidate for candidate in current if passes(candidate)]
    selected = eligible[:selection_limit]
    for candidate in eligible[selection_limit:]:
        plan.reject(candidate.key, "selection limit", f"selection limit ({selection_limit})")

    for candidate in selected:
        before = _promotion_source_fingerprint(workspace_dir, candidate)
        item = _rehydrate_promotion_candidate(workspace_dir, candidate)
        after = _promotion_source_fingerprint(workspace_dir, candidate)
        if before == after and item is not None and not is_contaminated_dreaming_snippet(item.snippet):
            plan.rehydrated.append(item)
            plan.source_fingerprints[candidate.key] = after
        elif item is None:
            plan.reject(candidate.key, "source rehydration", "source rehydration failed")
        elif before != after:
            plan.reject(candidate.key, "source changed", "source changed during apply")
        else:
            plan.reject(
                candidate.key, "contamination", "contamination filter after rehydration"
            )
    plan.store_fingerprints = {
        candidate.key: _store_entry_fingerprint(entries.get(candidate.key))
        for candidate in plan.rehydrated
    }
    return plan


def _plan_before_lock(
    *,
    config: MemoryConfig,
    consolidation: DeepConsolidation,
    plan: _ApplyPlan,
    now_ms: int,
    memory_file_max_chars: int,
    max_promoted_snippet_tokens: int,
    max_prior_entry_loss_fraction: float,
    identity: RuntimeIdentity,
    plan_fn: Any,
) -> _PrePlan | None:
    from memory_core.consolidation.llm_consolidation import (
        consolidation_candidate_fingerprint,
        hash_memory_content,
    )

    memory_path = MemoryWorkspace(config.workspace_dir).resolve_memory_path(PROMOTION_TARGET)
    existing = read_text_if_exists(memory_path)
    markers = set(extract_promotion_markers(existing))
    to_append = [candidate for candidate in plan.rehydrated if candidate.key not in markers]
    if not to_append:
        return None
    model_plan = plan_fn(
        consolidation,
        existing_memory=existing,
        candidates=to_append,
        max_prior_entry_loss_fraction=max_prior_entry_loss_fraction,
        memory_file_max_chars=memory_file_max_chars,
        max_promoted_snippet_tokens=max_promoted_snippet_tokens,
        now_ms=now_ms,
        identity=identity,
    )
    if model_plan is None:
        return None
    return _PrePlan(
        plan=model_plan,
        base_hash=hash_memory_content(existing),
        fingerprints={c.key: consolidation_candidate_fingerprint(c) for c in to_append},
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

    ``max_age_days < 0`` disables the age gate. Entries already promoted, with contaminated
    snippets or with an untrusted or system origin (``isPromotionOriginBlocked``: apply rejects
    them too, so they are excluded before scoring and the candidate limit) are never candidates.
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
        if not evaluation.reasons and not is_promotion_origin_blocked(evaluation.provenance)
    ]
    return sorted(
        candidates,
        key=lambda c: (-c.score, -c.recall_count, locale_sort_key(c.path)),
    )[:limit]


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
        # Scheduler and grounded-backfill keys are synthetic: only provenance-qualified
        # interactive recalls (`userQueryHashes`) satisfy user-query diversity.
        unique_queries = len(_user_query_hashes(raw))
        total_score = float(raw.get("totalScore") or 0)
        avg_score = clamp_score(total_score / signal_count)
        max_score = clamp_score(float(raw.get("maxScore") or 0))
        last_recalled_at = str(raw.get("lastRecalledAt") or iso_ms(now_ms))
        age_days = max(0.0, (now_ms - parse_ms(last_recalled_at, now_ms)) / DAY_MS)
        recall_days = [value for value in raw.get("recallDays", []) if isinstance(value, str)]
        context_diversity = unique_queries
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
            reasons.append(f"unique queries {context_diversity} < {min_unique_queries}")
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
                first_recalled_at=str(raw.get("firstRecalledAt") or ""),
                last_recalled_at=last_recalled_at,
                recall_days=tuple(recall_days),
                claim_hash=raw.get("claimHash") or None,
                project_key=raw.get("projectKey") or None,
                provenance=raw.get("provenance") if isinstance(raw.get("provenance"), dict) else None,
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


def _commit_promotion(
    *,
    config: MemoryConfig,
    store: ReindexableStore,
    now_ms: int,
    timezone: str,
    memory_file_max_chars: int,
    max_promoted_snippet_tokens: int,
    max_prior_entry_loss_fraction: float,
    identity: RuntimeIdentity,
    consolidation: DeepConsolidation | None,
    plan: _ApplyPlan,
    preplan: _PrePlan | None,
    ranked: Sequence[PromotionCandidate],
    evaluations: list[PromotionEvaluation],
    agent_id: str | None,
    origin_agent_ids: list[str],
    origins: MemoryEntryOriginLedger | None,
) -> tuple[MemoryPromotionRun, Any]:
    """The lock body of ``applyShortTermPromotions``: revalidate, commit MEMORY.md, mark, prune."""
    from memory_core.consolidation.llm_consolidation import (
        DeepConsolidationCommit,
        commit_deep_consolidation,
        is_consolidation_candidate_eligible,
        record_deep_consolidation_history,
    )

    workspace = MemoryWorkspace(config.workspace_dir)
    workspace_dir = Path(config.workspace_dir)
    target = PROMOTION_TARGET
    target_path = workspace.resolve_memory_path(target)
    before = read_text_if_exists(target_path)
    recall_path = recall_store_path(workspace_dir)
    summary = (
        f"ranked {len(ranked)} short-term promotion candidate(s); "
        f"evaluated {len(evaluations)} candidate(s); "
        f"rehydrated {len(plan.rehydrated)}; "
    )
    if not plan.rehydrated:
        run = MemoryPromotionRun(
            target=target,
            summary=f"{summary}appending 0; reconciled 0",
            outcome=PromotionWriteOutcome(
                should_write=False,
                target=target,
                entry="",
                reason="no live promotion candidates" if ranked else "no promotion candidates",
            ),
            diff="",
            indexed_files=0,
            chunks=store.count_chunks(),
            evaluated_candidates=evaluations,
            rejected_candidates=tuple(plan.describe(c) for c in plan.current),
        )
        return run, None

    # Revalidate against the store as it is under the locks.
    latest_entries = _readable_store_entries(read_recall_store(recall_path, now_ms))
    authoritative: list[PromotionCandidate] = []
    for candidate in plan.rehydrated:
        entry = latest_entries.get(candidate.key)
        source_unchanged = plan.source_fingerprints.get(
            candidate.key
        ) == _promotion_source_fingerprint(workspace_dir, candidate)
        if not isinstance(entry, dict):
            was_direct = consolidation is None and plan.store_fingerprints.get(
                candidate.key
            ) == _store_entry_fingerprint(None)
            if (
                was_direct
                and source_unchanged
                and not is_contaminated_dreaming_snippet(candidate.snippet)
            ):
                authoritative.append(candidate)
            continue
        if entry.get("promotedAt"):
            continue
        if (
            plan.store_fingerprints.get(candidate.key) != _store_entry_fingerprint(entry)
            or not source_unchanged
        ):
            continue
        current = _with_authoritative_provenance(
            candidate, entry.get("provenance") if isinstance(entry.get("provenance"), dict) else None
        )
        if consolidation is not None and not is_consolidation_candidate_eligible(current):
            continue
        if not is_contaminated_dreaming_snippet(current.snippet):
            authoritative.append(current)

    existing = read_text_if_exists(target_path)
    markers = set(extract_promotion_markers(existing))
    to_append = [c for c in authoritative if c.key not in markers]
    commit: DeepConsolidationCommit | None = None
    if consolidation is not None and preplan is not None and to_append:
        commit = commit_deep_consolidation(
            consolidation,
            memory_path=target_path,
            workspace=workspace_dir,
            plan=preplan.plan,
            base_hash=preplan.base_hash,
            to_append=to_append,
            planned_fingerprints=preplan.fingerprints,
            max_prior_entry_loss_fraction=max_prior_entry_loss_fraction,
            memory_file_max_chars=memory_file_max_chars,
            timezone=timezone,
            now_ms=now_ms,
            identity=identity,
            origins=origins if agent_id else None,
            origin_agent_ids=origin_agent_ids,
            retained_entry_keys={*markers, *latest_entries},
        )
    consolidated = commit is not None and commit.result is not None
    if consolidation is not None and preplan is not None and not consolidated:
        consolidation.log.warning(
            f"{DISPLAY_NAME}: promotion state or MEMORY.md changed during consolidation; "
            "using append-only fallback."
        )
        if commit is not None and commit.skipped_reason:
            consolidation.log.warning(
                f"{DISPLAY_NAME}: {commit.skipped_reason}; using append-only fallback."
            )
        # A failed rename or an outside edit leaves MEMORY.md as it is now.
        existing = read_text_if_exists(target_path)
        markers = set(extract_promotion_markers(existing))
        to_append = [c for c in authoritative if c.key not in markers]
    to_append_keys = {c.key for c in to_append}
    already_written = [c for c in authoritative if c.key not in to_append_keys]

    compacted_dates: tuple[str, ...] = ()
    deferred_reason: str | None = None
    entry_text = ""
    committed_content: str | None = None
    if consolidated and commit is not None and commit.result is not None:
        committed_content = commit.result.content
    elif to_append:
        entry_text = _build_promotion_section(
            to_append, now_ms, timezone, max_promoted_snippet_tokens, identity
        )
        compacted_dates, deferred_reason = _append_to_memory(
            target_path,
            entry_text,
            memory_file_max_chars=memory_file_max_chars,
            max_prior_entry_loss_fraction=max_prior_entry_loss_fraction,
        )
        if deferred_reason:
            for candidate in to_append:
                plan.reject(candidate.key, "memory budget", deferred_reason)
            if consolidation is not None:
                consolidation.log.info(
                    f"{DISPLAY_NAME}: deferred {len(to_append)} promotion candidate(s) "
                    f"because {deferred_reason}."
                )
        else:
            committed_content = read_text_if_exists(target_path)
    appended = to_append if committed_content is not None and not consolidated else []
    committed = [*already_written, *(to_append if consolidated else appended)]

    with recall_store_lock(workspace_dir):
        _mark_promoted(recall_path, committed, now_ms)
    if agent_id and origins is not None and committed_content is not None:
        retained_preimage_keys = commit.retained_preimage_keys if commit is not None else None
        if retained_preimage_keys is None:
            retained_preimage_keys = {
                key
                for item in read_memory_preimages(workspace_dir)
                for key in extract_promotion_markers(str(item.get("content", "")))
            }
        prune_memory_entry_origins(
            origins,
            workspace_dir=workspace_dir,
            agent_ids=origin_agent_ids,
            entry_keys=extract_promotion_markers(existing),
            retained_entry_keys={
                *extract_promotion_markers(committed_content),
                *_readable_store_entries(read_recall_store(recall_path, now_ms)),
                *retained_preimage_keys,
            },
        )
    indexed_files = 0
    reindex_error = None
    if (to_append or consolidated) and committed_content is not None:
        try:
            indexed_files = store.reindex(workspace)
        except Exception as exc:
            reindex_error = exception_message(exc)
    if consolidation is not None and commit is not None and commit.result is not None:
        # Published before the locks are released; the skip note is written after they are.
        record_deep_consolidation_history(consolidation, workspace_dir, commit, now_ms=now_ms)

    after = read_text_if_exists(target_path)
    committed_keys = {c.key for c in committed}
    deferred = tuple(to_append) if deferred_reason else ()
    outcome = PromotionWriteOutcome(
        should_write=bool(to_append) and not deferred_reason,
        target=target,
        entry=(
            commit.result.content.strip()
            if consolidated and commit is not None and commit.result is not None
            else entry_text.strip()
            if not deferred_reason
            else ""
        ),
        reason=(
            "short-term promotion deferred: memory budget"
            if deferred_reason
            else "short-term promotion consolidated"
            if consolidated
            else "short-term promotion"
            if to_append
            else "short-term promotion reconciled"
        ),
    )
    run = MemoryPromotionRun(
        target=target,
        summary=f"{summary}appending {len(to_append)}; reconciled {len(already_written)}",
        outcome=outcome,
        diff=unified_diff(before, after, target),
        indexed_files=indexed_files,
        chunks=store.count_chunks(),
        evaluated_candidates=evaluations,
        reindex_error=reindex_error,
        applied_candidates=tuple(committed),
        appended=len(to_append) if consolidated or appended else 0,
        reconciled_existing=len(already_written),
        compacted_dates=compacted_dates,
        deferred_candidates=deferred,
        deferred_reason=deferred_reason,
        consolidation=commit.result if commit is not None else None,
        consolidation_skipped_reason=commit.skipped_reason if commit is not None else None,
        rejected_candidates=tuple(
            plan.describe(c) for c in plan.current if c.key not in committed_keys
        ),
    )
    return run, commit


PromotionRejectionCategory = Literal[
    "origin",
    "consolidation origin/session",
    "contamination",
    "already promoted",
    "score threshold",
    "signal threshold",
    "query threshold",
    "age threshold",
    "selection limit",
    "source rehydration",
    "source changed",
    "memory budget",
    "candidate changed",
]


@dataclass(frozen=True)
class PromotionRejection:
    """One candidate that did not reach MEMORY.md (``rejectedCandidates`` of upstream's apply result).

    ``category`` is one of upstream's fixed diagnostic labels; ``reason`` adds the gate values.
    """

    candidate: PromotionCandidate
    reason: str
    category: PromotionRejectionCategory


def build_promotion_applied_event(
    *,
    memory_path: str,
    applied_candidates: Sequence[PromotionCandidate],
    now_ms: int,
) -> dict[str, Any]:
    """The ``memory.promotion.applied`` host event as the event store keeps it.

    Port of the event ``applyShortTermPromotions`` appends and of
    ``normalizeMemoryHostEventRecordForStorage`` (src/memory-host-sdk/event-store.ts): at most 10
    candidates, 256 bytes for each key and path (and the memory path), an ellipsis on a cut,
    ``storageTruncated`` when anything was cut and 8 KiB for the JSON, beyond which the candidates
    are dropped.
    """
    path_limit = 256
    truncated = False
    memory, cut = _truncate_utf8(memory_path, path_limit)
    truncated = truncated or cut
    items = []
    for candidate in applied_candidates[:10]:
        key, cut_key = _truncate_utf8(candidate.key, path_limit)
        path, cut_path = _truncate_utf8(candidate.path, path_limit)
        truncated = truncated or cut_key or cut_path
        items.append(
            {
                "key": key,
                "path": path,
                "startLine": candidate.start_line,
                "endLine": candidate.end_line,
                "score": candidate.score,
                "recallCount": candidate.recall_count,
            }
        )
    truncated = truncated or len(applied_candidates) > 10
    timestamp, cut_stamp = _truncate_utf8(iso_ms(now_ms), 128)
    truncated = truncated or cut_stamp
    event: dict[str, Any] = {
        "type": "memory.promotion.applied",
        "timestamp": timestamp,
        "memoryPath": memory,
        "applied": len(applied_candidates),
        "candidates": items,
    }
    if truncated:
        event["storageTruncated"] = True
    if _utf8_len(js_json_stringify(event)) > 8 * 1024:
        event = {**event, "candidates": [], "storageTruncated": True}
    return event


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
        first_recalled_at=evaluation.first_recalled_at,
        last_recalled_at=evaluation.last_recalled_at,
        age_days=evaluation.age_days,
        concept_tags=evaluation.concept_tags,
        components=dict(evaluation.components),
        recall_days=evaluation.recall_days,
        claim_hash=evaluation.claim_hash,
        project_key=evaluation.project_key,
        provenance=evaluation.provenance,
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
    recall_days = [value for value in entry.get("recallDays", []) if isinstance(value, str)]
    context_diversity = len(_user_query_hashes(entry))
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
        "phaseBoost": _phase_signal_boost(phase_entries.get(key), now_ms),
    }


def _candidate_score(components: dict[str, float]) -> float:
    # Left-to-right float addition like the upstream expression
    # (short-term-promotion.ts rankShortTermPromotionCandidates). Python 3.12's
    # built-in sum() compensates rounding and can differ in the last ulp.
    weighted = 0.0
    for key, weight in PROMOTION_COMPONENT_WEIGHTS.items():
        weighted += weight * float(components.get(key) or 0)
    return clamp_score(weighted + float(components.get("phaseBoost") or 0))


def _phase_signal_age_days(last_seen_at: Any, now_ms: int) -> float | None:
    if not isinstance(last_seen_at, str) or not last_seen_at:
        return None
    try:
        parsed = int(datetime.fromisoformat(last_seen_at.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None
    return max(0.0, (now_ms - parsed) / DAY_MS)


def _recency_component(age_days: float, half_life_days: float) -> float:
    # calculateRecencyComponent: a bad age or half-life reads as fully recent.
    if not math.isfinite(age_days) or age_days < 0:
        return 1.0
    if not math.isfinite(half_life_days) or half_life_days <= 0:
        return 1.0
    return math.exp(-(math.log(2) / half_life_days) * age_days)


def _phase_signal_boost(entry: Any, now_ms: int = 0) -> float:
    """``calculatePhaseSignalBoost``: log-scaled light and REM hits, decayed by their age."""
    if not isinstance(entry, dict):
        return 0.0
    light_strength = clamp_score(math.log1p(max(0, to_int(entry.get("lightHits"), 0))) / math.log1p(6))
    rem_strength = clamp_score(math.log1p(max(0, to_int(entry.get("remHits"), 0))) / math.log1p(6))
    light_age = _phase_signal_age_days(entry.get("lastLightAt"), now_ms)
    rem_age = _phase_signal_age_days(entry.get("lastRemAt"), now_ms)
    light_recency = 0.0 if light_age is None else clamp_score(_recency_component(light_age, 14))
    rem_recency = 0.0 if rem_age is None else clamp_score(_recency_component(rem_age, 14))
    return clamp_score(0.06 * light_strength * light_recency + 0.09 * rem_strength * rem_recency)


def _user_query_hashes(entry: dict[str, Any]) -> list[str]:
    """The entry's ``userQueryHashes``; legacy rows with only recall signals read as ``queryHashes``."""
    stored = entry.get("userQueryHashes")
    if isinstance(stored, list):
        return [value for value in dict.fromkeys(stored) if isinstance(value, str) and value.strip()]
    if to_int(entry.get("dailyCount"), 0) == 0 and to_int(entry.get("groundedCount"), 0) == 0:
        return [
            value
            for value in dict.fromkeys(entry.get("queryHashes") or [])
            if isinstance(value, str) and value.strip()
        ]
    return []


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


_MAX_PROMOTION_TRIGGER_PHRASE_CHARS = 64


def _normalize_promotion_trigger_phrase(value: str) -> str:
    single_line = re.sub(r"\s+", " ", re.sub(r"[\r\n,;]+", " ", re.sub(r"<!--|-->", " ", value))).strip()
    return "".join(list(single_line)[:_MAX_PROMOTION_TRIGGER_PHRASE_CHARS]).rstrip()


def _promotion_project_key(candidate: PromotionCandidate) -> str | None:
    key = candidate.project_key
    return key if key and not re.search(r"[\r\n<>]", key) else None


def build_promotion_recall_annotations(candidate: PromotionCandidate) -> str:
    """``buildPromotionRecallAnnotations``: the trigger phrases, importance and project of a line."""
    triggers = ", ".join(
        phrase
        for phrase in (_normalize_promotion_trigger_phrase(tag) for tag in candidate.concept_tags[:3])
        if phrase
    )
    # Math.round: halves round up.
    importance = min(10, max(3, math.floor(candidate.score * 10 + 0.5)))
    project_key = _promotion_project_key(candidate)
    project = f" <!-- project: {project_key} -->" if project_key else ""
    return f"<!-- trigger: {triggers} --> <!-- importance: {importance} -->{project}"


def group_promotion_candidates_by_project_key(
    candidates: list[PromotionCandidate],
) -> list[tuple[str | None, list[PromotionCandidate]]]:
    """``groupPromotionCandidatesByProjectKey``: stable key order, the global group first."""
    groups: dict[str, list[PromotionCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(_promotion_project_key(candidate) or "", []).append(candidate)
    return [(key or None, groups[key]) for key in sorted(groups)]


def _build_promotion_section(
    candidates: list[PromotionCandidate],
    now_ms: int,
    timezone: str,
    max_promoted_snippet_tokens: int = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> str:
    section_date = format_memory_dreaming_day(now_ms, timezone)
    lines = ["", f"## {PROMOTION_SECTION_TITLE} ({section_date})", ""]
    groups = group_promotion_candidates_by_project_key(candidates)
    for project_key, group in groups:
        if len(groups) > 1:
            lines.extend([f"### Project: {project_key}" if project_key else "### Global", ""])
        for candidate in group:
            source = f"{candidate.path}:{candidate.start_line}-{candidate.end_line}"
            lines.append(format_promotion_marker(candidate.key, identity))
            # Cap only the visible MEMORY.md text; the recall store keeps the full
            # rehydrated snippet for ranking and provenance.
            snippet = _format_promoted_snippet_for_memory(
                candidate.snippet, max_promoted_snippet_tokens
            )
            metadata = (
                f"[score={js_to_fixed(candidate.score, 3)} signals={candidate.signal_count} "
                f"recalls={candidate.recall_count} avg={js_to_fixed(candidate.avg_score, 3)} "
                f"source={source}]"
            )
            lines.append(f"- {snippet} {metadata} {build_promotion_recall_annotations(candidate)}")
        if len(groups) > 1:
            lines.append("")
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
    # short-term-promotion.ts:2349-2368 truncatePromotedSnippet: lengths, slices and
    # lastIndexOf positions are UTF-16 code units, the trim is trimEnd.
    limit = _resolve_promoted_snippet_char_limit(max_tokens)
    if limit == 0 or utf16_len(snippet) <= limit:
        return snippet
    hard_limit = truncate_utf16_safe(snippet, limit)
    sentence_boundary = max(
        _utf16_last_index_of(hard_limit, ". "),
        _utf16_last_index_of(hard_limit, "! "),
        _utf16_last_index_of(hard_limit, "? "),
    )
    word_boundary = _utf16_last_index_of(hard_limit, " ")
    if sentence_boundary >= math.floor(limit * 0.55):
        cut_at = sentence_boundary + 1
    elif word_boundary >= math.floor(limit * 0.65):
        cut_at = word_boundary
    else:
        cut_at = limit
    return f"{js_trim_end(utf16_slice(hard_limit, 0, cut_at))}..."


def _utf16_last_index_of(value: str, needle: str) -> int:
    index = value.rfind(needle)
    return index if index < 0 else utf16_len(value[:index])


def _format_promoted_snippet_for_memory(raw_snippet: str, max_tokens: int) -> str:
    normalized = re.sub(
        r"^[-*+] +", "", normalize_snippet(raw_snippet or "(no snippet captured)")
    ).strip()
    truncated = _truncate_promoted_snippet(normalized or "(no snippet captured)", max_tokens)
    # A hard cut inside a surrogate pair leaves a lone surrogate; Node's UTF-8 write
    # of MEMORY.md turns it into U+FFFD (same UTF-16 length, same bytes).
    return js_to_well_formed(truncated)


def _mark_promoted(path: Path, candidates: list[PromotionCandidate], now_ms: int) -> None:
    store = read_recall_store(path, now_ms)
    now_iso = iso_ms(now_ms)
    readable = _readable_store_entries(store)
    for candidate in candidates:
        entry = readable.get(candidate.key)
        if isinstance(entry, dict):
            # The store keeps the full rehydrated snippet and relocated range;
            # only the MEMORY.md presentation is token-capped.
            entry["startLine"] = candidate.start_line
            entry["endLine"] = candidate.end_line
            entry["snippet"] = candidate.snippet
            entry["promotedAt"] = now_iso
    # ``updatedAt`` never moves backwards (upstream: the later of now and the stored value).
    store["updatedAt"] = iso_ms(max(now_ms, parse_ms(str(store.get("updatedAt") or ""), 0)))
    write_recall_store(path, store)


def _append_to_memory(
    path: Path,
    section: str,
    memory_file_max_chars: int = DEFAULT_MEMORY_FILE_MAX_CHARS,
    max_prior_entry_loss_fraction: float = DEFAULT_DEEP_DREAMING_MAX_PRIOR_ENTRY_LOSS_FRACTION,
) -> tuple[tuple[str, ...], str | None]:
    """Write ``section`` below the budget-compacted MEMORY.md.

    Returns ``(dropped section dates, deferred reason)``. Mirrors the append fallback of upstream
    ``applyShortTermPromotions``: the oldest generated promotion sections are dropped until the
    file fits ``memory_file_max_chars``, without losing more than
    ``max_prior_entry_loss_fraction`` of the generated entries; an empty (or whitespace-only)
    result gets the ``# Long-Term Memory`` header. When the result still exceeds the budget
    nothing is written and the reason is returned (the "memory budget" rejection).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_text_if_exists(path)
    budget_chars = (
        max(0, math.floor(memory_file_max_chars))
        if isinstance(memory_file_max_chars, int | float) and math.isfinite(memory_file_max_chars)
        else DEFAULT_MEMORY_FILE_MAX_CHARS
    )
    content, dropped_dates = build_budgeted_memory_append(
        existing_memory=existing,
        new_section=section,
        budget_chars=budget_chars,
        max_prior_entry_loss_fraction=max(0.0, min(1.0, max_prior_entry_loss_fraction)),
    )
    if budget_chars > 0 and utf16_len(content) > budget_chars:
        return (), f"MEMORY.md budget exceeded ({utf16_len(content)} > {budget_chars} chars)"
    path.write_text(content, encoding="utf-8")
    return dropped_dates, None


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
        # memory-core hardening (no upstream check): never rehydrate from a file outside
        # the workspace, e.g. a stored ``memory/../../<other subject>/...`` path.
        if not is_workspace_contained_path(workspace_dir, relative_path):
            continue
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
    if _LONE_SURROGATE_RE.search(target_snippet) or _LONE_SURROGATE_RE.search(window_snippet):
        # compareCandidateWindow compares UTF-16 code units: a stored snippet cut inside
        # a surrogate pair (the 800-unit recall cap) still matches the line holding it.
        target_snippet = _utf16_unit_text(target_snippet)
        window_snippet = _utf16_unit_text(window_snippet)
    if window_snippet == target_snippet:
        return True, 3
    if target_snippet in window_snippet:
        return True, 2
    if window_snippet in target_snippet:
        return True, 1
    return False, 0


_LONE_SURROGATE_RE = re.compile("[\\ud800-\\udfff]")


def _utf16_unit_text(value: str) -> str:
    """Return ``value`` with one character per UTF-16 code unit (pairs split apart)."""
    data = value.encode("utf-16-le", "surrogatepass")
    return "".join(
        chr(int.from_bytes(data[index : index + 2], "little")) for index in range(0, len(data), 2)
    )


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
