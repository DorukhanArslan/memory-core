"""Drive individually selected tasks through the public HostKit and file store."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from equivalence.automation_job_state import validate_case
from memory_core.automation import AutomationJob, FileAutomationStore, compute_job_next_run_at_ms
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState


def run_sdk(case, directory: Path):
    validate_case(case)
    value = case["input"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / "workspace"
    workspace.mkdir()
    for name, content in value["files"].items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    store = FileAutomationStore(workspace)
    now = value["nowMs"]
    jobs = []
    for row in value["jobs"]:
        job = AutomationJob.from_json({**row, "createdAtMs": now, "updatedAtMs": now})
        jobs.append(replace(job, next_run_at_ms=compute_job_next_run_at_ms(job, now)))
    store.save_jobs(jobs)

    actual, raw_steps = [], []
    for step in value["steps"]:
        for name, content in step["writes"].items():
            (workspace / name).write_bytes(content.encode())
        at = step["atMs"]
        before = store.path.read_text(encoding="utf8")
        config = MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=False))
        memory = Memory.from_workspace(workspace, config=config, initialize=False)
        kit = HostKit(memory, now_ms=lambda: at)
        state = SessionState.new(session_key="agent:main:main", session_id="scheduled", kind="main")
        run = kit.heartbeat_task_prompt(state, step["jobId"], ensure=False)
        callbacks = []
        receipt = None
        if run is not None:
            if run.context is None or run.scheduled_wake is None or len(run.turn.scheduled_tasks) != 1:
                raise ValueError("The job did not produce a dispatchable individual heartbeat turn")
            (task,) = run.turn.scheduled_tasks
            arguments = value["toolCalls"][task.job_id]
            result = kit.dispatch("memory_get", arguments, session=run.session)
            callbacks.append({"wake": run.scheduled_wake.to_json(),
                              "tool": {"name": "memory_get", "arguments": arguments, "result": result}})
            outcome = run.complete(result["text"], ended_at_ms=at)
            receipt = {"turn": asdict(run.turn), "jobs": [job.to_json() for job in run.jobs],
                       "recorded": [job.to_json() for job in outcome.jobs_recorded],
                       "decision": asdict(outcome.decision), "transcript": outcome.transcript}
        after = store.path.read_text(encoding="utf8")
        files = {name: (workspace / name).read_bytes().decode("utf8") for name in value["files"]}
        actual.append({"jobId": step["jobId"], "atMs": at, "callbacks": callbacks, "files": files})
        raw_steps.append({"beforeStore": before, "afterStore": after, "run": receipt, "observation": actual[-1]})

    raw = {"workspace": str(workspace.resolve()), "store": str(store.path.resolve()), "steps": raw_steps}
    (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True) + "\n", encoding="utf8")
    return {"steps": actual}
