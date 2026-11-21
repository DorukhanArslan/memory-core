"""Replay the appended families and include each original scope point in its own gate."""
from __future__ import annotations

from equivalence import automation_job_outcomes, automation_job_state, compaction_assembly, dream_deep, dream_diary, dream_light, dream_rem, workspace_lock_cases
from equivalence.harness import _same_json
from equivalence.release_runtime import prepare_release_runtime

from followup_compaction import replay_active_history, replay_compaction
from equivalence import compaction_active_history
from equivalence import datetime_regex_family
from equivalence import engine_unicode_collation
from followup_unicode import replay_unicode
from followup_datetime import replay_datetime
import followup_date_boundaries as date_boundaries
from followup_diary import replay_diary
from followup_dreams import replay_dreams
from followup_flush import replay_flush
from equivalence import flush_plan_target
from followup_heartbeat import HEARTBEAT_GATE, replay_heartbeat
from followup_heartbeat_outcomes import replay_heartbeat_outcomes
from equivalence import heartbeat_turn_outcomes
from equivalence import heartbeat_turn_boundaries
from equivalence import recovery_failure, recovery_repair
from followup_interrupted_publication import replay_interrupted_publication
from followup_recovery import replay_recovery
from followup_jobs import replay_jobs
from followup_locks import replay_locks
from equivalence import provider_overflow_cases
from followup_overflow import replay_overflow


from equivalence import configured_redaction
from followup_configured_redaction import replay_configured_redaction
import followup_secret_boundaries
from equivalence.secret_boundary_inputs import POINTS as SECRET_BOUNDARIES


from equivalence import heartbeat_scratch_acceptance
from followup_scratch import replay_scratch


FAMILIES = {
    heartbeat_scratch_acceptance.OPERATION: (heartbeat_scratch_acceptance, "heartbeatScratchOutcomesComplete", replay_scratch),
    date_boundaries.POINT: (date_boundaries, "datetimeRegexBoundaryComplete", date_boundaries.replay),
    configured_redaction.POINT: (configured_redaction, "configuredRedactionOutcomesComplete", replay_configured_redaction),
    SECRET_BOUNDARIES[0]: (followup_secret_boundaries, "secretRedactionBoundariesComplete",
                           followup_secret_boundaries.replay_secret_boundaries),
    engine_unicode_collation.OPERATION: (engine_unicode_collation, "engineUnicodeFamilyComplete", replay_unicode),
    recovery_failure.OPERATION: (recovery_failure, "recoveryInterruptionFamilyComplete", replay_interrupted_publication),
    datetime_regex_family.REQUIREMENT: (datetime_regex_family, "datetimeRegexFamilyComplete", replay_datetime),
    provider_overflow_cases.OPERATION: (provider_overflow_cases, "providerOverflowFamilyComplete", replay_overflow),
    flush_plan_target.OPERATION: (flush_plan_target, "flushPlanTargetFamilyComplete", replay_flush),
    recovery_repair.REQUIREMENT: (recovery_repair, "recoveryRepairFamilyComplete", replay_recovery),
    heartbeat_turn_outcomes.OPERATION: (heartbeat_turn_outcomes, "heartbeatTurnOutcomesComplete", replay_heartbeat_outcomes),
    HEARTBEAT_GATE: (heartbeat_turn_boundaries, "heartbeatExclusionsComplete", replay_heartbeat),
    dream_light.OPERATION: (dream_light, "dreamLightFamilyComplete", replay_dreams),
    dream_rem.OPERATION: (dream_rem, "dreamRemFamilyComplete", replay_dreams),
    dream_deep.OPERATION: (dream_deep, "dreamDeepFamilyComplete", replay_dreams),
    dream_diary.OPERATION: (dream_diary, "dreamDiaryFamilyComplete", replay_diary),
    automation_job_state.OPERATION: (automation_job_state, "automationJobStateBoundariesComplete", replay_jobs),
    automation_job_outcomes.OPERATION: (automation_job_outcomes, "automationJobOutcomesComplete", replay_jobs),
    compaction_active_history.POINT: (compaction_active_history, "compactionActiveHistoryComplete", replay_active_history),
    compaction_assembly.OPERATION: (compaction_assembly, "compactionAssemblyRestartComplete", replay_compaction),
    workspace_lock_cases.OPERATION: (workspace_lock_cases, "workspaceLockFamilyComplete", replay_locks),
}
REPORT_FIELDS = {field for _, field, _ in FAMILIES.values()} | {
    "heartbeatScratchEvidenceDirectory", "heartbeatScratchError",
    "unicodeSourceImports", "unicodeRuntime", "unicodeSdkRuntime",
    "datetimeSourceImports", "modelSessionRuntimeBindings", "modelNodeAuthority", "redactionPolicySourceBindings",
    "recoveryInterruptionBindings", "recoveryInterruptionNode", "recoveryArtifactBindings", "recoveryArtifactNode", "recoveryIndexBindings", "recoveryIndexNode",
    "heartbeatCorpusSourceImports", "flushExecutionBindings", "flushPlanTargetNode", "dreamLightBindings", "dreamLightNode", "dreamRemBindings", "dreamRemNode", "dreamDiaryBindings", "dreamDiaryNode", "dreamDeepBindings", "dreamDeepNode", "workspaceLockBindings"}


