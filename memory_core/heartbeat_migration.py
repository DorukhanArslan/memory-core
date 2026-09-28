"""Retire a workspace HEARTBEAT.md: its text into monitor scratch, its ``tasks:`` into jobs.

v2026.9.6 no longer reads HEARTBEAT.md (3e2b3ea4d5e, #112967; 07e3855b465, #113131) and no
longer parses ``tasks:`` blocks at runtime (b23c7bd0f84, #113165); ``openclaw doctor --fix``
migrates old workspaces in two steps. This module ports both for a memory-core workspace root and
a host store (:class:`~memory_core.heartbeat_scratch.HeartbeatScratchStore` for the file
migration, :class:`~memory_core.automation.AutomationStore` for the task migration; the default
:class:`~memory_core.automation.FileAutomationStore` is both):

- :func:`migrate_heartbeat_md` (``maybeMigrateHeartbeatFilesToScratch``,
  ``src/commands/doctor-heartbeat-scratch-migration.ts``): the file is read no-follow with its
  containment, hard-link, 256 KiB and UTF-8 checks, operator-owned scratch (other content, an
  explicit unset) is left alone, a snapshot is archived first, the file is claimed by rename
  and hash-verified, copied into each agent's scratch by compare-and-swap with its source
  hash, and the claimed original is moved into a private archive directory; any failure rolls
  the scratch writes back and restores the file; interrupted claims are recovered;
- :func:`migrate_heartbeat_tasks` (``maybeMigrateHeartbeatTasksToCron``,
  ``doctor-heartbeat-task-migration.ts``): a valid ``tasks:`` block of the scratch becomes
  independent automation jobs (``every`` schedule from the interval, ``systemEvent`` payload,
  stable declaration keys, first run from the legacy task timestamp), refused with the tag's
  "could not be planned" warning when a job cannot be stored (``assertCronStoreCanPersist``),
  and the block leaves the scratch in the same compare-and-swap write; a rerun converges;
- :func:`analyze_legacy_heartbeat_tasks` (``src/commands/heartbeat-task-legacy.ts``): the
  doctor-only reader of the retired syntax, which also marks the bytes it removes;
- the read-only doctor health findings (``collectHeartbeatScratchMigrationFindings``,
  ``collectHeartbeatTaskMigrationFindings``).

Deviations (documented in docs/parity_matrix.md): archives live under the workspace,
``<root>/.memory-core/backups/heartbeat-migration/`` (upstream: ``<state>/backups/``); one call
migrates the agents sharing one workspace root, and ``retain_source`` (of the migration and
of its findings) stands for upstream's "a heartbeat owner of this file is disabled"; the monitor
job is implicit (its name is
upstream's ``Heartbeat (<agent>)``); fix hints and the job description name the memory-core
helpers instead of ``openclaw doctor``; the legacy task timestamps come in as
``legacy_task_state`` and the cleaned map comes back in the result for the host to persist;
jobs changed by another writer between planning and commit are not detected (upstream
``job-conflict``); OS error texts are Python's.
"""

from __future__ import annotations

import errno
import math
import os
import re
import stat
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from memory_core._heartbeat_constants import (
    CRON_JOB_SCRATCH_MAX_BYTES,
    HEARTBEAT_CLAIM_INFIX,
    HEARTBEAT_MONITOR_DISPLAY_NAME,
    HEARTBEAT_SCRATCH_CHANGE_COPIED,
    HEARTBEAT_SCRATCH_CHANGE_MIGRATED,
    HEARTBEAT_SCRATCH_ERROR_ARCHIVE_COLLISION,
    HEARTBEAT_SCRATCH_ERROR_CHANGED_AFTER_RESTORE,
    HEARTBEAT_SCRATCH_ERROR_CHANGED_BEFORE_CLAIM,
    HEARTBEAT_SCRATCH_ERROR_CHANGED_WHILE_HELD,
    HEARTBEAT_SCRATCH_ERROR_CLAIM_ESCAPES,
    HEARTBEAT_SCRATCH_ERROR_CLAIM_HELD,
    HEARTBEAT_SCRATCH_ERROR_ESCAPES,
    HEARTBEAT_SCRATCH_ERROR_HARDLINK,
    HEARTBEAT_SCRATCH_ERROR_MULTIPLE_CLAIMS,
    HEARTBEAT_SCRATCH_ERROR_NOT_FILE,
    HEARTBEAT_SCRATCH_ERROR_NOT_UTF8,
    HEARTBEAT_SCRATCH_ERROR_ORIGINAL_UNVERIFIED,
    HEARTBEAT_SCRATCH_ERROR_ORPHAN_CLAIM,
    HEARTBEAT_SCRATCH_ERROR_RECREATED,
    HEARTBEAT_SCRATCH_ERROR_RECREATED_WHILE_HELD,
    HEARTBEAT_SCRATCH_ERROR_RESTORE_FAILED,
    HEARTBEAT_SCRATCH_ERROR_RESTORED_UNVERIFIED,
    HEARTBEAT_SCRATCH_ERROR_REVERIFY,
    HEARTBEAT_SCRATCH_ERROR_SCRATCH_CHANGED,
    HEARTBEAT_SCRATCH_ERROR_STALE_CLAIM,
    HEARTBEAT_SCRATCH_ERROR_TARGET_ESCAPES,
    HEARTBEAT_SCRATCH_ERROR_VERIFY_FAILED,
    HEARTBEAT_SCRATCH_ERROR_WORKSPACE_CHANGED,
    HEARTBEAT_SCRATCH_FINDING_BLOCKED,
    HEARTBEAT_SCRATCH_FINDING_LEGACY,
    HEARTBEAT_SCRATCH_MIGRATION_CHECK_ID,
    HEARTBEAT_SCRATCH_MIGRATION_FIX_HINT,
    HEARTBEAT_SCRATCH_REASON_OWNER_DISABLED,
    HEARTBEAT_SCRATCH_REASON_OWNER_SKIPPED,
    HEARTBEAT_SCRATCH_WARNING_DIFFERENT,
    HEARTBEAT_SCRATCH_WARNING_NOT_FINALIZED,
    HEARTBEAT_SCRATCH_WARNING_NOT_MIGRATED,
    HEARTBEAT_SCRATCH_WARNING_NOT_REMOVED,
    HEARTBEAT_SCRATCH_WARNING_ROLLBACK,
    HEARTBEAT_SCRATCH_WARNING_UNREADABLE,
    HEARTBEAT_SCRATCH_WARNING_UNSET,
    HEARTBEAT_TASK_CHANGE,
    HEARTBEAT_TASK_DESCRIPTION,
    HEARTBEAT_TASK_DISPLAY_NAME,
    HEARTBEAT_TASK_ERROR_INCOMPLETE,
    HEARTBEAT_TASK_ERROR_NO_TASKS,
    HEARTBEAT_TASK_FINDING_BLOCKED,
    HEARTBEAT_TASK_FINDING_IN_SCRATCH,
    HEARTBEAT_TASK_FINDING_UNREADABLE,
    HEARTBEAT_TASK_INTERVAL_ERROR,
    HEARTBEAT_TASK_MIGRATION_CHECK_ID,
    HEARTBEAT_TASK_MIGRATION_FIX_HINT,
    HEARTBEAT_TASK_WARNING_COLLISION,
    HEARTBEAT_TASK_WARNING_COMMIT_FAILED,
    HEARTBEAT_TASK_WARNING_INVALID,
    HEARTBEAT_TASK_WARNING_NOT_PLANNED,
    HEARTBEAT_TASK_WARNING_SCRATCH_CHANGED,
    HEARTBEAT_TASK_WARNING_UNREADABLE,
    LEGACY_HEARTBEAT_FILENAME,
)
from memory_core.automation import (
    AutomationJob,
    AutomationStore,
    assert_automation_jobs_can_persist,
    compute_job_next_run_at_ms,
    heartbeat_task_declaration_key,
    is_heartbeat_task_job,
)
from memory_core.bootstrap._js import (
    JS_SPACE_CLASS,
    js_json_stringify,
    js_trim,
    truncate_utf16_safe,
)
from memory_core.bootstrap.tools_md import _format_error_message, _make_private_dirs, _shorten_home_path
from memory_core.heartbeat import parse_duration_ms
from memory_core.heartbeat_scratch import (
    HeartbeatScratch,
    HeartbeatScratchStore,
    hash_heartbeat_scratch_source,
)
from memory_core.project_name import PACKAGE_NAME, STATE_DIRNAME

