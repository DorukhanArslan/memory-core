"""Replay the appended families and include each original scope point in its own gate."""
from __future__ import annotations

from equivalence import automation_job_outcomes, automation_job_state, compaction_assembly, dream_deep, dream_diary, dream_light, dream_rem, workspace_lock_cases
from equivalence.harness import _same_json
from equivalence.release_runtime import prepare_release_runtime

from followup_compaction import replay_compaction
from followup_diary import replay_diary
from followup_dreams import replay_dreams
from followup_flush import replay_flush
from equivalence import flush_plan_target
from followup_heartbeat import HEARTBEAT_GATE, replay_heartbeat
from equivalence import heartbeat_turn_boundaries
from equivalence import recovery_repair
from followup_recovery import replay_recovery
from followup_jobs import replay_jobs
from followup_locks import replay_locks


FAMILIES = {
    flush_plan_target.OPERATION: (flush_plan_target, "flushPlanTargetFamilyComplete", replay_flush),
    recovery_repair.REQUIREMENT: (recovery_repair, "recoveryRepairFamilyComplete", replay_recovery),
    HEARTBEAT_GATE: (heartbeat_turn_boundaries, "heartbeatExclusionsComplete", replay_heartbeat),
    dream_light.OPERATION: (dream_light, "dreamLightFamilyComplete", replay_dreams),
    dream_rem.OPERATION: (dream_rem, "dreamRemFamilyComplete", replay_dreams),
    dream_deep.OPERATION: (dream_deep, "dreamDeepFamilyComplete", replay_dreams),
    dream_diary.OPERATION: (dream_diary, "dreamDiaryFamilyComplete", replay_diary),
    automation_job_state.OPERATION: (automation_job_state, "automationJobStateBoundariesComplete", replay_jobs),
    automation_job_outcomes.OPERATION: (automation_job_outcomes, "automationJobOutcomesComplete", replay_jobs),
    compaction_assembly.OPERATION: (compaction_assembly, "compactionAssemblyRestartComplete", replay_compaction),
    workspace_lock_cases.OPERATION: (workspace_lock_cases, "workspaceLockFamilyComplete", replay_locks),
}
REPORT_FIELDS = {field for _, field, _ in FAMILIES.values()} | {
    "recoveryArtifactBindings", "recoveryArtifactNode", "recoveryIndexBindings", "recoveryIndexNode",
    "heartbeatCorpusSourceImports", "flushExecutionBindings", "flushPlanTargetNode", "dreamLightBindings", "dreamLightNode", "dreamRemBindings", "dreamRemNode", "dreamDiaryBindings", "dreamDiaryNode", "dreamDeepBindings", "dreamDeepNode", "workspaceLockBindings"}


def family_key(case):
    if case["operation"] in {recovery_repair.ARTIFACT, recovery_repair.INDEX}:
        return recovery_repair.REQUIREMENT
    if HEARTBEAT_GATE in case.get("covers", ()):
        return HEARTBEAT_GATE
    return case["operation"]


def replay_followup(data, definitions, args, metrics):
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
        if set(rows[case["id"]]) != required:
            raise ValueError("An appended case, process trace or complete diagnostic is missing")
    for op, (family, field, replay) in FAMILIES.items():
        cases = [c for c in definitions if family_key(c) == op]
        if not _same_json(cases, family.build_cases()):
            raise ValueError("The registered ordered family differs from its frozen definitions")
        evidence = replay(data, cases, args, runtime)
        if [r["id"] for r in evidence] != [case["id"] for case in cases]:
            raise ValueError("Physical replay omitted or substituted a case")
        passed = all(r["publicMatch"] is True for r in evidence)
        if not (data[field] is family.family_complete(data["cases"]) is metrics["families"][op] is passed):
            raise ValueError("Appended family gate disagrees with the independent physical replay")
        results[op] = {"gate": field, "passed": passed, "cases": evidence,
                       "scopePoints": sorted({p for c in cases for p in c["covers"]})}
    return results
