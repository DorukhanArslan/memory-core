"""Replay the appended families and include each original scope point in its own gate."""
from __future__ import annotations

from equivalence import automation_job_outcomes, automation_job_state, dream_diary, dream_light, dream_rem, workspace_lock_cases
from equivalence.harness import _same_json
from equivalence.release_runtime import prepare_release_runtime

from followup_diary import replay_diary
from followup_dreams import replay_dreams
from followup_jobs import replay_jobs
from followup_locks import replay_locks


FAMILIES = {
    dream_light.OPERATION: (dream_light, "dreamLightFamilyComplete", replay_dreams),
    dream_rem.OPERATION: (dream_rem, "dreamRemFamilyComplete", replay_dreams),
    dream_diary.OPERATION: (dream_diary, "dreamDiaryFamilyComplete", replay_diary),
    automation_job_state.OPERATION: (automation_job_state, "automationJobStateBoundariesComplete", replay_jobs),
    automation_job_outcomes.OPERATION: (automation_job_outcomes, "automationJobOutcomesComplete", replay_jobs),
    workspace_lock_cases.OPERATION: (workspace_lock_cases, "workspaceLockFamilyComplete", replay_locks),
}
REPORT_FIELDS = {field for _, field, _ in FAMILIES.values()} | {
    "dreamLightBindings", "dreamLightNode", "dreamRemBindings", "dreamRemNode", "dreamDiaryBindings", "dreamDiaryNode", "workspaceLockBindings"}


def replay_followup(data, definitions, args, metrics):
    runtime = prepare_release_runtime(args.reference, args.release_runtime, download=False)
    results = {}
    expected = [case["id"] for case in definitions if case["operation"] in FAMILIES]
    rows = data["followupRows"]
    if set(rows) != set(expected) or not all(set(row) == {"case", "native", "python", "trace"} for row in rows.values()):
        raise ValueError("An appended case, process trace or complete diagnostic is missing")
    for op, (family, field, replay) in FAMILIES.items():
        cases = [c for c in definitions if c["operation"] == op]
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
