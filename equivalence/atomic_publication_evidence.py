"""Complete atomic IO observations and a narrowly bound physical-receipt codec.

This module supplies no writer, publication algorithm, rollback or expected
result. Unbound physical receipts remain unchanged in the comparable carrier.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import hashlib
import re
import stat
import traceback

SAFE_INTEGER = (1 << 53) - 1
STAT_FIELDS = ("dev", "ino", "mode", "nlink", "size", "uid", "gid", "mtimeNs", "ctimeNs")
RECEIPT_FIELDS = set(STAT_FIELDS)
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")


class AtomicEvidenceError(ValueError):
    """The observation cannot authorize its requested atomic evidence claim."""


def _integer(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and _DECIMAL.fullmatch(value):
        return int(value)
    if (isinstance(value, dict) and set(value) == {"type", "decimal"}
            and value["type"] in {"bigint", "integer"} and isinstance(value["decimal"], str)
            and _DECIMAL.fullmatch(value["decimal"])):
        return int(value["decimal"])
    raise AtomicEvidenceError("Physical stat fields require exact lossless integers")


def _lossless(value):
    if type(value) is int:
        return value if abs(value) <= SAFE_INTEGER else {"type": "integer", "decimal": str(value)}
    if isinstance(value, list):
        return [_lossless(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"type", "decimal"} and value.get("type") in {"bigint", "integer"}:
            return _lossless(_integer(value))
        return {key: _lossless(item) for key, item in value.items()}
    return value


def public_atomic_error(error: BaseException) -> dict:
    """Fixed nullable carrier fields plus every additional producer field.

    Original own-field presence, undefined values, stacks, and the Python bridge
    exception/context are retained separately by raw_atomic_error.
    """
    def observe(value):
        if isinstance(value, BaseException):
            return public_atomic_error(value)
        if isinstance(value, (tuple, list)):
            return [observe(item) for item in value]
        if isinstance(value, dict):
            return {key: observe(item) for key, item in value.items()}
        if isinstance(value, Path):
            return str(value)
        return value

    cause = getattr(error, "cause", error.__cause__)
    result = {"name": getattr(error, "name", type(error).__name__), "message": str(error),
              "code": getattr(error, "code", errno.errorcode.get(getattr(error, "errno", None))),
              "path": str(error.path) if hasattr(error, "path") else None,
              "cause": public_atomic_error(cause) if cause is not None else None}
    private = {"name", "message", "stack", "code", "path", "cause", "original_exception"}
    result.update({key: observe(value) for key, value in vars(error).items() if key not in private})
    for key in ("errno", "syscall"):
        if getattr(error, key, None) is not None:
            result[key] = getattr(error, key)
    return result


def raw_atomic_error(error: BaseException) -> dict:
    active = set()

    def observe(value):
        if isinstance(value, BaseException):
            if id(value) in active:
                return {"type": "exception-reference", "name": type(value).__name__, "message": str(value)}
            active.add(id(value))
            properties = {key: observe(item) for key, item in vars(value).items()}
            properties.update({key: observe(getattr(value, key)) for key in
                               ("errno", "strerror", "filename", "filename2") if hasattr(value, key)})
            result = {"type": type(value).__name__, "module": type(value).__module__,
                      "name": getattr(value, "name", type(value).__name__), "message": str(value),
                      "properties": properties, "args": observe(value.args),
                      "stack": "".join(traceback.format_exception(value)),
                      "cause": observe(value.__cause__), "context": observe(value.__context__),
                      "suppressContext": value.__suppress_context__}
            active.remove(id(value))
            return result
        if isinstance(value, (tuple, list)):
            return [observe(item) for item in value]
        if isinstance(value, dict):
            return {str(key): observe(item) for key, item in value.items()}
        if isinstance(value, Path):
            return str(value)
        return value

    return observe(error)


def _public_from_raw_error(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not isinstance(raw.get("message"), str):
        raise AtomicEvidenceError("A producer error requires its complete original raw exception")
    native = isinstance(raw.get("own"), dict)
    properties = raw["own"] if native else raw.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("stack", raw.get("stack")), str):
        raise AtomicEvidenceError("A producer error lost its actual stack and own fields")

    def observe(value):
        if isinstance(value, dict):
            if (isinstance(value.get("own"), dict) or isinstance(value.get("properties"), dict)) and "name" in value and "message" in value:
                return _public_from_raw_error(value)
            return {key: observe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [observe(item) for item in value]
        return value

    undefined = {"type": "undefined"}
    cause = properties.get("cause", None if native else raw.get("cause"))
    if cause == undefined:
        cause = None
    code = properties.get("code", errno.errorcode.get(properties.get("errno")))
    if code == undefined:
        code = None
    pathname = properties.get("path")
    if pathname == undefined:
        pathname = None
    result = {"name": raw["name"], "message": raw["message"], "code": code,
              "path": pathname, "cause": _public_from_raw_error(cause) if cause is not None else None}
    private = {"name", "message", "stack", "code", "path", "cause", "original_exception"}
    if not native:
        private |= {"strerror", "filename", "filename2"}
    for key, value in properties.items():
        if key not in private and value != undefined and not (key in {"errno", "syscall"} and value is None):
            result[key] = observe(value)
    return result


def _stat(value):
    if not isinstance(value, dict) or not set(STAT_FIELDS) <= set(value):
        raise AtomicEvidenceError("Actual descriptor observations require complete physical stats")
    return {key: _integer(value[key]) for key in STAT_FIELDS}


def _event_map(raw):
    events = raw.get("ioEvents")
    if not isinstance(events, list):
        raise AtomicEvidenceError("Atomic observations require complete ordered IO events")
    result = {}
    for event in events:
        if (not isinstance(event, dict) or type(event.get("seq")) is not int or event["seq"] in result
                or event["seq"] < 0 or not isinstance(event.get("arguments"), dict)):
            raise AtomicEvidenceError("Atomic IO sequence identities must be unique and explicit")
        if result and event["seq"] != max(result) + 1:
            raise AtomicEvidenceError("Atomic IO sequence is incomplete or reordered")
        result[event["seq"]] = event
    return result


def _owned(base: Path, value: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise AtomicEvidenceError("A physical stage requires its actual absolute owned pathname")
    path = Path(value)
    if not path.is_relative_to(base) or ".." in path.parts:
        raise AtomicEvidenceError("A physical stage cannot borrow an ambient pathname")
    return path


def _exclusive(flags) -> bool:
    return flags in {"wx", "wx+"} if isinstance(flags, str) else (
        type(flags) is int and flags & os.O_CREAT != 0 and flags & os.O_EXCL != 0)


def _stages(raw, events, base):
    values = raw.get("stageAllocations", [])
    if not isinstance(values, list):
        raise AtomicEvidenceError("Actual allocated stages must remain a complete ordered list")
    result = []
    for index, allocation in enumerate(values):
        if (not isinstance(allocation, dict) or allocation.get("id") != f"stage-{index}"
                or type(allocation.get("fd")) is not int or allocation["fd"] < 0
                or allocation.get("kind") not in {"exclusive-open", "native-stage"}):
            raise AtomicEvidenceError("Allocated stages require actual descriptor identities and creation kind")
        path = _owned(base, allocation.get("path"))
        before, after = events.get(allocation.get("beforeEvent")), events.get(allocation.get("afterEvent"))
        if (before is None or after is None or before.get("when") != "before" or after.get("when") != "after"
                or before["seq"] >= after["seq"] or before.get("role") != "stage"
                or before.get("actor") != allocation.get("actor") or after.get("actor") != allocation.get("actor")
                or before.get("path") != str(path) or after.get("path") != str(path)
                or not isinstance(after.get("result"), dict) or after["result"].get("fd") != allocation["fd"]
                or "error" in after):
            raise AtomicEvidenceError("A stage must bind its actual creation request, result and descriptor")
        observed = _stat(allocation.get("stat"))
        if _stat(after["result"].get("stat")) != observed or not stat.S_ISREG(observed["mode"]) or observed["nlink"] != 1:
            raise AtomicEvidenceError("A stage allocation must match its independent regular-file fstat")
        if allocation["kind"] == "exclusive-open":
            arguments = before["arguments"].get("args", [])
            if (len(arguments) < 3 or str(arguments[0]) != str(path) or not _exclusive(arguments[1])
                    or type(arguments[2]) is not int):
                raise AtomicEvidenceError("An allocated stage must come from the actual exclusive-open request")
        else:
            arguments = before["arguments"].get("args", [])
            if (before["arguments"].get("method") != "native.createStagedFile"
                    or type(allocation.get("parentFd")) is not int or len(arguments) < 2
                    or arguments[0] != allocation["parentFd"] or arguments[1] != path.name
                    or after["result"].get("parentFd") != allocation["parentFd"]
                    or after["result"].get("parentStat") != allocation.get("parentStat")):
                raise AtomicEvidenceError("Native stages require the original native creation operation")
            _stat(allocation.get("parentStat"))
        result.append({**allocation, "path": str(path), "stat": observed})
    return result


def _receipt_stat(value):
    if not isinstance(value, dict) or not RECEIPT_FIELDS <= set(value):
        return None
    try:
        return {key: _integer(value[key]) for key in STAT_FIELDS}
    except AtomicEvidenceError:
        return None


def _receipt_bindings(value, raw, events, stages):
    bindings = {}

    def visit(item):
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            directory = item.get("directory")
            if (isinstance(directory, dict) and "temporaryBasename" in item and "identity" in item
                    and isinstance(item["temporaryBasename"], str)):
                for allocation in stages:
                    stage_path = Path(allocation["path"])
                    if (item["temporaryBasename"] != stage_path.name or directory.get("path") != str(stage_path.parent)
                            or directory.get("realPath") != str(stage_path.parent)):
                        continue
                    actual = _receipt_stat(item["identity"])
                    live_events = []
                    for event in events.values():
                        if event["seq"] < allocation["afterEvent"] or event.get("fd") != allocation["fd"]:
                            continue
                        if (event.get("operation") == "close" and event.get("when") == "after"
                                and "error" not in event):
                            break
                        if event.get("actor") == allocation["actor"]:
                            live_events.append(event)
                    publications = [event for event in events.values()
                                    if event["seq"] > allocation["afterEvent"] and event.get("actor") == allocation["actor"]
                                    and event.get("operation") == "publish" and event.get("when") == "before"
                                    and (event.get("path") == str(stage_path) or event.get("arguments", {}).get("args", [None, None])[1:2] == [stage_path.name])]
                    publication_seq = min((event["seq"] for event in publications), default=-1)
                    syncs = [event["seq"] for event in live_events if event.get("operation") == "file-sync"
                             and event.get("when") == "after" and "error" not in event and event["seq"] < publication_seq]
                    prepared = [event for event in live_events if syncs and event["seq"] > max(syncs)
                                and event["seq"] < publication_seq and event.get("operation") == "fstat"
                                and event.get("when") == "after" and "error" not in event and isinstance(event.get("stat"), dict)]
                    observed = _stat(prepared[-1]["stat"]) if prepared else None
                    prepared_matches = observed is not None and {**observed, "mode": observed["mode"] & 0o7777} == actual
                    parent_stat = allocation.get("parentStat")
                    if parent_stat is None:
                        parent_stat = next((entry["stat"] for entry in raw.get("snapshots", {}).get("before", [])
                                            if entry.get("path") == str(stage_path.parent)), None)
                    parent_identity = directory.get("identity", {})
                    if (actual is not None and prepared_matches and parent_stat is not None
                            and set(parent_identity) == {"dev", "ino"}
                            and all(_integer(parent_identity[key]) == _stat(parent_stat)[key] for key in ("dev", "ino"))
                            and all(actual[key] == allocation["stat"][key] for key in ("dev", "ino"))):
                        bindings[id(item)] = allocation["id"]
            for child in item.values():
                visit(child)

    visit(value)
    return bindings


def encode_atomic_public(public: dict, raw: dict) -> dict:
    """Validate physical aliases first; unbound receipts retain their real values."""
    base = Path(raw.get("fixtureBase", ""))
    if not base.is_absolute():
        raise AtomicEvidenceError("Atomic codecs require an actual absolute fixture root")
    events = _event_map(raw)
    stages = _stages(raw, events, base)
    bindings = _receipt_bindings(public, raw, events, stages)
    paths = {allocation["path"]: str(Path(allocation["path"]).parent / f'.{allocation["id"]}') for allocation in stages}
    basenames = {Path(allocation["path"]).name: f'.{allocation["id"]}' for allocation in stages}
    attempts = raw.get("exclusiveAttempts", [])
    if not isinstance(attempts, list):
        raise AtomicEvidenceError("Exclusive IO attempts must retain their ordered results")
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict) or attempt.get("id") != f"attempt-{index}":
            raise AtomicEvidenceError("Exclusive attempt sequence is incomplete")
        pathname = _owned(base, attempt.get("path"))
        before, after = events.get(attempt.get("beforeEvent")), events.get(attempt.get("afterEvent"))
        if (before is None or after is None or before.get("when") != "before" or after.get("when") != "after"
                or before.get("path") != str(pathname) or after.get("path") != str(pathname)
                or before["seq"] >= after["seq"] or not _exclusive(attempt.get("flags"))
                or type(attempt.get("mode")) is not int):
            raise AtomicEvidenceError("An exclusive attempt requires the actual owned IO arguments and result")
        args = before["arguments"].get("args", [])
        if len(args) < 3 or str(args[0]) != str(pathname) or args[1:3] != [attempt["flags"], attempt["mode"]]:
            raise AtomicEvidenceError("An exclusive attempt cannot borrow another operation's flags or mode")
        if attempt.get("status") == "rejected":
            if ("error" not in after or "fd" in attempt or isinstance(after.get("result"), dict)
                    and "fd" in after["result"] or any(stage["path"] == str(pathname) for stage in stages)):
                raise AtomicEvidenceError("A returned or hidden stage fd cannot masquerade as a rejected attempt")
            paths[str(pathname)] = str(pathname.parent / f'.exclusive-attempt-{index}')
        elif attempt.get("status") != "returned":
            raise AtomicEvidenceError("An exclusive attempt has no actual returned/rejected result")

    def text(value):
        for actual, label in sorted(paths.items(), key=lambda item: -len(item[0])):
            value = value.replace(actual, label)
        return value.replace(str(base) + "/", "$FIXTURE/") if value != str(base) else "$FIXTURE"

    def encode(value, field=None):
        if isinstance(value, str):
            return basenames.get(value, value) if field == "temporaryBasename" else text(value)
        if isinstance(value, list):
            return [encode(item) for item in value]
        if isinstance(value, dict):
            bound = bindings.get(id(value))
            if bound:
                result = {key: encode(item, key) for key, item in value.items()}
                for key in ("dev", "ino", "mtimeNs", "ctimeNs"):
                    phase = "prepared:" if key in {"mtimeNs", "ctimeNs"} else ""
                    result["identity"][key] = f"$PHYSICAL:{bound}:{phase}{key}"
                for key in ("dev", "ino"):
                    result["directory"]["identity"][key] = f"$PHYSICAL:{bound}:directory:{key}"
                return result
            return _lossless({key: encode(item, key) for key, item in value.items()})
        return _lossless(value)

    return encode(public)


def _read_surviving_tree(base: Path) -> list[dict]:
    """Reread the complete subject through owned no-follow directory fds."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    outer = os.open(base, flags)
    result = []

    def physical(info):
        return {key: str(getattr(info, name)) for key, name in {
            "dev": "st_dev", "ino": "st_ino", "mode": "st_mode", "nlink": "st_nlink", "size": "st_size",
            "uid": "st_uid", "gid": "st_gid", "mtimeNs": "st_mtime_ns", "ctimeNs": "st_ctime_ns",
        }.items()}

    def visit(parent, name, pathname):
        observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
        kind = ("file" if stat.S_ISREG(observed.st_mode) else "directory" if stat.S_ISDIR(observed.st_mode)
                else "symlink" if stat.S_ISLNK(observed.st_mode) else "other")
        entry = {"path": str(pathname), "kind": kind, "mode": stat.S_IMODE(observed.st_mode), "stat": physical(observed)}
        opened = None
        try:
            if kind in {"file", "directory"}:
                opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_DIRECTORY if kind == "directory" else 0), dir_fd=parent)
                actual = os.fstat(opened)
                if (actual.st_dev, actual.st_ino, actual.st_mode) != (observed.st_dev, observed.st_ino, observed.st_mode):
                    raise AtomicEvidenceError("The actual surviving entry changed during independent descriptor admission")
            if kind == "file":
                chunks, length = [], 0
                while chunk := os.read(opened, 65536):
                    length += len(chunk)
                    if length > 16 * 1024 * 1024:
                        raise AtomicEvidenceError("The surviving atomic file exceeds the complete capture bound")
                    chunks.append(chunk)
                entry["bytes"] = list(b"".join(chunks))
            elif kind == "symlink":
                entry["link"] = os.readlink(name, dir_fd=parent)
            result.append(entry)
            if kind == "directory":
                with os.scandir(opened) as children:
                    names = sorted(child.name for child in children)
                for child in names:
                    visit(opened, child, pathname / child)
        finally:
            if opened is not None:
                os.close(opened)

    try:
        visit(outer, "subject", base / "subject")
    finally:
        os.close(outer)
    return result