def family_key(case):
    if case.get("id") in date_boundaries.IDS:
        return date_boundaries.POINT
    if configured_redaction.POINT in case.get("covers", ()):
        return configured_redaction.POINT
    if SECRET_BOUNDARIES[0] in case.get("covers", ()):
        return SECRET_BOUNDARIES[0]
    if compaction_active_history.active_case(case):
        return compaction_active_history.POINT
    if case.get("requirement") == datetime_regex_family.REQUIREMENT:
        return datetime_regex_family.REQUIREMENT
    if case["operation"] in {recovery_repair.ARTIFACT, recovery_repair.INDEX}:
        return recovery_repair.REQUIREMENT
    if HEARTBEAT_GATE in case.get("covers", ()):
        return HEARTBEAT_GATE
    return case["operation"]


def replay_followup(data, definitions, args, metrics, replay_rank):
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    results = {}
    expected = [case["id"] for case in definitions if family_key(case) in FAMILIES]
    rows = data["followupRows"]
    if set(rows) != set(expected):
        raise ValueError("An appended case is missing")
    for case in definitions:
        if case["id"] not in rows:
            continue
        required = {"case"} if (family_key(case) == HEARTBEAT_GATE and case["operation"] == "session-projection") else {"case", "native", "python", "trace"}
        if family_key(case) in {configured_redaction.POINT, SECRET_BOUNDARIES[0]} and case["operation"] == "redaction-policy-source":
            required = {"case", "python", "sourcePolicy"}
        if case["operation"] in {engine_unicode_collation.OPERATION, heartbeat_scratch_acceptance.OPERATION}:
            required = {"case"}
        if family_key(case) in {datetime_regex_family.REQUIREMENT, date_boundaries.POINT}:
            if case["operation"] in {datetime_regex_family.CLOCK, "session-projection"}:
                required = {"case"}
            elif case["operation"] == "redaction-policy-source":
                required = {"case", "python", "sourcePolicy"}
        if set(rows[case["id"]]) != required:
            raise ValueError("An appended case, process trace or complete diagnostic is missing")
    for op, (family, field, replay) in FAMILIES.items():
        cases = [c for c in definitions if family_key(c) == op]
        if not _same_json(cases, family.build_cases()):
            raise ValueError("The registered ordered family differs from its frozen definitions")
        if op == datetime_regex_family.REQUIREMENT:
            evidence = replay(data, cases, args, runtime, replay_rank)
        else:
            evidence = replay(data, cases, args, runtime)
        if [r["id"] for r in evidence] != [case["id"] for case in cases]:
            raise ValueError("Physical replay omitted or substituted a case")
        passed = (all(r["publicMatch"] is (r["id"] != date_boundaries.DIAGNOSTIC) for r in evidence)
                  if op == date_boundaries.POINT else all(r["publicMatch"] is True for r in evidence))
        if not (data[field] is family.family_complete(data["cases"]) is metrics["families"][op] is passed):
            raise ValueError("Appended family gate disagrees with the independent physical replay")
        results[op] = {"gate": field, "passed": passed, "cases": evidence,
                       "scopePoints": sorted({p for c in cases for p in c["covers"]})}
    return results
