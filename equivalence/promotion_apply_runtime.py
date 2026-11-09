"""Whole SDK promotion observations; no promotion decision is supplied here.

The actual owner gets the literal candidates/options, canonical recall store,
OpenClaw marker identity and real vectorless SQLite store. Observation failures
remain separate from its result/error. Filesystem/SQL snapshots are sequential
observations, not a claim of one atomic snapshot across those surfaces.
"""
from __future__ import annotations

from contextlib import ExitStack, closing
from copy import deepcopy
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import traceback
from typing import Any

_OWNER = Path(__file__).resolve().parents[1]
_OPTIONS = {
    "timezone": "timezone", "limit": "limit", "minScore": "min_score",
    "minRecallCount": "min_recall_count", "minUniqueQueries": "min_unique_queries",
    "maxAgeDays": "max_age_days", "recencyHalfLifeDays": "recency_half_life_days",
    "memoryFileMaxChars": "memory_file_max_chars",
    "maxPromotedSnippetTokens": "max_promoted_snippet_tokens",
    "maxPriorEntryLossFraction": "max_prior_entry_loss_fraction",
}


def _json_value(value: Any, seen: frozenset[int] = frozenset()) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"$type": "float", "value": repr(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "hex": bytes(value).hex()}
    if isinstance(value, BaseException):
        return _error_record(value, seen)
    if isinstance(value, Enum):
        return {"$type": f"{type(value).__module__}.{type(value).__qualname__}",
                "name": value.name, "value": _json_value(value.value, seen)}
    if id(value) in seen:
        return {"$type": "recursive-reference", "class": type(value).__qualname__}
    seen = seen | {id(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return {"$type": f"{type(value).__module__}.{type(value).__qualname__}",
                "fields": {field.name: _json_value(getattr(value, field.name), seen) for field in fields(value)}}
    if isinstance(value, dict):
        return {key: _json_value(item, seen) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item, seen) for item in value]
    return {"$type": f"{type(value).__module__}.{type(value).__qualname__}", "repr": repr(value)}


def _error_record(error: BaseException, seen: frozenset[int] = frozenset()) -> dict:
    if id(error) in seen:
        return {"$type": "exception-reference", "name": type(error).__name__}
    seen = seen | {id(error)}
    attributes = {}
    for name in sorted(set(vars(error)) | {name for name in dir(error) if not name.startswith("_")}):
        try:
            value = getattr(error, name)
        except BaseException as attribute_error:
            attributes[name] = {"attributeReadError": _error_record(attribute_error, seen)}
            continue
        if not callable(value):
            attributes[name] = _json_value(value, seen)
    result = {"name": type(error).__name__, "module": type(error).__module__, "message": str(error),
              "repr": repr(error), "args": _json_value(error.args, seen), "attributes": attributes,
              "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
              "suppressContext": error.__suppress_context__}
    if hasattr(error, "__notes__"):
        result["notes"] = _json_value(error.__notes__, seen)
    if error.__cause__ is not None:
        result["cause"] = _error_record(error.__cause__, seen)
    if error.__context__ is not None:
        result["context"] = _error_record(error.__context__, seen)
    return result


def _full_stat(value: os.stat_result) -> dict:
    return {name: str(getattr(value, name)) for name in dir(value) if name.startswith("st_")}


def _observe_path(path: Path) -> dict:
    """lstat determines kind before any file read; directories are never read."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"path": str(path), "kind": "missing"}
    except OSError as error:
        return {"path": str(path), "kind": "unobserved", "observationError": _error_record(error)}
    kind = ("file" if stat.S_ISREG(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode)
            else "symlink" if stat.S_ISLNK(info.st_mode) else "other")
    observed = {"path": str(path), "kind": kind, "stat": _full_stat(info)}
    if kind == "symlink":
        try:
            observed["link"] = os.readlink(path)
        except OSError as error:
            observed["observationError"] = _error_record(error)
    elif kind == "file":
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                observed["openedStat"] = _full_stat(opened)
                if not stat.S_ISREG(opened.st_mode):
                    observed["observationError"] = {"kind": "path-kind-changed-before-file-read"}
                    return observed
                content = stream.read()
            observed["hex"] = content.hex()
            try:
                observed["text"] = content.decode("utf-8")
            except UnicodeDecodeError as error:
                observed["textError"] = _error_record(error)
                observed["textUtf8SurrogateEscape"] = content.decode("utf-8", errors="surrogateescape")
        except OSError as error:
            observed["observationError"] = _error_record(error)
    return observed


def _filesystem_snapshot(root: Path) -> list[dict]:
    entries = []

    def visit(path: Path) -> None:
        observed = _observe_path(path)
        entries.append(observed)
        if observed["kind"] == "directory":
            try:
                children = sorted(path.iterdir())
            except OSError as error:
                observed["listingError"] = _error_record(error)
            else:
                for child in children:
                    visit(child)

    visit(root)
    return entries


def _sqlite_snapshot(path: Path) -> dict:
    result = {"databasePath": str(path)}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN DEFERRED")
            try:
                schema = [dict(row) for row in db.execute(
                    "SELECT type,name,tbl_name,rootpage,sql FROM sqlite_master ORDER BY type,name")]
                result["schemaCount"] = db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
                result["snapshotTransaction"] = {"mode": "deferred", "active": db.in_transaction,
                                                 "queryOnly": db.execute("PRAGMA query_only").fetchone()[0]}
                tables = []
                listing = list(db.execute("PRAGMA table_list"))
                for entry in schema:
                    if entry["type"] != "table":
                        continue
                    identifier = '"' + entry["name"].replace('"', '""') + '"'
                    metadata = next(row for row in listing if row["schema"] == "main" and row["name"] == entry["name"])
                    prefix = "" if metadata["wr"] else "rowid AS __rowid__,"
                    tables.append({"name": entry["name"],
                                   "columns": [dict(row) for row in db.execute(f"PRAGMA table_xinfo({identifier})")],
                                   "rowCount": db.execute(f"SELECT COUNT(*) FROM {identifier}").fetchone()[0],
                                   "rows": [dict(row) for row in db.execute(f"SELECT {prefix}* FROM {identifier}")]})
                result.update(schema=schema, tables=tables)
            finally:
                db.rollback()
    except Exception as error:
        result["observationError"] = _error_record(error)
    return _json_value(result)


def _safe_path(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise ValueError("An owned relative fixture path is required")
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("The fixture path escapes its owned root")
    return target


def _documents(workspace: Path, names: list[str]) -> tuple[list[dict], list[dict]]:
    public, rich = [], []
    for relative in dict.fromkeys(names):
        observed = _observe_path(_safe_path(workspace, relative))
        rich.append(deepcopy(observed))
        document = {"path": relative, "exists": (None if observed["kind"] == "unobserved"
                                                  else observed["kind"] != "missing"),
                    "kind": observed["kind"]}
        if observed["kind"] == "file" and "hex" in observed:
            document.update(bytes=observed["hex"], text=bytes.fromhex(observed["hex"]).decode("utf-8", errors="replace"))
        if observed["kind"] == "symlink" and "link" in observed:
            document["target"] = observed["link"]
        if "observationError" in observed:
            document["observationError"] = observed["observationError"]
        public.append(document)
    return public, rich


def _validate_input(arguments: dict) -> dict:
    if not isinstance(arguments, dict) or arguments.get("kind") != "promotion-apply-reconcile":
        raise ValueError("An explicit promotion apply/reconcile input is required")
    value = deepcopy(arguments)
    if set(value) != {"kind", "nowMs", "directories", "files", "recall", "candidates", "options"}:
        raise ValueError("Promotion input fields must be explicit literal host operations")
    if isinstance(value["nowMs"], bool) or not isinstance(value["nowMs"], int):
        raise ValueError("An explicit integer promotion timestamp is required")
    if not isinstance(value["directories"], list) or not isinstance(value["files"], dict):
        raise ValueError("Literal fixture directories and files are required")
    if not isinstance(value["candidates"], list) or not all(isinstance(item, dict) for item in value["candidates"]):
        raise ValueError("Literal candidate objects are required")
    if not isinstance(value["recall"], dict) or not isinstance(value["options"], dict):
        raise ValueError("Literal canonical recall and options are required")
    if set(value["options"]) - _OPTIONS.keys() or "timezone" not in value["options"]:
        raise ValueError("A promotion option is outside the declared public caller interface")
    for relative in [*value["directories"], *value["files"], *(item["path"] for item in value["candidates"])]:
        _safe_path(Path("/owned-promotion-fixture"), relative)
    if not all(isinstance(content, str) for content in value["files"].values()):
        raise ValueError("Literal UTF-8 source text is required")
    return value


def _public_result(run: Any, workspace: Path) -> dict:
    return {"memoryPath": str(workspace / run.target), "applied": len(run.applied_candidates), "appended": run.appended,
            "reconciledExisting": run.reconciled_existing,
            "appliedCandidates": [candidate.to_json() for candidate in run.applied_candidates],
            "rejectedCandidates": [{"candidate": item.candidate.to_json(), "reason": item.reason,
                                    "category": item.category} for item in run.rejected_candidates],
            "compactedSections": len(run.compacted_dates), "compactedDates": list(run.compacted_dates)}


def _source_owners() -> list[dict]:
    paths = {Path(__file__).resolve()}
    for name, module in list(sys.modules.items()):
        if (name == "memory_core" or name.startswith("memory_core.")
                or name in {"equivalence.promotion_apply_profile", "equivalence.get_contract"}):
            filename = getattr(module, "__file__", None)
            if filename:
                path = Path(filename).resolve()
                allowed = _OWNER / ("memory_core" if name == "memory_core" or name.startswith("memory_core.") else "equivalence")
                if not path.is_relative_to(allowed):
                    raise RuntimeError("Promotion imported an SDK outside its owning worktree")
                paths.add(path)
    return [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "sourceBytes": path.read_bytes().decode("utf-8")} for path in sorted(paths)]


def run_promotion_apply_reconcile(arguments: dict, *, evidence_directory: Path | None = None) -> dict:
    from equivalence.promotion_apply_profile import validate_promotion_apply_input

    value = _validate_input(validate_promotion_apply_input(arguments))
    from equivalence.get_contract import map_get_fixture_paths
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.consolidation.promotion import PromotionCandidate, run_short_term_promotion
    from memory_core.consolidation.store import read_canonical_recall_store, recall_store_path, write_recall_store
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    if not Path(memory_core.__file__).resolve().is_relative_to(_OWNER / "memory_core"):
        raise RuntimeError("Promotion imported an SDK outside its owning worktree")
    raw = {"kind": "sdk-promotion-apply-reconcile", "input": deepcopy(value), "pid": os.getpid(),
           "implementationRoot": str(_OWNER), "receipts": [], "snapshots": [],
           "eventSource": "Actual SDK on_event callbacks; no persistent Native event-record reader",
           "snapshotScope": "Sequential own-filesystem and independent readonly SQL observations; no cross-surface atomicity claim"}
    events = []
    receipt_lock = threading.RLock()

    def receipt(kind: str, **facts) -> dict:
        with receipt_lock:
            entry = {"sequence": len(raw["receipts"]) + 1, "kind": kind,
                     "timeNs": time.time_ns(), "monotonicNs": time.monotonic_ns(), **_json_value(facts)}
            raw["receipts"].append(entry)
            return entry

    def call(operation, arguments, invoke):
        receipt("call", operation=operation, when="before", arguments=arguments)
        try:
            actual = invoke()
        except BaseException as error:
            receipt("call", operation=operation, when="after", error=_error_record(error))
            raise
        receipt("call", operation=operation, when="after", result=actual)
        return actual

    with ExitStack() as cleanup:
        if evidence_directory is None:
            root = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix="sdk-promotion-apply-")))
        else:
            evidence_directory = Path(evidence_directory).resolve()
            evidence_directory.mkdir(parents=True, exist_ok=True)
            root = evidence_directory / "sdk-promotion-apply-fixture"
            root.mkdir(mode=0o700)
        raw["fixtureBase"] = str(root)
        workspace, state = root / "workspace", root / "state"
        documents = list(dict.fromkeys([*(item["path"] for item in value["candidates"]), *value["files"],
                                       *value["directories"], "MEMORY.md", "DREAMS.md"]))
        database = root / "index.sqlite"

        def snapshot(phase):
            tree = _filesystem_snapshot(root)
            databases = {str(database)} if database.exists() else set()
            databases.update(item["path"] for item in tree if item.get("hex", "").startswith(b"SQLite format 3\x00".hex()))
            raw["snapshots"].append({"phase": phase, "filesystem": tree,
                                     "sqlite": [_sqlite_snapshot(Path(path)) for path in sorted(databases)],
                                     "eventRecords": deepcopy(events)})

        def observe(phase):
            actual_documents, rich_documents = _documents(workspace, documents)
            raw.setdefault("documentObservations", []).append({"phase": phase, "observations": rich_documents})
            try:
                recall = call("read_canonical_recall_store", {"path": recall_store_path(workspace), "now_ms": value["nowMs"]},
                              lambda: read_canonical_recall_store(recall_store_path(workspace), value["nowMs"]))
            except Exception as error:
                recall = {"observationError": _error_record(error)}
            return {"documents": actual_documents, "recall": recall, "eventRecords": deepcopy(events)}

        try:
            call("Path.mkdir", {"path": workspace}, workspace.mkdir)
            for relative in value["directories"]:
                path = _safe_path(workspace, relative)
                call("Path.mkdir", {"path": path, "parents": True, "exist_ok": True},
                     lambda path=path: path.mkdir(parents=True, exist_ok=True))
            for relative, text in value["files"].items():
                path = _safe_path(workspace, relative)
                call("Path.mkdir", {"path": path.parent, "parents": True, "exist_ok": True},
                     lambda path=path: path.parent.mkdir(parents=True, exist_ok=True))
                call("Path.write_text", {"path": path, "data": text, "encoding": "utf-8", "newline": ""},
                     lambda path=path, text=text: path.write_text(text, encoding="utf-8", newline=""))
            payload = deepcopy(value["recall"])
            call("write_recall_store", {"path": recall_store_path(workspace), "store": deepcopy(payload)},
                 lambda: write_recall_store(recall_store_path(workspace), payload))
            receipt("post-call-arguments", operation="write_recall_store", store=payload)
            flags = call("FeatureFlags", {"vector_search": False}, lambda: FeatureFlags(vector_search=False))
            config = call("MemoryConfig", {"workspace_dir": workspace, "store_path": database, "flags": flags},
                          lambda: MemoryConfig(workspace_dir=workspace, store_path=database, flags=flags))
            store = call("SQLiteMemoryStore", {"config": config, "embeddings": None}, lambda: SQLiteMemoryStore(config, None))
            candidates = [call("PromotionCandidate.from_json", {"candidate": item},
                               lambda item=item: PromotionCandidate.from_json(item)) for item in value["candidates"]]
            options = {_OPTIONS[name]: item for name, item in value["options"].items()}
            raw["effectiveConfig"] = _json_value(config)
            raw["runtimeIdentity"] = _json_value(OPENCLAW_COMPAT_RUNTIME_IDENTITY)
            raw["storeDescriptor"] = {"class": f"{type(store).__module__}.{type(store).__qualname__}",
                                      "path": str(store.path)}

            def on_event(event):
                events.append(deepcopy(event))
                receipt("on_event", event=event)

            def lock_observer(phase, path):
                receipt("lock_observer", phase=phase, path=path, observedPath=_observe_path(path))

            snapshot("before-readback")
            output = {"provider": "none", "before": observe("before"), "outcome": {}}
            snapshot("before-invocation")
            receipt("call", operation="run_short_term_promotion", when="before", arguments={
                "config": config, "store": store, "now_ms": value["nowMs"], "candidates": candidates, **options,
                "identity": OPENCLAW_COMPAT_RUNTIME_IDENTITY, "state_dir": state,
                "on_event": on_event, "lock_observer": lock_observer,
            })
            try:
                run = run_short_term_promotion(config=config, store=store, now_ms=value["nowMs"],
                    candidates=candidates, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, state_dir=state,
                    on_event=on_event, lock_observer=lock_observer, **options)
            except BaseException as error:
                actual_error = _error_record(error)
                output["outcome"]["error"] = actual_error
                receipt("call", operation="run_short_term_promotion", when="after", error=actual_error)
            else:
                raw["richSdkResult"] = _json_value(run)
                receipt("call", operation="run_short_term_promotion", when="after", result=run)
            snapshot("actual-settlement-before-extra-readback")
            if "error" not in output["outcome"]:
                output["outcome"]["result"] = _public_result(run, workspace)
            output["after"] = observe("after")
            raw["indexReadbacks"] = {}
            for method in ("read_published_index", "count_chunks"):
                try:
                    raw["indexReadbacks"][method] = call("SQLiteMemoryStore." + method, {}, getattr(store, method))
                except Exception as error:
                    raw["indexReadbacks"][method] = {"observationError": _error_record(error)}
            snapshot("after-readback")
            raw["unmappedOutput"] = deepcopy(output)
            public = map_get_fixture_paths(output, str(root))
            raw["output"] = deepcopy(public)
            return public
        except BaseException as error:
            raw["driverFailure"] = _error_record(error)
            raise
        finally:
            try:
                raw["sourceOwners"] = _source_owners()
            except Exception as error:
                raw["sourceObservationError"] = _error_record(error)
            if evidence_directory is not None:
                (evidence_directory / "python-raw.json").write_text(
                    json.dumps([raw], ensure_ascii=True, allow_nan=False, indent=2) + "\n", encoding="utf-8")
