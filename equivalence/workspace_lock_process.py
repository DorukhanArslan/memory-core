"""Drive two independent applications against the same (or deliberately separate) workspace."""

import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

from equivalence.workspace_lock_cases import build_cases


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, allow_nan=False), encoding="utf8")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_bytes())


def _wait_marker(root, actor, process, marker):
    target = root / actor / (marker + ".json")
    deadline = time.monotonic() + 35
    while not target.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise ValueError(f"{actor} did not reach {marker}; original streams at {root / actor}")
        time.sleep(0.02)
    return read_json(target)


def _journals(root):
    result = {}
    for name in ("A", "B"):
        path = root / "workspaces" / name / "journal.txt"
        result[name] = path.read_bytes().hex() if path.is_file() else None
    return result


def retained_leases(root, side):
    if side == "native":
        database = root / "state" / "state" / "openclaw.sqlite"
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT entry_key, value_json FROM plugin_state_entries "
                                      "WHERE plugin_id=? AND namespace=? ORDER BY entry_key",
                                      ("memory-core", "short-term-locks")).fetchall()
        return [{"key": key, "value": json.loads(value)} for key, value in rows]
    from memory_core.consolidation.store import promotion_lock_path
    return [{"workspace": space.name, "bytes": path.read_bytes().hex()}
            for space in sorted((root / "workspaces").iterdir())
            if (path := promotion_lock_path(space)).exists()]


def _sdk_start(root, role, case):
    actor_dir = root / role
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    with (actor_dir / "stdout.log").open("wb") as stdout, (actor_dir / "stderr.log").open("wb") as stderr:
        return subprocess.Popen([sys.executable, "-m", "equivalence.workspace_lock_writer",
                                 str(root), role], env=env, stdout=stdout, stderr=stderr)


def _sdk_finish(root, role, process):
    path = root / role
    records = [json.loads(line) for line in (path / "receipts.jsonl").read_bytes().splitlines()]
    streams = {name: (path / name).read_text() for name in ("stdout.log", "stderr.log")}
    return {"pid": process.pid, "returncode": process.returncode, "receipts": records,
            "streams": streams, "files": {str(p.relative_to(root)): p.read_bytes().hex() for p in
                                         (root / "workspaces").rglob("*") if p.is_file()}}


def run_drive(case, root: Path, *, node=None, runtime=None):
    if case not in build_cases():
        raise ValueError("Unknown independent writer drive")
    if (node is None) != (runtime is None):
        raise ValueError("Native writer needs its pinned Node and release")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for name in ("holder", "waiter", "workspaces/A", "workspaces/B"):
        (root / name).mkdir(parents=True)
    write_json(root / "case.json", case)
    payload = case["input"]
    clocks = {"holder": payload["epochMs"], "waiter": payload["epochMs"] + payload["ageMs"]}
    write_json(root / "clock.json", clocks)
    observations = []
    processes = {}
    receipts = {}

    def snapshot(event):
        observations.append({"event": event, "journals": _journals(root), "clock": clocks.copy()})

    def start(role):
        if node is None:
            process = _sdk_start(root, role, case)
        else:
            from equivalence.workspace_lock_native import start_actor
            process = start_actor(root, role, case, node, runtime)
        processes[role] = process
        return process

    def finish(role):
        process = processes[role]
        process.wait(timeout=35)
        if node is None:
            receipts[role] = _sdk_finish(root, role, process)
        else:
            from equivalence.workspace_lock_native import finish_actor
            receipts[role] = finish_actor(root, role, case, node, runtime, process.pid, process.returncode)
        wanted = -signal.SIGKILL if role == "holder" and payload["holder"] == "kill" else 0
        if process.returncode != wanted:
            raise ValueError(f"Unexpected {role} exit {process.returncode} in {root}")

    try:
        snapshot("before")
        holder = start("holder")
        _wait_marker(root, "holder", holder, "entered")
        snapshot("holder-entered")
        if payload["holder"] == "kill":
            holder.kill()
            finish("holder")
            snapshot("holder-reaped")
        waiter = start("waiter")
        drive = payload["drive"]
        if drive in {"wait", "timeout", "at-threshold"}:
            _wait_marker(root, "waiter", waiter, "observed_twice")
            snapshot("contender-saw-holder")
            if drive == "wait":
                (root / "release").touch()
            else:
                clocks["waiter"] += 1 if drive == "at-threshold" else 10_000
                write_json(root / "clock.json", clocks)
        if drive == "timeout":
            _wait_marker(root, "waiter", waiter, "done")
            snapshot("contender-returned")
        else:
            _wait_marker(root, "waiter", waiter, "entered")
            snapshot("contender-entered")
        if payload["holder"] != "kill":
            (root / "release").touch(exist_ok=True)
            finish("holder")
            snapshot("holder-released")
        if drive != "timeout":
            (root / "finish-waiter").touch()
        finish("waiter")
        snapshot("after")
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.kill()
                process.wait()
    markers = {}
    for role in processes:
        directory = root / role
        markers[role] = {name: read_json(directory / (name + ".json"))
                         for name in ("entered", "observed_twice", "before-release", "done")
                         if (directory / (name + ".json")).is_file()}
    side = "sdk" if node is None else "native"
    return {"case": case, "side": side, "root": str(root), "finalLeases": retained_leases(root, side),
            "coordinatorPid": os.getpid(), "receipts": receipts, "markers": markers,
            "observations": observations, "caseSha256": hashlib.sha256((root / "case.json").read_bytes()).hexdigest()}
