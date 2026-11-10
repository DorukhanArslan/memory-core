"""Owned Linux read-lease fixture for a real pending memory-target write-open.

This process neither creates nor changes the target. Its parent supplies an empty,
single-link daily file in its own fixture workspace. A genuine kernel SIGIO is
the only BREAK receipt. VERIFY reacquires a real read lease after cancellation;
it cannot succeed while another process still holds a writable descriptor.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import signal
import stat
import sys
import time
from typing import Any


class LeaseFixture:
    """One descriptor, one owned path and bounded JSONL control messages."""

    def __init__(self, workspace: Path, relative_path: str, owner_pid: int) -> None:
        lexical = workspace.absolute()
        if (not workspace.is_absolute() or lexical != lexical.resolve(strict=True)
                or len(str(lexical).encode()) > 1024 or not lexical.is_dir()):
            raise ValueError("The lease workspace must be an existing canonical absolute directory")
        relative = PurePosixPath(relative_path)
        if (relative.is_absolute() or relative.as_posix() != relative_path
                or not re.fullmatch(r"memory/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md", relative_path)):
            raise ValueError("The lease target must be one declared daily memory file")
        if owner_pid <= 0 or os.getppid() != owner_pid:
            raise ValueError("The lease controller is not the declared actual parent process")
        self.path = lexical.joinpath(*relative.parts)
        if self.path != self.path.resolve(strict=True):
            raise ValueError("The lease target and its parents must not be symlink aliases")
        before = self.path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != 0:
            raise ValueError("The lease input must be an empty single-link regular file")
        self.fd: int | None = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(self.fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            os.close(self.fd)
            self.fd = None
            raise ValueError("The lease target changed during descriptor admission")
        self.identity = opened.st_dev, opened.st_ino
        self.sequence = 0
        self.held = False
        self.had_error = False
        self.request_ids: set[str] = set()

    def emit(self, event: str, **values: Any) -> None:
        # JSON lines remain atomic even if SIGIO arrives while another receipt is
        # emitted; signal handlers never re-enter Python's buffered stdout owner.
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGIO})
        try:
            receipt = {"kind": "host-turn-barrier-boundaries-lease", "sequence": self.sequence,
                       "event": event, "atNs": time.monotonic_ns(), "pid": os.getpid(),
                       "ppid": os.getppid(), **values}
            self.sequence += 1
            wire = (json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
            if len(wire) > 4096:
                raise ValueError("The lease receipt exceeds its atomic transport bound")
            if os.write(sys.stdout.fileno(), wire) != len(wire):
                raise OSError("The lease receipt was not written completely")
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)

    def target(self) -> dict[str, Any]:
        if self.fd is None:
            raise RuntimeError("The lease descriptor is already closed")
        current = self.path.lstat()
        opened = os.fstat(self.fd)
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                or (current.st_dev, current.st_ino) != self.identity
                or (opened.st_dev, opened.st_ino) != self.identity):
            raise ValueError("The bound lease target changed identity")
        if opened.st_size > 64 * 1024:
            raise ValueError("The lease target exceeds the bounded fixture observation size")
        data = os.pread(self.fd, opened.st_size + 1, 0)
        if len(data) != opened.st_size:
            raise ValueError("The bound lease target changed while it was observed")
        return {"path": str(self.path), "dev": opened.st_dev, "ino": opened.st_ino,
                "nlink": opened.st_nlink, "size": opened.st_size,
                "sha256": hashlib.sha256(data).hexdigest()}

    def arm(self) -> None:
        if self.fd is None:
            raise RuntimeError("The lease descriptor is closed")
        fcntl.fcntl(self.fd, fcntl.F_SETOWN, os.getpid())
        signal.signal(signal.SIGIO, self.on_break)
        fcntl.fcntl(self.fd, fcntl.F_SETLEASE, fcntl.F_RDLCK)
        self.held = True
        executable = Path(sys.executable).resolve(strict=True)
        script = Path(__file__).resolve(strict=True)
        self.emit("ARMED", target=self.target(), held=True,
                  leaseType=fcntl.fcntl(self.fd, fcntl.F_GETLEASE),
                  executable={"path": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                              "version": platform.python_version()},
                  script={"path": str(script), "sha256": hashlib.sha256(script.read_bytes()).hexdigest()},
                  kernel={"system": platform.system(), "release": platform.release()})

    def on_break(self, signum: int, _frame: Any) -> None:
        if self.fd is None:
            return
        self.emit("BREAK", signal=signum, target=self.target(), held=self.held,
                  leaseType=fcntl.fcntl(self.fd, fcntl.F_GETLEASE))

    def command(self, message: Any) -> bool:
        if (not isinstance(message, dict) or set(message) != {"command", "id"}
                or not isinstance(message["command"], str)
                or not isinstance(message["id"], str) or not message["id"]
                or len(message["id"]) > 128 or message["id"] in self.request_ids):
            raise ValueError("The lease command requires a unique bounded request identity")
        request_id, name = message["id"], message["command"]
        self.request_ids.add(request_id)
        if len(self.request_ids) > 16:
            raise ValueError("The lease command count exceeds the owned protocol bound")
        if name == "STOP":
            self.close(reason="STOP", request_id=request_id)
            return False
        if self.fd is None:
            raise RuntimeError("The lease descriptor is closed")
        if name == "RELEASE":
            if not self.held:
                raise ValueError("No held lease can be released a second time")
            observed = self.target()
            fcntl.fcntl(self.fd, fcntl.F_SETLEASE, fcntl.F_UNLCK)
            self.held = False
            self.emit("RELEASED", id=request_id, target=observed, held=False,
                      leaseType=fcntl.fcntl(self.fd, fcntl.F_GETLEASE))
        elif name in {"VERIFY", "REACQUIRE"}:
            if self.held:
                raise ValueError("A held lease cannot be reacquired")
            observed = self.target()
            fcntl.fcntl(self.fd, fcntl.F_SETLEASE, fcntl.F_RDLCK)
            self.held = True
            self.emit("VERIFIED", id=request_id, target=observed, held=True,
                      leaseType=fcntl.fcntl(self.fd, fcntl.F_GETLEASE))
        else:
            raise ValueError("Unknown lease command")
        return True

    def close(self, *, reason: str, request_id: str | None = None) -> None:
        if self.fd is None:
            return
        observed, held = self.target(), self.held
        os.close(self.fd)
        self.fd, self.held = None, False
        self.emit("CLOSED", id=request_id, reason=reason, target=observed,
                  releasedByClose=held, held=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--relative-path", required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    args = parser.parse_args()
    fixture = LeaseFixture(args.workspace, args.relative_path, args.owner_pid)
    try:
        fixture.arm()
        for wire in iter(lambda: sys.stdin.buffer.readline(8193), b""):
            try:
                if len(wire) > 8192 or not wire.endswith(b"\n"):
                    raise ValueError("The lease command exceeds its bounded JSON line")
                if not fixture.command(json.loads(wire)):
                    return 2 if fixture.had_error else 0
            except (OSError, ValueError, RuntimeError) as error:
                fixture.had_error = True
                fixture.emit("ERROR", error={"name": type(error).__name__, "message": str(error),
                                             "errno": getattr(error, "errno", None)})
        fixture.had_error = True
        fixture.close(reason="stdin-eof-before-STOP")
        return 2
    finally:
        fixture.close(reason="process-finally")


if __name__ == "__main__":
    raise SystemExit(main())
