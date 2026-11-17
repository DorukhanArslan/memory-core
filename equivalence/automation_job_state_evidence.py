"""Check that a match reached the task and read real workspace bytes on both sides."""
import json
from pathlib import Path
from equivalence.automation_job_state import validate_case, wire


def _same(actual, expected, label):
    if wire(actual) != wire(expected):
        raise ValueError("Scheduled memory task evidence: " + label)


def validate_observation(case, output):
    validate_case(case)
    value = case["input"]
    jobs = {row["id"]: row for row in value["jobs"]}
    files = dict(value["files"])
    if set(output) != {"steps"}:
        raise ValueError("Unexpected scheduled task output fields")
    # Each position is a distinct observable boundary; a pair of silent runners
    # or a runner that wakes both simultaneous jobs cannot satisfy this fixture.
    for step, observed, calls in zip(value["steps"], output["steps"], (0, 1, 0, 1, 0, 1, 1), strict=True):
        files.update(step["writes"])
        if set(observed) != {"jobId", "atMs", "callbacks", "files"}:
            raise ValueError("Unexpected scheduled task observation shape")
        job_id = step["jobId"]
        _same(observed["jobId"], job_id, "different driven job")
        _same(observed["atMs"], step["atMs"], "different clock")
        _same(observed["files"], files, "scheduled read changed the supplied workspace")
        _same(len(observed["callbacks"]), calls, "expected task boundary was not reached")
        for cb in observed["callbacks"]:
            job = jobs[job_id]
            _same(cb["wake"], {"source": "interval", "intent": "task", "agentId": job["agentId"],
                               "reason": "heartbeat-task:" + job_id, "tasks": [{
                                   "jobId": job_id, "name": job["name"], "prompt": job["payload"]["text"],
                               }]}, "wrong task or wake fields")
            args = value["toolCalls"][job_id]
            _same(cb["tool"]["arguments"], args, "tool arguments differ from the selected task")
            _same(cb["tool"]["name"], "memory_get", "wrong memory tool")
            result = cb["tool"]["result"]
            _same(result["path"], args["path"], "reader opened a different path")
            if args["path"] in files:
                _same(result["text"], files[args["path"]].splitlines()[args["from"] - 1],
                      "excerpt did not come from the current source")
                _same(result["status"], "ok", "reader did not return a live excerpt")
            else:
                _same(result["status"], "not_found", "the absent note was not read")


def validate_sdk(case, raw, output, directory, *, recorded_directory=None):
    validate_observation(case, output)
    workspace = Path(directory).resolve() / "workspace"
    recorded = Path(recorded_directory or directory).resolve() / "workspace"
    _same(raw["workspace"], str(recorded), "SDK workspace ownership differs")
    store = workspace / ".memory-core" / "automation.json"
    if Path(raw["store"]) != recorded / ".memory-core" / "automation.json" or store.is_symlink():
        raise ValueError("SDK scheduled task must use its own durable file store")
    previous = None
    for step, saved in zip(output["steps"], raw["steps"], strict=True):
        _same(saved["observation"], step, "SDK return lost its raw observation")
        if previous is not None:
            _same(saved["beforeStore"], previous, "SDK durable state did not survive reopen")
        previous = saved["afterStore"]
        before, after = ({job["id"]: job for job in json.loads(saved[key])["jobs"]}
                         for key in ("beforeStore", "afterStore"))
        receipt = saved["run"]
        if not step["callbacks"]:
            _same(receipt, None, "SDK callback ran when no task was admitted")
            _same(after, before, "SDK recorded a job on a silent drive")
            continue
        job_id = step["jobId"]
        wake = step["callbacks"][0]["wake"]
        [task] = receipt["turn"]["scheduled_tasks"]
        _same([{"jobId": task["job_id"], "name": task["name"], "prompt": task["prompt"]}],
              wake["tasks"], "SDK wake and prepared turn diverged")
        _same(receipt["jobs"], [before[job_id]], "SDK completed a different task")
        _same(receipt["recorded"], [after[job_id]], "SDK returned a different durable run")
        _same(after[job_id]["state"]["lastRunAtMs"], step["atMs"], "SDK did not record the completed run")
        _same({k: v for k, v in before.items() if k != job_id},
              {k: v for k, v in after.items() if k != job_id}, "SDK touched an unrelated job")
    _same(previous, store.read_text(encoding="utf8"), "SDK final file differs from its receipt")
    for name, contents in output["steps"][-1]["files"].items():
        _same((workspace / name).read_bytes().decode("utf8"), contents, "SDK final source bytes differ")


def validate_native(case, raw, output):
    """Bind each original wake and entire public tool result to the actual run receipt."""
    validate_observation(case, output)
    previous = raw["initialStore"]
    for step, saved in zip(output["steps"], raw["steps"], strict=True):
        _same([saved["jobId"], saved["atMs"]], [step["jobId"], step["atMs"]], "native drive identity differs")
        _same(saved["beforeStore"], previous, "native job store did not survive reopen")
        previous = saved["afterStore"]
        expected_files = {name: data.encode("utf8").hex() for name, data in step["files"].items()}
        _same(saved["fileBytes"], expected_files, "original filesystem bytes differ from the observed contents")
        if not step["callbacks"]:
            _same(saved["run"], {"ok": True, "ran": False, "reason": "not-due"}, "native drive unexpectedly ran")
            _same(saved["afterStore"], saved["beforeStore"], "native job mutated on a silent drive")
            _same(saved["events"], [], "unexpected native run event")
        else:
            _same(saved["run"], {"ok": True, "ran": True}, "native wake lacks a successful run receipt")
            events = saved["events"]
            _same([row["action"] for row in events], ["started", "finished", "scheduled"],
                  "native run did not complete and reschedule")
            job_id = step["jobId"]
            for event in events:
                _same(event["jobId"], job_id, "native event targets a different job")
            before, after = ({job["id"]: job for job in saved[key]["jobs"]} for key in ("beforeStore", "afterStore"))
            _same(events[1]["job"], after[job_id], "native completion does not reference the durable job")
            _same(events[1]["runAtMs"], step["atMs"], "native drive did not use the supplied clock")
            _same({k: v for k, v in before.items() if k != job_id},
                  {k: v for k, v in after.items() if k != job_id}, "native drive mutated another job")
        for callback, source in zip(step["callbacks"], saved["callbacks"], strict=True):
            _same(callback["wake"], source["wake"], "original wake differs from the callback")
            _same(callback["tool"]["name"], source["tool"]["name"], "different original tool")
            _same(callback["tool"]["arguments"], source["tool"]["arguments"], "different original arguments")
            envelope = source["tool"]["envelope"]
            if set(envelope) != {"content", "details"}:
                raise ValueError("Unexpected original scheduler memory tool envelope")
            [content] = envelope["content"]
            _same(content["type"], "text", "unsupported original tool envelope")
            _same(json.loads(content["text"]), envelope["details"], "original text and details disagree")
            _same(callback["tool"]["result"], envelope["details"], "original tool result is incomplete")
