"""Actual SDK atomic owners with bounded, delegated IO observation and faults."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from unittest.mock import patch


_KINDS = {"commit": "atomic-commit-runtime", "append": "atomic-append-runtime",
          "bootstrap": "atomic-bootstrap-runtime"}
_REQUEST_FIELDS = {"content", "expectedContent", "expectedHash", "allowInPlaceFallback",
                   "prependNewlineIfNeeded", "tempPrefix"}
_STAT_FIELDS = {"dev": "st_dev", "ino": "st_ino", "mode": "st_mode", "nlink": "st_nlink",
                "size": "st_size", "uid": "st_uid", "gid": "st_gid",
                "mtimeNs": "st_mtime_ns", "ctimeNs": "st_ctime_ns"}


def _full_stat(value):
    return {field: str(getattr(value, attribute)) for field, attribute in _STAT_FIELDS.items()}


def _json_value(value):
    if isinstance(value, os.stat_result):
        return _full_stat(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "bytes", "bytes": list(bytes(value))}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported actual atomic IO argument {type(value).__name__}")


def _snapshot(root):
    entries = []

    def visit(path):
        info = path.lstat()
        kind = ("file" if stat.S_ISREG(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode)
                else "symlink" if stat.S_ISLNK(info.st_mode) else "other")
        entry = {"path": str(path), "kind": kind, "mode": stat.S_IMODE(info.st_mode), "stat": _full_stat(info)}
        if kind == "file":
            entry["bytes"] = list(path.read_bytes())
        elif kind == "symlink":
            entry["link"] = os.readlink(path)
        entries.append(entry)
        if kind == "directory":
            for child in sorted(path.iterdir()):
                visit(child)

    visit(root)
    return entries


class _LiteralIOError(OSError):
    name = "Error"

    def __init__(self, facts):
        super().__init__(facts["message"])
        self.code = facts["code"]

    def __str__(self):
        return str(self.args[0])


class _ObservedIO:
    def __init__(self, value, root, target, raw, public_error, raw_error):
        self.value, self.root, self.target, self.raw = value, root, target, raw
        self.public_error, self.raw_error = public_error, raw_error
        self.local, self.lock = threading.local(), threading.RLock()
        self.original = {name: getattr(os, name) for name in (
            "open", "close", "read", "write", "pread", "pwrite", "fsync", "replace", "link", "unlink",
            "fstat", "stat", "lstat", "chmod", "fchmod", "ftruncate", "mkdir", "readlink",
        )}
        self.descriptors = {}
        self.stage_paths = set()
        self.matches = [0] * len(value["faults"])
        self.ready = {name: threading.Event() for name in ("first", "second")}
        self.release = {name: threading.Event() for name in ("first", "second")}
        self.stage_held = set()

    @property
    def actor(self):
        return getattr(self.local, "actor", "write")

    def event(self, operation, role, when, arguments, *, path=None, fd=None, **facts):
        with self.lock:
            event = {"seq": len(self.raw["ioEvents"]), "actor": self.actor, "operation": operation,
                     "role": role, "arguments": _json_value(arguments), "when": when,
                     **({"path": str(path)} if path is not None else {}),
                     **({"fd": fd} if fd is not None else {}), **facts}
            self.raw["ioEvents"].append(event)
            return event["seq"]

    def owned(self, path):
        if not isinstance(path, (str, bytes, os.PathLike)):
            return False
        filename = Path(os.path.abspath(os.fsdecode(path)))
        return filename == self.root or filename.is_relative_to(self.root)

    def role(self, path):
        path = Path(os.path.abspath(os.fsdecode(path)))
        if path == self.target:
            return "target"
        if str(path) in self.stage_paths:
            return "stage"
        return "parent" if path == self.root or path == self.target.parent else "target"

    def descriptor_stat(self, descriptor):
        try:
            return _full_stat(self.original["fstat"](descriptor))
        except OSError:
            return None

    def descriptor_path(self, descriptor):
        try:
            observed = self.original["readlink"](f"/proc/self/fd/{descriptor}")
            if self.owned(observed):
                return observed
        except OSError:
            pass
        return self.descriptors.get(descriptor, {}).get("path")

    def selected(self, operation, role, *, effects=None):
        for index, facts in enumerate(self.value["faults"]):
            if (facts["operation"] != operation or facts["role"] != role
                    or effects is not None and facts["effect"] not in effects):
                continue
            self.matches[index] += 1
            if self.matches[index] == facts["occurrence"] and self.raw["faults"][index]["matched"] == 0:
                return index, facts
        return None

    def inject(self, selected, related, *, result=None):
        index, facts = selected
        entry = self.raw["faults"][index]
        entry["matched"] += 1
        error = None if facts["effect"] in {"zero-write", "replace-stage", "external-inplace", "external-replace"} else _LiteralIOError(facts)
        sequence = self.event("fault", facts["role"], "after", {"input": facts, "ioEvent": related},
                              **({"error": self.public_error(error), "rawError": self.raw_error(error)} if error is not None else {"result": result}))
        entry["events"].append(sequence)
        if error is not None:
            raise error

    def _fixture_io(self, method, role, arguments, invoke, *, path=None, fd=None):
        before = self.event("fixture-" + method, role, "before", {"method": "os." + method, "args": arguments}, path=path, fd=fd)
        try:
            result = invoke()
        except BaseException as error:
            self.event("fixture-" + method, role, "after", {"method": "os." + method, "args": arguments},
                       path=path, fd=fd, error=self.public_error(error), rawError=self.raw_error(error))
            raise
        self.event("fixture-" + method, role, "after", {"method": "os." + method, "args": arguments},
                   path=path, fd=fd, result=_json_value(result))
        return result, before

    def fixture_write(self, path, content, *, exclusive, mode):
        flags = os.O_WRONLY | (os.O_CREAT | os.O_EXCL if exclusive else os.O_TRUNC)
        descriptor, _ = self._fixture_io("open", "target", [path, flags, mode],
            lambda: self.original["open"](path, flags, mode), path=path)
        try:
            data = memoryview(content.encode("utf-8"))
            while data:
                written, _ = self._fixture_io("write", "target", [descriptor, data],
                    lambda: self.original["write"](descriptor, data), path=path, fd=descriptor)
                if written <= 0:
                    raise RuntimeError("Literal external fixture write made no progress")
                data = data[written:]
        finally:
            self._fixture_io("close", "target", [descriptor], lambda: self.original["close"](descriptor), path=path, fd=descriptor)

    def mutate(self, selected, path):
        _index, facts = selected
        if facts["effect"] == "external-inplace":
            self.fixture_write(self.target, facts["externalContent"], exclusive=False, mode=0o666)
        elif facts["effect"] == "external-replace":
            external = self.target.parent / "external-replacement-0"
            self.fixture_write(external, facts["externalContent"], exclusive=True, mode=0o666)
            self._fixture_io("replace", "target", [external, self.target],
                lambda: self.original["replace"](external, self.target), path=self.target)
        else:
            parked = Path(path).parent / "parked-stage-0"
            self._fixture_io("replace", "stage", [path, parked],
                lambda: self.original["replace"](path, parked), path=path)
            self.fixture_write(Path(path), facts["externalContent"], exclusive=True, mode=0o600)

    def perform(self, operation, role, method, args, invoke, *, path=None, fd=None, select=True):
        arguments = {"method": "os." + method, "args": args}
        before = self.event(operation, role, "before", arguments, path=path, fd=fd,
                            **({"stat": self.descriptor_stat(fd)} if fd is not None and self.descriptor_stat(fd) is not None else {}))
        selected = self.selected(operation, role) if select else None
        if selected is not None and selected[1]["effect"] == "partial-write":
            delegated = [*args]
            delegated[1] = args[1][:selected[1]["bytes"]]
            self.raw["ioEvents"][before]["arguments"].update({"requestedArgs": _json_value(args),
                                                             "delegatedArgs": _json_value(delegated)})
        if selected is not None and selected[1]["effect"] == "replace-stage":
            self.mutate(selected, path)
            self.inject(selected, before)
            selected = None
        if selected is not None and selected[1]["effect"] == "reject-before":
            self.inject(selected, before)
        if selected is not None and selected[1]["effect"] == "zero-write":
            self.inject(selected, before, result=0)
            self.event(operation, role, "after", arguments, path=path, fd=fd, result=0)
            return 0
        try:
            result = invoke(selected)
        except BaseException as error:
            self.event(operation, role, "after", arguments, path=path, fd=fd, error=self.public_error(error), rawError=self.raw_error(error))
            raise
        returned_stat = _full_stat(result) if isinstance(result, os.stat_result) else self.descriptor_stat(fd) if fd is not None else None
        after = self.event(operation, role, "after", arguments, path=path, fd=fd, result=_json_value(result),
                           **({"stat": returned_stat} if returned_stat is not None else {}))
        if selected is not None:
            if selected[1]["effect"] in {"external-inplace", "external-replace"}:
                self.mutate(selected, path)
                self.inject(selected, after)
            else:
                self.inject(selected, after)
        return result

    def open(self, path, flags, mode=0o777, *args, **kwargs):
        if not self.owned(path):
            return self.original["open"](path, flags, mode, *args, **kwargs)
        role = "stage" if flags & os.O_CREAT and flags & os.O_EXCL and Path(path) != self.target else self.role(path)
        before = self.event("open", role, "before", {"method": "os.open", "args": [path, flags, mode], "kwargs": kwargs}, path=path)
        attempt = None
        if flags & os.O_CREAT and flags & os.O_EXCL:
            attempt = {"id": f"attempt-{len(self.raw['exclusiveAttempts'])}", "actor": self.actor,
                       "path": str(path), "flags": flags, "mode": mode, "beforeEvent": before}
            self.raw["exclusiveAttempts"].append(attempt)
            if role == "stage":
                self.stage_paths.add(str(path))
        try:
            descriptor = self.original["open"](path, flags, mode, *args, **kwargs)
        except BaseException as error:
            after = self.event("open", role, "after", {"method": "os.open", "args": [path, flags, mode], "kwargs": kwargs}, path=path,
                               error=self.public_error(error), rawError=self.raw_error(error))
            if attempt is not None:
                attempt.update({"afterEvent": after, "status": "rejected"})
            raise
        info = self.descriptor_stat(descriptor)
        self.descriptors[descriptor] = {"path": str(path), "role": role}
        after = self.event("open", role, "after", {"method": "os.open", "args": [path, flags, mode], "kwargs": kwargs}, path=path,
                           fd=descriptor, result={"fd": descriptor, "stat": info}, stat=info)
        if attempt is not None:
            attempt.update({"afterEvent": after, "status": "returned", "fd": descriptor})
            if role == "stage":
                allocation = {"id": f"stage-{len(self.raw['stageAllocations'])}", "actor": self.actor,
                              "path": str(path), "fd": descriptor, "kind": "exclusive-open",
                              "beforeEvent": before, "afterEvent": after, "stat": info}
                parents = [(fd, item) for fd, item in self.descriptors.items() if item["path"] == str(Path(path).parent) and item["role"] == "parent"]
                if parents:
                    allocation.update({"parentFd": parents[-1][0], "parentStat": self.descriptor_stat(parents[-1][0])})
                self.raw["stageAllocations"].append(allocation)
        schedule = self.value.get("concurrency", {}).get("schedule")
        if role == "stage" and schedule == "checked-replacements" and self.actor == "first" and "first" not in self.stage_held:
            self.stage_held.add("first")
            self.ready["first"].set()
            if not self.release["first"].wait(10):
                raise TimeoutError("The first actual replacement stage was not released")
        return descriptor

    def descriptor_call(self, method, descriptor, *args):
        if descriptor not in self.descriptors:
            return self.original[method](descriptor, *args)
        role, path = self.descriptors[descriptor]["role"], self.descriptor_path(descriptor)
        operation = ({"fsync": "parent-sync" if role == "parent" else "file-sync", "write": "write", "pwrite": "write",
                      "read": "before-read", "pread": "before-read"}).get(method, method)
        actual_args = [descriptor, *args]

        def invoke(selected):
            if selected is not None and selected[1]["effect"] == "partial-write":
                window = args[0][:selected[1]["bytes"]]
                actual = (window, *args[1:])
                return self.original[method](descriptor, *actual)
            result = self.original[method](descriptor, *args)
            if method == "close":
                self.descriptors.pop(descriptor, None)
            return result

        result = self.perform(operation, role, method, actual_args, invoke, path=path, fd=descriptor)
        if method == "fsync" and role == "stage" and self.value.get("concurrency", {}).get("schedule") == "exclusive-bootstrap":
            self.ready[self.actor].set()
            if not self.release[self.actor].wait(10):
                raise TimeoutError("The complete actual bootstrap stage was not released")
        return result

    def path_call(self, method, path, *args, **kwargs):
        if not self.owned(path):
            return self.original[method](path, *args, **kwargs)
        role = self.role(path)
        operation = "publish" if method in {"replace", "link"} else "cleanup" if method == "unlink" and role == "stage" else method
        observed_path = args[0] if method in {"replace", "link"} else path
        if method in {"replace", "link"}:
            role = "target"
        # B5 replaces a stale temporary name before the real cleanup identity
        # read. Its foreign winner must not be adopted as the original stage.
        primary_stage_sync_failed = any(fault["matched"] and fault["input"]["operation"] == "file-sync"
                                        and fault["input"]["role"] == "stage" for fault in self.raw["faults"])
        if method == "lstat" and role == "stage" and primary_stage_sync_failed:
            selected = self.selected("cleanup", "stage", effects={"replace-stage"})
            if selected is not None and selected[1]["effect"] == "replace-stage":
                before = self.event("cleanup", role, "before", {"method": "os.lstat", "args": [path]}, path=path)
                self.mutate(selected, path)
                self.inject(selected, before)
        try:
            return self.perform(operation, role, method, [path, *args],
                lambda _selected: self.original[method](path, *args, **kwargs), path=observed_path,
                select=operation not in {"lstat", "stat", "chmod", "mkdir"})
        except FileNotFoundError:
            if (method == "lstat" and Path(path) == self.target and self.actor == "second"
                    and self.value.get("concurrency", {}).get("schedule") == "exclusive-bootstrap"):
                self.ready["second"].set()
            raise

    def fstat(self, descriptor):
        if descriptor in self.descriptors:
            role, path = self.descriptors[descriptor]["role"], self.descriptor_path(descriptor)
            self.event("fstat", role, "before", {"method": "os.fstat", "args": [descriptor]}, path=path, fd=descriptor)
        result = self.original["fstat"](descriptor)
        if descriptor in self.descriptors:
            role, path = self.descriptors[descriptor]["role"], self.descriptor_path(descriptor)
            self.event("fstat", role, "after", {"method": "os.fstat", "args": [descriptor]},
                       path=path, fd=descriptor, result=_full_stat(result), stat=_full_stat(result))
        return result

    def install(self, stack):
        stack.enter_context(patch.object(os, "open", self.open))
        stack.enter_context(patch.object(os, "fstat", self.fstat))
        for method in ("close", "read", "write", "pread", "pwrite", "fsync", "fchmod", "ftruncate"):
            stack.enter_context(patch.object(os, method, lambda fd, *args, _method=method: self.descriptor_call(_method, fd, *args)))
        for method in ("replace", "link", "unlink", "stat", "lstat", "chmod", "mkdir"):
            stack.enter_context(patch.object(os, method, lambda path, *args, _method=method, **kwargs: self.path_call(_method, path, *args, **kwargs)))


def _validate_input(value):
    required = {"kind", "version", "path", "initial", "parentMode", "umask", "request", "faults"}
    if (not isinstance(value, dict) or value.get("version") != 1 or value.get("kind") not in _KINDS
            or not required <= set(value) or set(value) - required - {"concurrency"}
            or not isinstance(value.get("request"), dict) or set(value["request"]) != _REQUEST_FIELDS
            or value.get("path") not in {"MEMORY.md", "AGENTS.md", "memory/2026-09-04.md"}
            or value.get("parentMode") not in {0o755, 0o555} or value.get("umask") != 0o022
            or not isinstance(value.get("faults"), list)):
        raise ValueError("An explicit bounded atomic publication v1 fixture is required")
    request = value["request"]
    if (request["tempPrefix"] != ".MEMORY.atomic-proof"
            or type(request["allowInPlaceFallback"]) is not bool or type(request["prependNewlineIfNeeded"]) is not bool
            or request["content"] is not None and not isinstance(request["content"], str)
            or request["expectedContent"] is not None and not isinstance(request["expectedContent"], str)
            or request["expectedHash"] is not None and not isinstance(request["expectedHash"], str)):
        raise ValueError("Atomic requests must preserve their complete literal v1 fields")
    initial = value["initial"]
    if initial is not None and (not isinstance(initial, dict) or set(initial) != {"content", "mode"}
                                or not isinstance(initial["content"], str) or type(initial["mode"]) is not int):
        raise ValueError("Atomic initial files require their literal content and mode")
    for fault in value["faults"]:
        fields = {"id", "operation", "role", "effect", "occurrence", "code", "message"}
        if (not isinstance(fault, dict) or not fields <= set(fault) or set(fault) - fields - {"bytes", "externalContent"}
                or not isinstance(fault["id"], str) or fault["operation"] not in {
                    "write", "file-sync", "parent-sync", "publish", "close", "cleanup", "before-read"}
                or fault["role"] not in {"stage", "target", "parent"}
                or fault["effect"] not in {"reject-before", "reject-after", "partial-write", "zero-write",
                                            "replace-stage", "external-inplace", "external-replace"}
                or type(fault["occurrence"]) is not int or fault["occurrence"] < 1
                or fault["code"] is not None and not isinstance(fault["code"], str)
                or fault["message"] is not None and not isinstance(fault["message"], str)
                or fault["effect"] == "partial-write" and (type(fault.get("bytes")) is not int or fault["bytes"] < 0)
                or fault["effect"] in {"replace-stage", "external-inplace", "external-replace"}
                and not isinstance(fault.get("externalContent"), str)):
            raise ValueError("Atomic faults must use explicit owned IO facts and occurrence")
    if len({fault["id"] for fault in value["faults"]}) != len(value["faults"]):
        raise ValueError("Atomic fault identities must be unique")
    concurrency = value.get("concurrency")
    if concurrency is not None and (not isinstance(concurrency, dict) or set(concurrency) != {"schedule", "writers"}
            or concurrency["schedule"] != {"commit": "checked-replacements", "bootstrap": "exclusive-bootstrap"}.get(value["kind"])
            or not isinstance(concurrency["writers"], list) or len(concurrency["writers"]) != 2
            or any(not isinstance(writer, dict) or set(writer) != {"id", "content"}
                   or writer["id"] != identity or not isinstance(writer["content"], str)
                   for writer, identity in zip(concurrency["writers"], ("first", "second")))):
        raise ValueError("Atomic concurrency requires the two literal writer identities and schedule")


def run_atomic_publication(arguments, *, evidence_directory=None):
    import memory_core
    from memory_core.atomic_publication import append_memory_content, commit_memory_content
    from memory_core.bootstrap.lifecycle import _write_file_if_missing
    from equivalence.atomic_publication_evidence import encode_atomic_public, public_atomic_error, raw_atomic_error

    owner_root = Path(__file__).resolve().parents[1]
    if not Path(memory_core.__file__).resolve().is_relative_to(owner_root):
        raise RuntimeError("Atomic publication imported an SDK outside its owning worktree")
    value = deepcopy(arguments)
    _validate_input(value)
    evidence = Path(evidence_directory) if evidence_directory is not None else None
    if evidence is not None:
        evidence.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="python-atomic-fixture-", dir=evidence)).absolute()
    root, target = base / "subject", base / "subject" / value["path"]
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if value["initial"] is not None:
        target.write_text(value["initial"]["content"], encoding="utf-8")
        target.chmod(value["initial"]["mode"])
    target.parent.chmod(value["parentMode"])
    raw = {"schemaVersion": 1, "operation": _KINDS[value["kind"]], "kind": value["kind"], "input": value,
           "fixtureBase": str(base), "pid": os.getpid(), "threadId": 0, "requests": [], "ioEvents": [],
           "faults": [{"input": deepcopy(fact), "matched": 0, "events": []} for fact in value["faults"]],
           "snapshots": {"before": _snapshot(root), "after": []}, "outcomes": [], "codec": {"version": 1},
           "stageAllocations": [], "exclusiveAttempts": []}
    observed = _ObservedIO(value, root, target, raw, public_atomic_error, raw_atomic_error)

    def run_writer(identity, content):
        observed.local.actor = identity
        request = value["request"]
        if value["kind"] == "commit":
            kwargs = {"content": content, "expected_content": request["expectedContent"],
                      "expected_hash": request["expectedHash"], "allow_in_place_fallback": request["allowInPlaceFallback"],
                      "temp_prefix": request["tempPrefix"]}
            owner, invoke = "memory_core.atomic_publication.commit_memory_content", lambda: commit_memory_content(target, **kwargs)
        elif value["kind"] == "append":
            kwargs = {"content": content, "prepend_newline_if_needed": request["prependNewlineIfNeeded"]}
            owner, invoke = "memory_core.atomic_publication.append_memory_content", lambda: append_memory_content(target, **kwargs)
        else:
            kwargs = {"content": content}
            owner, invoke = "memory_core.bootstrap.lifecycle._write_file_if_missing", lambda: _write_file_if_missing(target, content)
        entry = {"id": identity, "owner": owner, "arguments": {"path": str(target), **deepcopy(kwargs)}}
        raw["requests"].append(entry)
        if identity == "second" and value.get("concurrency", {}).get("schedule") == "checked-replacements":
            observed.ready["second"].set()
        try:
            result = invoke()
            outcome = {"id": identity, "status": "fulfilled", "value": result}
        except BaseException as error:
            outcome = {"id": identity, "status": "rejected", "error": public_atomic_error(error)}
            entry["rawError"] = raw_atomic_error(error)
        entry["outcome"] = outcome
        return outcome

    mask = os.umask(value["umask"])
    try:
        with ExitStack() as stack:
            observed.install(stack)
            concurrency = value.get("concurrency")
            if concurrency is None:
                raw["outcomes"] = [run_writer("write", value["request"]["content"])]
            else:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(run_writer, "first", concurrency["writers"][0]["content"])
                    try:
                        if not observed.ready["first"].wait(10):
                            raise TimeoutError("First actual writer stage was not reached")
                        second = executor.submit(run_writer, "second", concurrency["writers"][1]["content"])
                        if not observed.ready["second"].wait(10):
                            raise TimeoutError("Second actual writer phase was not reached")
                        observed.release["first"].set()
                        first_result = first.result(timeout=10)
                        observed.release["second"].set()
                        raw["outcomes"] = [first_result, second.result(timeout=10)]
                    finally:
                        observed.release["first"].set()
                        observed.release["second"].set()
    finally:
        os.umask(mask)
        raw["snapshots"]["after"] = _snapshot(root)
        if evidence is not None:
            (evidence / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public = {"provider": "none", "outcomes": raw["outcomes"], "snapshots": {
        stage: [{key: item for key, item in entry.items() if key != "stat"} for entry in raw["snapshots"][stage]]
        for stage in ("before", "after")
    }}
    return encode_atomic_public(public, raw)
