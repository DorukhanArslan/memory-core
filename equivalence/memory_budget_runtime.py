"""Genuine SDK owners for the pending fixed memory-budget comparison."""
from __future__ import annotations

from dataclasses import asdict
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import stat
import tempfile

from equivalence.get_contract import map_get_fixture_paths
from equivalence.memory_budget_profile import validate_memory_budget_input
from memory_core.config import MemoryConfig
from memory_core.consolidation.promotion import PromotionCandidate, run_short_term_promotion
from memory_core.consolidation.store import read_recall_store, recall_store_path, write_recall_store
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.memory_budget import DEFAULT_MEMORY_FILE_MAX_CHARS, compact_memory_for_budget
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY


def _error(error):
    return {"name": type(error).__name__, "message": str(error), **vars(error)}


def _physical(root):
    result = []
    for path in sorted(root.rglob("*.sqlite")):
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            schema = [dict(row) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]
            tables = []
            for item in schema:
                if item["type"] != "table":
                    continue
                name = item["name"].replace('"', '""')
                rows = [{key: {"type": "bytes", "hex": value.hex()} if isinstance(value, bytes) else value
                         for key, value in dict(row).items()} for row in db.execute(f'SELECT * FROM "{name}"')]
                tables.append({"name": item["name"], "columns": [dict(row) for row in db.execute(f'PRAGMA table_info("{name}")')],
                    "rowCount": db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0], "rows": rows})
            result.append({"path": str(path), "schema": schema,
                "schemaCount": db.execute("SELECT COUNT(*) FROM sqlite_schema").fetchone()[0],
                "snapshotTransaction": {"mode": "deferred", "active": db.in_transaction}, "tables": tables})
            db.rollback()
    return result


def _documents(workspace, paths):
    result = []
    for relative in dict.fromkeys([*paths, "MEMORY.md", "DREAMS.md"]):
        target = workspace / relative
        content = target.read_bytes() if target.exists() else None
        result.append({"path": relative, "exists": content is not None,
            **({"bytes": content.hex(), "text": content.decode("utf-8", "replace")} if content is not None else {})})
    return result


def _tree(root):
    rows = []
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "symlink" if stat.S_ISLNK(info.st_mode) else "other"
        rows.append({"path": str(path), "kind": kind, "mode": info.st_mode, "dev": str(info.st_dev), "ino": str(info.st_ino),
            "nlink": str(info.st_nlink), "size": str(info.st_size), "mtimeNs": str(info.st_mtime_ns), "ctimeNs": str(info.st_ctime_ns),
            **({"target": str(path.readlink())} if kind == "symlink" else {})})
    return rows


def run_memory_budget(value, *, evidence_directory=None):
    validate_memory_budget_input(value)
    evidence = Path(evidence_directory) if evidence_directory is not None else Path(tempfile.mkdtemp(prefix="sdk-memory-budget-evidence-"))
    evidence.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="python-memory-budget-", dir=evidence))
    raw = {"kind": value["kind"], "input": deepcopy(value), "fixtureBase": str(root), "calls": []}
    if value["kind"] == "memory-budget":
        rows = []
        for item in value["cases"]:
            params = item["params"]
            try:
                result = compact_memory_for_budget(existing_memory=params["existingMemory"], new_section=params["newSection"],
                    budget_chars=params["budgetChars"], max_prior_entry_loss_fraction=params.get("maxPriorEntryLossFraction"),
                    identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
                raw["calls"].append({"operation": "compact_memory_for_budget", "params": params, "result": asdict(result)})
                rows.append({"id": item["id"], "result": {"compacted": result.compacted, "droppedDates": list(result.dropped_dates)}})
            except Exception as error:
                raw["calls"].append({"operation": "compact_memory_for_budget", "params": params, "error": _error(error)})
                rows.append({"id": item["id"], "error": _error(error)})
        public = {"provider": "none", "defaultMemoryFileMaxChars": DEFAULT_MEMORY_FILE_MAX_CHARS, "cases": rows}
    elif value["kind"] == "memory-budget-apply":
        workspace = root / "workspace"
        workspace.mkdir()
        for relative, text in value["files"].items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            raw["calls"].append({"operation": "write", "path": str(target), "text": text})
        seed = deepcopy(value["recall"])
        before = deepcopy(seed)
        seed_return = write_recall_store(recall_store_path(workspace), seed)
        raw["calls"].append({"operation": "write_recall_store", "path": str(recall_store_path(workspace)),
            "valueBefore": before, "valueAfter": seed, "ownReturn": seed_return})
        config = MemoryConfig(workspace, flags=FeatureFlags(vector_search=False))
        store = SQLiteMemoryStore(config, None)
        events = []
        options = value["options"]
        try:
            result = run_short_term_promotion(config=config, store=store, now_ms=value["nowMs"], timezone=options["timezone"],
                limit=options["limit"], min_score=options["minScore"], min_recall_count=options["minRecallCount"],
                min_unique_queries=options["minUniqueQueries"], memory_file_max_chars=options["memoryFileMaxChars"],
                max_prior_entry_loss_fraction=options["maxPriorEntryLossFraction"],
                candidates=[PromotionCandidate.from_json(row) for row in value["candidates"]],
                identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, state_dir=root / "state", on_event=events.append)
            raw["calls"].append({"operation": "run_short_term_promotion", "candidates": value["candidates"], "options": options,
                "nowMs": value["nowMs"], "ownReturn": asdict(result)})
            applied = {"memoryPath": str(workspace / result.target), "applied": len(result.applied_candidates),
                "appended": result.appended, "reconciledExisting": result.reconciled_existing,
                "appliedCandidates": [row.to_json() for row in result.applied_candidates],
                "rejectedCandidates": [{"candidate": row.candidate.to_json(), "reason": row.reason, "category": row.category}
                    for row in result.rejected_candidates],
                "compactedSections": len(result.compacted_dates), "compactedDates": list(result.compacted_dates)}
            public = {"provider": "none", "result": applied}
        except Exception as error:
            raw["calls"].append({"operation": "run_short_term_promotion", "candidates": value["candidates"], "options": options,
                "nowMs": value["nowMs"], "error": _error(error)})
            public = {"provider": "none", "error": _error(error)}
        public.update(documents=_documents(workspace, value["files"]), recall=read_recall_store(recall_store_path(workspace), value["nowMs"]),
            eventRecords=events)
        raw["physical"] = _physical(root)
        raw["fsTree"] = _tree(root)
        raw["files"] = [{"path": str(path), "bytes": path.read_bytes().hex()} for path in sorted(root.rglob("*")) if path.is_file()]
        raw["eventRecords"] = events
    else:
        raise ValueError("Unknown memory-budget profile")
    (evidence / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, default=str), encoding="utf-8")
    return map_get_fixture_paths(public, str(root))


if __name__ == "__main__":
    import sys

    request = json.load(sys.stdin)
    json.dump(run_memory_budget(request["input"], evidence_directory=request.get("evidenceDirectory")), sys.stdout, ensure_ascii=True)
