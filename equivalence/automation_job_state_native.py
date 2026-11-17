"""Authenticate and run the original explicit scheduled memory task in isolation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from equivalence.automation_job_state import DIGEST, validate_case, wire
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import prepare_release_runtime

MODULES = Path(__file__).resolve().parent
DRIVER = MODULES / "automation_job_state_native.mjs"
PRELOAD = MODULES / "automation_job_state_native_preload.mjs"
SOURCE_OWNERS = (
    "src/cron/service.ts", "src/cron/service/ops-run.ts", "src/cron/service/ops-run-preparation.ts",
    "src/cron/service/jobs-scheduling.ts", "src/cron/service/timer-execution.ts",
    "src/cron/service/timer-outcomes.ts", "src/cron/heartbeat-task.ts", "src/cron/store.ts",
    "src/cron/schedule.ts", "extensions/memory-core/src/tools.ts",
    "extensions/memory-core/src/memory-read-tool.ts", "packages/memory-host-sdk/src/host/read-file.ts",
)
MAIN_OWNERS = (
    "dist/service-u8zoxec7.mjs", "dist/jobs-scheduling-u2B7TBDi.mjs", "dist/schedule-DpJ8jCLT.mjs",
    "dist/heartbeat-task-BGANU0wH.mjs", "dist/plugin-sdk/cron-store-runtime.js",
    "dist/store-6B9iwkza.mjs", "dist/tools-DotaQGXh.mjs", "dist/read-file-CH8NQLbp.mjs",
)
WRITE_ENTRY = "dist/infra/sqlite-store.worker.js"
WRITE_OWNER = "dist/openclaw-state-worker-runtime-DsFyroJI.mjs"
READ_ENTRY = "dist/infra/sqlite-readonly-location.worker.js"


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _source_bindings(checkout):
    result = []
    for name in SOURCE_OWNERS:
        committed = subprocess.run(["git", "show", f"{REFERENCE_COMMIT}:{name}"], cwd=checkout,
                                   check=True, capture_output=True, timeout=10).stdout
        if (checkout / name).read_bytes() != committed:
            raise ValueError("The scheduled memory task source differs from its pinned checkout")
        result.append({"path": name, "sha256": _digest(committed)})
    return result


def _traces(directory, paths, pid, authority, root, context_digest):
    loaded, bootstraps, traces, module_ids = {}, [], [], set()
    seen_roles = set()
    for file in sorted(directory.glob("trace-*.jsonl")):
        content = file.read_bytes()
        head, *rows = [json.loads(line) for line in content.splitlines()]
        if (head.get("event") != "bootstrap" or head.get("node") != authority["execPath"]
                or head.get("contextSha256") != context_digest
                or file.name != f"trace-{head['pid']}-{head['threadId']}.jsonl"):
            raise ValueError("Unexpected scheduler trace identity")
        if head["pid"] == pid and head["threadId"] == 0 and head["ppid"] == os.getpid():
            role, entry, required = "scheduler", DRIVER, (*MAIN_OWNERS, str(DRIVER), "dist/croner.js")
        elif head["pid"] == pid and head["threadId"] > 0:
            role, entry, required = "store-worker", root / WRITE_ENTRY, (WRITE_ENTRY, WRITE_OWNER, "dist/croner.js")
        elif head["ppid"] == pid and head["threadId"] == 0:
            role, entry, required = "read-location", root / READ_ENTRY, (READ_ENTRY,)
        else:
            raise ValueError("Unexpected scheduler process or worker ancestry")
        if head["entry"] != str(entry):
            raise ValueError("Unexpected scheduled memory task runtime entry: " + head["entry"])
        bootstraps.append({**head, "role": role})
        own = set()
        for row in rows:
            index = row.get("load")
            if type(index) is not int or not 0 <= index < len(paths):
                raise ValueError("Invalid scheduler module load index")
            target, digest, package, name = paths[index]
            module_ids.add(index)
            if package == "driver":
                if role != "scheduler" or Path(target) != DRIVER:
                    raise ValueError("An unexpected task driver ran in an original worker")
                own.add(target)
            elif package == "node_modules/croner":
                own.add(name)
            else:
                loaded[package, name] = {"package": package, "path": name, "sha256": digest}
                if package == "node_modules/openclaw":
                    own.add(name)
        if not set(required) <= own:
            raise ValueError("Scheduled memory task actor omitted its required original owners")
        seen_roles.add(role)
        traces.append({"name": file.name, "sha256": _digest(content), "loads": len(rows)})
    if seen_roles != {"scheduler", "store-worker", "read-location"}:
        raise ValueError("Incomplete scheduler, store and read-location process traces")
    table = {index: {"package": paths[index][2], "path": paths[index][3], "sha256": paths[index][1]}
             for index in sorted(module_ids)}
    (directory / "loaded-modules.json").write_bytes(wire(table))
    return {"bootstraps": bootstraps, "loaded": sorted(loaded.values(), key=lambda row: (row["package"], row["path"])),
            "traces": traces, "moduleTableSha256": _digest(wire(table))}


def run_native(case, *, checkout: Path, runtime_root: Path, node: Path, evidence_directory: Path,
               runtime: dict | None = None, croner_archive: Path | None = None):
    validate_case(case)
    checkout = checkout.resolve(strict=True)
    root = runtime_root.resolve(strict=True)
    if root.name != "openclaw" or root.parent.name != "node_modules":
        raise ValueError("The scheduler requires the official OpenClaw package root")
    cache = root.parents[1]
    if runtime is None:
        runtime = prepare_release_runtime(checkout, cache)
    if (runtime["runtimeRoot"] != str(root) or runtime["buildAttestation"]["commit"] != REFERENCE_COMMIT
            or runtime["kind"] != "verified-release-runtime"):
        raise ValueError("The scheduler requires the verified pinned OpenClaw release")
    authority = prepare_model_node_authority(node)
    sources = _source_bindings(checkout)
    archive = croner_archive or Path(os.environ.get("MEMORY_EQ_CRONER_ARCHIVE",
                        cache.parent / "heartbeat-dependencies/archives/croner-10.0.1.tgz"))
    directory = evidence_directory.resolve() / "scheduled-task-original"
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    request = directory / "request.json"
    request.write_bytes(wire(case))
    for name in ("state", "cache", "tmp"):
        (directory / name).mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix="memory-task-dependency-") as temporary:
        private = Path(temporary)
        extra = prepare_heartbeat_dependency(checkout, private, archive, install=True)
        paths = []
        for package in [*runtime["packages"], extra]:
            for item in package["files"]:
                target = Path(package["directory"]) / item["path"]
                paths.append((str(target), item["sha256"], package["location"], item["path"]))
        paths.append((str(DRIVER), _digest(DRIVER.read_bytes()), "driver", DRIVER.name))
        if len({entry[0] for entry in paths}) != len(paths):
            raise ValueError("Two authenticated artifacts occupy the same scheduler path")
        context_path = private / "context.json"
        context = {"files": [row[:2] for row in paths], "trace": str(directory / "trace"),
                   "scheduler": str(root / "dist/schedule-DpJ8jCLT.mjs"),
                   "croner": str(Path(extra["directory"]) / "dist/croner.js")}
        context_path.write_bytes(wire(context))
        env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
               "OPENCLAW_STATE_DIR": str(directory / "state"), "OPENCLAW_HOME": str(directory),
               "XDG_CACHE_HOME": str(directory / "cache"), "TMPDIR": str(directory / "tmp"),
               "OPENCLAW_LOG_LEVEL": "silent", "NODE_OPTIONS": "--import=" + PRELOAD.as_uri(),
               "MEMORY_EQ_JOB_STATE_CONTEXT": str(context_path)}
        with (directory / "stdout.json").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
            with subprocess.Popen([authority["execPath"], str(DRIVER), str(request), str(root), str(directory)],
                                  cwd=directory, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr) as process:
                try:
                    code = process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    process.kill()
                    raise
        if code:
            raise ValueError(f"Original scheduler exited {code}, see {directory / 'stderr.log'}")
        trace = _traces(directory, paths, process.pid, authority, root, _digest(context_path.read_bytes()))
    result = json.loads((directory / "stdout.json").read_bytes())
    result["raw"].update({
        "sourceBindings": {"referenceCommit": REFERENCE_COMMIT, "sourceBuildReproduced": False, "owners": sources},
        "release": {key: runtime[key] for key in ("buildAttestation", "lockfileSha256", "manifestSha256")},
        "dependency": {key: extra[key] for key in ("name", "version", "integrity", "archiveSha256", "filesSha256")},
        "node": authority, "caseSha256": DIGEST,
        "workspace": str(directory / "workspace"), "store": str(directory / "state/cron/jobs.json"),
        "sqlite": str(directory / "state/state/openclaw.sqlite"),
        "stdoutSha256": _digest((directory / "stdout.json").read_bytes()),
        "driverSha256": _digest(DRIVER.read_bytes()), "preloadSha256": _digest(PRELOAD.read_bytes()),
    })
    result.update(releaseSources=trace["loaded"], releaseTrace=trace)
    return result
