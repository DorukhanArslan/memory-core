"""Drive the SDK's public sweep and observe the real workspace after each operation."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat

from equivalence.dream_light import NOW, validate_case
from equivalence import dream_rem
from equivalence.dream_rem_sdk import rem_options
from memory_core.consolidation.rem_phase import prepare_rem_phase
from memory_core.consolidation.dream_narrative import run_rem_narrative
from equivalence.promotion_apply_runtime import _json_value, _safe_path
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.consolidation.dreaming import DreamingIngestion, LightDreamingOptions, run_dreaming_sweep
from memory_core.consolidation.daily_ingestion import ingest_daily_memory_signals
from memory_core.consolidation.light_phase import prepare_light_phase, publish_daily_dreaming_phase_block
from memory_core.consolidation.session_ingestion import ingest_session_transcript_signals
from memory_core.consolidation.store import (
    phase_signal_store_path, read_canonical_phase_signal_store, read_canonical_recall_store, recall_store_path,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY


def event_projection(events, workspace):
    """Map only an emitted path owned by the current fixture."""
    result = deepcopy(events)
    prefix = str(workspace) + "/"
    for event in result:
        for key in ("reportPath", "inlinePath", "memoryPath"):
            path = event.get(key)
            if isinstance(path, str) and path.startswith(prefix):
                event[key] = "$WORKSPACE/" + path[len(prefix):]
    return result


def _owner(fn):
    path = Path(inspect.getsourcefile(fn)).resolve()
    return {"name": fn.__qualname__, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def snapshot_files(root: Path, blobs: dict) -> dict:
    """Read regular files once per operation and retain one copy of each distinct content."""
    tree = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4 * 1024 * 1024:
            raise ValueError("Unsafe or unexpectedly large SDK light dreaming fixture file")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest not in blobs:
            blobs[digest] = base64.b64encode(content).decode("ascii")
        tree[path.relative_to(root).as_posix()] = {
            "size": len(content), "sha256": digest, "mtimeNs": info.st_mtime_ns,
        }
    return tree


def run_sdk(case, evidence_directory):
    from tempfile import TemporaryDirectory
    if evidence_directory is None:
        with TemporaryDirectory(prefix="light-sdk-") as path:
            return run_sdk(case, Path(path))
    phase = "rem" if case.get("operation") == dream_rem.OPERATION else "light"
    (dream_rem.validate_case if phase == "rem" else validate_case)(case)
    value = case["input"]
    opts = value["options"]
    directory = Path(evidence_directory).absolute()
    if directory.resolve() != directory:
        raise ValueError("SDK dreaming evidence requires a directory without redirects")
    directory.mkdir(exist_ok=True, parents=True)
    root = directory / "sdk-fixture"
    root.mkdir()
    workspace = root / "workspace"
    workspace.mkdir()
    events = []
    observations = []
    calls, phase_results = [], []
    owners = (prepare_rem_phase, run_rem_narrative) if phase == "rem" else (prepare_light_phase,)
    raw = {"kind": f"dream-{phase}-sdk", "input": deepcopy(value), "workspace": str(workspace),
           "owners": [_owner(fn) for fn in (run_dreaming_sweep, *owners, publish_daily_dreaming_phase_block,
                                             ingest_daily_memory_signals, ingest_session_transcript_signals,
                                             read_canonical_recall_store, read_canonical_phase_signal_store)],
           "operations": [], "events": events, "snapshots": [], "blobs": {}}

    if phase == "rem":
        raw["modelCalls"] = []

    def snapshot():
        raw["snapshots"].append(snapshot_files(root, raw["blobs"]))

    now = NOW
    try:
        for name, text in value["files"].items():
            file = _safe_path(workspace, name)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(text.encode("utf8"))
            os.utime(file, ns=(NOW * 1_000_000,) * 2)
        snapshot()
        for op in value["operations"]:
            row = {"operation": deepcopy(op)}
            raw["operations"].append(row)
            if op["op"] == "remove":
                _safe_path(workspace, op["path"]).unlink()
            else:
                now = op["nowMs"]
                config = MemoryConfig(workspace_dir=workspace, store_path=root / "index.sqlite",
                                      flags=FeatureFlags(vector_search=False))
                store = SQLiteMemoryStore(config, None)
                options = rem_options(opts, workspace, now, calls, raw["modelCalls"]) if phase == "rem" else {
                    "light_options": LightDreamingOptions(enabled=opts["enabled"], dedupe_similarity=opts["dedupeSimilarity"],
                                                         storage_mode=opts["storageMode"])}
                outcome = run_dreaming_sweep(config=config, store=store, phase=phase, now_ms=now,
                    timezone=opts["timezone"], limit=opts["limit"], identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                    ingestion=DreamingIngestion(lookback_days=opts["lookbackDays"], limit=opts["limit"],
                        agent_ids=("main",), corpus_entries=lambda _agent: ()),
                    **options,
                    on_event=lambda event: events.append(deepcopy(event)))
                row["return"] = _json_value(outcome)
                if phase == "rem":
                    phase_results.append({"degradedPhases": int(outcome.narrative_status == "degraded"),
                                          "pendingNarratives": int(outcome.narrative_status == "pending")})
            readback = {"operation": deepcopy(op),
                        "documents": {f.relative_to(workspace).as_posix(): f.read_bytes().decode("utf8")
                                      for f in sorted(workspace.rglob("*.md")) if f.is_file()},
                        "recall": read_canonical_recall_store(recall_store_path(workspace), now),
                        "signals": read_canonical_phase_signal_store(phase_signal_store_path(workspace), now),
                        "events": event_projection(events, workspace)}
            if phase == "rem":
                readback.update(modelCalls=deepcopy(calls), sweepResults=deepcopy(phase_results))
            row["events"] = deepcopy(events)
            row["observation"] = deepcopy(readback)
            observations.append(readback)
            snapshot()
        raw["complete"] = True
    except Exception as exc:
        raw.update(complete=False, error=_json_value(exc))
        snapshot()
        raise
    finally:
        raw["output"] = {"observations": observations}
        (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, separators=(",", ":")))
    return raw["output"]
