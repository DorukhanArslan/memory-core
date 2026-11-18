"""Run the four frozen turn-outcome cases against the pinned original release."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from equivalence.automation_job_state_native import PRELOAD, _digest
from equivalence.automation_job_state_native import READ_ENTRY, WRITE_ENTRY, WRITE_OWNER
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.heartbeat_turn_outcomes import build_cases, wire
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import prepare_release_runtime

DRIVER = Path(__file__).resolve().with_suffix(".mjs")
CLOCK = DRIVER.with_name("heartbeat_turn_outcomes_native_clock.mjs")
OWNERS = (
    "src/infra/heartbeat-runner-run.ts", "src/infra/heartbeat-runner-execution.ts",
    "src/infra/heartbeat-runner-prompt.ts", "src/infra/heartbeat-runner-session.ts",
    "src/infra/heartbeat-dispatch.ts", "src/infra/heartbeat-events.ts", "src/infra/system-events.ts",
    "src/infra/system-event-ownership.ts", "src/infra/outbound/deliver-channel.ts",
    "src/infra/outbound/deliver-core.ts", "src/infra/delivery-queue-sqlite.kernel.ts",
    "src/cron/scratch-store.ts", "src/cron/store.ts", "src/cron/service.ts",
    "src/cron/service/ops-run-preparation.ts", "src/cron/service/jobs-scheduling.ts",
    "src/cron/service/timer-execution.ts", "src/cron/heartbeat-task.ts",
    "src/config/sessions/session-accessor.sqlite-entry.ts",
)
MAIN = {
    "dist/heartbeat-runner-run-CGCaTa5u.mjs", "dist/system-events-CGtOrtY9.mjs",
    "dist/system-event-ownership-rW7KBn85.mjs", "dist/session-accessor-CiKKTlbe.mjs",
    "dist/scratch-store-BsjpiVxl.mjs", "dist/plugin-sdk/cron-store-runtime.js",
    "dist/registry-empty-BTjzcMW2.mjs", "dist/runtime-9cxii0oQ.mjs",
}
LEASE_OWNER = "dist/openclaw-state-lease-worker-storage-CTe98nAl.mjs"


def _trace_actors(directory, table, case, evidence):
    root = Path(evidence["runtimeRoot"])
    required = MAIN | {"clock", "driver"}
    if any("tasks" in step for step in case["input"]["steps"]):
        required |= {"dist/service-u8zoxec7.mjs", "dist/jobs-scheduling-u2B7TBDi.mjs", "dist/croner.js"}
    workers = {WRITE_ENTRY, "dist/state/openclaw-state-read.worker.js",
               "dist/config/sessions/session-transcript.worker.js", "dist/config/sessions/disk-budget.worker.js",
               "dist/config/sessions/session-accessor.sqlite-archive.worker.js"}
    receipts, observed, actor_ids, used = [], set(), set(), set()
    pid = evidence["processPid"]
    for file in sorted(directory.glob("load-*.jsonl")):
        data = file.read_bytes()
        head, *entries = (json.loads(line) for line in data.splitlines())
        child, parent, thread = head["pid"], head["ppid"], head["threadId"]
        if (head["event"] != "bootstrap" or head["node"] != evidence["nodePath"]
                or head["contextSha256"] != evidence["contextSha256"] or (child, thread) in actor_ids
                or file.name != f"load-{child}-{thread}.jsonl"):
            raise ValueError("Unexpected heartbeat actor bootstrap")
        actor_ids.add((child, thread))
        if child == pid and parent == evidence["coordinatorPid"] and thread == 0:
            role, owners = "main", required
            if head["entry"] != evidence["driverPath"]:
                raise ValueError("Unexpected heartbeat main entry")
        elif child == pid and parent == evidence["coordinatorPid"] and thread > 0:
            role = Path(head["entry"]).relative_to(root).as_posix()
            if role not in workers:
                raise ValueError("Unrecognized heartbeat worker: " + role)
            owners = {"clock", role}
        elif parent == pid and thread == 0 and Path(head["entry"]) == root / READ_ENTRY:
            role, owners = "read-location", {"clock", READ_ENTRY}
        else:
            raise ValueError("Unexpected heartbeat worker ancestry")
        indexes = [e["load"] for e in entries]
        if any(type(i) is not int or str(i) not in table for i in indexes) or len(set(indexes)) != len(indexes):
            raise ValueError("Unexpected heartbeat load index")
        names = {table[str(i)]["path"] for i in indexes if table[str(i)]["package"]
                 in ("driver", "node_modules/croner", "node_modules/openclaw")}
        if role == WRITE_ENTRY:
            if WRITE_OWNER in names:
                role = "state-store"
            else:
                role = "lease-store"
                owners.add(LEASE_OWNER)
        if not owners <= names:
            raise ValueError("Missing heartbeat owner(s) in " + role + ": " + str(owners - names))
        observed.add(role)
        used.update(map(str, indexes))
        receipts.append({"file": file.name, "sha256": _digest(data), "loads": len(entries), "role": role,
                         "bootstrap": head})
    required_roles = (workers - {WRITE_ENTRY}) | {"main", "state-store", "lease-store"}
    if not required_roles <= observed:
        raise ValueError("Missing heartbeat process actors: " + str(required_roles - observed))
    return receipts, used


def _source_bindings(checkout):
    rows = []
    for path in OWNERS:
        actual = (checkout / path).read_bytes()
        pinned = subprocess.run(["git", "show", f"{REFERENCE_COMMIT}:{path}"], cwd=checkout,
                                check=True, capture_output=True, timeout=10).stdout
        if actual != pinned:
            raise ValueError("The heartbeat source differs from its pinned commit: " + path)
        rows.append({"path": path, "sha256": _digest(actual)})
    return {"referenceCommit": REFERENCE_COMMIT, "owners": rows, "sourceBuildReproduced": False}


def _physical_state(directory):
    paths = {"state/state/openclaw.sqlite": ("cron_jobs", "cron_job_scratch"),
             "state/agents/main/agent/openclaw-agent.sqlite": ("session_nodes", "session_key_contract")}
    result = {}
    for relative, tables in paths.items():
        path = (directory / relative).resolve(strict=True)
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            # These table names are fixed here and never come from a scenario.
            result[relative] = {name: [{k: ({"hex": v.hex()} if isinstance(v, bytes) else v)
                                         for k, v in dict(row).items()}
                                        for row in db.execute('SELECT * FROM "' + name + '"')]
                                for name in tables}
    return result


def run_native(case, *, checkout: Path, runtime_root: Path, node: Path, evidence_directory: Path,
               runtime=None, croner_archive=None):
    if wire(case) not in [wire(item) for item in build_cases()]:
        raise ValueError("Expected a complete frozen heartbeat turn-outcome case")
    root = runtime_root.resolve(strict=True)
    checkout = checkout.resolve(strict=True)
    node = node.resolve(strict=True)
    cache = root.parents[1]
    runtime = runtime or prepare_release_runtime(checkout, cache)
    if (runtime["kind"] != "verified-release-runtime" or runtime["runtimeRoot"] != str(root)
            or runtime["buildAttestation"]["commit"] != REFERENCE_COMMIT):
        raise ValueError("The heartbeat requires the verified pinned release")
    authority = prepare_model_node_authority(node)
    sources = _source_bindings(checkout)
    archive = croner_archive or Path(os.environ.get("MEMORY_EQ_CRONER_ARCHIVE",
                        cache.parent / "heartbeat-dependencies/archives/croner-10.0.1.tgz"))
    directory = evidence_directory.resolve() / case["id"]
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    for item in ("state", "workspace", "cache", "tmp"):
        (directory / item).mkdir(mode=0o700)
    request = directory / "request.json"
    request.write_bytes(wire(case))
    clock = directory / "clock"
    clock.write_text(str(case["input"]["nowMs"]))
    result_file = directory / "result.json"
    with tempfile.TemporaryDirectory(prefix="memory-heartbeat-outcomes-") as tmp:
        private = Path(tmp)
        extra = prepare_heartbeat_dependency(checkout, private, archive, install=True)
        files = [(str(Path(pkg["directory"]) / item["path"]), item["sha256"], pkg["location"], item["path"])
                 for pkg in [*runtime["packages"], extra] for item in pkg["files"]]
        files.extend((str(file), _digest(file.read_bytes()), "driver", name)
                     for file, name in [(DRIVER, "driver"), (CLOCK, "clock")])
        if len({item[0] for item in files}) != len(files):
            raise ValueError("Two authenticated heartbeat artifacts occupy the same location")
        context_path = private / "context.json"
        context_path.write_bytes(wire({"trace": str(directory / "load"), "files": [item[:2] for item in files],
                                      "scheduler": str(root / "dist/schedule-DpJ8jCLT.mjs"),
                                      "croner": str(Path(extra["directory"]) / "dist/croner.js")}))
        env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
               "OPENCLAW_LOG_LEVEL": "silent", "OPENCLAW_HOME": str(directory),
               "OPENCLAW_CONFIG_PATH": str(directory / "config.json"), "OPENCLAW_STATE_DIR": str(directory / "state"),
               "XDG_CACHE_HOME": str(directory / "cache"), "TMPDIR": str(directory / "tmp"),
               "NODE_OPTIONS": f"--import={PRELOAD.as_uri()} --import={CLOCK.as_uri()}",
               "MEMORY_EQ_HEARTBEAT_CLOCK": str(clock), "MEMORY_EQ_JOB_STATE_CONTEXT": str(context_path)}
        with (directory / "stdout.log").open("xb") as out, (directory / "stderr.log").open("xb") as err:
            with subprocess.Popen([str(node), str(DRIVER), str(request), str(root), str(directory), str(result_file)],
                                  cwd=directory, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err) as process:
                try:
                    code = process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    process.kill()
                    raise
        if code:
            raise ValueError(f"Original heartbeat exited {code}: {directory / 'stderr.log'}")
        evidence = {"runtimeRoot": str(root), "nodePath": str(node), "driverPath": str(DRIVER),
                    "coordinatorPid": os.getpid(), "processPid": process.pid, "contextSha256": _digest(context_path.read_bytes())}
        complete = {str(i): {"package": pkg, "path": name, "sha256": digest}
                    for i, (_, digest, pkg, name) in enumerate(files)}
        # Persist the loaded subset along with its stable index space.
        actors, used = _trace_actors(directory, complete, case, evidence)
        table = {i: complete[i] for i in sorted(used, key=int)}
    (directory / "modules.json").write_bytes(wire(table))
    trace = {**evidence, "actors": actors, "moduleTableSha256": _digest(wire(table)),
             "files": {name: _digest((directory / name).read_bytes()) for name in
                       ("request.json", "result.json", "stdout.log", "stderr.log", "modules.json")}}
    result = json.loads(result_file.read_bytes())
    result["raw"].update({"evidence": trace, "sourceBindings": sources, "release": {k: runtime[k] for k in
                              ("buildAttestation", "lockfileSha256", "manifestSha256")},
                          "dependency": {k: extra[k] for k in ("name", "version", "integrity", "archiveSha256", "filesSha256")},
                          "node": authority, "physical": _physical_state(directory),
                          "driverSha256": _digest(DRIVER.read_bytes()), "clockSha256": _digest(CLOCK.read_bytes()),
                          "preloadSha256": _digest(PRELOAD.read_bytes())})
    validate_native(case, result["raw"], result["actual"], evidence_directory)
    return {**result, "releaseTrace": trace,
            "releaseSources": [item for item in table.values() if item["package"] not in ("driver", "node_modules/croner")]}


def validate_native(case, raw, actual, attempt):
    """Reopen the bytes, actors and SQLite owners and rederive every compared observation."""
    if wire(case) not in {wire(item) for item in build_cases()}:
        raise ValueError("Unrecognized heartbeat outcome case")
    directory = Path(attempt) / case["id"]
    trace = raw["evidence"]
    expected_files = ("request.json", "result.json", "stdout.log", "stderr.log", "modules.json")
    if (trace["files"] != {name: _digest((directory / name).read_bytes()) for name in expected_files}
            or (directory / "request.json").read_bytes() != wire(case)):
        raise ValueError("A retained heartbeat observation or input changed")
    table = json.loads((directory / "modules.json").read_bytes())
    actors, used = _trace_actors(directory, table, case, trace)
    if (set(table) != used or trace["actors"] != actors or trace["moduleTableSha256"] != _digest(wire(table))
            or raw["node"]["execPath"] != trace["nodePath"] or raw["sourceBindings"]["referenceCommit"] != REFERENCE_COMMIT
            or raw["release"]["buildAttestation"]["commit"] != REFERENCE_COMMIT
            or {item["path"] for item in raw["sourceBindings"]["owners"]} != set(OWNERS)):
        raise ValueError("The retained heartbeat process owners changed")
    driver_digests = {row["path"]: row["sha256"] for row in table.values() if row["package"] == "driver"}
    if (driver_digests != {"driver": _digest(DRIVER.read_bytes()), "clock": _digest(CLOCK.read_bytes())}
            or driver_digests != {"driver": raw["driverSha256"], "clock": raw["clockSha256"]}
            or raw["preloadSha256"] != _digest(PRELOAD.read_bytes())):
        raise ValueError("The heartbeat driver identity changed")
    captured = json.loads((directory / "result.json").read_bytes())
    if (captured != {"actual": actual, "raw": {"initial": raw["initial"], "steps": raw["steps"]}}
            or raw["physical"] != _physical_state(directory)):
        raise ValueError("Captured heartbeat outputs or physical store evidence changed")
    derived = []
    previous = raw["initial"]
    supply = []
    for index, (step, row) in enumerate(zip(case["input"]["steps"], raw["steps"], strict=True)):
        at = case["input"]["nowMs"] + 60_000 * index
        if row["at"] != at or row["label"] != step["label"] or len(row["calls"]) > 1:
            raise ValueError("Unexpected heartbeat tick, step or number of model calls")
        before, after = row["before"], row["after"]
        state = before["monitor"]["state"]
        if before["session"] != previous["session"]:
            raise ValueError("The previous heartbeat session was not reopened")
        if "scratch" in step:
            if not row["scratchWrite"]["ok"] or state["scratch"]["content"] != step["scratch"]:
                raise ValueError("The scratch input did not reach the original store")
        elif state != previous["monitor"]["state"]:
            raise ValueError("The monitor scratch changed between heartbeat turns")
        if after["monitor"] != before["monitor"]:
            raise ValueError("Heartbeat unexpectedly changed its input monitor")
        if "tasks" in step:
            supply = step["tasks"]
        if supply:
            tasks = {t["jobId"] for t in supply}
            calls = [t["jobId"] for wake in row["wakes"] for t in wake["wake"]["tasks"]]
            receipts = {r["id"]: r["result"] for r in row["cronReceipts"]}
            if (set(receipts) != tasks or sorted(calls) != sorted(row["due"])
                    or {k for k, r in receipts.items() if r["ok"] and r["ran"]} != set(calls)
                    or set(tasks) - set(calls) != {k for k, r in receipts.items() if r.get("reason") == "not-due"}
                    or sorted(calls) != sorted(t["jobId"] for t in row["runArguments"]["tasks"])):
                raise ValueError("Persisted cron scheduling disagrees with its real heartbeat callback receipts")
        queue_before = before["queue"]
        prior_ids = [e["id"] for e in previous["queue"]]
        if ([e["id"] for e in queue_before[:len(prior_ids)]] != prior_ids
                or [{k: event[k] for k in ("text", "contextKey")} for event in queue_before[len(prior_ids):]]
                != step.get("events", [])):
            raise ValueError("Queued event occurrences did not survive to the next heartbeat")
        result = row["run"]
        if len(row["events"]) > 1:
            raise ValueError("Multiple heartbeat dispositions for one turn")
        event = row["events"][0] if row["events"] else {}
        sends = row["sends"]
        status = result["status"]
        if status in ("failed", "skipped"):
            disposition = status
            if event and (event["status"] != status or event.get("reason") != result["reason"]):
                raise ValueError("Heartbeat event disagrees with its public run receipt")
        elif status == "ran" and event.get("status") == "skipped":
            disposition = event["reason"]
        elif status == "ran" and event.get("status") in ("ok-empty", "ok-token"):
            disposition = "quiet"
        elif status == "ran" and event.get("status") == "sent":
            disposition = "delivered"
        else:
            raise ValueError("Unknown original heartbeat run or event")
        if (disposition == "delivered") != bool(sends):
            raise ValueError("The reported delivery disagrees with the local recipient")
        for sent in sends:
            if (sent["args"]["to"] != "42000" or sent["result"]["chatId"] != "42000"
                    or sent["result"]["channel"] != "telegram" or sent["args"]["text"] != event["preview"]):
                raise ValueError("Unexpected local heartbeat recipient or delivery text")
        session_fields = ("lastHeartbeatText", "lastHeartbeatSentAt")
        after_fields = tuple(after["session"].get(k) for k in session_fields)
        before_fields = tuple(before["session"].get(k) for k in session_fields)
        if after_fields != ((sends[-1]["args"]["text"], at) if sends else before_fields):
            raise ValueError("Durable delivery state does not agree with the recording recipient")
        context = row["calls"][0]["args"][0] if row["calls"] else {}
        if row["calls"]:
            call = row["calls"][0]
            if (call.get("error", {}).get("message") != step.get("error")
                    or (not step.get("error") and call["result"] != {"text": step["reply"]})):
                raise ValueError("The scripted reply/error did not reach the model boundary")
        derived.append({"label": row["label"], "status": status, "reason": result.get("reason"),
                        "disposition": disposition, "body": context.get("Body"),
                        "internalTurnSource": context.get("InternalTurnSource"),
                        "queueAfter": [{"text": e["text"], "contextKey": e.get("contextKey")} for e in after["queue"]],
                        "sent": [s["args"]["text"] for s in sends]})
        previous = after
    if actual != derived:
        raise ValueError("The heartbeat comparison does not follow from the physical run observations")
    db = raw["physical"]["state/state/openclaw.sqlite"]
    if {j["job_id"] for j in db["cron_jobs"]} != {j["id"] for j in previous["store"]["jobs"]}:
        raise ValueError("The final durable cron job identities changed")
    scratch = previous["monitor"]["state"].get("scratch")
    if [(r["content"], r["revision"]) for r in db["cron_job_scratch"]] != (
            [(scratch["content"], scratch["revision"])] if scratch else []):
        raise ValueError("The final durable monitor scratch changed")
    agent = raw["physical"]["state/agents/main/agent/openclaw-agent.sqlite"]["session_nodes"]
    if len(agent) != 1 or any(json.loads(agent[0]["entry_json"]).get(k) != previous["session"].get(k)
                              for k in ("sessionId", "lastHeartbeatText", "lastHeartbeatSentAt")):
        raise ValueError("The final durable heartbeat session changed")
    return True
