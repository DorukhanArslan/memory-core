"""Actual flush-target authority and filesystem failure comparisons.

Only the public Python helper performs target preparation. The transport owns
temporary files, records filesystem API calls and supplies deterministic authority/failure
inputs. Symlinks, hard links and non-regular files remain a declared stricter
Python policy outside this admitted-file fixture domain. No complete plan/target
acceptance point is credited by these comparisons.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import errno
import inspect
import os
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import patch


TARGET = "memory/2026-09-25.md"
EXISTING_HEX = b"- kept\n\x00\xff\xf0\x9f\x98\x80".hex()
_VALIDATION_MESSAGES = {
    "Invalid memory flush target path",
    "Memory flush target path must stay inside the workspace",
}
_FAILURE_CODES = {"mkdir": "EACCES", "open": "EIO", "close": "EIO"}


def build_flush_target_cases() -> list[dict[str, Any]]:
    """Bounded target-preparation cases; every native decision uses its owner."""
    cases: list[dict[str, Any]] = []

    def add(name: str, **arguments: Any) -> None:
        cases.append({
            "id": f"flush-target-boundary-{name}",
            "requirement": "flush.plan-target", "operation": "flush-target",
            "input": {"relativePath": TARGET, **arguments}, "covers": [],
            "driverScope": "actual target helper authority checks and owned filesystem effects",
            "declaredDeviation": (
                "Python additionally refuses symlinks, hard links and non-regular files; "
                "these fixtures use admitted regular files and owned directories."
            ),
            "normalizationPolicy": (
                "Preserve callback order, mkdir/open/close events, real descriptor closure, "
                "directories and exact file bytes. Normalize only declared injected authority "
                "errors, the two path-validation messages, and injected filesystem API errno "
                "code, operation "
                "and owned relative path. Close failure is injected after real handle release. "
                "Unexpected errors retain diagnostic fields with only owned temp roots replaced. "
                "A legacy helper lacking assert_current is invoked normally and reports zero checks."
            ),
        })

    add("new")
    add("existing-bytes", existingHex=EXISTING_HEX)
    add("trimmed-path", relativePath=f"  {TARGET}\t")
    for check in (1, 2, 3):
        add(f"revoke-{check}-new", rejectAt=check)
        add(f"revoke-{check}-existing", rejectAt=check, existingHex=EXISTING_HEX)
    add("cancel-after-open-existing", rejectAt=3, authorityError="cancelled",
        existingHex=EXISTING_HEX)
    for operation in _FAILURE_CODES:
        add(f"{operation}-failure-new", failOperation=operation)
        add(f"{operation}-failure-existing", failOperation=operation, existingHex=EXISTING_HEX)
    add("close-failure-overrides-revocation", rejectAt=3, failOperation="close",
        existingHex=EXISTING_HEX)
    for name, relative in (("blank", ""), ("whitespace", " \t"),
                           ("absolute", "@workspace/memory/x.md"),
                           ("parent", "../x.md"), ("root", ".")):
        add(f"invalid-{name}", relativePath=relative, rejectAt=1)
    return cases


def _snapshot(root: Path) -> dict[str, Any]:
    entries = sorted(root.rglob("*"))
    return {
        "directories": [entry.relative_to(root).as_posix() for entry in entries if entry.is_dir()],
        "files": {entry.relative_to(root).as_posix(): {"hex": entry.read_bytes().hex()}
                  for entry in entries if entry.is_file()},
    }


def _closed(descriptor: int) -> bool:
    try:
        os.fstat(descriptor)
    except OSError as error:
        if error.errno == errno.EBADF:
            return True
        raise
    return False


def run_flush_target(arguments: dict[str, Any]) -> dict[str, Any]:
    """Call the public helper, observing its actual owned filesystem operations.

    ``Path.mkdir`` and native ``fs.promises.mkdir`` are corresponding operation
    boundaries. Injecting below ``Path.mkdir`` would let its ``exist_ok`` handling
    swallow an injected error for an existing directory, unlike the native
    injection point. Open/close still delegate to real OS descriptor operations.
    """
    from memory_core.memory_flush import ensure_memory_flush_target_file

    fail_operation = arguments.get("failOperation")
    if fail_operation is not None and fail_operation not in _FAILURE_CODES:
        raise ValueError("Unsupported flush target failure operation")
    reject_at = arguments.get("rejectAt")
    if reject_at is not None and reject_at not in (1, 2, 3):
        raise ValueError("Unsupported flush target authority check")
    authority_kind = arguments.get("authorityError", "revoked")
    if authority_kind not in ("revoked", "cancelled"):
        raise ValueError("Unsupported flush target authority error")

    with tempfile.TemporaryDirectory(prefix="memory-flush-target-") as temporary:
        root = Path(temporary) / "workspace"
        root.mkdir()
        relative = arguments["relativePath"].replace("@workspace", str(root))
        # All seeded paths come from this adapter's fixed admitted-file domain.
        target = root / TARGET
        parent = target.parent
        if "existingHex" in arguments:
            parent.mkdir()
            target.write_bytes(bytes.fromhex(arguments["existingHex"]))
        events: list[str] = []
        descriptors: list[dict[str, Any]] = []
        checks = 0
        authority_error: RuntimeError | asyncio.CancelledError | None = None
        injected_error: OSError | None = None
        original_mkdir, original_open, original_close = Path.mkdir, os.open, os.close

        def failure(operation: str) -> None:
            nonlocal injected_error
            if fail_operation == operation:
                filename = parent if operation == "mkdir" else target
                injected_error = OSError(getattr(errno, _FAILURE_CODES[operation]),
                                         f"Injected {operation} failure", str(filename))
                raise injected_error

        def assert_current() -> None:
            nonlocal checks, authority_error
            checks += 1
            events.append(f"assert:{checks}")
            if checks == reject_at:
                error_type = asyncio.CancelledError if authority_kind == "cancelled" else RuntimeError
                authority_error = error_type(f"Flush target {authority_kind} at check {checks}")
                raise authority_error

        def mkdir(filename: Any, *args: Any, **kwargs: Any) -> None:
            if Path(filename) == parent:
                events.append("mkdir:memory")
                failure("mkdir")
            return original_mkdir(filename, *args, **kwargs)

        def open_file(filename: Any, *args: Any, **kwargs: Any) -> int:
            observed = Path(filename) == target
            if observed:
                events.append(f"open:{TARGET}")
                failure("open")
            descriptor = original_open(filename, *args, **kwargs)
            if observed:
                descriptors.append({"fd": descriptor, "closeCalls": 0})
            return descriptor

        def close_file(descriptor: int) -> None:
            observed = next((entry for entry in descriptors if entry["fd"] == descriptor), None)
            if observed is not None:
                observed["closeCalls"] += 1
                events.append(f"close:{TARGET}")
            original_close(descriptor)
            if observed is not None:
                failure("close")

        def normalize(error: BaseException) -> dict[str, Any]:
            if error is authority_error:
                return {"kind": "authority", "reason": authority_kind, "check": checks,
                        "message": str(error)}
            if error is injected_error:
                return {"kind": "os", "code": _FAILURE_CODES[fail_operation],
                        "operation": fail_operation,
                        "path": "memory" if fail_operation == "mkdir" else TARGET}
            if isinstance(error, ValueError) and str(error) in _VALIDATION_MESSAGES:
                return {"kind": "validation", "message": str(error)}
            diagnostic: dict[str, Any] = {
                "kind": "unexpected", "name": type(error).__name__,
                "message": str(error).replace(str(root), "@workspace"),
            }
            if isinstance(error, OSError):
                diagnostic["errno"] = error.errno
                diagnostic["filename"] = str(error.filename).replace(str(root), "@workspace")
            return diagnostic

        callback_supported = "assert_current" in inspect.signature(
            ensure_memory_flush_target_file).parameters
        result: dict[str, Any]
        try:
            with ExitStack() as patches:
                patches.enter_context(patch.object(Path, "mkdir", mkdir))
                patches.enter_context(patch("os.open", open_file))
                patches.enter_context(patch("os.close", close_file))
                try:
                    if callback_supported:
                        ensure_memory_flush_target_file(root, relative, assert_current=assert_current)
                    else:
                        # Execute the actual legacy implementation, exposing its missing checks.
                        ensure_memory_flush_target_file(root, relative)
                    result = {"ok": True}
                except (Exception, asyncio.CancelledError) as error:
                    result = {"ok": False, "error": normalize(error)}
            result.update({
                "authorityCallbackSupported": callback_supported, "checks": checks, "events": events,
                "descriptors": [{"opened": True, "closeCalls": entry["closeCalls"],
                                 "closed": _closed(entry["fd"])} for entry in descriptors],
                **_snapshot(root),
            })
            return result
        finally:
            # Report leaks before fixture cleanup; cleanup never turns a leak into a match.
            for entry in descriptors:
                if not _closed(entry["fd"]):
                    original_close(entry["fd"])
