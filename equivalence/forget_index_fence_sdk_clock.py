"""Declared V2 clock fixtures over original SDK source and syscall frames.

This file is outside the production SDK. It neither replaces a producer nor
wraps an OS syscall. The profiler observes original return values; only the
declared source-write boundary performs the extra real ``os.utime`` operation.
Every fixture failure is retained separately from the original API settlement.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat
import sys
import time


class DatetimeClockProxy:
    """Delegate everything except ``now`` to one original datetime class."""

    def __init__(self, original, wall_ms, record):
        self.original, self.wall_ms, self.record = original, wall_ms, record
        self.failures = []

    def __call__(self, *arguments, **options):
        return self.original(*arguments, **options)

    def __getattr__(self, name):
        return getattr(self.original, name)

    def now(self, tz=None):
        wall = self.wall_ms()
        returned = self.original.fromtimestamp(wall / 1000, tz=tz)
        receipt = {"wallClockNowMs": wall, "timezone": repr(tz), "returnedISO": returned.isoformat(),
                     "returnedClass": {"module": type(returned).__module__, "name": type(returned).__qualname__},
                     "atNs": str(time.monotonic_ns())}
        try:
            self.record(receipt, sys._getframe(1))
        except BaseException as error:
            self.failures.append({"receipt": receipt, "error": {"module": type(error).__module__,
                "name": type(error).__qualname__, "message": str(error)}})
        return returned


class OwnedSourceWriteClock:
    """Timestamp only verified original owned source inodes at declared boundaries.

    ``owners`` maps exact loaded original code objects to precomputed source
    witnesses and a source role (io, write-all, atomic, append, in-place,
    dreams). Tests may supply labelled stand-ins without executing their bodies.
    No source lookup or observer mutex occurs in the passive IO recorder.
    """

    def __init__(self, *, root, actor, policy, owners, scope, encode, full_stat):
        self.root, self.actor = Path(root).resolve(), actor
        self.policy, self.owners = deepcopy(policy), dict(owners)
        self.scope, self.encode, self.full_stat = scope, encode, full_stat
        self.receipts, self.original_io, self.failures = [], [], []
        self.source_reads = []
        self.descriptors, self.failed_frames, self.pending_renames = {}, set(), {}
        self.committed_versions = {}
        self.sequence = 0
        self.original_os = {name: getattr(os, name) for name in (
            "open", "write", "pwrite", "fsync", "ftruncate", "close", "replace", "utime",
            "read", "pread", "lstat", "fstat", "unlink")}

    def _event(self, collection, event, **values):
        self.sequence += 1
        row = {"sequence": self.sequence, "event": event, "pid": os.getpid(),
               "actor": self.actor, "atNs": str(time.monotonic_ns()), **values}
        collection.append(row)
        return row

    def _failure(self, error, frame=None):
        owner = self.owners.get(frame.f_code) if frame is not None else None
        self._event(self.failures, "source-clock-observation-invalid", error={
            "module": type(error).__module__, "name": type(error).__qualname__, "message": str(error)},
            sourceCode=deepcopy(owner.get("code")) if owner else None,
            scope=deepcopy(self.scope()))

    def _stack(self, frame):
        rows = []
        while frame is not None:
            owner = self.owners.get(frame.f_code)
            if owner:
                rows.append({"sourceRole": owner["role"], "code": deepcopy(owner["code"])})
            frame = getattr(frame, "f_back", None)
        return rows

    def _owner(self, frame):
        while frame is not None:
            owner = self.owners.get(frame.f_code)
            if owner and owner["role"] in {"atomic", "append", "in-place", "dreams"}:
                path = frame.f_locals.get("path")
                if path is not None:
                    return owner["role"], frame, Path(path)
            frame = getattr(frame, "f_back", None)
        return None

    def _eligible(self, path):
        return path.suffix.lower() in {".md", ".txt"}

    def _owned(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.is_symlink() or path.resolve() != path or not path.resolve().is_relative_to(self.root):
            raise ValueError("A source-clock inode escaped its exact owned workspace")
        return path

    def _tick(self):
        scope = self.scope()
        if scope is None:
            raise ValueError("An original source write has no source-bound public call scope")
        key = f"{scope['kind']}:{scope['label']}"
        tick = self.policy["ticksByCall"].get(key)
        if tick is None or tick["actor"] != self.actor:
            raise ValueError("An original source write has no frozen tick for its actual actor and call")
        if scope.get("wallClockNowMs") != tick["wallClockNowMs"]:
            raise ValueError("The source-clock call-entry wall phase differs from its frozen tick")
        if (type(tick["ordinal"]) is not int or tick["ordinal"] < 1
                or type(tick["mtimeMs"]) is not int or tick["mtimeMs"] % 1000
                or tick["atimeMs"] != tick["mtimeMs"] or tick["mtimeMs"] > tick["wallClockNowMs"]):
            raise ValueError("The frozen source-clock tick is not an admitted whole-second input")
        return key, deepcopy(tick)

    def _inspect(self, path, descriptor=None):
        info = os.fstat(descriptor) if descriptor is not None else path.lstat()
        named = path.lstat()
        identity = info.st_dev, info.st_ino
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink()
                or (named.st_dev, named.st_ino) != identity):
            raise ValueError("The original source-clock inode no longer matches its owned pathname")
        # A separate NOATIME reader neither moves the original writable offset
        # nor changes the atime that this fixture has just supplied.
        if not hasattr(os, "O_NOATIME"):
            raise ValueError("Lossless source-clock inspection requires owned-inode O_NOATIME support")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME
        reader = os.open(path, flags)
        read_results = []
        try:
            opened = os.fstat(reader)
            if (opened.st_dev, opened.st_ino) != identity:
                raise ValueError("The source-clock read handle differs from its owned original inode")
            while True:
                chunk = os.read(reader, 1 << 16)
                read_results.append(chunk)
                if not chunk:
                    break
            payload = b"".join(read_results)
        finally:
            os.close(reader)
        after = os.fstat(descriptor) if descriptor is not None else path.lstat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                info.st_dev, info.st_ino, len(payload), info.st_mtime_ns, info.st_ctime_ns):
            raise ValueError("An original source inode changed during source-clock inspection")
        return {"stat": self.full_stat(info), "statAfterRead": self.full_stat(after),
                "bytes": payload.hex(), "sha256": hashlib.sha256(payload).hexdigest(),
                "identity": {"device": info.st_dev, "inode": info.st_ino}, "size": len(payload),
                "inspectionRead": {"descriptor": reader, "flags": flags,
                    "openedStat": self.full_stat(opened), "readReturns": [chunk.hex() for chunk in read_results]}}

    def _clock(self, *, frame, mode, path, stage, descriptor, state, original_arguments):
        path, stage = self._owned(path), self._owned(stage)
        key, tick = self._tick()
        before = self._inspect(stage, descriptor)
        if state.get("expectedBytes") is not None and before["bytes"] != state["expectedBytes"]:
            raise ValueError("The completed original staged bytes differ from the original write argument")
        if mode != "atomic-closed-stage" and not state.get("fullWrite"):
            raise ValueError("A source-clock boundary lacks the original full-write return")
        if mode != "atomic-closed-stage" and not state.get("fsync"):
            raise ValueError("A source-clock boundary lacks its actual original fsync return")
        target = descriptor if descriptor is not None else stage
        ns = (tick["atimeMs"] * 1_000_000, tick["mtimeMs"] * 1_000_000)
        receipt = self._event(self.receipts, "source-write-clock-v2", protocol=self.policy["protocol"],
            callKey=key, tick=tick, path=path.relative_to(self.root).as_posix(), ownedRoot=str(self.root),
            absolutePath=str(path), stagePath=str(stage), mode=mode, descriptor=descriptor,
            sourceStack=self._stack(frame), originalArguments=self.encode(original_arguments),
            originalOpen=deepcopy(state.get("open")), originalWrites=deepcopy(state.get("writes", [])),
            originalFullWrite=deepcopy(state.get("fullWrite")), originalFsync=deepcopy(state.get("fsync")),
            originalFsyncPresent=bool(state.get("fsync")), originalTextIO=deepcopy(state.get("textIO", [])),
            before=before, utimeArguments={"target": self.encode(target), "ns": list(ns)}, committed=False)
        receipt["utimeEnterAtNs"] = str(time.monotonic_ns())
        try:
            returned = self.original_os["utime"](target, ns=ns)
        except BaseException as error:
            receipt["utimeError"] = {"module": type(error).__module__, "name": type(error).__qualname__,
                "message": str(error), "args": self.encode(error.args), "errno": getattr(error, "errno", None)}
            receipt["utimeErrorAtNs"] = str(time.monotonic_ns())
            raise
        receipt.update(utimeReturn=self.encode(returned), utimeReturnAtNs=str(time.monotonic_ns()))
        receipt["statImmediatelyAfterUtime"] = self.full_stat(os.fstat(descriptor) if descriptor is not None else stage.lstat())
        receipt["after"] = self._inspect(stage, descriptor)
        if (receipt["after"]["identity"] != before["identity"] or receipt["after"]["bytes"] != before["bytes"]
                or int(receipt["after"]["stat"]["st_mtime_ns"]) != ns[1]):
            raise ValueError("The real source-clock operation did not retain its owned inode, bytes and declared mtime")
        return receipt

    def _commit(self, receipt, frame, returned, *, witness):
        receipt.update(committed=True, originalCommit={"witness": witness,
            "returned": self.encode(returned), "atNs": str(time.monotonic_ns()), "sourceStack": self._stack(frame)})
        target = self._owned(receipt["absolutePath"])
        receipt["committedState"] = self._inspect(target)
        if (receipt["committedState"]["identity"] != receipt["before"]["identity"]
                or receipt["committedState"]["bytes"] != receipt["before"]["bytes"]):
            raise ValueError("The successful original source commit did not publish its clocked inode and bytes")
        key = receipt["callKey"], receipt["path"]
        previous = self.committed_versions.get(key)
        current = receipt["committedState"]["sha256"]
        self.committed_versions[key] = current
        if previous is not None and previous != current:
            raise ValueError("Distinct committed bytes for one public call and path are unsupported by the frozen source clock")

    def _io_return(self, frame, returned):
        function, arguments = frame.f_locals.get("function"), frame.f_locals.get("args", ())
        if not arguments or id(frame) in self.failed_frames:
            return
        name = next((name for name, original in self.original_os.items() if function is original), None)
        if name is None:
            return
        source = self._owner(getattr(frame, "f_back", None))
        if source is None or not self._eligible(source[2]):
            return
        role, owner_frame, path = source
        scope = deepcopy(self.scope())
        row = self._event(self.original_io, "original-source-io-return", syscall=name,
            arguments=self.encode(tuple(bytes(item) if isinstance(item, memoryview) else item for item in arguments)),
            returned=self.encode(returned), scope=scope, sourceStack=self._stack(frame))
        if isinstance(returned, os.stat_result):
            row["returnedStat"] = self.full_stat(returned)
        if name == "unlink":
            row["ownerCode"] = deepcopy(self.owners[owner_frame.f_code]["code"])
            row["ownerArguments"] = {key: self.encode(owner_frame.f_locals[key]) for key in (
                "path", "content", "expected_content", "expected_hash") if key in owner_frame.f_locals}
        if name == "open" and type(returned) is int and len(arguments) > 1 and arguments[1] & os.O_ACCMODE != os.O_RDONLY:
            self.descriptors[returned] = {"role": role, "path": path, "stage": Path(arguments[0]), "open": row,
                                          "writes": [], "ownerFrameId": id(owner_frame)}
            return
        descriptor = arguments[0]
        state = self.descriptors.get(descriptor) if type(descriptor) is int else None
        if name in {"write", "pwrite"} and state is not None:
            state["writes"].append(row)
        elif name == "fsync" and state is not None:
            state["fsync"] = row
        elif name == "close" and state is not None:
            if state.get("clock") is not None:
                self._commit(state["clock"], frame, returned, witness="original-owned-fd-close-return")
            self.descriptors.pop(descriptor, None)
        elif name == "replace":
            receipt = self.pending_renames.pop(id(frame), None)
            if receipt is not None:
                self._commit(receipt, frame, returned, witness="original-os-replace-return")

    def _before_io_c_call(self, frame, function):
        arguments = frame.f_locals.get("args", ())
        if function is self.original_os["replace"] and frame.f_locals.get("function") is function and len(arguments) == 2:
            source = self._owner(getattr(frame, "f_back", None))
            if source is None or source[0] != "atomic" or not self._eligible(source[2]):
                return
            descriptor = source[1].f_locals.get("descriptor")
            state = self.descriptors.get(descriptor)
            if state is None:
                raise ValueError("An original atomic rename lacks its genuine owned staged descriptor")
            receipt = self._clock(frame=frame, mode="atomic-staged", path=arguments[1], stage=arguments[0],
                descriptor=descriptor, state=state, original_arguments=arguments)
            self.pending_renames[id(frame)] = receipt
        elif function is self.original_os["close"] and frame.f_locals.get("function") is function and arguments:
            state = self.descriptors.get(arguments[0])
            if state is not None and state["role"] in {"append", "in-place"} and state.get("fullWrite") and state.get("fsync"):
                state["clock"] = self._clock(frame=frame, mode="in-place-owned-fd", path=state["path"],
                    stage=state["path"], descriptor=arguments[0], state=state, original_arguments=arguments)

    def _dreams(self, frame, event, function):
        path, temporary = Path(frame.f_locals["path"]), frame.f_locals.get("temporary")
        if not self._eligible(path):
            return
        record = frame.f_locals.get("handle")
        if record is not None and event in {"c_return", "c_exception"} and getattr(function, "__self__", None) is record:
            self._event(self.original_io, "original-dreams-textio-settlement", method=getattr(function, "__name__", None),
                settlement="returned" if event == "c_return" else "raised", sourceFrameObjectId=str(id(frame)),
                sourceStack=self._stack(frame), scope=deepcopy(self.scope()))
        if event == "c_call" and function is self.original_os["replace"] and temporary is not None:
            if record is None or not record.closed:
                raise ValueError("The original DREAMS stage has not closed its text writer before rename")
            state = {"expectedBytes": frame.f_locals["content"].encode("utf8").hex(),
                "textIO": [row for row in self.original_io if row["event"] == "original-dreams-textio-settlement"
                           and row.get("sourceFrameObjectId") == str(id(frame))]}
            self.pending_renames[id(frame)] = self._clock(frame=frame, mode="atomic-closed-stage", path=path,
                stage=Path(temporary), descriptor=None, state=state, original_arguments=(temporary, path))
        elif event == "c_exception" and function is self.original_os["replace"]:
            receipt = self.pending_renames.pop(id(frame), None)
            if receipt is not None:
                receipt["originalCommit"] = {"witness": "original-os-replace-c-exception", "atNs": str(time.monotonic_ns())}
        elif event == "return":
            receipt = self.pending_renames.pop(id(frame), None)
            if receipt is not None:
                self._commit(receipt, frame, function, witness="original-dreams-atomic-writer-return")

    def profile(self, frame, event, argument):
        owner = self.owners.get(frame.f_code)
        if owner is None:
            return
        try:
            if event == "call":
                self.failed_frames.discard(id(frame))
            if owner["role"] == "io":
                if event == "return":
                    self._io_return(frame, argument)
                elif event == "c_call":
                    self._before_io_c_call(frame, argument)
                elif event in {"c_return", "c_exception"} and argument is self.original_os["replace"]:
                    receipt = self.pending_renames.get(id(frame))
                    if receipt is not None:
                        receipt["originalRenameCSettlement"] = {"status": "returned" if event == "c_return" else "raised",
                            "atNs": str(time.monotonic_ns()), "sourceStack": self._stack(frame),
                            "returnValueAvailableAtThisProfileEvent": False}
            elif owner["role"] == "write-all" and event == "return" and id(frame) not in self.failed_frames:
                state = self.descriptors.get(frame.f_locals.get("descriptor"))
                if state is not None:
                    state["fullWrite"] = self._event(self.original_io, "original-full-write-return",
                        descriptor=frame.f_locals["descriptor"], returned=self.encode(argument), sourceStack=self._stack(frame))
                    if state["role"] == "atomic":
                        state["expectedBytes"] = bytes(frame.f_locals["content"]).hex()
            elif owner["role"] == "dreams":
                self._dreams(frame, event, argument)
            elif (owner["role"] == "source-read" and event == "return" and argument is not None
                  and getattr(argument, "source", None) == "memory" and self._eligible(Path(argument.path))):
                self._event(self.source_reads, "original-index-source-read-return", scope=deepcopy(self.scope()),
                    sourceCode=deepcopy(owner["code"]), arguments=self.encode(frame.f_locals), returned=self.encode(argument))
        except BaseException as error:
            self._failure(error, frame)

    def trace(self, frame, event, argument):
        owner = self.owners.get(frame.f_code)
        if owner is not None and owner["role"] in {"io", "write-all"} and event == "exception":
            self.failed_frames.add(id(frame))
            if owner["role"] == "io":
                error = argument[1]
                self._event(self.original_io, "original-source-io-exception",
                    arguments=self.encode(tuple(bytes(item) if isinstance(item, memoryview) else item
                                                for item in frame.f_locals.get("args", ()))),
                    error={"module": type(error).__module__, "name": type(error).__qualname__, "message": str(error)},
                    sourceStack=self._stack(frame), scope=deepcopy(self.scope()))
                receipt = self.pending_renames.pop(id(frame), None)
                if receipt is not None:
                    receipt["originalCommit"] = {"witness": "original-os-replace-raised",
                        "error": {"module": type(error).__module__, "name": type(error).__qualname__, "message": str(error)},
                        "atNs": str(time.monotonic_ns())}

