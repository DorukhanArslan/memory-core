"""Secure memory-file reads (OpenClaw ``readMemoryFile`` and the fs-safe subset it relies on).

Ports, at OpenClaw v2026.9.6:

- ``packages/memory-host-sdk/src/host/read-file.ts`` ``readMemoryFile`` for workspace reads:
  the memory-path gate (``MEMORY_PATH_NOT_ALLOWED``, 67f55de5553 #144669), the fs-safe root
  resolve, ``statRegularFile``, the read and its ``not_found`` outcomes (a file that vanished or
  changed identity during the read is ``not_found``);
- ``read-file-shared.ts`` ``buildMemoryReadResult`` / ``buildMemoryReadResultFromSlice``:
  ``status: "ok"`` (35e0bc22ead #125979), the dropped trailing-newline sentinel (1b6ad8da8f8
  #115722), the greedy line fit (a7f2413c4b0 #140634) with UTF-16 lengths and the pair-safe cut
  (``truncateUtf16Safe``, c3d567db95d #102478), ``resolveIntegerOption`` (964c8c84c18 #122299);
- ``read-retry.ts`` ``retryTransientMemoryRead``;
- ``@openclaw/fs-safe`` 0.18.1 (the built package ``readMemoryFile`` reads through):
  ``resolveRootContext`` (root-context.js), ``RootHandle.resolve`` (root-impl.js:211-214, a
  final symlink is kept and the canonical path returned) over ``traverseRootPath``
  (root-path.js), ``statRegularFile`` and ``readRegularFile`` (regular-file.js).

Texts, codes and limits come from the generated ``memory_core.tools._memory_tool_constants``.

Not ported: ``extraPaths`` (memory-core has no extra memory roots), Windows path aliases, and
fs-safe's ``shortPath`` home shortening: memory-core's core reads no environment, so the paths in
refusal messages are shown in full where upstream writes ``~`` for the home directory
(documented deviation). Operating-system errors keep Python's message text and carry the errno
name as their code (Node's ``code``); upstream shows Node's message (``EACCES: permission
denied, open '<path>'``), Python shows ``[Errno 13] Permission denied: '<path>'`` (documented
deviation, decision D6 of docs/upstream_port_v2026_9_6.md). The ``default_lines`` option is
upstream's ``defaultLines``, but the ``memory_get`` tool passes
``MemoryConfig.memory_get_default_lines`` where the tag's ``readAgentMemoryFile`` passes nothing
(read-file.ts:211-218): the same 120 lines by default, a host-set window otherwise (documented
deviation).
"""

from __future__ import annotations

import errno
import math
import os
import re
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from memory_core.bootstrap._js import js_trim, truncate_utf16_safe, utf16_len
from memory_core.tools.common import extract_error_code
from memory_core.tools._memory_tool_constants import (
    DEFAULT_MEMORY_READ_LINES,
    DEFAULT_MEMORY_READ_MAX_CHARS,
    FS_SAFE_FILE_CHANGED_TEMPLATE,
    FS_SAFE_FILE_NOT_FOUND_TEMPLATE,
    FS_SAFE_IDENTITY_MISMATCH_ERROR,
    FS_SAFE_INVALID_PATH_CODE,
    FS_SAFE_NOT_DIRECTORY_TEMPLATE,
    FS_SAFE_NOT_FOUND_CODES,
    FS_SAFE_NOT_REGULAR_FILE_ERROR,
    FS_SAFE_NOT_REGULAR_READ_TEMPLATE,
    FS_SAFE_OUTSIDE_WORKSPACE_CODE,
    FS_SAFE_OUTSIDE_WORKSPACE_ERROR,
    FS_SAFE_PATH_MISMATCH_CODE,
    FS_SAFE_PATH_TOO_LONG_ERROR,
    FS_SAFE_ROOT_BOUNDARY_LABEL,
    FS_SAFE_ROOT_NOT_DIRECTORY_ERROR,
    FS_SAFE_ROOT_NOT_FOUND_CODE,
    FS_SAFE_ROOT_NOT_FOUND_ERROR,
    FS_SAFE_SYMLINK_CODE,
    FS_SAFE_SYMLINK_ESCAPE_TEMPLATE,
    FS_SAFE_SYMLINK_OPEN_CODES,
    FS_SAFE_SYMLINK_UNRESOLVED_ERROR,
    FS_SAFE_UNSAFE_DETAIL_PATTERN,
    MEMORY_FILE_MISSING_CODES,
    MEMORY_PATH_NOT_ALLOWED_CODE,
    MEMORY_PATH_NOT_ALLOWED_ERROR,
    MEMORY_PATH_REQUIRED_ERROR,
    MEMORY_READ_CONTINUE_TEMPLATE,
    MEMORY_READ_FALLBACK_HINT,
    MEMORY_READ_MAX_CHARS_NOTICE,
    TRANSIENT_MEMORY_READ_ATTEMPTS,
    TRANSIENT_MEMORY_READ_CODES,
    TRANSIENT_MEMORY_READ_MAX_DELAY_MS,
    TRANSIENT_MEMORY_READ_MESSAGE_FLAGS,
    TRANSIENT_MEMORY_READ_MESSAGE_PATTERN,
    TRANSIENT_MEMORY_READ_MIN_DELAY_MS,
)
from memory_core.workspace import is_memory_path

