"""Managed dreaming turns over the host's resolved memory workspaces."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
import logging
from pathlib import Path
import re
import time
from typing import Any

from memory_core.bootstrap._js import js_trim, locale_sort_key
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import iso_ms
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.artifacts import update_dreams_file
from memory_core.consolidation.dream_narrative import append_fallback_narrative, run_dream_narrative
from memory_core.consolidation.dreaming import DreamingIngestion, run_dreaming_sweep
from memory_core.consolidation.dreaming_repair import repair_dreaming_recall
from memory_core.consolidation.light_phase import LightDreamingOptions, _managed_phase_block, _publish
from memory_core.consolidation.llm_consolidation import DeepConsolidation, LlmConsolidationOptions
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.policy import DeepDreamingPolicy
from memory_core.consolidation.promotion import (
    DEFAULT_MEMORY_FILE_MAX_CHARS, ReindexableStore, format_memory_dreaming_day,
    rank_short_term_promotion_candidates, run_short_term_promotion,
)
from memory_core.consolidation.rem_phase import RemDreamingOptions
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

DREAMING_EVENT_TEXT = "__openclaw_memory_core_short_term_promotion_dream__"
_LOG = logging.getLogger(__name__)
_DIARY_JOBS = ThreadPoolExecutor(thread_name_prefix="dream-diary")


@dataclass(frozen=True)
class DreamingWorkspace:
    """The real store and workspace owners supplied by the host's memory roster."""
    config: MemoryConfig
    store: ReindexableStore
    agent_ids: tuple[str, ...] = ()
    origins: MemoryEntryOriginLedger | None = None
    artifact_provenance: MemoryArtifactProvenanceStore | None = None
    memory_file_max_chars: int = DEFAULT_MEMORY_FILE_MAX_CHARS


@dataclass(frozen=True)
class ManagedDreamingOptions:
    policy: DeepDreamingPolicy = field(default_factory=DeepDreamingPolicy)
    light: LightDreamingOptions = field(default_factory=LightDreamingOptions)
    rem: RemDreamingOptions = field(default_factory=RemDreamingOptions)
    light_limit: int = 100
    rem_limit: int = 10
    light_ingestion: DreamingIngestion = field(default_factory=lambda: DreamingIngestion(lookback_days=2, limit=100))
    rem_ingestion: DreamingIngestion = field(default_factory=lambda: DreamingIngestion(lookback_days=7, limit=10))
    timezone: str = "UTC"
    storage_mode: str = "separate"
    separate_reports: bool = False
    model: str | None = None


def _is_managed_turn(trigger, body, session_key, agent_id, read_pending):
    if trigger not in ("cron", "heartbeat"):
        return False
    if not any(re.sub(r"^\[cron:[^\]]+\]\s*", "", js_trim(line)) == DREAMING_EVENT_TEXT
               for line in re.split(r"\r?\n", body or "")):
        return False
    if trigger == "cron":
        return True
    key = js_trim(session_key or "")
    keys = [key, key.removesuffix(":heartbeat")] if key.endswith(":heartbeat") else [key]
    return bool(key and read_pending and any(
        str(e.get("contextKey", "")).startswith("cron:") and js_trim(e.get("text") or "") == DREAMING_EVENT_TEXT
        for session in keys for e in read_pending(session, agent_id)))


def _write_deep_report(root, lines, has_content, options, now, on_event):
    event = {"type": "memory.dream.completed", "timestamp": iso_ms(now), "phase": "deep",
             "outcome": "completed", "lineCount": len(lines), "storageMode": options.storage_mode}
    if has_content:
        body = "\n".join(lines)
        dest = update_dreams_file(root, lambda original, path: (
            _managed_phase_block(original, "## Deep Sleep", "deep", body), path))
        event["inlinePath"] = str(dest)
        if options.storage_mode in {"separate", "both"} or options.separate_reports:
            report = f"memory/dreaming/deep/{format_memory_dreaming_day(now, options.timezone)}.md"
            _publish(root, report, f"# Deep Sleep\n\n{body}\n")
            event["reportPath"] = str(root / report)
    if on_event is not None:
        on_event(event)