def _validate_fault_binding(expected, observed, events):
    if (observed.get("input") != expected or observed.get("matched") != 1
            or not isinstance(observed.get("events"), list) or len(observed["events"]) != 1):
        raise AtomicEvidenceError("An untriggered or altered atomic IO fault cannot pass")
    fault = events.get(observed["events"][0])
    if (fault is None or fault.get("operation") != "fault" or fault.get("when") != "after"
            or fault.get("role") != expected["role"] or fault.get("arguments", {}).get("input") != expected):
        raise AtomicEvidenceError("A fault cannot borrow an unrelated ordinary IO event")
    related = events.get(fault["arguments"].get("ioEvent"))
    if (related is None or related["seq"] >= fault["seq"] or related.get("actor") != fault.get("actor")
            or related.get("role") != expected["role"] or related.get("operation") != expected["operation"]):
        raise AtomicEvidenceError("The declared fault differs from its actual actor, role or IO operation")

    def same_call(left, right):
        return (left.get("actor") == right.get("actor") and left.get("operation") == right.get("operation")
                and left.get("role") == right.get("role")
                and all(left.get("arguments", {}).get(key) == right.get("arguments", {}).get(key) for key in ("method", "args")))

    if related.get("when") == "before":
        before = related
    else:
        before = next((item for item in reversed(list(events.values())) if item["seq"] < related["seq"]
                       and item.get("when") == "before" and same_call(item, related)), None)
    if before is None:
        raise AtomicEvidenceError("A fault result has no corresponding actual IO request")
    attempts = [item for item in events.values() if item["seq"] <= before["seq"] and item.get("when") == "before"
                and item.get("operation") == expected["operation"] and item.get("role") == expected["role"]]
    if len(attempts) != expected["occurrence"]:
        raise AtomicEvidenceError("The fault did not occur at its declared actual IO occurrence")
    afters = [item for item in events.values() if item["seq"] > before["seq"] and item.get("when") == "after"
              and same_call(item, before) and item.get("operation") != "fault"]
    effect = expected["effect"]
    if effect in {"reject-before", "reject-after", "partial-write"}:
        error = fault.get("error")
        if (not isinstance(error, dict) or error.get("name") != "Error"
                or error.get("code") != expected["code"] or error.get("message") != expected["message"]):
            raise AtomicEvidenceError("The actual injected producer error differs from its literal code and message")
    if effect == "reject-before":
        if related is not before:
            raise AtomicEvidenceError("A pre-dispatch rejection cannot claim a completed syscall")
    elif effect in {"reject-after", "partial-write", "external-inplace", "external-replace"}:
        completed = next((item for item in afters if item["seq"] < fault["seq"] and "error" not in item and "result" in item), None)
        if completed is None:
            raise AtomicEvidenceError("A post-dispatch fault requires the actual completed delegated IO first")
        if effect == "partial-write":
            written = completed["result"].get("bytesWritten") if isinstance(completed["result"], dict) else completed["result"]
            arguments = before["arguments"]
            if (type(written) is not int or not 0 < written <= expected["bytes"]
                    or "requestedArgs" not in arguments or "delegatedArgs" not in arguments
                    or arguments["requestedArgs"] == arguments["delegatedArgs"]):
                raise AtomicEvidenceError("A partial write lost its actual prefix return or delegated byte window")
    elif effect == "zero-write":
        def zero(item):
            result = item.get("result")
            return result == 0 or isinstance(result, dict) and result.get("bytesWritten") == 0
        if related is not before or not zero(fault) or not any(zero(item) for item in afters):
            raise AtomicEvidenceError("A zero-progress write must retain the actual injected zero return")
    elif effect != "replace-stage":
        raise AtomicEvidenceError("The atomic IO fault effect was not declared")
    if effect in {"replace-stage", "external-inplace", "external-replace"}:
        mutations = [item for item in events.values() if before["seq"] < item["seq"] < fault["seq"]
                     and str(item.get("operation", "")).startswith(("fixture.", "fixture-"))]
        if (not mutations or not any(item.get("when") == "after" and "error" not in item and "result" in item for item in mutations)
                or not any("write" in item.get("arguments", {}).get("method", "") for item in mutations)):
            raise AtomicEvidenceError("An external fixture mutation requires its complete actual delegated IO")


