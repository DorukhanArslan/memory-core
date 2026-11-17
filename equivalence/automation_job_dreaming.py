"""Portable observations of live managed dreaming and offline Doctor repairs."""
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from equivalence.automation_job_dreaming_inputs import KEY, dreaming_input
from equivalence.automation_job_outcomes_native import _collect_traces, portable_jobs
from equivalence.automation_job_state import wire
from equivalence.automation_job_state_native import PRELOAD, _digest
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.release_runtime import prepare_release_runtime
from memory_core.automation import AutomationJob, FileAutomationStore
from memory_core.consolidation.dreaming_automation import reconcile_dreaming_jobs, repair_dreaming_jobs

DRIVER = Path(__file__).with_name("automation_job_dreaming_native.mjs")
SOURCE = ("extensions/memory-core/src/dreaming-cron.ts", "extensions/memory-core/src/dreaming.ts",
          "extensions/memory-core/src/migration/doctor-dreaming-cron.ts", "extensions/memory-core/src/migration/dreaming-cron-classifier.ts",
          "src/memory-host-sdk/dreaming.ts", "src/plugins/services.ts", "src/plugins/service-cron.ts",
          "src/cron/store/doctor.ts", "src/commands/doctor-sqlite-maintenance-lock.ts")
MAIN = {"dist/extensions/memory-core/index.js", "dist/extensions/memory-core/doctor-contract-api.js",
        "dist/services-Bej96uol.mjs", "dist/service-u8zoxec7.mjs", "dist/doctor-Dbs5zYHU.mjs",
        "dist/doctor-sqlite-maintenance-lock-CjN2a1si.mjs", "dist/openclaw-agent-db-DRy3ui_B.mjs",
        "dist/plugin-lifecycle-lease-Bv0VNQKi.mjs"}


def _check(case):
    if wire(case["input"]) != wire(dreaming_input()):
        raise ValueError("The managed dreaming case must contain the complete frozen sequence")


