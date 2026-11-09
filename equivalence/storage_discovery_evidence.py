"""Bind complete discovery results to retained actual exception diagnostics."""
from __future__ import annotations

import errno
from pathlib import Path

from equivalence.get_contract import map_get_fixture_paths


def _exception_envelope(error: dict, side: str) -> dict:
    if not isinstance(error, dict) or not all(isinstance(error.get(key), str) for key in ("type", "name", "message")):
        raise ValueError("Discovery diagnostics need actual exception identities and messages")
    if side == "native":
        entries = error.get("properties")
        if not isinstance(entries, list) or any(not isinstance(item, dict) or not {
            "key", "enumerable", "configurable", "kind", "value",
        } <= set(item) or not ({"writable"} if item.get("kind") == "data" else {"get", "set"}) <= set(item)
               or item.get("kind") not in {"data", "accessor"}
               for item in entries):
            raise ValueError("Native discovery errors need all original own properties")
        properties = {item["key"]: item["value"] for item in entries}
        if len(properties) != len(entries) or not isinstance(properties.get("stack"), str):
            raise ValueError("Native discovery errors need an original stack and unique properties")
        cause = properties.get("cause")
        code, path = properties.get("code"), properties.get("path")
    else:
        properties = error.get("properties")
        if (not isinstance(properties, dict) or not isinstance(error.get("stack"), str)
                or not isinstance(error.get("args"), list) or not isinstance(error.get("module"), str)):
            raise ValueError("SDK discovery errors need full exception/OS attributes and traceback")
        cause = properties.get("cause", error.get("cause"))
        code = properties.get("code", errno.errorcode.get(properties.get("errno")))
        path = properties.get("path", properties.get("filename"))
        if error["type"] == "MemorySourceIOError":
            original = properties.get("original_exception")
            if (not isinstance(original, dict) or not isinstance(original.get("stack"), str)
                    or not {"errno", "strerror", "filename", "filename2"} <= set(original.get("properties", {}))
                    or properties.get("syscall") not in {"scandir", "lstat", "realpath"}):
                raise ValueError("The production IO bridge must preserve the complete original Python OS exception")
        if error["name"] == "MemorySourceScanError" and isinstance(cause, dict) and cause.get("type") == "MemorySourceIOError":
            if error.get("cause") != cause.get("properties", {}).get("original_exception"):
                raise ValueError("The real raised Python cause must remain bound to the public IO bridge")
    if error["name"] == "MemorySourceScanError" and not {"path", "code", "cause"} <= set(properties):
        raise ValueError("The original scan error needs its complete path, code and cause properties")
    return {"type": error["name"], "message": error["message"], "code": code, "path": path,
            "cause": _exception_envelope(cause, side) if cause is not None else None}


def validate_storage_discovery_diagnostic(record: dict, arguments: dict, result: dict, *, side: str) -> None:
    """Require complete raw results/causes; stacks and OS data remain private."""
    from equivalence.harness import _same_json

    if side not in {"native", "python"} or not isinstance(record, dict) or record.get("kind") != "storage-discovery":
        raise ValueError("A genuine discovery side and diagnostic record are required")
    base = record.get("fixtureBase")
    if (not isinstance(base, str) or not Path(base).is_absolute()
            or record.get("workspaceRoot") != str(Path(base) / "workspace") or not _same_json(record.get("input"), arguments)):
        raise ValueError("Discovery evidence must retain the owned fixture and exact input")
    snapshots = record.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != 1 + len(arguments.get("steps", [])):
        raise ValueError("Every actual discovery snapshot must be retained")
    public = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("result"), dict):
            raise ValueError("Discovery snapshots need their complete actual result")
        observed = snapshot["result"]
        if "error" in observed:
            if not _same_json(observed, {"error": _exception_envelope(snapshot.get("exception"), side)}):
                raise ValueError("The complete discovery error must match its actual exception and cause")
        elif "exception" in snapshot:
            raise ValueError("A successful discovery snapshot cannot conceal an exception")
        public.append(observed)
    if not _same_json(record.get("result"), {"snapshots": public}) or not _same_json(
        map_get_fixture_paths(record["result"], base), result,
    ):
        raise ValueError("Complete raw discovery results must match the wire after the exact owned-root codec")