__all__ = [
    "HEARTBEAT_MIGRATION_ARCHIVE_PARTS",
    "LEGACY_HEARTBEAT_FILENAME",
    "HeartbeatMigrationFinding",
    "HeartbeatMigrationResult",
    "LegacyHeartbeatTask",
    "LegacyHeartbeatTaskDocument",
    "analyze_legacy_heartbeat_tasks",
    "heartbeat_md_migration_findings",
    "heartbeat_task_migration_findings",
    "migrate_heartbeat_md",
    "migrate_heartbeat_tasks",
]

HEARTBEAT_MIGRATION_ARCHIVE_PARTS = (STATE_DIRNAME, "backups", "heartbeat-migration")
# Named where upstream names `openclaw doctor --fix` / `openclaw doctor`.
MIGRATE_HEARTBEAT_MD_COMMAND = f"{PACKAGE_NAME}.heartbeat_migration.migrate_heartbeat_md()"
MIGRATE_HEARTBEAT_TASKS_COMMAND = f"{PACKAGE_NAME}.heartbeat_migration.migrate_heartbeat_tasks()"
LEGACY_HEARTBEAT_FILE_REQUIREMENT = "legacy-heartbeat-file"
HEARTBEAT_FILE_MIGRATION_BLOCKED_REQUIREMENT = "heartbeat-file-migration-blocked"
HEARTBEAT_TASKS_IN_SCRATCH_REQUIREMENT = "heartbeat-tasks-in-scratch"
HEARTBEAT_TASK_MIGRATION_BLOCKED_REQUIREMENT = "heartbeat-task-migration-blocked"
_TASK_DESCRIPTION = HEARTBEAT_TASK_DESCRIPTION.replace(
    "openclaw doctor", MIGRATE_HEARTBEAT_TASKS_COMMAND
)
# @openclaw/fs-safe regular-file.js texts (readRegularFile), which the doctor read surfaces.
_FS_SAFE_TOO_LARGE = "File exceeds {max_bytes} bytes: {path}"
_FS_SAFE_NOT_REGULAR = "path must be a regular file"


# --- legacy tasks: syntax ----------------------------------------------------------------------

_LINE_RE = re.compile("[^\r\n]*(?:\r\n|\n|\r|\\Z)")
_LINE_ENDING_RE = re.compile("(?:\r\n|\n|\r)\\Z")
_NON_SPACE_RE = re.compile(f"[^{JS_SPACE_CLASS}]")  # JavaScript \S
_EDGE_QUOTES_RE = re.compile("^[\"']|[\"']\\Z")


@dataclass(frozen=True)
class LegacyHeartbeatTask:
    """One complete ``tasks:`` entry of the retired syntax (``LegacyHeartbeatTask``)."""

    name: str
    interval: str
    prompt: str

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "interval": self.interval, "prompt": self.prompt}


@dataclass(frozen=True)
class LegacyHeartbeatTaskDocument:
    """``analyzeLegacyHeartbeatTasks``: the parsed tasks and the text without their block.

    ``task_entry_count`` counts every started entry, complete or not, so a migration can refuse
    a block that would silently lose an incomplete entry.
    """

    has_tasks_block: bool
    task_entry_count: int
    tasks: tuple[LegacyHeartbeatTask, ...]
    stripped_content: str

    def to_json(self) -> dict[str, Any]:
        return {
            "hasTasksBlock": self.has_tasks_block,
            "taskEntryCount": self.task_entry_count,
            "tasks": [task.to_json() for task in self.tasks],
            "strippedContent": self.stripped_content,
        }


