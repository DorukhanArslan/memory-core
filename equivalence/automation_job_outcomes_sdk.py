"""Drive host scheduling and Doctor migration through their public SDK owners."""
from dataclasses import asdict
import json
from pathlib import Path

from equivalence.automation_job_outcomes_native import portable_findings, portable_jobs
from memory_core.automation import AutomationJob, FileAutomationStore, compute_job_next_run_at_ms, is_job_due
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.heartbeat_migration import (
    MIGRATE_HEARTBEAT_TASKS_COMMAND, heartbeat_task_migration_findings, migrate_session_heartbeat_tasks,
)
from memory_core.host import HostKit, SessionState
from memory_core.session_catalog import MemorySessionCatalog


def _scheduling(value, directory):
    probes, probe_errors = [], []
    for index, item in enumerate(value["probes"]):
        job = AutomationJob.from_json(item["job"])
        due = is_job_due(job, item["nowMs"], forced=item["forced"])
        try:
            next_run = compute_job_next_run_at_ms(job, item["nowMs"])
            probes.append({"nextRunAtMs": next_run, "due": due})
        except ValueError as exc:
            probe_errors.append({"index": index, "name": type(exc).__name__, "message": str(exc)})
            probes.append({"due": due, "scheduleError": str(exc)})
    store = FileAutomationStore(directory)
    store.save_jobs([AutomationJob.from_json(job) for job in value["jobs"]])
    runs, raw = [], []
    for spec in value["runs"]:
        before = store.path.read_bytes().decode("utf8")
        callbacks = []
        def heartbeat(run):
            callbacks.append({"wake": run.scheduled_wake.to_json(), "reply": spec["reply"]})
            return spec["reply"]

        config = MemoryConfig(workspace_dir=directory, agent_id="main", flags=FeatureFlags(vector_search=False))
        kit = HostKit(Memory.from_workspace(directory, config=config, initialize=False), now_ms=lambda: spec["atMs"])
        session = SessionState.new(session_key="agent:main:main", session_id="scheduling", kind="main")
        receipt = kit.run_heartbeat_task(session, spec["jobId"], heartbeat, forced=spec["mode"] == "force", ensure=False)
        after = store.path.read_bytes().decode("utf8")
        jobs = [job.to_json() for job in FileAutomationStore(directory).list_jobs()]
        runs.append({"receipt": receipt, "callbacks": callbacks, "jobs": jobs})
        raw.append({"beforeStore": before, "afterStore": after, "observation": runs[-1]})
    return {"probes": probes, "runs": runs}, {"probes": probes, "probeErrors": probe_errors, "runs": raw, "store": str(store.path)}


def _migration(value, directory):
    output, raw = [], []
    for spec in value["scenarios"]:
        root = directory / spec["name"]
        root.mkdir()
        store = FileAutomationStore(root)
        monitor = store.enroll_heartbeat_monitor("main", "fixture-monitor")
        store.write_job_scratch("main", monitor.job_id, spec["scratch"], now_ms=spec["nowMs"])
        store.save_jobs([AutomationJob.from_json(job) for job in spec["jobs"]])
        session_key = "agent:main:main"
        def reopen_session():
            return MemorySessionCatalog(root / "sessions.sqlite", clock_ms=lambda: spec["nowMs"])

        reopen_session().upsert_session(session_key, {"sessionId": "legacy", "heartbeatTaskState": spec["legacyTaskState"]})
        phases, captures, minted = [], [], {}
        for phase in spec["phases"]:
            store = FileAutomationStore(root)
            catalog = reopen_session()
            before = {"store": store.path.read_bytes().decode("utf8"), "session": catalog.get_session_entry(session_key)}
            result = migrate_session_heartbeat_tasks(store, catalog, session_key, repair=phase != "preview", now_ms=spec["nowMs"])
            store = FileAutomationStore(root)
            session = reopen_session().get_session_entry(session_key)
            scratch = store.read_heartbeat_monitor_scratch("main")
            findings = [item.to_json() for item in heartbeat_task_migration_findings(store)]
            jobs = [job.to_json() for job in store.list_jobs()]
            receipt = {"changes": list(result.changes), "warnings": list(result.warnings)}
            phases.append({"phase": phase, "receipt": receipt, "after": {
                "jobs": portable_jobs(jobs, {job["id"] for job in spec["jobs"]}, minted),
                "scratch": scratch.state.to_json(), "legacyTaskState": session.get("heartbeatTaskState"),
                "findings": portable_findings(findings, store.path, MIGRATE_HEARTBEAT_TASKS_COMMAND)}})
            captures.append({"before": before, "receipt": asdict(result), "after": {
                "store": store.path.read_bytes().decode("utf8"), "session": session, "monitor": scratch.state.to_json(),
                "jobs": jobs, "findings": findings}, "observed": phases[-1]})
        output.append({"name": spec["name"], "phases": phases})
        raw.append({"name": spec["name"], "storePath": str(store.path), "sessionPath": str(catalog.path), "phases": captures})
    return {"scenarios": output}, {"scenarios": raw}


def run_sdk(case, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    kind = case["input"]["kind"]
    actual, raw = {"scheduling": _scheduling, "migration": _migration}[kind](case["input"], directory)
    (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True) + "\n", encoding="utf8")
    return actual
