"""Run a heartbeat through the public host kit with a real file store and local recipient."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import hashlib
import json
from pathlib import Path

from equivalence.heartbeat_turn_outcomes import build_cases, wire
from memory_core.automation import AutomationJob, FileAutomationStore
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.heartbeat_events import HeartbeatSystemEvent
from memory_core.host import HostKit, SessionState
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY


def _raw(value):
    if isinstance(value, SessionState):
        return value.to_json()
    if is_dataclass(value):
        return {field.name: _raw(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _raw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_raw(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _snapshot(path):
    return path.read_text(encoding="utf8") if path.is_file() else None


def run_sdk(case, directory):
    if wire(case) not in {wire(c) for c in build_cases()}:
        raise ValueError("Unexpected heartbeat outcome fixture")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / "workspace"
    workspace.mkdir()
    store = FileAutomationStore(workspace)
    state_file = directory / "host-session.json"
    delivered = directory / "delivered.jsonl"
    delivered.write_bytes(b"")
    session = SessionState.new(session_key="agent:main:main", session_id="heartbeat-outcomes", kind="main")
    state_file.write_bytes(wire(session.to_json()))
    config = MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(workspace, config=config, initialize=False)
    queue, actual, captures = [], [], []
    serial = 0

    def append_events(events):
        nonlocal serial
        for item in events:
            serial += 1
            queue.append(HeartbeatSystemEvent(str(serial), item["text"], item["contextKey"]))

    for i, step in enumerate(case["input"]["steps"]):
        at = case["input"]["nowMs"] + i * 60_000
        if "scratch" in step:
            owner = store.enroll_heartbeat_monitor("main", "orchard-monitor")
            store.write_job_scratch("main", owner.job_id, step["scratch"],
                                    expected_owner_generation=owner.generation, now_ms=at)
        if "tasks" in step:
            jobs = [AutomationJob(id=item["jobId"], name=item["name"], agent_id="main", every_ms=86_400_000,
                       text=item["prompt"], anchor_ms=at, created_at_ms=at, updated_at_ms=at,
                       declaration_key="heartbeat-task:main:" + item["jobId"],
                       next_run_at_ms=at if item["due"] else at + 86_400_000)
                    for item in step["tasks"]]
            store.save_jobs(jobs)
        append_events(step.get("events", []))
        before_queue = _raw(queue)
        session_before = state_file.read_bytes()
        before_store = _snapshot(store.path)
        session = SessionState.from_json(json.loads(session_before))
        kit = HostKit(memory, now_ms=lambda: at, timezone="UTC", time_format="12",
                      identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        local = step.get("target") == "local"
        run = kit.heartbeat_prompt(session, source=step["source"], reason=step["reason"],
            every=step.get("every", "5m"), main_queue_size=1 if step.get("busy") else 0,
            pending_events=tuple(queue), can_relay_to_user=local, prompt=step.get("prompt"), ensure=False)
        calls = []

        def reply(prepared):
            calls.append({"turn": _raw(prepared.turn), "context": _raw(prepared.context),
                          "session": prepared.session.to_json(), "scheduled": _raw(prepared.jobs)})
            append_events(step.get("late", []))
            if "error" in step:
                raise RuntimeError(step["error"])
            return step["reply"]

        def send(text):
            with delivered.open("ab") as stream:
                stream.write(wire({"text": text}) + b"\n")

        before_sent = len(delivered.read_bytes().splitlines())
        result = run.dispatch(reply, send=send if local else None)
        queue = [event for event in queue if event.id not in result.consumed_event_ids]
        state_file.write_bytes(wire(result.session.to_json()))
        sent = [json.loads(line)["text"] for line in delivered.read_bytes().splitlines()[before_sent:]]
        observation = {"label": step["label"], "status": result.status, "reason": result.reason,
                       "disposition": result.disposition, "body": calls[0]["turn"]["message"] if calls else None,
                       "internalTurnSource": calls[0]["turn"]["internal_turn_source"] if calls else None,
                       "queueAfter": [{"text": event.text, "contextKey": event.context_key} for event in queue],
                       "sent": sent}
        actual.append(observation)
        captures.append({"label": step["label"], "queueBefore": before_queue, "queueAfter": _raw(queue),
                         "sessionBefore": json.loads(session_before), "sessionAfter": json.loads(state_file.read_bytes()),
                         "storeBefore": before_store, "storeAfter": _snapshot(store.path), "calls": calls,
                         "result": _raw(result), "recipientAfter": delivered.read_text(encoding="utf8"),
                         "observation": observation})
    raw = {"caseSha256": hashlib.sha256(wire(case)).hexdigest(), "drives": captures,
           "workspace": str(workspace), "files": {"session": state_file.name, "recipient": delivered.name,
           "store": str(store.path.relative_to(directory))}}
    (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, allow_nan=False) + "\n")
    return actual
