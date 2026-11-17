"""Authenticated original run and Doctor processes for scheduled memory tasks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import UUID

from equivalence.automation_job_outcomes_inputs import migration_input, scheduling_input
from equivalence.automation_job_state import wire
from equivalence.automation_job_state_native import (
    PRELOAD, READ_ENTRY, SOURCE_OWNERS, WRITE_ENTRY, WRITE_OWNER, _digest,
)
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import prepare_release_runtime

DRIVER = Path(__file__).with_suffix(".mjs")
OWNERS = (*SOURCE_OWNERS, "src/cron/service/one-shot-schedule.ts", "src/cron/parse.ts",
          "src/commands/doctor-heartbeat-task-migration.ts", "src/commands/heartbeat-task-legacy.ts",
          "src/cron/heartbeat-monitor.ts", "src/cron/scratch-store.ts",
          "src/infra/heartbeat-runner-session.ts", "src/config/sessions/session-accessor.sqlite-entry.ts")
MAIN = {"dist/plugin-sdk/cron-store-runtime.js", "dist/jobs-scheduling-u2B7TBDi.mjs", "dist/schedule-DpJ8jCLT.mjs"}
MIGRATION = {"dist/doctor-heartbeat-task-migration-BSKsU-82.mjs", "dist/heartbeat-monitor-DczrY0HS.mjs",
             "dist/scratch-store-BsjpiVxl.mjs", "dist/heartbeat-runner-session-BlQRaBUC.mjs",
             "dist/session-accessor.sqlite-entry-BrsmAX-T.mjs"}


def portable_findings(findings, store_path, command):
    rows = []
    for item in findings:
        if (item["path"] != str(store_path)
                or item["fixHint"] != f"Run {command} to convert heartbeat tasks into automations."):
            raise ValueError("Unexpected public task-migration store or remediation")
        rows.append({**item, "path": "<automation-store>",
                     "fixHint": "Run <task-migration-command> to convert heartbeat tasks into automations."})
    return rows


def portable_jobs(jobs, supplied, minted):
    result = []
    for job in jobs:
        if job["id"] in supplied:
            result.append(job)
            continue
        key, identifier = job["declarationKey"], job["id"]
        if UUID(identifier).version != 4 or str(UUID(identifier)) != identifier:
            raise ValueError("Generated task has no canonical UUID4 identity")
        if minted.setdefault(key, identifier) != identifier or len(set(minted.values())) != len(minted):
            raise ValueError("Generated task lost its unique declaration or durable identity")
        result.append({**job, "id": {"declarationKey": key}})
    return result


def _migration(spec, directory, stages):
    seed, *phases = stages
    minted, phases_out = {}, []
    previous = seed["after"]
    for name, phase in zip(spec["phases"], phases, strict=True):
        before = phase["before"]
        after = phase["after"]
        # The session entry's native metadata can include activity timestamps.
        for key in ("store", "monitor", "findings"):
            if before[key] != previous[key]:
                raise ValueError("Original task migration failed to reopen its prior data")
        if before["session"]["entry"].get("heartbeatTaskState") != previous["session"]["entry"].get("heartbeatTaskState"):
            raise ValueError("Legacy timestamps were not durable")
        previous = after
        monitor_id = after["monitor"]["jobId"]
        jobs = [job for job in after["store"]["jobs"] if job["id"] != monitor_id]
        phases_out.append({"phase": name, "receipt": phase["receipt"], "after": {
            "jobs": portable_jobs(jobs, {job["id"] for job in spec["jobs"]}, minted),
            "scratch": after["monitor"]["state"], "legacyTaskState": after["session"]["entry"].get("heartbeatTaskState"),
            "findings": portable_findings(after["findings"], directory / "state/cron/jobs.json", "openclaw doctor --fix"),
        }})
    return {"name": spec["name"], "phases": phases_out}


def _collect_traces(trace_dir, files, node, pid, root, kind, context_digest, loads, *, driver=DRIVER, main_owners=None):
    receipts, roles = [], set()
    for path in sorted(trace_dir.glob("load-*.jsonl")):
        data = path.read_bytes()
        head, *rows = map(json.loads, data.splitlines())
        if (head["event"] != "bootstrap" or head["node"] != str(node) or head["contextSha256"] != context_digest
                or path.name != f"load-{head['pid']}-{head['threadId']}.jsonl"):
            raise ValueError("Invalid original task-outcomes trace identity")
        if head["pid"] == pid and head["threadId"] == 0 and head["ppid"] == os.getpid():
            role, entry = "main", driver
            required = main_owners or (MAIN | ({"dist/service-u8zoxec7.mjs"} if kind == "scheduling" else MIGRATION))
            required = required | {"driver", "dist/croner.js"}
        elif head["pid"] == pid and head["threadId"] > 0:
            owners = {WRITE_ENTRY: ("worker", {WRITE_ENTRY, WRITE_OWNER})}
            if kind == "migration":
                for name in ("disk-budget.worker.js", "session-accessor.sqlite-archive.worker.js"):
                    relative = "dist/config/sessions/" + name
                    owners[relative] = ("session-maintenance", {relative})
            if kind == "dreaming":
                readonly = "dist/cron/store/read-only.worker.js"
                owners[readonly] = ("cron-inspection", {readonly})
            relative = Path(head["entry"]).relative_to(root).as_posix()
            if relative not in owners:
                raise ValueError("Unrecognized original task worker: " + relative)
            role, required = owners[relative]
            entry = root / relative
        elif head["ppid"] == pid and head["threadId"] == 0:
            role, entry, required = "location", root / READ_ENTRY, {READ_ENTRY}
        else:
            raise ValueError("Unexpected scheduled-task process ancestry")
        if str(entry) != head["entry"]:
            raise ValueError("Unexpected scheduled-task actor: " + head["entry"])
        seen = set()
        for row in rows:
            i = row["load"]
            if type(i) is not int or not 0 <= i < len(files):
                raise ValueError("Unexpected original module load")
            _, _, package, name = files[i]
            if package in ("node_modules/openclaw", "node_modules/croner", "driver"):
                seen.add(name)
            loads.add(i)
        if not required <= seen:
            raise ValueError("Missing original scheduled-task actor imports: " + str(required - seen))
        roles.add(role)
        receipts.append({"bootstrap": head, "role": role, "file": path.name, "sha256": _digest(data), "loads": len(rows)})
    if not {"main", "worker"} <= roles:
        raise ValueError("The real scheduler or its SQLite worker did not start")
    return receipts


def run_native(case, *, checkout: Path, runtime_root: Path, node: Path, evidence_directory: Path,
               runtime=None, croner_archive=None):
    value = case["input"]
    if wire(value) not in (wire(scheduling_input()), wire(migration_input())):
        raise ValueError("The native outcomes driver requires its whole frozen input")
    root = runtime_root.resolve(strict=True)
    cache = root.parents[1]
    node = node.resolve(strict=True)
    runtime = runtime or prepare_release_runtime(checkout, cache)
    if runtime["runtimeRoot"] != str(root) or runtime["buildAttestation"]["commit"] != REFERENCE_COMMIT:
        raise ValueError("Expected the verified pinned release")
    authority = prepare_model_node_authority(node)
    sources = []
    for owner in OWNERS:
        raw = subprocess.run(["git", "show", f"{REFERENCE_COMMIT}:{owner}"], cwd=checkout,
                             capture_output=True, check=True, timeout=10).stdout
        if (checkout / owner).read_bytes() != raw:
            raise ValueError("A pinned original task outcome owner changed")
        sources.append({"path": owner, "sha256": _digest(raw)})
    archive = croner_archive or Path(os.environ.get("MEMORY_EQ_CRONER_ARCHIVE",
                       cache.parent / "heartbeat-dependencies/archives/croner-10.0.1.tgz"))
    directory = evidence_directory.resolve() / ("task-outcomes-" + value["kind"])
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    scenarios = value.get("scenarios", [value])
    traces, loads, stages, observed = [], set(), [], []
    with tempfile.TemporaryDirectory(prefix="memory-outcomes-croner-") as tmp:
        private = Path(tmp)
        extra = prepare_heartbeat_dependency(checkout, private, archive, install=True)
        files = [(str(Path(pkg["directory"]) / f["path"]), f["sha256"], pkg["location"], f["path"])
                 for pkg in [*runtime["packages"], extra] for f in pkg["files"]]
        files.append((str(DRIVER), _digest(DRIVER.read_bytes()), "driver", "driver"))
        context = {"files": [entry[:2] for entry in files], "scheduler": str(root / "dist/schedule-DpJ8jCLT.mjs"),
                   "croner": str(Path(extra["directory"]) / "dist/croner.js")}
        for scenario in scenarios:
            fixture = directory / scenario.get("name", "scheduling")
            fixture.mkdir()
            for part in ("state", "cache", "tmp", "workspace"):
                (fixture / part).mkdir(mode=0o700)
            request_path = fixture / "request.json"
            request_path.write_bytes(wire(scenario))
            phases = ["scheduling"] if value["kind"] == "scheduling" else ["seed", *scenario["phases"]]
            raw_stages = []
            for phase in phases:
                stage = fixture / phase
                stage.mkdir()
                context_path = private / "context.json"
                context_path.write_bytes(wire({**context, "trace": str(stage / "load")}))
                env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
                       "OPENCLAW_LOG_LEVEL": "silent", "OPENCLAW_HOME": str(fixture), "OPENCLAW_STATE_DIR": str(fixture / "state"),
                       "XDG_CACHE_HOME": str(fixture / "cache"), "TMPDIR": str(fixture / "tmp"),
                       "NODE_OPTIONS": "--import=" + PRELOAD.as_uri(), "MEMORY_EQ_JOB_STATE_CONTEXT": str(context_path)}
                destination = stage / "result.json"
                with (stage / "stdout.log").open("xb") as out, (stage / "stderr.log").open("xb") as err:
                    with subprocess.Popen([str(node), str(DRIVER), str(request_path), str(root), str(fixture),
                                           phase, str(destination)], cwd=fixture, env=env, stdin=subprocess.DEVNULL,
                                          stdout=out, stderr=err) as process:
                        try:
                            code = process.wait(timeout=60)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            raise
                if code:
                    raise ValueError(f"Scheduled memory outcome exited {code}: {stage / 'stderr.log'}")
                actors = _collect_traces(stage, files, node, process.pid, root, value["kind"],
                                         _digest(context_path.read_bytes()), loads)
                result = destination.read_bytes()
                traces.append({"directory": str(stage), "actors": actors, "requestSha256": _digest(request_path.read_bytes()),
                               "resultSha256": _digest(result), "stdoutSha256": _digest((stage / "stdout.log").read_bytes()),
                               "stderrSha256": _digest((stage / "stderr.log").read_bytes())})
                raw_stages.append(json.loads(result))
            stages.append({"name": fixture.name, "directory": str(fixture), "observations": raw_stages})
            if value["kind"] == "migration":
                observed.append(_migration(scenario, fixture, raw_stages))
        table = {i: {"package": files[i][2], "path": files[i][3], "sha256": files[i][1]} for i in sorted(loads)}
        (directory / "modules.json").write_bytes(wire(table))
    if value["kind"] == "scheduling":
        [batch] = stages[0]["observations"]
        actual = {"probes": batch["probes"], "runs": [{"receipt": row["receipt"], "callbacks": row["callbacks"],
                  "jobs": row["afterStore"]["jobs"]} for row in batch["runs"]]}
    else:
        actual = {"scenarios": observed}
    original = [entry for entry in table.values() if entry["package"] not in {"driver", "node_modules/croner"}]
    raw = {"stages": stages, "node": authority, "sourceBindings": sources, "caseSha256": _digest(wire(case)),
           "release": {key: runtime[key] for key in ("buildAttestation", "lockfileSha256", "manifestSha256")},
           "dependency": {key: extra[key] for key in ("name", "version", "integrity", "archiveSha256", "filesSha256")},
           "driverSha256": _digest(DRIVER.read_bytes()), "preloadSha256": _digest(PRELOAD.read_bytes())}
    return {"actual": actual, "raw": raw, "releaseSources": original,
            "releaseTrace": {"traces": traces, "moduleTableSha256": _digest(wire(table))}}
