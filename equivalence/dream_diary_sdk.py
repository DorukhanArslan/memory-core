"""Observe the SDK's diary publisher under real file mutations and competing writes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import time

from equivalence.dream_diary import build_cases
from equivalence.dream_light import NOW
from equivalence.dream_light_sdk import event_projection, _owner
from memory_core.bootstrap.classification import classify_workspace_memory_paths
from memory_core.consolidation._util import iso_ms, write_json_atomic
from memory_core.consolidation.artifacts import read_recent_dream_diary_entries, resolve_dreams_path, update_dreams_file
from memory_core.consolidation.dream_narrative import append_narrative_entry
from memory_core.consolidation.light_phase import publish_daily_dreaming_phase_block
from memory_core.consolidation.promotion import format_memory_dreaming_day
from memory_core.consolidation.store import (
    memory_workspace_lock, promotion_lock_path, read_canonical_recall_store, recall_store_path,
)


def capture(workspace: Path):
    files = {}
    for path in sorted(workspace.rglob("*")):
        meta = path.lstat()
        if stat.S_ISDIR(meta.st_mode):
            continue
        item = {"mode": stat.S_IMODE(meta.st_mode), "mtimeNs": meta.st_mtime_ns, "ino": meta.st_ino}
        if stat.S_ISLNK(meta.st_mode):
            item.update(kind="link", target=os.readlink(path))
        elif stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1:
            data = path.read_bytes()
            item.update(kind="file", text=data.decode(), sha256=hashlib.sha256(data).hexdigest())
        else:
            raise ValueError("Unowned SDK diary fixture")
        files[path.relative_to(workspace).as_posix()] = item
    return files


def documents(files):
    return {name: ({"link": f["target"]} if f["kind"] == "link" else {"text": f["text"]})
            for name, f in files.items() if name.endswith(".md")}


def _append(workspace, params):
    return append_narrative_entry(workspace=workspace, narrative=params["narrative"], now_ms=params["nowMs"],
                                  timezone=params["timezone"], source_entry_keys=params["keys"],
                                  recent_diary_entries=params["recent"])


def _race(workspace, op, facts):
    entered, attempted, finish = (threading.Event() for _ in range(3))
    timeout = 5

    def first():
        with memory_workspace_lock(workspace):
            path = append_narrative_entry(workspace=workspace, narrative=op["first"],
                                          now_ms=op["nowMs"], timezone="UTC")
            facts.append({"event": "first-published", "path": str(path), "thread": threading.get_native_id()})
            entered.set()
            if not finish.wait(timeout):
                raise TimeoutError("Diary fixture lost the second writer")

    def second():
        facts.append({"event": "second-attempted", "thread": threading.get_native_id()})
        attempted.set()
        return _append(workspace, op["second"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(first)
        try:
            if not entered.wait(timeout):
                holder.result(timeout=1)
                raise TimeoutError("First diary writer failed to enter")
            waiter = pool.submit(second)
            if not attempted.wait(timeout):
                raise TimeoutError("Second diary writer failed to start")
            time.sleep(0.04)
            mid = resolve_dreams_path(workspace).read_text()
            facts.append({"event": "contention", "lease": json.loads(promotion_lock_path(workspace).read_bytes()),
                          "pending": not waiter.done(), "text": mid})
        finally:
            finish.set()
        holder.result(timeout=timeout)
        result = waiter.result(timeout=timeout)
    facts.append({"event": "second-published", "path": str(result)})
    return {"status": "raced", "pending": facts[-2]["pending"], "intermediate": mid}


SDK_OWNERS = (append_narrative_entry, update_dreams_file, read_recent_dream_diary_entries,
              publish_daily_dreaming_phase_block, classify_workspace_memory_paths, memory_workspace_lock)


def run_sdk(case, directory):
    if case not in build_cases():
        raise ValueError("Unknown diary fixture")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / "sdk-diary"
    workspace.mkdir()
    value = case["input"]
    source = value["source"]
    for name, content in value["files"].items():
        file = workspace / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content.encode())
        os.utime(file, ns=(NOW * 1_000_000,) * 2)
    store = recall_store_path(workspace)
    write_json_atomic(store, {"version": 1, "updatedAt": iso_ms(NOW), "entries": {source["key"]: source}})
    stream = directory / "sdk-callbacks.jsonl"
    stream.touch(exist_ok=False)
    raw = {"case": deepcopy(case), "workspace": str(workspace), "owners": [_owner(fn) for fn in SDK_OWNERS],
           "initial": capture(workspace), "rows": [], "race": []}
    observations = []

    def event(item):
        with stream.open("a") as out:
            out.write(json.dumps(item) + "\n")

    for op in value["operations"]:
        kind = op["op"]
        row = {"operation": deepcopy(op)}
        if kind == "phase":
            with memory_workspace_lock(workspace):
                paths = publish_daily_dreaming_phase_block(
                    workspace=workspace, phase=op["phase"], day=format_memory_dreaming_day(op["nowMs"], op["timezone"]),
                    lines=op["lines"], has_content=True, now_iso=iso_ms(op["nowMs"]),
                    storage_mode=op["storageMode"], separate_reports=False, on_event=event,
                )
            outcome = {"status": "published", "paths": paths}
        elif kind == "append":
            try:
                result = _append(workspace, op)
                row["returnPath"] = None if result is None else str(result)
                outcome = {"status": "skipped"} if result is None else {"status": "published", "path": result.name}
            except OSError as exc:
                row["error"] = {"class": type(exc).__name__, "message": str(exc)}
                outcome = {"status": "failed", "message": str(exc)}
        elif kind == "race":
            outcome = _race(workspace, op, raw["race"])
        else:
            if kind == "forget-source":
                with memory_workspace_lock(workspace):
                    updated = read_canonical_recall_store(store, op["nowMs"])
                    del updated["entries"][op["key"]]
                    write_json_atomic(store, updated)
            elif kind == "change-diary":
                update_dreams_file(workspace, lambda _old, _path: (op["text"], None))
            elif kind == "make-symlink":
                file = workspace / op["path"]
                file.unlink()
                file.symlink_to(op["target"])
            elif kind == "restore-file":
                file = workspace / op["path"]
                file.unlink()
                file.write_text(op["text"])
            else:
                raise ValueError("Unknown diary operation")
            outcome = {"status": "fixture"}
        files = capture(workspace)
        docs = documents(files)
        events = [json.loads(line) for line in stream.read_text().splitlines()]
        public = {"operation": deepcopy(op), "outcome": outcome, "documents": docs,
                  "recent": read_recent_dream_diary_entries(workspace),
                  "trust": classify_workspace_memory_paths(workspace, sorted(docs)),
                  "events": event_projection(events, workspace),
                  "sourceKeys": sorted(read_canonical_recall_store(store, NOW)["entries"])}
        row.update(files=files, callbacks=events, observation=deepcopy(public))
        raw["rows"].append(row)
        observations.append(public)
    raw["complete"] = True
    (directory / "python-raw.json").write_text(json.dumps([raw], separators=(",", ":")))
    return {"observations": observations}
