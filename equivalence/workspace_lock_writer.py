"""The SDK application under contention. The normal workspace lock owns every decision."""

import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

from equivalence.workspace_lock_process import read_json, write_json
from memory_core.consolidation import store
from memory_core.consolidation._util import parse_ms
from memory_core.consolidation.file_lock import process_start_time


def run(root, role):
    drive = read_json(root / "case.json")["input"]
    directory = root / role
    space = "B" if role == "waiter" and drive["workspace"] == "other" else "A"
    workspace = root / "workspaces" / space
    target = store.promotion_lock_path(workspace)
    seen = 0

    def receipt(event, **details):
        row = {"event": event, "pid": os.getpid(), "ppid": os.getppid(), **details}
        with (directory / "receipts.jsonl").open("a", encoding="utf8") as stream:
            stream.write(json.dumps(row) + "\n")

    def lease_marker(name):
        disk = target.read_bytes()
        data = json.loads(disk)
        lease = {"owner": f"{data['pid']}:{data['ownerToken']}", "acquiredAt": parse_ms(data["createdAt"], -1)}
        if "ownerStartTime" in data:
            lease["ownerStartTime"] = data["ownerStartTime"]
        observation = {"pid": os.getpid(), "workspace": space, "lease": lease, "bytes": disk.hex()}
        receipt(name, **{k: v for k, v in observation.items() if k != "pid"})
        write_json(directory / (name + ".json"), observation)

    def observed_stale(path, now_ms):
        nonlocal seen
        before = path.read_bytes()
        result = original_stale(path, now_ms)
        if role == "waiter":
            seen += 1
            if seen <= 3 or result:
                receipt("observed", nowMs=now_ms, bytes=before.hex(), stealable=result)
            if seen == 2:
                write_json(directory / "observed_twice.json", {"pid": os.getpid(), "observations": seen})
        return result

    def wait_for(filename):
        until = time.monotonic() + 45
        while not (root / filename).exists():
            if time.monotonic() > until:
                raise TimeoutError(filename)
            time.sleep(0.02)

    def append_line():
        line = drive["lines"][0 if role == "holder" else 1]
        with (workspace / "journal.txt").open("ab") as journal:
            journal.write(line.encode())
            journal.flush()
            os.fsync(journal.fileno())

    original_stale = store._lock_is_stale
    supplied_clock = SimpleNamespace(monotonic=time.monotonic, sleep=time.sleep,
                                    time=lambda: read_json(root / "clock.json")[role] / 1000)
    receipt("start", processStartTime=process_start_time(os.getpid()), clock=read_json(root / "clock.json"))
    with patch.object(store, "time", supplied_clock), patch.object(store, "_lock_is_stale", observed_stale):
        try:
            with store.memory_workspace_lock(workspace):
                with store.memory_workspace_lock(workspace):
                    append_line()
                lease_marker("original-lease")
                if role == "holder" and drive["holder"] == "replace-start-time":
                    before = json.loads(target.read_bytes())
                    earlier = process_start_time(os.getppid())
                    if earlier is None or earlier >= before["ownerStartTime"]:
                        raise RuntimeError("The prior process must have a distinct start identity")
                    after = {**before, "ownerStartTime": earlier}
                    store.write_json_atomic(target, after)
                    receipt("replace-start-time", priorPid=os.getppid(), before=before, after=after)
                lease_marker("entered")
                wait_for("release" if role == "holder" else "finish-waiter")
                if role == "waiter":
                    lease_marker("before-release")
        except store.MemoryWorkspaceLockHeldError as error:
            result = {"status": "held", "error": {"code": error.code, "outcome": error.outcome,
                                                 "message": str(error)}}
        else:
            result = {"status": "acquired", "error": None}
    receipt("done", **result, finalLease=target.read_bytes().hex() if target.exists() else None)
    write_json(directory / "done.json", result)


if __name__ == "__main__":
    run(Path(sys.argv[1]), sys.argv[2])