def _split_lines(content: str) -> list[tuple[str, str]]:
    # heartbeat-task-legacy.ts splitHeartbeatLines: (raw, source-with-line-ending) pairs.
    lines: list[tuple[str, str]] = []
    for match in _LINE_RE.finditer(content):
        source = match.group(0)
        if not source:
            continue
        lines.append((_LINE_ENDING_RE.sub("", source), source))
    return lines


def _scan_line(raw: str, state: list[bool]) -> tuple[bool, str, str]:
    # heartbeat-task-legacy.ts scanHeartbeatLine -> (hasHtmlComment, htmlCommentRaw, visible)
    cursor = 0
    has_comment = state[0]
    comment_raw = ""
    visible = ""
    while cursor < len(raw):
        if state[0]:
            end = raw.find("-->", cursor)
            if end == -1:
                comment_raw += raw[cursor:]
                return has_comment, comment_raw, visible
            comment_raw += raw[cursor : end + 3]
            state[0] = False
            cursor = end + 3
            continue
        start = raw.find("<!--", cursor)
        if start == -1:
            outside = raw[cursor:]
            visible += outside
            comment_raw += _NON_SPACE_RE.sub("", outside)
            return has_comment, comment_raw, visible
        outside = raw[cursor:start]
        visible += outside
        comment_raw += _NON_SPACE_RE.sub("", outside) + "<!--"
        has_comment = True
        state[0] = True
        cursor = start + 4
    return has_comment, comment_raw, visible


def _unquote(value: str) -> str:
    return _EDGE_QUOTES_RE.sub("", js_trim(value))


def analyze_legacy_heartbeat_tasks(content: str) -> LegacyHeartbeatTaskDocument:
    """Port of ``analyzeLegacyHeartbeatTasks``: parse ``tasks:`` blocks and mark their bytes.

    Recognises::

        tasks:
          - name: inbox
            interval: 30m
            prompt: Check urgent inbox items

    Every visible ``tasks:`` line starts a block; blank lines, ``- name:`` entries and
    indented ``interval:``/``prompt:`` fields belong to it, and any other visible line ends it
    and is kept byte for byte. Text inside HTML comments is invisible to the parser, but a
    comment on a removed line survives in ``stripped_content``.
    """
    state = [False]
    lines = []
    for raw, source in _split_lines(content):
        has_comment, comment_raw, visible = _scan_line(raw, state)
        ending = source[len(raw) :]
        lines.append((raw, source, visible, comment_raw + ending if has_comment else None))
    removed: set[int] = set()
    tasks: list[LegacyHeartbeatTask] = []
    entry_count = 0
    has_block = False
    in_block = False
    current: dict[str, str] | None = None
    orphan_open = False

    def finish() -> None:
        nonlocal current
        if current and current.get("name") and current.get("interval") and current.get("prompt"):
            tasks.append(
                LegacyHeartbeatTask(current["name"], current["interval"], current["prompt"])
            )
        current = None

    for index, (raw, _source, visible, _comment) in enumerate(lines):
        trimmed = js_trim(visible)
        if trimmed == "tasks:":
            finish()
            orphan_open = False
            has_block = True
            in_block = True
            removed.add(index)
            continue
        if not in_block:
            continue
        if not trimmed:
            if not js_trim(raw):
                removed.add(index)
            continue
        if trimmed.startswith("- name:"):
            finish()
            orphan_open = False
            entry_count += 1
            current = {"name": _unquote(trimmed[len("- name:") :])}
            removed.add(index)
            continue
        indented = visible.startswith(" ") or visible.startswith("\t")
        field = next(
            (name for name in ("interval", "prompt") if trimmed.startswith(f"{name}:")), None
        )
        if indented and field is not None:
            if current is not None:
                current[field] = _unquote(trimmed[len(field) + 1 :])
            elif not orphan_open:
                entry_count += 1
                orphan_open = True
            removed.add(index)
            continue
        finish()
        orphan_open = False
        in_block = False
    finish()
    stripped = "".join(
        (comment or "") if index in removed else source
        for index, (_raw, source, _visible, comment) in enumerate(lines)
    )
    return LegacyHeartbeatTaskDocument(has_block, entry_count, tuple(tasks), stripped)


@dataclass(frozen=True)
class _ValidatedTask:
    task: LegacyHeartbeatTask
    interval_ms: int
    occurrence_index: int


def _validate_tasks(
    tasks: Sequence[LegacyHeartbeatTask], declared_entry_count: int
) -> list[_ValidatedTask]:
    # doctor-heartbeat-task-migration.ts validateTasks
    if not tasks:
        raise ValueError(HEARTBEAT_TASK_ERROR_NO_TASKS)
    if len(tasks) != declared_entry_count:
        raise ValueError(HEARTBEAT_TASK_ERROR_INCOMPLETE)
    counts: dict[str, int] = {}
    validated: list[_ValidatedTask] = []
    for task in tasks:
        interval_ms = parse_duration_ms(task.interval, default_unit="m")
        if interval_ms <= 0:
            raise ValueError(
                HEARTBEAT_TASK_INTERVAL_ERROR.format(name_json=js_json_stringify(task.name))
            )
        occurrence = counts.get(task.name, 0)
        counts[task.name] = occurrence + 1
        validated.append(_ValidatedTask(task, interval_ms, occurrence))
    return validated


# --- results and findings ----------------------------------------------------------------------


