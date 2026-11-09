"""Owned get-fixture observations, separate from the production read result.

All OS stat properties and complete regular-file bytes remain in raw evidence.
The comparison uses content, portable POSIX metadata, actual hardlink relations,
and exact within-run stability of write-related stat facts. Access times remain
raw because reading a file can update them.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
import io
import os
from pathlib import Path
import stat
from typing import Any


_POSIX = ("mode", "uid", "gid", "nlink", "rdev")
_WRITE_STAT = ("dev", "ino", "mode", "nlink", "uid", "gid", "rdev", "size",
               "blksize", "blocks", "mtimeNs", "ctimeNs")
_RACE_ENV = ("NODE_ENV", "VITEST", "FS_SAFE_NATIVE_MODE", "OPENCLAW_FS_SAFE_NATIVE_MODE",
             "FS_SAFE_PYTHON_MODE", "OPENCLAW_FS_SAFE_PYTHON_MODE")


@contextmanager
def get_fixture_read_race(input: Any, base: Path):
    """Perform one fixed owned OS mutation immediately before the real SDK open.

    Both baseline pathlib and the checked descriptor owner still call their real
    IO operation. Neither bytes nor errors are supplied by this fixture seam.
    """
    if input is None:
        yield None
        return
    from equivalence.get_read_race_profile import GET_READ_RACE_INPUT

    if input != GET_READ_RACE_INPUT:
        raise ValueError("Only the fixed owned pre-open mutation is approved")
    filename, backup, target = (base / "workspace/memory/race.md",
                                base / "workspace/memory/race.before.md", base / "outside/secret.md")
    def environment():
        return {key: os.environ.get(key) for key in _RACE_ENV}
    observed: dict[str, Any] = {**deepcopy(input), "events": ["arm"],
                               "environment": {"before": environment(), "dispatch": None},
                               "mutation": None, "actualOpen": None}
    prior_io_open, prior_os_open = io.open, os.open
    dispatched = False

    def mutate(path):
        nonlocal dispatched
        if not isinstance(path, str | bytes | os.PathLike) or os.fsdecode(path) != str(filename):
            return False
        if dispatched:
            raise ValueError("The fixed read-race mutation must dispatch exactly once")
        dispatched = True
        observed["events"].append("dispatch")
        observed["environment"]["dispatch"] = environment()
        before = filename.lstat()
        filename.rename(backup)
        filename.symlink_to(target)
        observed["mutation"] = {
            "path": str(filename), "backup": str(backup), "target": str(target),
            "beforeStat": _raw_stat(before), "backupStat": _raw_stat(backup.lstat()),
            "afterStat": _raw_stat(filename.lstat()), "targetStat": _raw_stat(target.lstat()),
            "linkTarget": os.readlink(filename),
        }
        return True

    def opened(call, path, *args, **kwargs):
        changed = mutate(path)
        try:
            result = call(path, *args, **kwargs)
        except BaseException as error:
            if changed:
                observed["actualOpen"] = {"ok": False, "type": type(error).__name__,
                                          "message": str(error), "errno": getattr(error, "errno", None)}
            raise
        if changed:
            descriptor = result if isinstance(result, int) else result.fileno()
            observed["actualOpen"] = {"ok": True, "rawStat": _raw_stat(os.fstat(descriptor))}
        return result

    io.open = lambda path, *args, **kwargs: opened(prior_io_open, path, *args, **kwargs)
    os.open = lambda path, *args, **kwargs: opened(prior_os_open, path, *args, **kwargs)
    try:
        yield observed
    finally:
        io.open, os.open = prior_io_open, prior_os_open
        observed["events"].append("disarm")
        observed["environment"]["afterDisarm"] = environment()


def derive_get_read_race_observation(raw: Any, base: str, *, native: bool) -> dict[str, Any]:
    """Validate the one real mutation; all detailed OS/environment data stay raw."""
    from equivalence.get_read_race_profile import GET_READ_RACE_INPUT

    if not isinstance(raw, dict) or any(raw.get(key) != value for key, value in GET_READ_RACE_INPUT.items()):
        raise ValueError("The actual read race must retain its exact original hook and mutation kind")
    if raw.get("events") != ["arm", "dispatch", "disarm"]:
        raise ValueError("The fixed read race must arm, dispatch once and disarm")
    mutation, environment = raw.get("mutation"), raw.get("environment")
    expected = {"path": base + "/workspace/memory/race.md", "backup": base + "/workspace/memory/race.before.md",
                "target": base + "/outside/secret.md"}
    if (not isinstance(mutation, dict) or any(mutation.get(key) != value for key, value in expected.items())
            or mutation.get("linkTarget") != expected["target"]):
        raise ValueError("The race mutation must remain exactly within its two owned roots")
    format = "node-bigint-stats" if native else "python-os-stat"
    facts = {key: _facts({"rawStat": mutation[key]}, format)
             for key in ("beforeStat", "backupStat", "afterStat", "targetStat")}
    if (_kind(int(facts["beforeStat"]["mode"])) != "file"
            or _kind(int(facts["afterStat"]["mode"])) != "symlink"
            or _kind(int(facts["targetStat"]["mode"])) != "file"
            or any(facts["beforeStat"][key] != facts["backupStat"][key] for key in ("dev", "ino"))):
        raise ValueError("Race identity evidence must show the actual original inode and replacement symlink")
    before = environment.get("before") if isinstance(environment, dict) else None
    if (not isinstance(before, dict) or set(before) != set(_RACE_ENV)
            or environment.get("dispatch") != before or environment.get("afterDisarm") != before):
        raise ValueError("Actual reads and disarm must retain the original runtime/backend environment")
    if native:
        if (set(environment) != {"before", "duringSetter", "afterSetter", "dispatch", "afterDisarm"}
                or environment["duringSetter"] != {**before, "NODE_ENV": "test"}
                or environment["afterSetter"] != before or raw.get("installedHookKeys") != ["afterPreOpenLstat"]
                or raw.get("hookCleared") is not True
                or not isinstance(raw.get("callerStack"), str)
                or "/@openclaw/fs-safe/dist/local-file-descriptor.js:41:" not in raw["callerStack"]):
            raise ValueError("The original native pre-open owner and narrow setter-only environment must be attested")
    return {**GET_READ_RACE_INPUT, "dispatches": 1, "disarmed": True}


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
    if (not isinstance(record, dict) or set(record) != {"kind", "fixtureBase", "filesystem", *(
        ["readRace"] if arguments.get("readRace") is not None else []
    )} or record["kind"] != "filesystem"):
        raise ValueError("SDK snapshot evidence requires its complete owned record")
    base = record["fixtureBase"]
    if not isinstance(base, str) or not Path(base).is_absolute():
        raise ValueError("SDK fixture observations require their actual absolute owned root")
    validate_get_filesystem_observation(record["filesystem"], public.get("filesystem"), base)
    if arguments.get("readRace") is not None:
        if not _same_json(derive_get_read_race_observation(record.get("readRace"), base, native=False), public.get("readRace")):
            raise ValueError("SDK race results lost their actual OS mutation evidence")
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