def _backup_rows(file, original, store_path):
    if file.is_symlink() or not file.is_file() or not file.name.endswith(".bak"):
        raise ValueError("Missing verified Doctor backup")
    if not original:
        return json.loads(file.read_bytes())["jobs"]
    jobs = []
    with sqlite3.connect(file.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        if db.execute("pragma integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Original SQLite backup failed integrity checking")
        for definition, state, updated in db.execute(
            "SELECT job_json,state_json,runtime_updated_at_ms FROM cron_jobs WHERE store_key=? ORDER BY sort_order",
            (str(store_path),)):
            job = json.loads(definition)
            job["state"] = json.loads(state)
            if updated is not None:
                job["updatedAtMs"] = updated
            jobs.append(job)
    return jobs


def _backup_digests(raw, store_path, original):
    return {path: _digest(Path(path).read_bytes()) for row in raw["phases"] for path in row["backups"]
            if _owned_backup(Path(path), store_path, original)}


def _owned_backup(path, store, original):
    parent = store.parents[1] / "state" if original else store.parent
    base = r"openclaw\.sqlite\.doctor-cron-[0-9]+-" if original else re.escape(store.name) + r"\.doctor-cron-"
    if (not path.is_absolute() or path.parent != parent
            or not re.fullmatch(base + r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}\.bak", path.name)):
        raise ValueError("Invalid managed dreaming backup provenance")
    return True


def _observe(spec, raw, store_path, original, *, retained=None, recorded=None, digests=None):
    supplied, minted = {job["id"] for job in spec["jobs"]}, {}
    previous = raw["initial"]["jobs"]
    if previous != spec["jobs"]:
        raise ValueError("Dreaming job seed did not persist exactly")
    phases = []
    seen_backups = set()
    for step, row in zip(spec["phases"], raw["phases"], strict=True):
        if row["before"]["jobs"] != previous or row["operation"] != step["operation"]:
            raise ValueError("A dreaming phase did not observe the preceding store")
        previous = row["after"]["jobs"]
        backups = [Path(path) for path in row["backups"]]
        backup = None
        if backups:
            [file] = backups
            _owned_backup(file, store_path, original)
            if str(file) in seen_backups:
                raise ValueError("Doctor reused a backup identity")
            seen_backups.add(str(file))
            physical = retained / file.relative_to(recorded) if recorded is not None else file
            if not physical.is_file() or physical.resolve(strict=True) != physical or physical.stat().st_nlink != 1:
                raise ValueError("Doctor backup is unavailable or is not an independent retained file")
            if digests is not None and _digest(physical.read_bytes()) != digests.get(str(file)):
                raise ValueError("Retained Doctor backup changed since capture")
            backup = _backup_rows(physical, original, store_path)
            if backup != row["before"]["jobs"]:
                raise ValueError("Doctor backup does not contain the complete pre-repair job set")
        storage = "SQLite" if original else "JSON"
        command = "openclaw doctor --fix" if original else "repair_dreaming_jobs()"
        def message(text):
            text = text.replace(f" in {store_path} ", " in <automation-store> ")
            text = text.replace(f" after a verified {storage} backup.", " after a verified <store> backup.")
            text = text.replace(f"run {command}. Runtime reconciliation", "run <repair-command>. Runtime reconciliation")
            if backups:
                text = text.replace(f"{storage} backup: {file}.", "<store> backup: <verified-backup>.")
            return text
        receipt = row["receipt"]
        if receipt is not None:
            receipt = {k: [message(s) for s in v] if isinstance(v, list) else v for k, v in receipt.items()}
        phases.append({"operation": row["operation"], "receipt": receipt,
                       "jobs": portable_jobs(previous, supplied, minted),
                       "logs": [{**entry, "message": message(entry["message"])} for entry in row["logs"]],
                       "backupJobs": None if backup is None else portable_jobs(backup, supplied, minted)})
    if digests is not None and set(digests) != seen_backups:
        raise ValueError("Unexpected extra or missing Doctor backup")
    return {"name": spec["name"], "phases": phases}


def run_sdk(case, directory):
    _check(case)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    observations, raws = [], []
    for spec in case["input"]["scenarios"]:
        root = directory / spec["name"]
        root.mkdir()
        store = FileAutomationStore(root)
        store.save_jobs([AutomationJob.from_json(row) for row in spec["jobs"]])
        phases = []
        raw = {"initial": {"jobs": [row.to_json() for row in store.list_jobs()]}, "phases": phases}
        for index, step in enumerate(spec["phases"]):
            store = FileAutomationStore(root)
            cfg = {"plugins": {"entries": {"memory-core": {"config": {"dreaming": step["dreaming"]}}}}}
            before = {"jobs": [row.to_json() for row in store.list_jobs()]}
            previous_backups = set(store.path.parent.glob("*.bak"))
            logs, receipt = [], None
            if step["operation"] == "reconcile":
                logs = reconcile_dreaming_jobs(store, cfg, now_ms=case["input"]["nowMs"] + index)
            else:
                receipt = repair_dreaming_jobs(store, cfg, preview=step["operation"] == "doctor-preview")
            phases.append({"operation": step["operation"], "before": before,
                           "after": {"jobs": [row.to_json() for row in store.list_jobs()]}, "logs": logs, "receipt": receipt,
                           "backups": sorted(str(p) for p in set(store.path.parent.glob("*.bak")) - previous_backups)})
        observations.append(_observe(spec, raw, store.path, False))
        raws.append({"store": str(store.path), "data": raw, "backupSha256": _backup_digests(raw, store.path, False)})
    raw = {"scenarios": raws}
    actual = {"scenarios": observations}
    validate_raw(case, raw, actual, original=False)
    (directory / "python-raw.json").write_bytes(wire([raw]))
    return actual


def run_native(case, *, checkout, runtime_root, node, evidence_directory, runtime=None, croner_archive=None):
    _check(case)
    root, node = runtime_root.resolve(strict=True), node.resolve(strict=True)
    cache = root.parents[1]
    runtime = runtime or prepare_release_runtime(checkout, cache)
    if runtime["runtimeRoot"] != str(root) or runtime["buildAttestation"]["commit"] != REFERENCE_COMMIT:
        raise ValueError("Expected the pinned managed dreaming release")
    authority = prepare_model_node_authority(node)
    source = []
    for owner in SOURCE:
        data = subprocess.run(["git", "show", f"{REFERENCE_COMMIT}:{owner}"], cwd=checkout, capture_output=True,
                              check=True, timeout=10).stdout
        if data != (checkout / owner).read_bytes():
            raise ValueError("The original dreaming source changed")
        source.append({"path": owner, "sha256": _digest(data)})
    archive = croner_archive or Path(os.environ.get("MEMORY_EQ_CRONER_ARCHIVE", cache.parent /
                                                   "heartbeat-dependencies/archives/croner-10.0.1.tgz"))
    directory = Path(evidence_directory).resolve() / "managed-dreaming"
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    loads, observations, trace, raw = set(), [], [], []
    with tempfile.TemporaryDirectory(prefix="dreaming-croner-") as temp:
        private = Path(temp)
        extra = prepare_heartbeat_dependency(checkout, private, archive, install=True)
        files = [(str(Path(pkg["directory"]) / f["path"]), f["sha256"], pkg["location"], f["path"])
                 for pkg in [*runtime["packages"], extra] for f in pkg["files"]]
        files.append((str(DRIVER), _digest(DRIVER.read_bytes()), "driver", "driver"))
        for spec in case["input"]["scenarios"]:
            stage = directory / spec["name"]
            stage.mkdir()
            for name in ("state", "cache", "tmp", "workspace"):
                (stage / name).mkdir(mode=0o700)
            context = {"files": [row[:2] for row in files], "scheduler": str(root / "dist/schedule-DpJ8jCLT.mjs"),
                       "croner": str(Path(extra["directory"]) / "dist/croner.js"), "trace": str(stage / "load")}
            context_path = private / "context.json"
            context_path.write_bytes(wire(context))
            request = stage / "request.json"
            request.write_bytes(wire({"scenario": spec, "nowMs": case["input"]["nowMs"]}))
            result = stage / "result.json"
            env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
                   "OPENCLAW_LOG_LEVEL": "silent", "OPENCLAW_HOME": str(stage), "OPENCLAW_STATE_DIR": str(stage / "state"),
                   "XDG_CACHE_HOME": str(stage / "cache"), "TMPDIR": str(stage / "tmp"),
                   "NODE_OPTIONS": "--import=" + PRELOAD.as_uri(), "MEMORY_EQ_JOB_STATE_CONTEXT": str(context_path)}
            with (stage / "stdout.log").open("xb") as out, (stage / "stderr.log").open("xb") as err:
                with subprocess.Popen([str(node), str(DRIVER), str(request), str(root), str(stage), str(result)],
                                      cwd=stage, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err) as child:
                    try:
                        code = child.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        raise
            if code:
                raise ValueError(f"Original dreaming exited {code}: {stage / 'stderr.log'}")
            actors = _collect_traces(stage, files, node, child.pid, root, "dreaming", _digest(context_path.read_bytes()),
                                     loads, driver=DRIVER, main_owners=MAIN)
            data = json.loads(result.read_bytes())
            store_path = stage / "state/cron/jobs.json"
            observations.append(_observe(spec, data, store_path, True))
            raw.append({"store": str(store_path), "data": data, "backupSha256": _backup_digests(data, store_path, True)})
            trace.append({"directory": str(stage), "actors": actors, "resultSha256": _digest(result.read_bytes()),
                          "requestSha256": _digest(request.read_bytes()), "stderrSha256": _digest((stage / "stderr.log").read_bytes()),
                          "stdoutSha256": _digest((stage / "stdout.log").read_bytes())})
        table = {i: {"package": files[i][2], "path": files[i][3], "sha256": files[i][1]} for i in sorted(loads)}
        (directory / "modules.json").write_bytes(wire(table))
    result = {"actual": {"scenarios": observations}, "raw": {"scenarios": raw, "node": authority, "sourceBindings": source,
            "caseSha256": _digest(wire(case)), "driverSha256": _digest(DRIVER.read_bytes()), "preloadSha256": _digest(PRELOAD.read_bytes()),
            "release": {k: runtime[k] for k in ("buildAttestation", "lockfileSha256", "manifestSha256")},
            "dependency": {k: extra[k] for k in ("name", "version", "integrity", "archiveSha256", "filesSha256")}},
            "releaseSources": [r for r in table.values() if r["package"] not in {"driver", "node_modules/croner"}],
            "releaseTrace": {"traces": trace, "moduleTableSha256": _digest(wire(table))}}
    validate_raw(case, result["raw"], result["actual"], original=True)
    return result


def validate_observation(case, output):
    _check(case)
    scenarios = case["input"]["scenarios"]
    for spec, observed in zip(scenarios, output["scenarios"], strict=True):
        if spec["name"] != observed["name"]:
            raise ValueError("Wrong managed dreaming scenario")
        unowned = [r for r in spec["jobs"] if r["id"] in {"operator", "elsewhere"}]
        for expected, stage in zip(spec["phases"], observed["phases"], strict=True):
            if stage["operation"] != expected["operation"] or any(r not in stage["jobs"] for r in unowned):
                raise ValueError("A dreaming operation replaced a user-authored job or changed phase")
        phases = observed["phases"]
        owned = [[job for job in phase["jobs"] if job.get("declarationKey") == KEY] for phase in phases]
        if spec["name"] == "lifecycle":
            first, second, updated = (rows[0] for rows in owned[:3])
            if ([len(rows) for rows in owned] != [1, 1, 1, 0] or first != second or first["id"] != updated["id"]
                    or first["schedule"]["expr"] != "0 3 * * *" or first["payload"]["kind"] != "agentTurn"
                    or updated["schedule"] != {"kind": "cron", "expr": "17 4 * * *", "tz": "Europe/Istanbul"}
                    or updated["state"]["nextRunAtMs"] == first["state"]["nextRunAtMs"]):
                raise ValueError("Managed dreaming add, reopen, update or removal did not occur")
        elif spec["name"] == "managed-edits":
            if (owned[0] != owned[1] or len(owned[0]) != 1 or owned[0][0]["id"] != "duplicate"
                    or owned[0][0]["payload"].get("timeoutSeconds") != 55):
                raise ValueError("Managed dreaming lost the selected declaration or operator fields")
        else:
            repaired = next(stage for stage in phases if stage["operation"] == "doctor-repair")
            if (repaired["backupJobs"] != spec["jobs"] or len(repaired["receipt"]["changes"]) != 1
                    or not repaired["receipt"]["warnings"]):
                raise ValueError("Managed dreaming Doctor did not retain its full backup or ownership warning")
            if spec["name"] == "historical":
                pre, post = phases[1], phases[2]
                survivor = next(job for job in post["jobs"] if job["id"] == "previous-deep")
                if (pre["jobs"] != spec["jobs"] or len(post["jobs"]) != 3 or post["jobs"] != phases[3]["jobs"]
                        or survivor.get("declarationKey") != KEY or survivor["state"] != spec["jobs"][1]["state"]):
                    raise ValueError("Historical dreaming repair disturbed state, IDs or ownership")
            elif len(repaired["jobs"]) != len(unowned):
                raise ValueError("Disabled dreaming Doctor did not retire the historical job")


def validate_raw(case, raw, output, *, original, retained_directory=None, recorded_directory=None):
    validate_observation(case, output)
    if (retained_directory is None) != (recorded_directory is None):
        raise ValueError("Dreaming evidence relocation requires both retained and recorded roots")
    recorded = Path(recorded_directory) if recorded_directory is not None else None
    retained = Path(retained_directory) if retained_directory is not None else None
    if retained is not None and (not retained.is_absolute() or retained.resolve(strict=True) != retained
                                 or not recorded.is_absolute() or ".." in recorded.parts):
        raise ValueError("Managed dreaming evidence must use an absolute owned root")
    for spec, source, observed in zip(case["input"]["scenarios"], raw["scenarios"], output["scenarios"], strict=True):
        store = Path(source["store"])
        if recorded is not None:
            suffix = Path(spec["name"]) / ("state/cron/jobs.json" if original else ".memory-core/automation.json")
            valid = {suffix, Path("managed-dreaming") / suffix} if original else {suffix}
            if store.relative_to(recorded) not in valid:
                raise ValueError("Dreaming source store escaped its recorded scenario")
        if original:
            for record in source["data"]["phases"]:
                if (record["operation"] == "reconcile" and record["registeredServices"] != ["memory-core-dreaming"]
                        or record["operation"] == "doctor-repair" and not record["backups"]):
                    raise ValueError("The original managed dreaming service or Doctor did not execute")
        if _observe(spec, source["data"], store, original, retained=retained, recorded=recorded,
                    digests=source["backupSha256"]) != observed:
            raise ValueError("Managed dreaming public observations differ from their actual receipts")