@dataclass(frozen=True)
class HeartbeatMigrationResult:
    """Upstream ``{changes, warnings}`` plus what the host persists.

    ``jobs`` are the automation jobs a task migration created or converged; ``task_state`` is
    the legacy task-timestamp map without the migrated names (``None`` when it had none left),
    to replace the host's copy when ``task_state_changed``.
    """

    changes: tuple[str, ...]
    warnings: tuple[str, ...]
    jobs: tuple[AutomationJob, ...] = ()
    task_state: dict[str, float] | None = None
    task_state_changed: bool = False


@dataclass(frozen=True)
class HeartbeatMigrationFinding:
    """One doctor ``HealthFinding`` of the heartbeat migrations."""

    check_id: str
    severity: Literal["warning", "error"]
    message: str
    path: str
    target: str
    requirement: str
    fix_hint: str

    def to_json(self) -> dict[str, str]:
        return {
            "checkId": self.check_id,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "target": self.target,
            "requirement": self.requirement,
            "fixHint": self.fix_hint,
        }


class HeartbeatMigrationError(RuntimeError):
    pass


class _ClaimChangedError(HeartbeatMigrationError):
    """``HeartbeatClaimChangedError``: the claimed file is not the one that was read."""


# --- HEARTBEAT.md -> scratch ------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    path: str
    entry_key: str
    content: str
    sha256: str


def _is_inside(root: str, target: str) -> bool:
    return target == root or target.startswith(root.rstrip("/") + "/")


def _read_regular_text(real_path: str) -> str:
    # readRegularFile({maxBytes: 256 KiB}) plus the strict UTF-8 decode of the doctor read.
    info = os.lstat(real_path)
    if not stat.S_ISREG(info.st_mode):
        raise HeartbeatMigrationError(_FS_SAFE_NOT_REGULAR)
    if info.st_size > CRON_JOB_SCRATCH_MAX_BYTES:
        raise HeartbeatMigrationError(
            _FS_SAFE_TOO_LARGE.format(max_bytes=CRON_JOB_SCRATCH_MAX_BYTES, path=real_path)
        )
    with open(real_path, "rb") as handle:
        data = handle.read(CRON_JOB_SCRATCH_MAX_BYTES + 1)
    if len(data) > CRON_JOB_SCRATCH_MAX_BYTES:
        raise HeartbeatMigrationError(
            _FS_SAFE_TOO_LARGE.format(max_bytes=CRON_JOB_SCRATCH_MAX_BYTES, path=real_path)
        )
    try:
        # new TextDecoder("utf-8", {fatal: true}) drops a leading BOM.
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_NOT_UTF8) from None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _find_stale_claim(heartbeat_path: Path) -> Path | None:
    # doctor-heartbeat-scratch-migration.ts findStaleHeartbeatClaim
    pattern = re.compile(
        "^"
        + re.escape(heartbeat_path.name)
        + re.escape(HEARTBEAT_CLAIM_INFIX)
        + "[0-9]+-[0-9a-f]{12}\\Z"
    )
    try:
        entries = os.listdir(heartbeat_path.parent)
    except FileNotFoundError:
        return None
    claims = [entry for entry in entries if pattern.match(entry)]
    if len(claims) > 1:
        raise HeartbeatMigrationError(
            HEARTBEAT_SCRATCH_ERROR_MULTIPLE_CLAIMS.format(path=heartbeat_path)
        )
    if not claims:
        return None
    claim = claims[0]
    owner = claim[claim.rfind(HEARTBEAT_CLAIM_INFIX) + len(HEARTBEAT_CLAIM_INFIX) :].split("-")[0]
    pid = int(owner)
    if pid <= 2**53 - 1 and pid != os.getpid() and _is_process_alive(pid):
        raise HeartbeatMigrationError(
            HEARTBEAT_SCRATCH_ERROR_CLAIM_HELD.format(path=heartbeat_path, pid=pid)
        )
    return heartbeat_path.parent / claim


def _restore_claim_no_clobber(claim: Path, destination: Path) -> None:
    try:
        os.link(claim, destination, follow_symlinks=False)
        os.unlink(claim)
    except FileExistsError as exc:
        conflict = Path(f"{claim}.conflict-{int(time.time() * 1000)}")
        os.rename(claim, conflict)
        raise HeartbeatMigrationError(
            HEARTBEAT_SCRATCH_ERROR_RECREATED.format(conflict_path=conflict)
        ) from exc


def _read_heartbeat_source(workspace: Path, *, recover_claims: bool) -> _Source | None:
    # doctor-heartbeat-scratch-migration.ts readHeartbeatSource
    heartbeat_path = workspace / LEGACY_HEARTBEAT_FILENAME
    try:
        info = os.lstat(heartbeat_path)
        orphan = _find_stale_claim(heartbeat_path)
        if orphan is not None:
            raise HeartbeatMigrationError(
                HEARTBEAT_SCRATCH_ERROR_ORPHAN_CLAIM.format(path=heartbeat_path, claim=orphan)
            )
    except FileNotFoundError as exc:
        stale = _find_stale_claim(heartbeat_path)
        if stale is None:
            return None
        if not recover_claims:
            raise HeartbeatMigrationError(
                HEARTBEAT_SCRATCH_ERROR_STALE_CLAIM.format(claim=stale).replace(
                    "openclaw doctor --fix", MIGRATE_HEARTBEAT_MD_COMMAND
                )
            ) from exc
        _restore_claim_no_clobber(stale, heartbeat_path)
        info = os.lstat(heartbeat_path)
    if not stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
        raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_NOT_FILE)
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_HARDLINK)
    workspace_real = os.path.realpath(workspace, strict=True)
    source_real = os.path.realpath(heartbeat_path, strict=True)
    if source_real != workspace_real and not _is_inside(workspace_real, source_real):
        raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_ESCAPES)
    content = _read_regular_text(source_real)
    return _Source(
        path=str(heartbeat_path),
        entry_key=os.path.join(workspace_real, LEGACY_HEARTBEAT_FILENAME),
        content=content,
        sha256=hash_heartbeat_scratch_source(content),
    )