def _run_deep(target, options, owner, agent_ids, complete, now, identity, state_dir, on_event, dispatch, stats):
    root = target.config.workspace_dir
    repair = repair_dreaming_recall(root, now)
    policy = options.policy
    gates = dict(limit=policy.limit, min_score=policy.min_score, min_recall_count=policy.min_recall_count,
                 min_unique_queries=policy.min_unique_queries, recency_half_life_days=policy.recency_half_life_days,
                 max_age_days=policy.max_age_days)
    candidates = rank_short_term_promotion_candidates(config=target.config, now_ms=now, for_publication=True, **gates)
    stats["candidates"] += len(candidates)
    consolidation = None
    if complete is not None and owner:
        def model(request):
            body = {"agentId": owner, "message": request.message, "extraSystemPrompt": request.system_prompt,
                    "timeoutMs": request.timeout_ms}
            if request.model:
                body["model"] = request.model
            return complete(body)["text"]

        consolidation = DeepConsolidation(model, LlmConsolidationOptions(
            enabled=True, model_name=options.model, memory_file_max_chars=target.memory_file_max_chars,
            max_prior_entry_loss_fraction=policy.max_prior_entry_loss_fraction,
            max_promoted_snippet_tokens=policy.max_promoted_snippet_tokens))
    run = run_short_term_promotion(
        config=target.config, store=target.store, now_ms=now, timezone=options.timezone,
        candidates=candidates, identity=identity, agent_id=owner, workspace_agent_ids=agent_ids,
        origins=target.origins, artifact_provenance=target.artifact_provenance, consolidation=consolidation,
        memory_file_max_chars=target.memory_file_max_chars, state_dir=state_dir, on_event=on_event,
        max_prior_entry_loss_fraction=policy.max_prior_entry_loss_fraction,
        max_promoted_snippet_tokens=policy.max_promoted_snippet_tokens, **gates,
    )
    promoted = run.applied_candidates
    stats["applied"] += len(promoted)
    lines = [f"- Repaired recall artifacts: {repair}."] if repair else []
    lines.extend([f"- Ranked {len(candidates)} candidate(s) for durable promotion.",
                  f"- Promoted {len(promoted)} candidate(s) into MEMORY.md."])
    counts = Counter(r.category for r in run.rejected_candidates)
    if counts:
        summary = ", ".join(f"{category}: {counts[category]}" for category in sorted(counts, key=locale_sort_key))
        lines.append(f"- Not promoted: {sum(counts.values())} candidate(s) ({summary}).")
    _write_deep_report(root, lines, bool(repair or promoted or counts.keys() - {"memory budget"}),
                       options, now, on_event)
    status = "skipped"
    if promoted:
        if complete is None:
            append_fallback_narrative(root, now, options.timezone)
        else:
            snippets = [c.snippet for c in promoted if c.snippet]
            if snippets:
                def narrate():
                    return run_dream_narrative(workspace_dir=root, agent_id=owner, complete=complete, model=options.model,
                        snippets=snippets, promotions=snippets, source_entry_keys=list(dict.fromkeys(c.key for c in promoted)),
                        now_ms=now, timezone=options.timezone)
                status = dispatch(narrate) if dispatch else narrate()
    return status


def run_managed_dreaming_turn(
    *, trigger: str, cleaned_body: str, workspaces: Sequence[DreamingWorkspace], options: ManagedDreamingOptions,
    agent_id: str | None = None, session_key: str | None = None, read_pending_events: Callable | None = None,
    complete: Callable[[dict], Mapping[str, Any]] | None = None, now_ms: Callable[[], int] | None = None,
    submit_narrative: Callable | None = None, identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
    state_dir: Path | None = None, on_event: Callable | None = None, logger: logging.Logger = _LOG,
) -> dict | None:
    """Run the managed before-agent-reply hook with its queued event and resolved host roster.

    The host supplies current time, an optional keyed state directory and an optional model. A cron
    caller can supply its task queue. Heartbeat turns await diary publication before returning.
    """
    if not _is_managed_turn(trigger, cleaned_body, session_key, agent_id, read_pending_events):
        return None
    if not options.policy.enabled:
        return {"handled": True, "reason": "memory-core: short-term dreaming disabled"}
    if not workspaces:
        return {"handled": True, "reason": "memory-core: short-term dreaming missing workspace"}
    if options.policy.limit == 0:
        return {"handled": True, "reason": "memory-core: short-term dreaming disabled by limit"}

    def detach(job):
        (submit_narrative or _DIARY_JOBS.submit)(job)
        return "pending"

    dispatch = detach if trigger == "cron" else None
    by_root = {}
    for target in workspaces:
        root = target.config.workspace_dir
        if root not in by_root:
            by_root[root] = target, []
        by_root[root][1].extend(target.agent_ids)
    stats = Counter()
    failed = 0
    narratives = Counter()
    for root, (target, owners) in by_root.items():
        ids = tuple(dict.fromkeys(owner.lower().strip() for owner in owners if owner.strip()))
        owner = (agent_id or "").lower().strip()
        owner = owner if owner in ids else min(ids, default=owner) or None
        now = now_ms() if now_ms else time.time_ns() // 1_000_000
        try:
            for phase, opts, limit, ingestion in (
                ("light", options.light, options.light_limit, options.light_ingestion),
                ("rem", options.rem, options.rem_limit, options.rem_ingestion),
            ):
                phase_options = replace(opts, complete=complete, storage_mode=options.storage_mode,
                                        separate_reports=options.separate_reports)
                result = run_dreaming_sweep(config=target.config, store=target.store, phase=phase, limit=limit,
                    ingestion=replace(ingestion, agent_ids=ids, limit=limit), now_ms=now,
                    timezone=options.timezone, identity=identity, origins=target.origins, on_event=on_event,
                    agent_id=owner, dispatch_narrative=dispatch, **{phase + "_options": phase_options})
                narratives[result.narrative_status] += 1
        except Exception as error:
            failed += 1
            logger.error("memory-core: dreaming sweep failed for workspace %s: %s", root, error)
            continue
        try:
            status = _run_deep(target, options, owner, ids, complete, now, identity,
                               state_dir, on_event, dispatch, stats)
            narratives[status] += 1
        except Exception as error:
            failed += 1
            logger.error("memory-core: dreaming promotion failed for workspace %s: %s", root, error)
            if on_event:
                on_event({"type": "memory.dream.completed", "timestamp": iso_ms(now), "phase": "deep",
                          "outcome": "failed", "error": str(error), "lineCount": 0, "storageMode": options.storage_mode})
    summary = (f"memory-core: dreaming promotion complete (workspaces={len(by_root)}, candidates={stats['candidates']}, "
               f"applied={stats['applied']}, failed={failed}, degraded={narratives['degraded']}, "
               f"narrativesPending={narratives['pending']}).")
    (logger.warning if failed == len(by_root) or narratives["degraded"] else logger.info)(summary)
    status = "degraded" if narratives["degraded"] else "processed"
    return {"handled": True, "reason": "memory-core: short-term dreaming " + status}
