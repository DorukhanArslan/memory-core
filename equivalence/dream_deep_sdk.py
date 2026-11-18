"""Drive the public managed callback and retain its real workspace and host observations."""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import traceback

from equivalence.dream_deep import NOW, TOKEN, validate_case
from equivalence.dream_light_sdk import _owner, event_projection, snapshot_files
from equivalence.promotion_apply_runtime import _safe_path
from memory_core.config import MemoryConfig
from memory_core.consolidation import DreamingWorkspace, ManagedDreamingOptions, run_managed_dreaming_turn
from memory_core.consolidation.artifacts import read_memory_preimages
from memory_core.consolidation.dreaming_repair import repair_dreaming_recall
from memory_core.consolidation.light_phase import LightDreamingOptions
from memory_core.consolidation.managed_dreaming import _run_deep
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.policy import resolve_deep_dreaming_policy
from memory_core.consolidation.rem_phase import RemDreamingOptions
from memory_core.consolidation.store import (
    phase_signal_store_path, read_canonical_phase_signal_store, read_canonical_recall_store, recall_store_path,
)
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY


def _origin_fields(row):
    return {"entryKey": row.entry_key, "agentId": row.agent_id, "sessionId": row.session_id,
            "sessionKey": row.session_key, "originClass": row.origin_class, "observedAt": row.observed_at}


def run_sdk(case, evidence_directory):
    if evidence_directory is None:
        with TemporaryDirectory() as directory:
            return run_sdk(case, Path(directory))
    validate_case(case)
    directory = Path(evidence_directory)
    directory.mkdir(exist_ok=True, parents=True)
    root = directory / "sdk-fixture"
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=False, parents=True)
    value = case["input"]
    opts = value["options"]
    events, logs, model_calls = [], [], []
    raw = {"kind": "sdk-managed-dreaming", "input": deepcopy(value), "root": str(root),
           "owners": [_owner(fn) for fn in (run_managed_dreaming_turn, _run_deep, repair_dreaming_recall)],
           "blobs": {}, "snapshots": [], "atReturnSnapshots": [], "turnReceipts": [], "calls": [], "events": events, "logs": logs, "provider": []}
    results = []

    def snapshot():
        tree = snapshot_files(root, raw["blobs"])
        raw["snapshots"].append(tree)
        return tree

    def complete(request):
        reply = value["provider"][len(model_calls)]
        model_calls.append(deepcopy(request))
        raw["provider"].append({"request": deepcopy(request), "reply": deepcopy(reply), "returned": deepcopy(reply),
            "nowMs": now, "caller": [(f.filename, f.name) for f in traceback.extract_stack()[-8:]]})
        return deepcopy(reply)

    class Capture(logging.Handler):
        def emit(self, record):
            logs.append({"level": record.levelname.lower(), "text": record.getMessage()})

    logger = logging.Logger("deep-fixture")
    logger.addHandler(Capture())
    try:
        for name, text in value["files"].items():
            path = _safe_path(workspace, name)
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(text.encode("utf8"))
            os.utime(path, ns=(NOW * 1_000_000,) * 2)
        ledger = MemoryEntryOriginLedger(lambda agent: root / "agents" / agent / "origins.sqlite")
        if value["originSeeds"]:
            ledger.record("main", [MemoryEntryOrigin(row["entryKey"], row["agentId"], row["sessionId"], row["sessionKey"],
                    row["originClass"], row["observedAt"]) for row in value["originSeeds"]])
        config = MemoryConfig(workspace_dir=workspace, store_path=root / "index.sqlite", flags=FeatureFlags(vector_search=False))
        target = DreamingWorkspace(config, SQLiteMemoryStore(config, None), ("main",), origins=ledger)
        phase = {"enabled": opts["enabled"], **{k: opts[k] for k in ("limit", "minRecallCount", "minUniqueQueries", "minScore")}}
        options = ManagedDreamingOptions(policy=resolve_deep_dreaming_policy({"dreaming": {
            "enabled": opts["enabled"], "phases": {"deep": phase}}}),
            light=LightDreamingOptions(enabled=opts["light"]), rem=RemDreamingOptions(enabled=opts["rem"]),
            timezone=opts["timezone"], storage_mode=opts["storageMode"])
        snapshot()
        queue = {}
        for turn in value["turns"]:
            now = turn["nowMs"]
            if turn["queued"]:
                queue[("agent:main:main", "main")] = [{"contextKey": "cron:observatory", "text": TOKEN}]
            jobs = []
            out = run_managed_dreaming_turn(trigger=turn["trigger"], cleaned_body=turn["cleanedBody"],
                    workspaces=[target], options=options, agent_id=turn["agentId"], session_key=turn["sessionKey"],
                    read_pending_events=lambda key, agent: queue.get((key, agent), []),
                    complete=complete if value["provider"] is not None else None, now_ms=lambda: now,
                    submit_narrative=jobs.append, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                    state_dir=root / "state", on_event=lambda event: events.append(deepcopy(event)), logger=logger)
            raw["atReturnSnapshots"].append(snapshot_files(root, raw["blobs"]))
            diary = workspace / "DREAMS.md"
            at_return = diary.read_text() if diary.is_file() else None
            raw["calls"].append({"turn": turn, "returned": deepcopy(out), "diaryAtReturn": at_return,
                                 "queuedJobs": len(jobs)})
            for job in jobs:
                job()
            raw["turnReceipts"].append({"providerCalls": len(model_calls), "logCount": len(logs), "eventCount": len(events)})
            snapshot()
            results.append({"turn": deepcopy(turn), "returned": out, "diaryAtReturn": at_return,
                 "documents": {f.relative_to(workspace).as_posix(): f.read_bytes().decode("utf8")
                               for f in sorted(workspace.rglob("*.md")) if f.is_file()},
                 "recall": read_canonical_recall_store(recall_store_path(workspace), now),
                 "signals": read_canonical_phase_signal_store(phase_signal_store_path(workspace), now),
                 "preimages": read_memory_preimages(workspace), "origins": [_origin_fields(r) for r in ledger.list("main")],
                 "events": event_projection(events, workspace), "modelCalls": deepcopy(model_calls),
                 "summaries": [log["text"] for log in logs if log["text"].startswith("memory-core: dreaming promotion complete")]})
        raw["completed"] = True
    finally:
        raw["observations"] = results
        (directory / "python-raw.json").write_text(json.dumps([raw], separators=(",", ":")))
    return {"observations": results}