def heartbeat_migration_archive_dir(root: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(root)))).joinpath(
        *HEARTBEAT_MIGRATION_ARCHIVE_PARTS
    )


def _archive_path(root: Path, agent_id: str, sha256: str) -> Path:
    safe = re.sub("[^A-Za-z0-9._-]+", "-", agent_id)
    return heartbeat_migration_archive_dir(root) / f"{safe}-{sha256}.md"


def _archive_source(root: Path, agent_id: str, source: _Source) -> None:
    # doctor-heartbeat-scratch-migration.ts archiveSource: write once (wx, 0600), or verify.
    archive = _archive_path(root, agent_id, source.sha256)
    _make_private_dirs(archive.parent)
    try:
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        existing = archive.read_bytes().decode("utf-8", errors="replace")
        if hash_heartbeat_scratch_source(existing) != source.sha256:
            raise HeartbeatMigrationError(
                HEARTBEAT_SCRATCH_ERROR_ARCHIVE_COLLISION.format(archive=archive)
            ) from exc
        return
    try:
        os.write(fd, source.content.encode("utf-8"))
    finally:
        os.close(fd)


class _Claim:
    """``claimHeartbeatSource``: the source renamed aside and proven to hold the read bytes."""

    def __init__(self, source: _Source):
        self.source = source
        self.workspace_real = os.path.dirname(source.entry_key)
        self._assert_workspace_unchanged()
        self.path = Path(
            f"{source.entry_key}{HEARTBEAT_CLAIM_INFIX}{os.getpid()}-{source.sha256[:12]}"
        )
        os.rename(source.entry_key, self.path)
        try:
            self._assert_workspace_unchanged()
            claim_real = os.path.realpath(self.path, strict=True)
            if claim_real != self.workspace_real and not _is_inside(
                self.workspace_real, claim_real
            ):
                raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_CLAIM_ESCAPES)
            if hash_heartbeat_scratch_source(_read_regular_text(claim_real)) != source.sha256:
                raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_CHANGED_BEFORE_CLAIM)
        except Exception as exc:
            self.restore(exc)
            raise

    def _assert_workspace_unchanged(self) -> None:
        if os.path.realpath(os.path.dirname(self.source.path)) != self.workspace_real:
            raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_WORKSPACE_CHANGED)

    def restore(self, cause: BaseException | None) -> None:
        try:
            _restore_claim_no_clobber(self.path, Path(self.source.entry_key))
        except Exception as error:
            if "preserved at" in str(error):
                raise
            raise HeartbeatMigrationError(
                HEARTBEAT_SCRATCH_ERROR_RESTORE_FAILED.format(claim=self.path)
            ) from (cause or error)

    def _read_final(self, path: str | os.PathLike[str]) -> str:
        self._assert_workspace_unchanged()
        real = os.path.realpath(path, strict=True)
        if real != self.workspace_real and not _is_inside(self.workspace_real, real):
            raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_TARGET_ESCAPES)
        return _read_regular_text(real)

    def _fail_changed(self, message: str, cause: BaseException | None = None) -> None:
        error = _ClaimChangedError(message)
        error.__cause__ = cause
        try:
            self.restore(error)
        except Exception:
            pass
        raise error

    def retain(self) -> None:
        self.restore(None)
        try:
            final = self._read_final(self.source.entry_key)
        except Exception as exc:
            raise _ClaimChangedError(HEARTBEAT_SCRATCH_ERROR_RESTORED_UNVERIFIED) from exc
        if hash_heartbeat_scratch_source(final) != self.source.sha256:
            raise _ClaimChangedError(HEARTBEAT_SCRATCH_ERROR_CHANGED_AFTER_RESTORE)

    def release(self, archive_path: Path) -> None:
        try:
            final = self._read_final(self.path)
        except Exception as exc:
            self._fail_changed(HEARTBEAT_SCRATCH_ERROR_REVERIFY, exc)
            raise AssertionError("unreachable") from exc
        if hash_heartbeat_scratch_source(final) != self.source.sha256:
            self._fail_changed(HEARTBEAT_SCRATCH_ERROR_CHANGED_WHILE_HELD)
        try:
            os.lstat(self.source.entry_key)
            recreated = True
        except FileNotFoundError:
            recreated = False
        except OSError as exc:
            self._fail_changed(HEARTBEAT_SCRATCH_ERROR_ORIGINAL_UNVERIFIED, exc)
            raise AssertionError("unreachable") from exc
        if recreated:
            self._fail_changed(HEARTBEAT_SCRATCH_ERROR_RECREATED_WHILE_HELD)
        if stat.S_ISLNK(os.lstat(self.path).st_mode):
            os.unlink(self.path)
            return
        for base in (str(archive_path), f"{self.source.entry_key}.doctor-archived"):
            _make_private_dirs(Path(base).parent)
            archive_dir = tempfile.mkdtemp(prefix=f"{os.path.basename(base)}.", dir=os.path.dirname(base))
            try:
                os.rename(self.path, os.path.join(archive_dir, LEGACY_HEARTBEAT_FILENAME))
                return
            except OSError as exc:
                try:
                    os.rmdir(archive_dir)
                except OSError:
                    pass
                if exc.errno != errno.EXDEV or base != str(archive_path):
                    raise


def _monitor_name(agent_id: str) -> str:
    return HEARTBEAT_MONITOR_DISPLAY_NAME.format(agent_id=agent_id)