def validate_atomic_publication_raw(case: dict, public: dict, raw: dict, *, evidence_directory: Path | None = None,
                                    expected_side: str | None = None, verify_tree: bool = False) -> None:
    """Independently bind the raw carrier before accepting its encoded result."""
    from equivalence.atomic_publication_profile import ATOMIC_PUBLICATION_PROFILES

    if (raw.get("schemaVersion") != 1 or raw.get("operation") != case.get("operation")
            or raw.get("kind") != ATOMIC_PUBLICATION_PROFILES.get(case.get("operation"))
            or raw.get("input") != case.get("input") or type(raw.get("pid")) is not int
            or raw.get("pid", 0) <= 0 or raw.get("threadId") != 0):
        raise AtomicEvidenceError("Atomic evidence must execute its literal request and original process")
    if expected_side == "native":
        backend = raw.get("defaultNativeBinding")
        if (not isinstance(backend, dict) or backend.get("available") is not True
                or backend.get("overrideVariablesAbsent") is not True
                or not isinstance(backend.get("functions"), list)
                or not {"createStagedFile", "stagedFileMatches", "removeStagedFile", "closeOwnedFd", "renameReplace", "renameNoReplace"} <= set(backend["functions"])):
            raise AtomicEvidenceError("Native atomic observations require their genuine default available backend without overrides")
    base = Path(raw.get("fixtureBase", ""))
    if (not base.is_absolute() or evidence_directory is not None and base.parent != evidence_directory
            or not base.name.startswith(("native-atomic-", "python-atomic-"))):
        raise AtomicEvidenceError("Atomic evidence requires its exact case-owned fixture root")
    if (not isinstance(raw.get("requests"), list) or not raw["requests"]
            or not isinstance(raw.get("outcomes"), list) or len(raw["requests"]) != len(raw["outcomes"])):
        raise AtomicEvidenceError("Each literal atomic writer requires a complete original request and outcome")
    expected_ids = [writer["id"] for writer in raw["input"].get("concurrency", {}).get("writers", [])] or ["write"]
    if ([item.get("id") for item in raw["requests"]] != expected_ids
            or [item.get("id") for item in raw["outcomes"]] != expected_ids
            or any(request.get("outcome") != outcome for request, outcome in zip(raw["requests"], raw["outcomes"]))):
        raise AtomicEvidenceError("Atomic writer order, request outcomes or complete errors were changed")
    target = str(base / "subject" / raw["input"]["path"])
    request_input = raw["input"]["request"]
    contents = {writer["id"]: writer["content"] for writer in raw["input"].get("concurrency", {}).get("writers", [])}
    for request in raw["requests"]:
        content = contents.get(request["id"], request_input["content"])
        native = request.get("owner") in {"commitMemoryContent", "Root.append", "publishBootstrapFile"}
        if (expected_side == "native" and not native or expected_side == "sdk" and native
                or expected_side not in {None, "native", "sdk"}):
            raise AtomicEvidenceError("An atomic side cannot impersonate the other implementation's public owner")
        if raw["kind"] == "commit":
            expected_owner = "commitMemoryContent" if native else "memory_core.atomic_publication.commit_memory_content"
            arguments = ({"filePath": target, "content": content, "expectedContent": request_input["expectedContent"],
                          "expectedHash": request_input["expectedHash"], "allowInPlaceFallback": request_input["allowInPlaceFallback"],
                          "tempPrefix": request_input["tempPrefix"]} if native else
                         {"path": target, "content": content, "expected_content": request_input["expectedContent"],
                          "expected_hash": request_input["expectedHash"], "allow_in_place_fallback": request_input["allowInPlaceFallback"],
                          "temp_prefix": request_input["tempPrefix"]})
        elif raw["kind"] == "append":
            expected_owner = "Root.append" if native else "memory_core.atomic_publication.append_memory_content"
            arguments = ({"relativePath": raw["input"]["path"], "data": content,
                          "options": {"mkdir": True, "prependNewlineIfNeeded": request_input["prependNewlineIfNeeded"]}} if native else
                         {"path": target, "content": content, "prepend_newline_if_needed": request_input["prependNewlineIfNeeded"]})
        else:
            expected_owner = "publishBootstrapFile" if native else "memory_core.bootstrap.lifecycle._write_file_if_missing"
            arguments = {"filePath" if native else "path": target, "content": content}
        if request.get("owner") != expected_owner or request.get("arguments") != arguments:
            raise AtomicEvidenceError("The actual atomic owner and complete dispatched arguments differ from the literal request")
        outcome = request["outcome"]
        if outcome.get("status") == "rejected":
            if outcome.get("error") != _public_from_raw_error(request.get("rawError")):
                raise AtomicEvidenceError("The public atomic error dropped or changed an original producer field or cause")
        elif outcome.get("status") != "fulfilled" or set(outcome) != {"id", "status", "value"}:
            raise AtomicEvidenceError("An atomic request must preserve its complete original result or error")
    snapshots = raw.get("snapshots")
    if not isinstance(snapshots, dict) or set(snapshots) != {"before", "after"}:
        raise AtomicEvidenceError("Atomic evidence must retain both complete physical trees")
    logical = {}
    for when, entries in snapshots.items():
        if not isinstance(entries, list) or not entries:
            raise AtomicEvidenceError("Atomic evidence lost its subject root or surviving files")
        seen = set()
        logical[when] = []
        for entry in entries:
            path = _owned(base, entry.get("path"))
            if str(path) in seen or not path.is_relative_to(base / "subject"):
                raise AtomicEvidenceError("Atomic tree entries must retain unique owned subject paths")
            seen.add(str(path))
            physical = _stat(entry.get("stat"))
            if entry.get("mode") != physical["mode"] & 0o7777:
                raise AtomicEvidenceError("Atomic public modes differ from their actual physical snapshots")
            if entry.get("kind") == "file":
                data = entry.get("bytes")
                if (not isinstance(data, list) or any(type(byte) is not int or not 0 <= byte <= 255 for byte in data)
                        or len(data) != physical["size"] or not stat.S_ISREG(physical["mode"])):
                    raise AtomicEvidenceError("Every surviving file requires its actual complete bytes and length")
            elif entry.get("kind") == "directory":
                if not stat.S_ISDIR(physical["mode"]):
                    raise AtomicEvidenceError("A physical directory cannot be rewritten as another object kind")
            elif entry.get("kind") == "symlink":
                if not stat.S_ISLNK(physical["mode"]) or not isinstance(entry.get("link"), str):
                    raise AtomicEvidenceError("A surviving symlink requires its original physical link value")
            elif entry.get("kind") != "other":
                raise AtomicEvidenceError("Atomic physical entries need an explicit original kind")
            logical[when].append({key: value for key, value in entry.items() if key != "stat"})
    initial = raw["input"]["initial"]
    initial_entry = next((entry for entry in snapshots["before"] if entry["path"] == target), None)
    parent_entry = next((entry for entry in snapshots["before"] if entry["path"] == str(Path(target).parent)), None)
    if parent_entry is None or parent_entry.get("mode") != raw["input"]["parentMode"]:
        raise AtomicEvidenceError("The actual atomic parent mode differs from the literal initial fixture")
    if initial is None:
        if initial_entry is not None:
            raise AtomicEvidenceError("An absent target was prepopulated before the actual original owner")
    elif (initial_entry is None or initial_entry.get("mode") != initial["mode"]
          or initial_entry.get("bytes") != list(initial["content"].encode("utf-8"))):
        raise AtomicEvidenceError("The complete initial file bytes or mode differ from the literal fixture")
    faults = raw.get("faults")
    if not isinstance(faults, list) or len(faults) != len(raw["input"].get("faults", [])):
        raise AtomicEvidenceError("All declared atomic fault attempts must remain visible")
    events = _event_map(raw)
    for expected, observed in zip(raw["input"].get("faults", []), faults):
        _validate_fault_binding(expected, observed, events)
    for event in events.values():
        if "error" in event and ("rawError" not in event or event["error"] != _public_from_raw_error(event["rawError"])):
            raise AtomicEvidenceError("An atomic IO error lost its actual original stack, own fields or recursive cause")
    if verify_tree and _read_surviving_tree(base) != snapshots["after"]:
        raise AtomicEvidenceError("The complete independently reread surviving tree differs from the retained atomic snapshot")
    expected_public = encode_atomic_public({"provider": "none", "outcomes": raw["outcomes"], "snapshots": logical}, raw)
    if expected_public != public:
        raise AtomicEvidenceError("Atomic output dropped or changed complete raw errors, outcomes, physical facts or order")