_T = TypeVar("_T")

# error-detail.js UNSAFE_ERROR_DETAIL_CHARACTERS (flags "gu": every match, code points).
_UNSAFE_DETAIL_RE = re.compile(FS_SAFE_UNSAFE_DETAIL_PATTERN)
# read-retry.ts TRANSIENT_MEMORY_READ_MESSAGE (flag "i").
_TRANSIENT_MESSAGE_RE = re.compile(
    TRANSIENT_MEMORY_READ_MESSAGE_PATTERN,
    re.IGNORECASE if "i" in TRANSIENT_MEMORY_READ_MESSAGE_FLAGS else 0,
)
_TRANSIENT_ERRNOS = frozenset(
    value for value in (getattr(errno, name, None) for name in TRANSIENT_MEMORY_READ_CODES) if value
)
# resolveReadOpenFlags (read-open-flags.js): no symlink follow, non-blocking on POSIX.
_READ_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


class MemoryReadError(Exception):
    """A memory read failure carrying upstream's error ``code`` when it has one.

    ``code`` is an fs-safe ``FsSafeError`` code (``outside-workspace``, ``invalid-path``,
    ``path-mismatch``, ``not-found``, ``symlink``), ``MEMORY_PATH_NOT_ALLOWED``, a Node-style
    errno name (``ENOTDIR``, ``ENOENT``), or ``None`` for upstream's plain ``Error`` refusals
    (``path required``, ``path must be a regular file``). The fs-safe wrappers keep the error
    they wrap as ``__cause__``, which ``format_error_message`` appends as `` | <cause>``.
    """

    def __init__(
        self, message: str, *, code: str | None = None, cause: BaseException | None = None
    ):
        super().__init__(message)
        self.code = code
        if cause is not None:
            self.__cause__ = cause


def is_file_missing_error(error: BaseException) -> bool:
    """``isFileMissingError`` (packages/memory-host-sdk/src/host/fs-utils.ts:15-27)."""
    return extract_error_code(error) in MEMORY_FILE_MISSING_CODES


def _is_not_found_path_error(error: BaseException) -> bool:
    # fs-safe path.js isNotFoundPathError: a Node error whose code is ENOENT or ENOTDIR.
    return isinstance(error, OSError | MemoryReadError) and extract_error_code(error) in (
        FS_SAFE_NOT_FOUND_CODES
    )


def format_error_detail(value: str) -> str:
    """fs-safe error-detail.js ``formatErrorDetail``: control and line-separator characters as
    ``\\uXXXX`` escapes."""
    return _UNSAFE_DETAIL_RE.sub(lambda match: f"\\u{ord(match.group(0)):04x}", value)


def short_path(value: str) -> str:
    """fs-safe ``shortPath`` without the home shortening (the core reads no environment)."""
    return format_error_detail(value)


def _memory_path_not_allowed() -> MemoryReadError:
    # read-file.ts:35-39 memoryPathNotAllowed.
    return MemoryReadError(MEMORY_PATH_NOT_ALLOWED_ERROR, code=MEMORY_PATH_NOT_ALLOWED_CODE)