def heartbeat_md_migration_findings(
    root: str | os.PathLike[str], *, agent_id: str = "main", retain_source: bool = False
) -> tuple[HeartbeatMigrationFinding, ...]:
    """Port of ``collectHeartbeatScratchMigrationFindings`` for one agent (read-only).

    A HEARTBEAT.md at ``root`` gives a ``legacy-heartbeat-file`` warning (v2026.9.6 never reads
    it); one the migration would refuse gives a ``heartbeat-file-migration-blocked`` error.
    ``retain_source`` is :func:`migrate_heartbeat_md`'s flag (upstream: a heartbeat owner of the
    file is disabled): the file is meant to stay, so a readable one reports nothing
    (``disabledEntryKeys.has(source.entryKey)``); an unreadable one still reports its error.
    """
    workspace = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
    heartbeat_path = workspace / LEGACY_HEARTBEAT_FILENAME
    fix_hint = HEARTBEAT_SCRATCH_MIGRATION_FIX_HINT.format(command=MIGRATE_HEARTBEAT_MD_COMMAND)
    try:
        source = _read_heartbeat_source(workspace, recover_claims=False)
    except Exception as exc:
        return (
            HeartbeatMigrationFinding(
                HEARTBEAT_SCRATCH_MIGRATION_CHECK_ID,
                "error",
                HEARTBEAT_SCRATCH_FINDING_BLOCKED.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                ),
                str(heartbeat_path),
                agent_id,
                HEARTBEAT_FILE_MIGRATION_BLOCKED_REQUIREMENT,
                fix_hint,
            ),
        )
    if source is None or retain_source:
        return ()
    return (
        HeartbeatMigrationFinding(
            HEARTBEAT_SCRATCH_MIGRATION_CHECK_ID,
            "warning",
            HEARTBEAT_SCRATCH_FINDING_LEGACY.format(agent_id=agent_id),
            str(heartbeat_path),
            agent_id,
            LEGACY_HEARTBEAT_FILE_REQUIREMENT,
            fix_hint,
        ),
    )


def migrate_heartbeat_md(
    root: str | os.PathLike[str],
    store: HeartbeatScratchStore,
    *,
    agent_ids: Sequence[str] = ("main",),
    retain_source: bool = False,
    now_ms: int | None = None,
) -> HeartbeatMigrationResult:
    """Move ``<root>/HEARTBEAT.md`` into the heartbeat monitor scratch of ``agent_ids``.

    Port of ``maybeMigrateHeartbeatFilesToScratch`` (``shouldRepair``) for the agents whose
    workspace is ``root``. Each agent's scratch gets the file's exact text with its SHA-256 as
    ``source_sha256``, unless that agent already has different scratch or an explicit unset
    (warned, left unchanged, file kept). The file is archived to
    ``<root>/.memory-core/backups/heartbeat-migration/<agent>-<sha256>.md`` and removed after its
    claimed bytes are verified again; ``retain_source`` keeps it in place (upstream: another
    heartbeat owner of the file is disabled). Reruns are idempotent. The ``tasks:`` block stays
    in the scratch until :func:`migrate_heartbeat_tasks` runs.
    """
    workspace = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
    changes: list[str] = []
    warnings: list[str] = []
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    groups: dict[str, tuple[_Source, list[str]]] = {}
    for agent_id in agent_ids:
        try:
            source = _read_heartbeat_source(workspace, recover_claims=True)
        except Exception as exc:
            warnings.append(
                HEARTBEAT_SCRATCH_WARNING_UNREADABLE.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                )
            )
            continue
        if source is None:
            continue
        group = groups.setdefault(source.entry_key, (source, []))
        group[1].append(agent_id)

    for source, agents in groups.values():
        shown = _shorten_home_path(source.path)
        keep_source = retain_source
        import_agents: list[str] = []
        write_needed = False
        planned: dict[str, int] = {}
        for agent_id in agents:
            state = store.read_scratch(agent_id)
            current = state.scratch
            planned[agent_id] = state.current_revision
            if state.current_revision > 0 and current is None:
                warnings.append(HEARTBEAT_SCRATCH_WARNING_UNSET.format(agent_id=agent_id))
                keep_source = True
            elif (
                current is not None
                and current.content != source.content
                and current.source_sha256 != source.sha256
            ):
                warnings.append(HEARTBEAT_SCRATCH_WARNING_DIFFERENT.format(agent_id=agent_id))
                keep_source = True
            else:
                import_agents.append(agent_id)
                if current is None or current.source_sha256 != source.sha256:
                    write_needed = True
        if not import_agents or (keep_source and not write_needed):
            continue
        if not keep_source:
            try:
                _archive_source(workspace, import_agents[0], source)
            except Exception as exc:
                warnings.append(
                    HEARTBEAT_SCRATCH_WARNING_NOT_MIGRATED.format(
                        path=shown, error=_format_error_message(exc)
                    )
                )
                continue
        try:
            claim = _Claim(source)
        except Exception as exc:
            warnings.append(
                HEARTBEAT_SCRATCH_WARNING_NOT_MIGRATED.format(
                    path=shown, error=_format_error_message(exc)
                )
            )
            continue

        imported_all = True
        group_changes: list[str] = []
        committed: list[tuple[str, HeartbeatScratch | None, int]] = []
        for agent_id in import_agents:
            try:
                state = store.read_scratch(agent_id)
                should_write = state.scratch is None or state.scratch.source_sha256 != source.sha256
                if should_write:
                    write = store.write_scratch(
                        agent_id,
                        source.content,
                        expected_revision=planned.get(agent_id, state.current_revision),
                        source_sha256=source.sha256,
                        now_ms=stamp,
                    )
                    if not write.ok:
                        raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_SCRATCH_CHANGED)
                    committed.append((agent_id, state.scratch, write.current_revision))
                verified = store.read_scratch(agent_id).scratch
                if verified is None or verified.source_sha256 != source.sha256:
                    raise HeartbeatMigrationError(HEARTBEAT_SCRATCH_ERROR_VERIFY_FAILED)
                if not keep_source or should_write:
                    if keep_source:
                        reason = (
                            HEARTBEAT_SCRATCH_REASON_OWNER_DISABLED
                            if retain_source
                            else HEARTBEAT_SCRATCH_REASON_OWNER_SKIPPED
                        )
                        group_changes.append(
                            HEARTBEAT_SCRATCH_CHANGE_COPIED.format(
                                path=shown, monitor=_monitor_name(agent_id), reason=reason
                            )
                        )
                    else:
                        group_changes.append(
                            HEARTBEAT_SCRATCH_CHANGE_MIGRATED.format(
                                path=shown, monitor=_monitor_name(agent_id)
                            )
                        )
            except Exception as exc:
                warnings.append(
                    HEARTBEAT_SCRATCH_WARNING_NOT_FINALIZED.format(
                        agent_id=agent_id, error=_format_error_message(exc)
                    )
                )
                imported_all = False

        def rollback() -> None:
            for agent_id, previous, new_revision in reversed(committed):
                if previous is None:
                    if not store.delete_scratch(agent_id, expected_revision=new_revision):
                        warnings.append(HEARTBEAT_SCRATCH_WARNING_ROLLBACK.format(agent_id=agent_id))
                    continue
                revert = store.write_scratch(
                    agent_id,
                    previous.content,
                    expected_revision=new_revision,
                    source_sha256=previous.source_sha256,
                    now_ms=stamp,
                )
                if not revert.ok:
                    warnings.append(HEARTBEAT_SCRATCH_WARNING_ROLLBACK.format(agent_id=agent_id))

        if not imported_all:
            rollback()
            try:
                claim.restore(None)
            except Exception as exc:
                warnings.append(_format_error_message(exc))
            continue
        if keep_source:
            try:
                claim.retain()
                changes.extend(group_changes)
            except Exception as exc:
                rollback()
                warnings.append(
                    HEARTBEAT_SCRATCH_WARNING_NOT_MIGRATED.format(
                        path=shown, error=_format_error_message(exc)
                    )
                )
            continue
        try:
            claim.release(_archive_path(workspace, import_agents[0], source.sha256))
            changes.extend(group_changes)
        except _ClaimChangedError as exc:
            rollback()
            warnings.append(
                HEARTBEAT_SCRATCH_WARNING_NOT_MIGRATED.format(
                    path=shown, error=_format_error_message(exc)
                )
            )
        except Exception as exc:
            changes.extend(group_changes)
            warnings.append(
                HEARTBEAT_SCRATCH_WARNING_NOT_REMOVED.format(
                    path=shown, error=_format_error_message(exc)
                )
            )
    return HeartbeatMigrationResult(tuple(changes), tuple(warnings))