def dump_atomic_raw(directory: Path, raw: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False, indent=2) + "\n")


def validate_atomic_return_checkpoint(case, raw, events, *, raw_bytes: bytes, input_sha256: str) -> dict:
    """Keep owner-return and process-exit observations at their actual phases."""
    if not isinstance(events, list) or not events:
        raise AtomicEvidenceError("Atomic return observations require their trusted actual lifecycle trace")
    for event in events:
        if (event.get("caseId") != case["id"] or event.get("inputSha256") != input_sha256
                or event.get("fixtureBase") != raw["fixtureBase"] or event.get("pid") != raw["pid"]
                or event.get("threadId") != 0):
            raise AtomicEvidenceError("An atomic lifecycle event borrowed another case, actor or fixture")
    starts = [event for event in events if event["event"] == "atomic-owner-start"]
    settles = [event for event in events if event["event"] == "atomic-owner-settle"]
    returns = [event for event in events if event["event"] == "atomic-return-checkpoint"]
    exit_starts = [event for event in events if event["event"] == "atomic-exit-start"]
    exit_ends = [event for event in events if event["event"] == "atomic-exit-end"]
    steps = [request["id"] for request in raw["requests"]]
    if ([event.get("stepId") for event in starts] != steps
            or sorted(event.get("stepId") for event in settles) != sorted(steps)
            or len(returns) != 1 or len(exit_starts) != 1 or len(exit_ends) != 1):
        raise AtomicEvidenceError("Atomic original calls, settlements, return checkpoint and exit must be unique and complete")
    checkpoint, exit_start, exit_end = returns[0], exit_starts[0], exit_ends[0]
    if (not all(events.index(start) < events.index(next(item for item in settles if item["stepId"] == start["stepId"])) < events.index(checkpoint) for start in starts)
            or not events.index(checkpoint) < events.index(exit_start) < events.index(exit_end)
            or exit_start.get("checkpointCompleted") is not True):
        raise AtomicEvidenceError("Atomic lifecycle observations were collected out of the actual call/return/exit order")
    if (checkpoint.get("rawSha256") != hashlib.sha256(raw_bytes).hexdigest()
            or checkpoint.get("rawBytes") != len(raw_bytes) or checkpoint.get("ioEventCount") != len(raw["ioEvents"])
            or checkpoint.get("subjectTree") != raw["snapshots"]["after"]
            or starts[0].get("beforeTree") != raw["snapshots"]["before"]):
        raise AtomicEvidenceError("The independent trusted return checkpoint differs from its complete actual journal or physical tree")
    for request, start in zip(raw["requests"], starts):
        settlement = next(event for event in settles if event["stepId"] == request["id"])
        if (start.get("owner") != request["owner"] or start.get("arguments") != request["arguments"]
                or settlement.get("owner") != request["owner"] or settlement.get("arguments") != request["arguments"]
                or settlement.get("outcome") != request["outcome"]
                or request["outcome"]["status"] == "rejected" and settlement.get("rawError") != request.get("rawError")):
            raise AtomicEvidenceError("The trusted original Promise settlement differs from the adapter's complete actual owner result")
    if checkpoint.get("settlements") != [{key: value for key, value in event.items()
                                          if key not in {"event", "caseId", "inputSha256", "fixtureBase", "pid", "threadId"}}
                                         for event in settles]:
        raise AtomicEvidenceError("The atomic return checkpoint lost the original actual settlement sequence")
    actual_exit = _read_surviving_tree(Path(raw["fixtureBase"]))
    if exit_end.get("error") is not None or exit_end.get("subjectTree") != actual_exit:
        raise AtomicEvidenceError("The independently reread post-process tree differs from the original trusted exit observation")
    for event in events:
        if event["event"] == "atomic-exit-io":
            if not events.index(exit_start) < events.index(event) < events.index(exit_end):
                raise AtomicEvidenceError("An original exit IO observation escaped its actual process-exit phase")
            arguments = event.get("arguments")
            if (not isinstance(arguments, list) or not arguments or not isinstance(arguments[0], str)
                    or not Path(arguments[0]).is_relative_to(Path(raw["fixtureBase"]) / "subject")):
                raise AtomicEvidenceError("The original exit observer captured an ambient IO path")
    return {"kind": "trusted-original-owner-return-and-process-exit-observations",
            "events": events, "postProcessSubjectTree": actual_exit,
            "operationReturnEqualsProcessExit": raw["snapshots"]["after"] == actual_exit}
