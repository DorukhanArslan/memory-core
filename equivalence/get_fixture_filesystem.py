"""Owned get-fixture observations, separate from the production read result.

All OS stat properties and complete regular-file bytes remain in raw evidence.
The comparison uses content, portable POSIX metadata, actual hardlink relations,
and exact within-run stability of write-related stat facts. Access times remain
raw because reading a file can update them.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import os
from pathlib import Path
import stat
from typing import Any


_POSIX = ("mode", "uid", "gid", "nlink", "rdev")
_WRITE_STAT = ("dev", "ino", "mode", "nlink", "uid", "gid", "rdev", "size",
               "blksize", "blocks", "mtimeNs", "ctimeNs")


def _kind(mode: int) -> str:
    for predicate, name in ((stat.S_ISREG, "file"), (stat.S_ISDIR, "directory"),
                            (stat.S_ISLNK, "symlink"), (stat.S_ISFIFO, "fifo"),
                            (stat.S_ISSOCK, "socket"), (stat.S_ISCHR, "character-device"),
                            (stat.S_ISBLK, "block-device")):
        if predicate(mode):
            return name
    return "unknown"


def _raw_stat(info: os.stat_result) -> dict[str, Any]:
    return {key: (str(value) if isinstance(value, int) else value)
            for key in dir(info) if key.startswith("st_")
            and isinstance(value := getattr(info, key), int | float)}


def snapshot_get_fixture(base: Path) -> dict[str, Any]:
    """Inspect only the two owned roots; never follow directory/file symlinks."""
    entries: list[dict[str, Any]] = []

    def visit(filename: Path, *, root: bool = False) -> None:
        relative = filename.relative_to(base).as_posix()
        try:
            info = filename.lstat()
        except (FileNotFoundError, NotADirectoryError):
            if not root:
                raise
            entries.append({"path": relative, "kind": "missing"})
            return
        entry: dict[str, Any] = {"path": relative, "kind": _kind(info.st_mode),
                                 "rawStat": _raw_stat(info)}
        if stat.S_ISLNK(info.st_mode):
            entry["target"] = os.readlink(filename)
        elif stat.S_ISREG(info.st_mode):
            descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(descriptor)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError("Owned fixture changed during its nofollow snapshot")
                entry["openedStat"] = _raw_stat(opened)
                blocks = []
                while data := os.read(descriptor, 64 * 1024):
                    blocks.append(data)
                entry["bytesBase64"] = base64.b64encode(b"".join(blocks)).decode("ascii")
            finally:
                os.close(descriptor)
        entries.append(entry)
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(filename.iterdir(), key=lambda path: os.fsencode(path.name)):
                visit(child)

    for name in ("workspace", "outside"):
        visit(base / name, root=True)
    return {"statFormat": "python-os-stat", "entries": entries}


def _facts(entry: dict[str, Any], format: str, *, opened: bool = False) -> dict[str, str]:
    raw = entry["openedStat" if opened else "rawStat"]
    if format == "python-os-stat":
        return {key: str(raw["st_" + ({"mtimeNs": "mtime_ns", "ctimeNs": "ctime_ns"}.get(key, key))])
                for key in _WRITE_STAT}
    if format == "node-bigint-stats":
        return {key: str(raw[key]) for key in _WRITE_STAT}
    raise ValueError("Unknown actual fixture stat format")


def _manifest(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[list[str]]]:
    format, entries = snapshot["statFormat"], snapshot["entries"]
    manifest: dict[str, Any] = {}
    identities: dict[tuple[str, str], list[str]] = {}
    for entry in entries:
        relative = entry["path"]
        if (not isinstance(relative, str) or relative in manifest or relative.startswith("/")
                or ".." in relative.split("/") or relative.split("/")[0] not in {"workspace", "outside"}):
            raise ValueError("Snapshot entries must remain unique within the two owned roots")
        kind = entry["kind"]
        if kind == "missing":
            if relative not in {"workspace", "outside"} or set(entry) != {"path", "kind"}:
                raise ValueError("Only an owned root can be absent from a snapshot")
            manifest[relative] = {"kind": kind}
            continue
        facts = _facts(entry, format)
        if _kind(int(facts["mode"])) != kind:
            raise ValueError("Snapshot type differs from its actual lstat mode")
        value = {"kind": kind, **{key: int(facts[key]) for key in _POSIX}}
        if kind == "file":
            octets = base64.b64decode(entry["bytesBase64"], validate=True)
            opened = _facts(entry, format, opened=True)
            if facts != opened:
                raise ValueError("Snapshot bytes lack their actual matching opened file identity")
            if len(octets) != int(facts["size"]) or base64.b64encode(octets).decode() != entry["bytesBase64"]:
                raise ValueError("Snapshot must retain complete canonical file bytes")
            value.update({"size": len(octets), "bytesBase64": entry["bytesBase64"]})
            identities.setdefault((facts["dev"], facts["ino"]), []).append(relative)
        elif kind == "symlink":
            if not isinstance(entry.get("target"), str):
                raise ValueError("Snapshot must retain the actual symlink target")
            value["target"] = entry["target"]
        manifest[relative] = value
    if not {"workspace", "outside"} <= manifest.keys():
        raise ValueError("Every snapshot must observe both owned roots")
    hardlinks = sorted(sorted(paths) for paths in identities.values() if len(paths) > 1)
    return manifest, hardlinks


def derive_get_filesystem_observation(raw: dict[str, Any]) -> dict[str, Any]:
    """Recompute the declared comparison facts from complete retained OS data."""
    if set(raw) != {"before", "after"}:
        raise ValueError("Owned filesystem evidence requires pre- and post-API observations")
    before, links_before = _manifest(raw["before"])
    after, links_after = _manifest(raw["after"])
    first = {entry["path"]: entry for entry in raw["before"]["entries"]}
    last = {entry["path"]: entry for entry in raw["after"]["entries"]}
    stable = first.keys() == last.keys()
    for relative in first.keys() & last.keys():
        left, right = first[relative], last[relative]
        stable = stable and left["kind"] == right["kind"]
        if left["kind"] != "missing" and right["kind"] != "missing":
            stable = stable and _facts(left, raw["before"]["statFormat"]) == _facts(right, raw["after"]["statFormat"])
    return {"before": before, "after": after,
            "hardlinksBefore": links_before, "hardlinksAfter": links_after,
            "contentUnchanged": before == after and links_before == links_after,
            "writeStatsUnchanged": stable}


def validate_get_filesystem_observation(raw: Any, public: Any, fixture_base: str) -> None:
    from equivalence.get_contract import map_get_fixture_paths
    from equivalence.search_contract import _same_json

    if not isinstance(raw, dict) or not _same_json(
        map_get_fixture_paths(derive_get_filesystem_observation(raw), fixture_base), public,
    ):
        raise ValueError("Public filesystem observations differ from complete actual raw snapshots")


def validate_python_get_filesystem_evidence(snapshots: list[Any], arguments: dict[str, Any],
                                           public: dict[str, Any]) -> None:
    """Bind SDK comparison facts and arguments to their original evidence rows."""
    from equivalence.get_contract import map_get_fixture_paths
    from equivalence.search_contract import _same_json, decode_search_tool_envelope

    if len(snapshots) != len(arguments["steps"]) + 1:
        raise ValueError("Every SDK operation and the complete filesystem observation are required")
    record = snapshots[-1]
    if not isinstance(record, dict) or set(record) != {"kind", "fixtureBase", "filesystem"} or record["kind"] != "filesystem":
        raise ValueError("SDK snapshot evidence requires its complete owned record")
    base = record["fixtureBase"]
    if not isinstance(base, str) or not Path(base).is_absolute():
        raise ValueError("SDK fixture observations require their actual absolute owned root")
    validate_get_filesystem_observation(record["filesystem"], public.get("filesystem"), base)
    for index, (original, requested, observed) in enumerate(zip(
        snapshots[:-1], arguments["steps"], public["steps"], strict=True,
    )):
        expected = deepcopy(requested.get("params"))
        if isinstance(expected, dict) and isinstance(expected.get("path"), str):
            expected["path"] = owned_get_input_path(expected["path"], Path(base), require_owned=True)
        if (not isinstance(original, dict) or original.get("index") != index
                or original.get("fixtureBase") != base or not _same_json(original.get("params"), expected)):
            raise ValueError("Actual SDK arguments differ from suffix-preserving owned-token expansion")
        actual = ({"result": decode_search_tool_envelope(original["result"])}
                  if "result" in original else {"error": original["error"]})
        if not _same_json(map_get_fixture_paths(actual, base), observed):
            raise ValueError("SDK public results differ from their complete original tool envelopes")


def owned_get_input_path(value: str, base: Path, *, configuration: bool = False,
                         require_owned: bool = False) -> str:
    """Expand only owned root tokens; preserve hostile argument suffixes verbatim."""
    original = value
    for token, root in (("$WORKSPACE", base / "workspace"), ("$OUTSIDE", base / "outside")):
        if value == token or value.startswith(token + "/"):
            value = str(root) + value[len(token):]
            break
    if configuration or require_owned or value != original:
        from memory_core.bootstrap._js import js_trim

        checked = js_trim(value)
        candidate = os.path.abspath(os.path.join(base / "workspace", os.path.expanduser(checked) if configuration else checked))
        if not Path(candidate).is_relative_to(base):
            raise ValueError("Expanded get inputs must remain within their complete owned fixture")
    return value


def owned_get_extra_paths(values: list[Any], base: Path) -> list[Any]:
    result = []
    for value in values:
        if isinstance(value, str):
            result.append(owned_get_input_path(value, base, configuration=True))
        elif isinstance(value, dict) and isinstance(value.get("path"), str):
            result.append({**deepcopy(value), "path": owned_get_input_path(value["path"], base, configuration=True)})
        else:
            raise ValueError("Owned extra roots require a string path or path/pattern record")
    return result