# --- scratch tasks -> automation jobs ---------------------------------------------------------


def _store_path(store: object) -> str:
    return os.fspath(getattr(store, "path", "")) if getattr(store, "path", None) else ""


def heartbeat_task_migration_findings(
    store: HeartbeatScratchStore, *, agent_id: str = "main"
) -> tuple[HeartbeatMigrationFinding, ...]:
    """Port of ``collectHeartbeatTaskMigrationFindings`` for one agent (read-only)."""
    fix_hint = HEARTBEAT_TASK_MIGRATION_FIX_HINT.format(command=MIGRATE_HEARTBEAT_TASKS_COMMAND)
    path = _store_path(store)

    def finding(requirement: str, severity: str, message: str) -> HeartbeatMigrationFinding:
        return HeartbeatMigrationFinding(
            HEARTBEAT_TASK_MIGRATION_CHECK_ID, severity, message, path, agent_id, requirement,
            fix_hint,
        )  # type: ignore[arg-type]

    try:
        content = store.read_scratch(agent_id).content
    except Exception as exc:
        return (
            finding(
                HEARTBEAT_TASK_MIGRATION_BLOCKED_REQUIREMENT,
                "error",
                HEARTBEAT_TASK_FINDING_UNREADABLE.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                ),
            ),
        )
    if not content:
        return ()
    document = analyze_legacy_heartbeat_tasks(content)
    if not document.has_tasks_block:
        return ()
    try:
        _validate_tasks(document.tasks, document.task_entry_count)
    except ValueError as exc:
        return (
            finding(
                HEARTBEAT_TASK_MIGRATION_BLOCKED_REQUIREMENT,
                "error",
                HEARTBEAT_TASK_FINDING_BLOCKED.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                ),
            ),
        )
    count = len(document.tasks)
    return (
        finding(
            HEARTBEAT_TASKS_IN_SCRATCH_REQUIREMENT,
            "warning",
            HEARTBEAT_TASK_FINDING_IN_SCRATCH.format(
                agent_id=agent_id, count=count, plural="" if count == 1 else "s"
            ),
        ),
    )