def _resolve_root(workspace_dir: Path) -> str:
    # root-context.js resolveRootContext: realpath, then a directory check.
    try:
        root_real = os.path.realpath(workspace_dir, strict=True)
        root_stat = os.stat(root_real)
    except OSError as error:
        if _is_not_found_path_error(error):
            raise MemoryReadError(FS_SAFE_ROOT_NOT_FOUND_ERROR, code=FS_SAFE_ROOT_NOT_FOUND_CODE)
        raise
    if not stat.S_ISDIR(root_stat.st_mode):
        raise MemoryReadError(FS_SAFE_ROOT_NOT_DIRECTORY_ERROR, code=FS_SAFE_INVALID_PATH_CODE)
    return root_real


def _is_inside(root: str, candidate: str) -> bool:
    # root-boundary.js admitPathInsideRoot on POSIX: the root itself or a path below it.
    root_with_sep = root if root.endswith(os.sep) else root + os.sep
    return candidate == root or candidate.startswith(root_with_sep)


def _resolve_existing_ancestor(target: str) -> str:
    # root-path-existing.js resolveExistingAncestor: canonicalize the deepest existing ancestor.
    normalized = os.path.normpath(target)
    cursor = normalized
    filesystem_root = os.path.abspath(os.sep)
    while cursor != filesystem_root and not os.path.exists(cursor):
        cursor = os.path.dirname(cursor)
    if not os.path.exists(cursor):
        return normalized
    try:
        resolved_ancestor = os.path.realpath(cursor, strict=True)
    except OSError:
        return normalized
    if cursor == normalized:
        return resolved_ancestor
    suffix = normalized[len(cursor) :].lstrip(os.sep)
    return os.path.normpath(os.path.join(resolved_ancestor, suffix))


def _resolve_symlink_hop(symlink_path: str) -> str:
    # root-path-existing.js resolveSymlinkHopPath.
    try:
        return os.path.realpath(symlink_path, strict=True)
    except OSError as error:
        if extract_error_code(error) in FS_SAFE_SYMLINK_OPEN_CODES:
            raise MemoryReadError(
                FS_SAFE_SYMLINK_UNRESOLVED_ERROR, code=FS_SAFE_SYMLINK_CODE, cause=error
            ) from error
        if not _is_not_found_path_error(error):
            raise
        target = os.readlink(symlink_path)
        link_dir = os.path.dirname(symlink_path)
        return _resolve_existing_ancestor(os.path.join(link_dir, target))


def _not_a_directory(path: str) -> MemoryReadError:
    # root-path.js:242-246 assertDirectoryBeforeMoreSegments.
    return MemoryReadError(
        format_error_detail(FS_SAFE_NOT_DIRECTORY_TEMPLATE.format(path=path)), code="ENOTDIR"
    )


def _traverse_root_path(root_real: str, rel_path: str) -> str:
    """root-path.js ``traverseRootPath`` with ``allowFinalSymlink`` (RootHandle.resolve).

    Walks ``rel_path`` from the root realpath: a missing component ends the checks (the rest
    is missing too), a non-directory component before the last one is ``ENOTDIR``, the final
    component may be a symlink (kept), and every other symlink is followed and must stay inside
    the root. Returns the canonical path.
    """
    segments = [segment for segment in rel_path.split("/") if segment]
    lexical = canonical = root_real
    missing = False
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if segment == ".":
            continue
        if segment == "..":
            lexical = os.path.dirname(lexical)
            canonical = os.path.dirname(canonical)
            continue
        lexical = os.path.join(lexical, segment)
        if missing:
            canonical = os.path.join(canonical, segment)
            continue
        try:
            entry = os.lstat(lexical)
        except OSError as error:
            if not _is_not_found_path_error(error):
                raise
            canonical = os.path.join(canonical, segment)
            missing = True
            continue
        if not stat.S_ISLNK(entry.st_mode):
            if not is_last and not stat.S_ISDIR(entry.st_mode):
                raise _not_a_directory(lexical)
            canonical = os.path.join(canonical, segment)
            continue
        if is_last:
            # allowFinalSymlink: the link itself is the target; statRegularFile refuses it.
            canonical = os.path.join(canonical, segment)
            break
        link_canonical = _resolve_symlink_hop(lexical)
        if not _is_inside(root_real, link_canonical):
            # root-path-errors.js:21 symlinkEscapeError.
            raise MemoryReadError(
                FS_SAFE_SYMLINK_ESCAPE_TEMPLATE.format(
                    boundary=FS_SAFE_ROOT_BOUNDARY_LABEL,
                    root=short_path(root_real),
                    path=short_path(lexical),
                )
            )
        canonical = lexical = link_canonical
        # assertResolvedLinkDirectory: a followed link before the last segment is a directory.
        if not stat.S_ISDIR(os.stat(link_canonical).st_mode):
            raise _not_a_directory(link_canonical)
    return canonical


