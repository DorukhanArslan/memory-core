"""Consolidation views for the Lab over :mod:`memory_core.consolidation` (demo-only JSON).

Promotion sweeps, dreaming phases, audit and repair all run in the package; this
module serializes their results and records each run's file changes through
the Lab snapshots (source ``promotion``, ``dreaming`` or ``repair``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from demo.lab_runtime import LAB_TIMEZONE, LabError, LabRuntime, safe_exception_message
from memory_core.consolidation import (
    DEFAULT_DEEP_DREAMING_ENABLED,
    DEFAULT_DEEP_DREAMING_LIMIT,
    DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS,
    DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT,
    DEFAULT_DEEP_DREAMING_MIN_SCORE,
    DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
    DREAMING_PHASES,
    PROMOTION_COMPONENT_WEIGHTS,
    SHORT_TERM_LOCK_RELATIVE_PATH,
    SHORT_TERM_STORE_RELATIVE_PATH,
    DreamingSweepResult,
    MemoryPromotionRun,
    PromotionEvaluation,
    audit_short_term_promotion_artifacts,
    evaluate_short_term_promotion_candidates,
    repair_short_term_promotion_artifacts,
    run_dreaming_sweep,
    run_short_term_promotion,
)

# Lab promotion runs use the package defaults of run_short_term_promotion.
LAB_PROMOTION_LIMIT = 5


def serialize_parsed(parsed: Any) -> dict[str, Any]:
    return {
        "shouldWrite": parsed.should_write,
        "target": parsed.target,
        "entry": parsed.entry,
        "reason": parsed.reason,
        "error": parsed.error,
    }


def serialize_evaluation(candidate: PromotionEvaluation, *, selected: bool = False) -> dict[str, Any]:
    reasons = list(candidate.reasons)
    return {
        "key": candidate.key,
        "path": candidate.path,
        "startLine": candidate.start_line,
        "endLine": candidate.end_line,
        "snippet": candidate.snippet,
        "score": round(candidate.score, 3),
        "recallCount": candidate.recall_count,
        "dailyCount": candidate.daily_count,
        "groundedCount": candidate.grounded_count,
        "signalCount": candidate.signal_count,
        "avgScore": round(candidate.avg_score, 3),
        "maxScore": round(candidate.max_score, 3),
        "uniqueQueries": candidate.unique_queries,
        "contextDiversity": candidate.context_diversity,
        "ageDays": round(candidate.age_days, 3),
        "conceptTags": list(candidate.concept_tags),
        "components": {key: round(value, 3) for key, value in candidate.components.items()},
        # Gate flags read the package's reason prefixes (evaluate_short_term_promotion_candidates).
        "gates": {
            "score": not any(reason.startswith("score ") for reason in reasons),
            "recall": not any(reason.startswith("signals ") for reason in reasons),
            "unique": not any(reason.startswith("unique queries") for reason in reasons),
            "age": not any(reason.startswith("age ") for reason in reasons),
        },
        "selected": selected or not reasons,
        "reasons": reasons,
    }


def serialize_promotion(run: MemoryPromotionRun) -> dict[str, Any]:
    applied = {candidate.key for candidate in run.applied_candidates}
    return {
        "target": run.target,
        "rawText": run.summary,
        "parsed": serialize_parsed(run.outcome),
        "diff": run.diff,
        "indexedFiles": run.indexed_files,
        "chunks": run.chunks,
        "evaluatedCandidates": [
            serialize_evaluation(candidate, selected=candidate.key in applied)
            for candidate in run.evaluated_candidates
        ],
        "applied": [candidate.key for candidate in run.applied_candidates],
        "appended": run.appended,
        "reconciledExisting": run.reconciled_existing,
        "compactedDates": list(run.compacted_dates),
        "reindexError": run.reindex_error,
    }


def serialize_dreaming(sweep: DreamingSweepResult) -> dict[str, Any]:
    return {
        "phase": sweep.phase,
        "candidateCount": len(sweep.candidates),
        "candidateKeys": [candidate.key for candidate in sweep.candidates],
        "phaseSignalsRecorded": sweep.phase_signals_recorded,
        "filesChanged": list(sweep.files_changed),
        "promotion": serialize_promotion(sweep.promotion) if sweep.promotion else None,
        "skipReason": sweep.skip_reason,
    }


def serialize_audit(lab: LabRuntime, audit: Any) -> dict[str, Any]:
    return {
        "storePath": str(lab.root / SHORT_TERM_STORE_RELATIVE_PATH),
        "lockPath": str(lab.root / SHORT_TERM_LOCK_RELATIVE_PATH),
        "updatedAt": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "exists": audit.exists,
        "entryCount": audit.entry_count,
        "promotedCount": audit.promoted_entry_count,
        "spacedEntryCount": audit.spaced_entry_count,
        "conceptTaggedEntryCount": audit.concept_tagged_entry_count,
        "invalidEntryCount": audit.invalid_entry_count,
        "issues": [
            {"severity": issue.severity, "code": issue.code, "message": issue.message, "fixable": issue.fixable}
            for issue in audit.issues
        ],
    }


def promotion_gates() -> dict[str, Any]:
    return {
        "minScore": DEFAULT_DEEP_DREAMING_MIN_SCORE,
        "minRecallCount": DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT,
        "minUniqueQueries": DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES,
        "limit": LAB_PROMOTION_LIMIT,
        "maxAgeDays": None,
        "recencyHalfLifeDays": DEFAULT_RECENCY_HALF_LIFE_DAYS,
        "deepPolicyDefaults": {
            "enabled": DEFAULT_DEEP_DREAMING_ENABLED,
            "limit": DEFAULT_DEEP_DREAMING_LIMIT,
            "minScore": DEFAULT_DEEP_DREAMING_MIN_SCORE,
            "minRecallCount": DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT,
            "minUniqueQueries": DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES,
            "maxAgeDays": DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS,
        },
    }


def promotion_weights() -> dict[str, float]:
    return dict(PROMOTION_COMPONENT_WEIGHTS)


def _matrix_label(prefixes: tuple[str, ...]) -> str:
    from demo.parity_results import parse_parity_matrix

    rows = [row for row in parse_parity_matrix() if row["area"].startswith(prefixes)]
    statuses = "; ".join(f"{row['area']}: {row['status']}" for row in rows)
    return f"paket (memory_core.consolidation) · {statuses}" if statuses else "paket (memory_core.consolidation)"


def consolidation_view(lab: LabRuntime) -> dict[str, Any]:
    """GET /api/lab/consolidation: curated writes beside scored promotion."""
    config = lab.config()
    now = lab.now_ms()
    evaluations = evaluate_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        min_score=DEFAULT_DEEP_DREAMING_MIN_SCORE,
        min_recall_count=DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT,
        min_unique_queries=DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES,
    )
    candidates = []
    selected = 0
    for evaluation in evaluations:
        passes = not evaluation.reasons and selected < LAB_PROMOTION_LIMIT
        if passes:
            selected += 1
        item = serialize_evaluation(evaluation, selected=passes)
        if not evaluation.reasons and not passes:
            item["selected"] = False
            item["reasons"] = [f"limit {LAB_PROMOTION_LIMIT} reached"]
        candidates.append(item)
    audit = audit_short_term_promotion_artifacts(config=config, now_ms=now)
    return {
        "curated": [
            {key: value for key, value in write.items() if key != "before"}
            for write in lab.curated_writes
        ],
        "shortTerm": {
            "entries": audit.entry_count,
            "promoted": audit.promoted_entry_count,
            "storePath": SHORT_TERM_STORE_RELATIVE_PATH,
            "exists": audit.exists,
        },
        "candidates": candidates,
        "gates": promotion_gates(),
        "weights": promotion_weights(),
        "lastPromotion": lab.consolidation_results.get("promotion"),
        "lastDreaming": lab.consolidation_results.get("dreaming"),
        "audit": lab.consolidation_results.get("audit"),
        "repair": lab.consolidation_results.get("repair"),
        "labels": {
            "curated": "uzantı: turda anında yazar, kapı yok",
            "scored": _matrix_label(("Promotion", "Apply short-term", "Deep dreaming", "Recall tracking")),
        },
        "flags": {
            name: lab.settings.flags.get(name, True)
            for name in ("curated_memory_writes", "curation.memory_md", "curation.user_md",
                         "curation.daily_note", "curation.proactive_preferences")
        },
    }


def run_promotion(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    embedding = lab.resolve_embedding(payload)
    store = lab.store(embedding)
    with lab.tracked("promotion"):
        try:
            run = run_short_term_promotion(
                config=lab.config(mode=lab.default_search_mode(embedding)),
                store=store,
                now_ms=lab.now_ms(),
                timezone=LAB_TIMEZONE,
                limit=LAB_PROMOTION_LIMIT,
            )
        except Exception as exc:
            raise LabError(
                502,
                f"memory promote failed: {safe_exception_message(exc, lab.secret_values(payload))}",
                code="promotion_failed",
                redacted=True,
            ) from exc
    result = serialize_promotion(run)
    lab.consolidation_results["promotion"] = {**result, "ts": lab.now_ms()}
    lab.bus.emit(
        "promotion.swept",
        summary=f"terfi taraması: {run.summary}",
        data={"applied": result["applied"], "shouldWrite": result["parsed"]["shouldWrite"],
              "reason": result["parsed"]["reason"]},
    )
    return {"promotion": result}


def run_dreaming(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    phase = str(payload.get("phase") or "light")
    if phase not in DREAMING_PHASES:
        raise LabError(400, f"phase must be one of {', '.join(DREAMING_PHASES)}", code="invalid_phase")
    embedding = lab.resolve_embedding(payload)
    store = lab.store(embedding)
    with lab.tracked("dreaming"):
        try:
            sweep = run_dreaming_sweep(
                config=lab.config(mode=lab.default_search_mode(embedding)),
                store=store,
                phase=phase,
                now_ms=lab.now_ms(),
                timezone=LAB_TIMEZONE,
            )
        except Exception as exc:
            raise LabError(
                502,
                f"dreaming run failed: {safe_exception_message(exc, lab.secret_values(payload))}",
                code="dreaming_failed",
                redacted=True,
            ) from exc
    result = serialize_dreaming(sweep)
    if result["filesChanged"]:
        try:
            result.update(lab.reindex(store))
            result["reindexError"] = None
        except Exception as exc:
            result["reindexError"] = safe_exception_message(exc, lab.secret_values(payload))
    lab.consolidation_results["dreaming"] = {**result, "ts": lab.now_ms()}
    lab.bus.emit(
        "dreaming.swept",
        summary=f"rüya: {phase} · {result['candidateCount']} aday",
        data={"phase": phase, "filesChanged": result["filesChanged"], "skipReason": result["skipReason"]},
    )
    return {"dreamingSweep": result}


def run_audit(lab: LabRuntime) -> dict[str, Any]:
    audit = serialize_audit(
        lab, audit_short_term_promotion_artifacts(config=lab.config(), now_ms=lab.now_ms())
    )
    lab.consolidation_results["audit"] = audit
    lab.bus.emit(
        "audit.completed",
        summary=f"denetim: {len(audit['issues'])} sorun",
        data={"issues": len(audit["issues"]), "entryCount": audit["entryCount"]},
    )
    return {"memoryAudit": audit}


def run_repair(lab: LabRuntime) -> dict[str, Any]:
    with lab.tracked("repair"):
        repair = repair_short_term_promotion_artifacts(config=lab.config(), now_ms=lab.now_ms()).as_dict()
    lab.consolidation_results["repair"] = repair
    lab.bus.emit("repair.completed", summary="onarım tamam", data=repair)
    audit = run_audit(lab)["memoryAudit"]
    return {"memoryRepair": repair, "memoryAudit": audit}