def _legacy_last_run(task_state: Mapping[str, Any] | None, name: str) -> int | None:
    if not task_state or name not in task_state:
        return None
    value = task_state[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(value) if float(value).is_integer() else value  # type: ignore[return-value]


def _converge_task_job(
    *,
    agent_id: str,
    validated: _ValidatedTask,
    last_run_at_ms: int | None,
    existing: AutomationJob | None,
    now_ms: int,
) -> AutomationJob:
    # doctor-heartbeat-task-migration.ts taskJobInput + convergeTaskJob
    task = validated.task
    interval_ms = validated.interval_ms
    existing_anchor = (
        existing.anchor_ms if existing is not None and existing.every_ms == interval_ms else None
    )
    if last_run_at_ms is None or last_run_at_ms + interval_ms <= now_ms:
        next_due = now_ms + 1
    else:
        next_due = last_run_at_ms + interval_ms
    anchor = existing_anchor if existing_anchor is not None else next_due
    display_name = truncate_utf16_safe(HEARTBEAT_TASK_DISPLAY_NAME.format(name=task.name), 200)
    if existing is None:
        job = AutomationJob(
            id=str(uuid.uuid4()),
            declaration_key=heartbeat_task_declaration_key(
                agent_id, task.name, validated.occurrence_index
            ),
            display_name=display_name,
            name=task.name,
            description=_TASK_DESCRIPTION,
            agent_id=agent_id,
            enabled=True,
            every_ms=interval_ms,
            anchor_ms=anchor,
            text=task.prompt,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            last_run_at_ms=last_run_at_ms,
        )
        return replace(job, next_run_at_ms=compute_job_next_run_at_ms(job, now_ms))
    job = replace(
        existing,
        display_name=display_name,
        every_ms=interval_ms,
        anchor_ms=anchor,
        text=task.prompt,
        enabled=True,
    )

    def declarative(value: AutomationJob) -> tuple[Any, ...]:
        return (value.every_ms, value.anchor_ms, value.text, value.display_name, value.enabled)

    if declarative(existing) == declarative(job):
        return job
    job = replace(job, updated_at_ms=now_ms)
    if (existing.every_ms, existing.anchor_ms, existing.enabled) != (
        job.every_ms,
        job.anchor_ms,
        job.enabled,
    ) or not (isinstance(job.next_run_at_ms, (int, float)) and job.next_run_at_ms > 0):
        job = replace(job, next_run_at_ms=compute_job_next_run_at_ms(job, now_ms))
    return job


def migrate_heartbeat_tasks(
    store: AutomationStore,
    *,
    agent_id: str = "main",
    legacy_task_state: Mapping[str, float] | None = None,
    now_ms: int | None = None,
) -> HeartbeatMigrationResult:
    """Turn the ``tasks:`` block of an agent's monitor scratch into automation jobs.

    Port of ``maybeMigrateHeartbeatTasksToCron`` (``shouldRepair``) for one agent. ``store``
    is an :class:`~memory_core.automation.AutomationStore` (``list_jobs`` plus the atomic
    scratch-and-jobs ``save_jobs``; :class:`~memory_core.automation.FileAutomationStore` by
    default); rows the store cannot load are not listed, so they take no part in the
    declaration-collision check. A block with an incomplete entry, a
    non-positive interval or no complete entry is refused with a warning; each task becomes
    (or converges) a job with an ``every`` schedule, its prompt as the payload, the stable
    ``heartbeat-task:`` declaration key and a first run right after ``now_ms`` or one interval
    after the task's ``legacy_task_state`` timestamp; the scratch keeps everything but the
    block, in the same compare-and-swap write. Returns the jobs and the legacy task state
    without the migrated names.
    """
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        state = store.read_scratch(agent_id)
    except Exception as exc:
        return HeartbeatMigrationResult(
            (),
            (
                HEARTBEAT_TASK_WARNING_UNREADABLE.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                ),
            ),
        )
    scratch = state.scratch
    if scratch is None:
        return HeartbeatMigrationResult((), ())
    document = analyze_legacy_heartbeat_tasks(scratch.content)
    if not document.has_tasks_block:
        return HeartbeatMigrationResult((), ())
    try:
        validated = _validate_tasks(document.tasks, document.task_entry_count)
    except ValueError as exc:
        return HeartbeatMigrationResult(
            (),
            (
                HEARTBEAT_TASK_WARNING_INVALID.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                ),
            ),
        )
    existing_jobs = store.list_jobs()
    planned: list[tuple[AutomationJob | None, AutomationJob]] = []
    for item in validated:
        key = heartbeat_task_declaration_key(agent_id, item.task.name, item.occurrence_index)
        matches = [job for job in existing_jobs if job.declaration_key == key]
        existing = matches[0] if matches else None
        if len(matches) > 1 or (
            existing is not None
            and (
                not is_heartbeat_task_job(existing)
                or existing.agent_id != agent_id
                or existing.name != item.task.name
            )
        ):
            return HeartbeatMigrationResult(
                (),
                (
                    HEARTBEAT_TASK_WARNING_COLLISION.format(
                        agent_id=agent_id, name_json=js_json_stringify(item.task.name)
                    ),
                ),
            )
        job = _converge_task_job(
            agent_id=agent_id,
            validated=item,
            last_run_at_ms=_legacy_last_run(legacy_task_state, item.task.name),
            existing=existing,
            now_ms=stamp,
        )
        planned.append((existing, job))
    try:
        # assertCronStoreCanPersist over the planned jobs: a legacy timestamp that is fractional,
        # negative or outside Date's range cannot be stored, so nothing is written.
        persisted = assert_automation_jobs_can_persist([job for _previous, job in planned])
    except ValueError as exc:
        return HeartbeatMigrationResult(
            (),
            (
                HEARTBEAT_TASK_WARNING_NOT_PLANNED.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                ),
            ),
        )
    planned = [(previous, job) for (previous, _planned), job in zip(planned, persisted, strict=True)]
    try:
        committed = store.save_jobs(
            [job for previous, job in planned if previous != job],
            scratch_agent_id=agent_id,
            scratch_content=document.stripped_content,
            scratch_expected_revision=scratch.revision,
            scratch_source_sha256=scratch.source_sha256,
            now_ms=stamp,
        )
    except Exception as exc:
        return HeartbeatMigrationResult(
            (),
            (
                HEARTBEAT_TASK_WARNING_COMMIT_FAILED.format(
                    agent_id=agent_id, error=_format_error_message(exc)
                ),
            ),
        )
    if committed is not None and not committed.ok:
        return HeartbeatMigrationResult(
            (), (HEARTBEAT_TASK_WARNING_SCRATCH_CHANGED.format(agent_id=agent_id),)
        )
    count = len(document.tasks)
    change = HEARTBEAT_TASK_CHANGE.format(
        count=count, plural="" if count == 1 else "s", agent_id=agent_id
    )
    remaining = dict(legacy_task_state or {})
    changed = False
    for task in document.tasks:
        if task.name in remaining:
            del remaining[task.name]
            changed = True
    return HeartbeatMigrationResult(
        (change,),
        (),
        jobs=tuple(job for _previous, job in planned),
        task_state=(remaining or None) if changed else (dict(legacy_task_state) if legacy_task_state else None),
        task_state_changed=changed,
    )