def resolve_in_workspace_root(root_real: str, rel_path: str) -> str:
    """``resolvePathInRoot`` (root-context.js) through ``RootHandle.resolve``.

    fs-safe's own ``symlink`` errors pass through; ``ENAMETOOLONG`` becomes ``invalid-path`` /
    ``relative path is too long``; any other failure becomes ``outside-workspace`` / ``file is
    outside workspace root``, with the original error as the cause.
    """
    try:
        return _traverse_root_path(root_real, rel_path)
    except MemoryReadError as error:
        if error.code == FS_SAFE_SYMLINK_CODE:
            raise
        raise MemoryReadError(
            FS_SAFE_OUTSIDE_WORKSPACE_ERROR, code=FS_SAFE_OUTSIDE_WORKSPACE_CODE, cause=error
        ) from error
    except Exception as error:
        if extract_error_code(error) == "ENAMETOOLONG":
            raise MemoryReadError(
                FS_SAFE_PATH_TOO_LONG_ERROR, code=FS_SAFE_INVALID_PATH_CODE, cause=error
            ) from error
        raise MemoryReadError(
            FS_SAFE_OUTSIDE_WORKSPACE_ERROR, code=FS_SAFE_OUTSIDE_WORKSPACE_CODE, cause=error
        ) from error


def stat_regular_file(path: str) -> os.stat_result | None:
    """fs-safe ``statRegularFile``: ``None`` when missing; a symlink or non-regular file raises
    ``path must be a regular file``."""
    try:
        entry = os.lstat(path)
    except OSError as error:
        if _is_not_found_path_error(error):
            return None
        raise
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
        raise MemoryReadError(FS_SAFE_NOT_REGULAR_FILE_ERROR)
    return entry


def _identity_mismatch() -> MemoryReadError:
    # strict-file-identity.js identityMismatch.
    return MemoryReadError(FS_SAFE_IDENTITY_MISMATCH_ERROR, code=FS_SAFE_PATH_MISMATCH_CODE)


def _file_changed(path: str) -> MemoryReadError:
    return MemoryReadError(
        FS_SAFE_FILE_CHANGED_TEMPLATE.format(path=path), code=FS_SAFE_PATH_MISMATCH_CODE
    )


def read_regular_file(path: str) -> bytes:
    """fs-safe ``readRegularFile``: lstat, open without following links, and read the bytes only
    when the opened file is the same regular file as before the open and still at ``path``."""
    try:
        before = os.lstat(path)
    except OSError as error:
        if _is_not_found_path_error(error):
            raise MemoryReadError(
                FS_SAFE_FILE_NOT_FOUND_TEMPLATE.format(path=path), code="ENOENT"
            ) from error
        raise
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise MemoryReadError(FS_SAFE_NOT_REGULAR_FILE_ERROR)
    try:
        descriptor = os.open(path, _READ_OPEN_FLAGS)
    except OSError as error:
        if _is_not_found_path_error(error):
            raise _file_changed(path) from error
        raise
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise MemoryReadError(FS_SAFE_NOT_REGULAR_READ_TEMPLATE.format(path=path))
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise _identity_mismatch()
        try:
            current = os.lstat(path)
        except OSError as error:
            if _is_not_found_path_error(error):
                raise _file_changed(path) from error
            raise
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise MemoryReadError(FS_SAFE_NOT_REGULAR_READ_TEMPLATE.format(path=path))
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise _identity_mismatch()
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def is_transient_memory_read_error(error: BaseException) -> bool:
    """read-retry.ts ``isTransientMemoryReadError``: EAGAIN, EWOULDBLOCK or EDEADLK (by code or
    errno), or libuv's ``Unknown system error -11`` text."""
    if extract_error_code(error) in TRANSIENT_MEMORY_READ_CODES:
        return True
    if isinstance(error, OSError) and error.errno in _TRANSIENT_ERRNOS:
        return True
    return _TRANSIENT_MESSAGE_RE.search(str(error)) is not None


def retry_transient_memory_read(
    read: Callable[[], _T], *, sleep: Callable[[float], Any] = time.sleep
) -> _T:
    """read-retry.ts ``retryTransientMemoryRead``: up to 3 attempts, 25 ms then 50 ms apart
    (``retryAsync`` with jitter 0: ``min(max(min * 2^(attempt-1), min), max)``)."""
    attempt = 1
    while True:
        try:
            return read()
        except Exception as error:
            if attempt >= TRANSIENT_MEMORY_READ_ATTEMPTS:
                raise
            if not is_transient_memory_read_error(error):
                raise
            minimum = TRANSIENT_MEMORY_READ_MIN_DELAY_MS
            delay_ms = min(
                max(minimum * 2 ** (attempt - 1), minimum), TRANSIENT_MEMORY_READ_MAX_DELAY_MS
            )
            sleep(delay_ms / 1000)
            attempt += 1


def resolve_integer_option(value: object, fallback: int, *, minimum: int | None = None) -> int:
    """normalization-core ``resolveIntegerOption``: a finite number, else ``fallback``; floored
    and bounded below by ``minimum``."""
    finite = (
        isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
    )
    floored = math.floor(value if finite else fallback)  # type: ignore[arg-type]
    return floored if minimum is None else max(minimum, floored)


def _continuation_notice(*, next_from: int | None, suggest_read_fallback: bool) -> str:
    # read-file-shared.ts:15-27 buildContinuationNotice.
    base = (
        MEMORY_READ_CONTINUE_TEMPLATE.format(next_from=next_from)
        if next_from is not None
        else MEMORY_READ_MAX_CHARS_NOTICE
    )
    fallback = MEMORY_READ_FALLBACK_HINT if suggest_read_fallback else ""
    return f"\n\n{base[:-1]}{fallback}]"


def _fit_lines_to_char_budget(lines: list[str], max_chars: int) -> tuple[str, int, bool]:
    # read-file-shared.ts:30-53 fitLinesToCharBudget (a7f2413c4b0 #140634): greedy, an oversized
    # first line is kept and cut pair-safe; lengths are UTF-16 code units.
    included = 0
    chars = 0
    for line in lines:
        next_chars = chars + utf16_len(line) + (1 if included > 0 else 0)
        if included > 0 and next_chars > max_chars:
            break
        included += 1
        chars = next_chars
    text = truncate_utf16_safe("\n".join(lines[:included]), max_chars)
    return text, included, chars > max_chars


def build_memory_read_result_from_slice(
    *,
    selected_lines: list[str],
    rel_path: str,
    start_line: int,
    more_source_lines_remain: bool = False,
    max_chars: int | None = None,
    suggest_read_fallback: bool = False,
) -> dict:
    """read-file-shared.ts:56-94 ``buildMemoryReadResultFromSlice``."""
    start = resolve_integer_option(start_line, 1, minimum=1)
    text, included, hard_truncated = _fit_lines_to_char_budget(
        selected_lines,
        resolve_integer_option(max_chars, DEFAULT_MEMORY_READ_MAX_CHARS, minimum=1),
    )
    char_cap_truncated = hard_truncated or included < len(selected_lines)
    next_from = (
        start + included
        if not hard_truncated and (more_source_lines_remain or included < len(selected_lines))
        else None
    )
    truncated = char_cap_truncated or more_source_lines_remain
    if truncated and (text or hard_truncated):
        text = text + _continuation_notice(
            next_from=next_from, suggest_read_fallback=hard_truncated and suggest_read_fallback
        )
    result: dict[str, Any] = {
        "status": "ok",
        "text": text,
        "path": rel_path,
        "from": start,
        "lines": included,
    }
    if truncated:
        result["truncated"] = True
    if next_from is not None:
        result["nextFrom"] = next_from
    return result


def build_memory_read_result(
    *,
    content: str,
    rel_path: str,
    from_line: int | None = None,
    lines: int | None = None,
    default_lines: int | None = None,
    max_chars: int | None = None,
    suggest_read_fallback: bool = False,
) -> dict:
    """read-file-shared.ts:97-128 ``buildMemoryReadResult``: the file's lines without the
    sentinel a terminal newline leaves, then the requested window."""
    file_lines = content.split("\n")
    if file_lines[-1] == "":
        file_lines.pop()
    start = resolve_integer_option(from_line, 1, minimum=1)
    requested = resolve_integer_option(
        lines if lines is not None else default_lines, DEFAULT_MEMORY_READ_LINES, minimum=1
    )
    selected = file_lines[start - 1 : start - 1 + requested]
    return build_memory_read_result_from_slice(
        selected_lines=selected,
        rel_path=rel_path,
        start_line=start,
        more_source_lines_remain=start - 1 + len(selected) < len(file_lines),
        max_chars=max_chars,
        suggest_read_fallback=suggest_read_fallback,
    )


def _not_found(rel_path: str) -> dict:
    return {"status": "not_found", "text": "", "path": rel_path}


def read_memory_file(
    workspace_dir: str | os.PathLike[str],
    rel_path: str,
    *,
    from_line: int | None = None,
    lines: int | None = None,
    default_lines: int | None = None,
    max_chars: int | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> dict:
    """read-file.ts:85-194 ``readMemoryFile`` for a workspace read.

    Returns ``{"status": "ok", ...}`` or ``{"status": "not_found", "text": "", "path"}``; raises
    :class:`MemoryReadError` (or an ``OSError``) on refusal or a failed read, which the tool turns
    into ``{"status": "error", "code", "error"}``. The gate is lexical first:
    ``memory/../AGENTS.md`` and absolute paths outside the workspace are refused, then
    ``isMemoryPath`` (``MEMORY.md``, ``USER.md``, ``dreams.md`` in any case, ``memory/...``) and
    the ``.md`` suffix. ``sleep`` is the transient-retry delay (tests pass a stub).
    """
    raw_path = js_trim(rel_path)
    if not raw_path:
        raise MemoryReadError(MEMORY_PATH_REQUIRED_ERROR)
    workspace = os.fspath(workspace_dir)
    abs_path = os.path.normpath(
        raw_path if os.path.isabs(raw_path) else os.path.join(workspace, raw_path)
    )
    relative = os.path.relpath(abs_path, workspace).replace("\\", "/")
    if relative == ".":
        relative = ""
    in_workspace = bool(relative) and not relative.startswith("..") and not os.path.isabs(relative)
    if not in_workspace or not is_memory_path(relative):
        raise _memory_path_not_allowed()
    if not abs_path.endswith(".md"):
        raise _memory_path_not_allowed()
    try:
        # Workspace reads resolve through the safe fs root first (read-file.ts:155-166).
        resolve_in_workspace_root(_resolve_root(Path(workspace)), relative)
    except Exception as error:
        if is_file_missing_error(error):
            return _not_found(relative)
        raise
    if stat_regular_file(abs_path) is None:
        return _not_found(relative)
    try:
        data = retry_transient_memory_read(lambda: read_regular_file(abs_path), sleep=sleep)
    except Exception as error:
        # isFileDisappearedDuringReadError (read-file.ts:72-82).
        if is_file_missing_error(error) or extract_error_code(error) == FS_SAFE_PATH_MISMATCH_CODE:
            return _not_found(relative)
        raise
    return build_memory_read_result(
        # Buffer.toString("utf-8"): no newline translation, invalid bytes replaced.
        content=data.decode("utf-8", errors="replace"),
        rel_path=relative,
        from_line=from_line,
        lines=lines,
        default_lines=default_lines,
        max_chars=max_chars,
        suggest_read_fallback=True,
    )
