"""Workspace seeding, setup state and the BOOTSTRAP.md lifecycle.

Port of OpenClaw ``src/agents/workspace.ts`` at the parity pin v2026.9.6:
``fileContentDiffersFromTemplate``, ``hasWorkspaceUserContentEvidence`` /
``hasWorkspaceSkillEvidence``, ``workspaceProfileLooksConfigured``,
``reconcileWorkspaceBootstrapCompletionState``, ``isWorkspaceSetupCompleted`` /
``resolveWorkspaceBootstrapStatus`` and the seeding and BOOTSTRAP.md steps of
``ensureAgentWorkspace`` (AGENTS.md always, SOUL/IDENTITY/USER unless skipped or setup is
complete; TOOLS.md and HEARTBEAT.md are no longer seeded, 669db2968fc #113966, 3e2b3ea4d5e
#112967), plus ``stripFrontMatter`` and the legacy-state gate of
``src/agents/workspace-legacy-state.ts`` (#109147).

Deviations (also listed in docs/parity_matrix.md › Workspace bootstrap files):

- Setup state. Upstream keeps setup state and attestations in its shared SQLite state DB
  (``src/agents/workspace-state-store.ts``); memory-core keeps ``{version, bootstrapSeededAt,
  setupCompletedAt}`` in ``<root>/.memory-core/workspace-state.json``. What upstream makes
  observable through files is ported: a workspace that still holds upstream's retired JSON
  state (``openclaw-workspace-state.json``, ``.openclaw/workspace-state.json``, or an
  interrupted doctor claim of either) fails closed with
  :class:`WorkspaceStateMigrationRequiredError` until
  :func:`migrate_legacy_workspace_state` imports it (upstream: ``openclaw doctor --fix``);
  runtime code never parses those files. Attestation sources (upstream's state-dir files and
  sibling ``<workspace>.attested`` markers) are not checked: memory-core has no attestation store.
  Stricter than upstream: ``assertNoUnmigratedWorkspaceState`` caches a clean check per source
  set for the process lifetime (``checkedWorkspaceSourceSets``,
  ``src/agents/workspace-legacy-state.ts:196-213``), so a legacy file that appears later is
  ignored until restart; memory-core checks on every call (a library has no process lifetime to
  scope such a cache to).
- Templates come from the host (``templates``), default to empty strings, and never carry
  OpenClaw template wording. They pass through upstream's front-matter stripping like
  ``loadTemplate`` output.
- Not ported: workspace attestations and the ``WorkspaceVanishedError`` guard, the custom
  agent ``purpose`` instructions, ``git init`` for brand-new workspaces, the
  ``ensureBootstrapFiles: false`` and ``runtime-managed-implicit`` modes, remote workspace
  access. ``seed_bootstrap=False`` is a memory-core extension for hosts without a bootstrap
  ritual: where upstream would write BOOTSTRAP.md, memory-core marks setup complete instead (an
  existing BOOTSTRAP.md is still honoured).
- One ``now_ms`` stamps every timestamp of a call (upstream calls ``new Date()`` per
  timestamp).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from memory_core.bootstrap._js import JS_WHITESPACE, js_json_stringify, js_trim, js_utf8_encode
from memory_core.bootstrap.files import exact_workspace_entry_exists
from memory_core.bootstrap.layout import DEFAULT_WORKSPACE_LAYOUT, WorkspaceLayout
from memory_core.project_name import PACKAGE_NAME, STATE_DIRNAME

WORKSPACE_STATE_VERSION = 1
MEMORY_CORE_WORKSPACE_STATE_FILENAME = "workspace-state.json"
# src/agents/workspace-legacy-state.ts: retired upstream setup files, read only by doctor.
OPENCLAW_WORKSPACE_STATE_FILENAME = "openclaw-workspace-state.json"
OPENCLAW_LEGACY_WORKSPACE_STATE_DIRNAME = ".openclaw"
OPENCLAW_LEGACY_WORKSPACE_STATE_FILENAME = "workspace-state.json"
WORKSPACE_DOCTOR_CLAIM_SUFFIX = ".doctor-importing"
# src/infra/state-migrations.workspace-setup-files.ts SETUP_MAX_BYTES.
LEGACY_WORKSPACE_SETUP_MAX_BYTES = 64 * 1024
MIGRATE_LEGACY_WORKSPACE_STATE_COMMAND = f"{PACKAGE_NAME}.bootstrap.migrate_legacy_workspace_state()"

BootstrapStatus = Literal["pending", "complete"]


@dataclass(frozen=True)
class WorkspaceSetupState:
    """``{version: 1, bootstrapSeededAt?, setupCompletedAt?}`` as upstream stores it."""

    version: int = WORKSPACE_STATE_VERSION
    bootstrap_seeded_at: str | None = None
    setup_completed_at: str | None = None

    @property
    def has_marker(self) -> bool:
        return bool(self.bootstrap_seeded_at or self.setup_completed_at)

    @property
    def setup_completed(self) -> bool:
        value = self.setup_completed_at
        return isinstance(value, str) and bool(js_trim(value))

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {"version": WORKSPACE_STATE_VERSION}
        if self.bootstrap_seeded_at is not None:
            data["bootstrapSeededAt"] = self.bootstrap_seeded_at
        if self.setup_completed_at is not None:
            data["setupCompletedAt"] = self.setup_completed_at
        return data


@dataclass(frozen=True)
class WorkspaceInitResult:
    """Outcome of :func:`initialize_agent_workspace`.

    ``created_files`` and ``created_dirs`` name what this call created, in
    creation order. ``bootstrap_removed`` is true when completion evidence made
    the reconcile step delete BOOTSTRAP.md.
    """

    root: Path
    created_files: tuple[str, ...]
    created_dirs: tuple[str, ...]
    bootstrap_seeded: bool
    bootstrap_removed: bool
    state: WorkspaceSetupState
    bootstrap_status: BootstrapStatus


def strip_template_front_matter(content: str) -> str:
    """Port of ``stripFrontMatter`` (workspace.ts:106-118)."""
    if not content.startswith("---"):
        return content
    end_index = content.find("\n---", 3)
    if end_index == -1:
        return content
    return content[end_index + len("\n---") :].lstrip(JS_WHITESPACE)


def _iso_from_ms(now_ms: int | float) -> str:
    moment = datetime.fromtimestamp(int(now_ms) / 1000, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(now_ms) % 1000:03d}Z"


def _root_path(root: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(root))))


def _state_path(root: Path) -> Path:
    return root / STATE_DIRNAME / MEMORY_CORE_WORKSPACE_STATE_FILENAME


def legacy_workspace_state_paths(root: str | os.PathLike[str]) -> tuple[Path, Path]:
    """Upstream's retired setup files for a workspace (``resolveLegacyWorkspaceSourcePaths``).

    Bound to the canonical (real) workspace path like upstream's ``setupStatePaths``.
    """
    canonical = Path(os.path.realpath(_root_path(root)))
    return (
        canonical / OPENCLAW_WORKSPACE_STATE_FILENAME,
        canonical / OPENCLAW_LEGACY_WORKSPACE_STATE_DIRNAME / OPENCLAW_LEGACY_WORKSPACE_STATE_FILENAME,
    )


def _path_may_exist(path: Path) -> bool:
    # pathMayExistSync (src/infra/path-existence.ts): only a definite ENOENT means absent.
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


class WorkspaceStateMigrationRequiredError(RuntimeError):
    """Upstream's retired JSON setup state is still in the workspace.

    Port of ``assertNoUnmigratedWorkspaceState`` (``src/agents/workspace-legacy-state.ts``):
    upstream refuses to read or seed such a workspace until ``openclaw doctor --fix`` imports
    the file; memory-core's import is :func:`migrate_legacy_workspace_state`.
    """

    def __init__(self, workspace_dir: str, blocked_paths: tuple[str, ...]):
        self.workspace_dir = workspace_dir
        self.blocked_paths = blocked_paths
        super().__init__(
            f"Legacy workspace setup state requires migration for {workspace_dir}; "
            f"run {MIGRATE_LEGACY_WORKSPACE_STATE_COMMAND}."
        )


def assert_no_unmigrated_workspace_state(root: str | os.PathLike[str]) -> None:
    """Fail closed while an upstream legacy setup file or its doctor claim exists.

    Deviation: checked on every call; upstream skips source sets it already found clean in
    this process (``checkedWorkspaceSourceSets``).
    """
    blocked = tuple(
        str(candidate)
        for source in legacy_workspace_state_paths(root)
        for candidate in (source, Path(f"{source}{WORKSPACE_DOCTOR_CLAIM_SUFFIX}"))
        if _path_may_exist(candidate)
    )
    if blocked:
        raise WorkspaceStateMigrationRequiredError(
            os.path.realpath(_root_path(root)), blocked
        )


def _reject_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def _parse_state(raw: str) -> WorkspaceSetupState | None:
    """Parse memory-core's own state file (the pin's ``parseWorkspaceSetupState`` shape)."""
    try:
        parsed = json.loads(raw, parse_constant=_reject_constant)
    except ValueError:
        return None
    if isinstance(parsed, list):
        return WorkspaceSetupState()
    if not isinstance(parsed, dict):
        return None

    def string_value(key: str) -> str | None:
        value = parsed.get(key)
        return value if isinstance(value, str) else None

    return WorkspaceSetupState(
        bootstrap_seeded_at=string_value("bootstrapSeededAt"),
        setup_completed_at=string_value("setupCompletedAt"),
    )


def _read_state_file(path: Path) -> WorkspaceSetupState | None:
    try:
        raw = path.read_bytes().decode("utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return None
    return _parse_state(raw)


def _write_state(root: Path, state: WorkspaceSetupState) -> None:
    """``JSON.stringify(state, null, 2) + "\\n"``, written atomically."""
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = js_json_stringify(state.to_json(), indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(js_utf8_encode(content))
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def read_stored_workspace_setup_state(root: str | os.PathLike[str]) -> WorkspaceSetupState:
    """The stored setup state, without the legacy-state gate.

    Upstream ``readWorkspaceStateSnapshot(dir).setup`` (``src/agents/workspace-state-store.ts``,
    the SQLite row); memory-core reads ``<root>/.memory-core/workspace-state.json`` (absent,
    unreadable as a directory, or not a JSON object: no markers).
    """
    return _read_state_file(_state_path(_root_path(root))) or WorkspaceSetupState()


def read_workspace_setup_state(root: str | os.PathLike[str]) -> WorkspaceSetupState:
    """Setup state of a workspace (upstream ``readCanonicalWorkspaceStateSnapshot().setup``).

    Raises :class:`WorkspaceStateMigrationRequiredError` while upstream's retired JSON state
    is present, then returns :func:`read_stored_workspace_setup_state`.
    """
    root_path = _root_path(root)
    assert_no_unmigrated_workspace_state(root_path)
    return read_stored_workspace_setup_state(root_path)


def is_workspace_setup_completed(root: str | os.PathLike[str]) -> bool:
    """Port of ``isWorkspaceSetupCompleted`` (``src/agents/workspace.ts``)."""
    return read_workspace_setup_state(root).setup_completed


def bootstrap_status(
    root: str | os.PathLike[str], layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
) -> BootstrapStatus:
    """Port of ``resolveWorkspaceBootstrapStatus`` (``src/agents/workspace.ts``)."""
    root_path = _root_path(root)
    if read_workspace_setup_state(root_path).setup_completed:
        return "complete"
    return "pending" if os.path.exists(root_path / layout.bootstrap_file) else "complete"


def _write_file_if_missing(path: Path, content: str) -> bool:
    try:
        with open(path, "xb") as handle:
            handle.write(js_utf8_encode(content))
    except FileExistsError:
        return False
    return True


def _differs_from_template(path: Path, template: str) -> bool:
    try:
        return path.read_bytes().decode("utf-8", errors="replace") != template
    except FileNotFoundError:
        return False


def _has_skill_evidence(root: Path) -> bool:
    try:
        entries = list(os.scandir(root / "skills"))
    except OSError:
        return False
    for entry in entries:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if is_dir and os.path.exists(root / "skills" / entry.name / "SKILL.md"):
            return True
    return False


def has_workspace_user_content_evidence(
    root: str | os.PathLike[str],
    *,
    include_git: bool = False,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> bool:
    """``memory/``, exact ``MEMORY.md``, a ``skills/*/SKILL.md`` (``.git`` optional)."""
    root_path = _root_path(root)
    indicators = [root_path / "memory"]
    if include_git:
        indicators.append(root_path / ".git")
    if any(os.path.exists(indicator) for indicator in indicators):
        return True
    if exact_workspace_entry_exists(root_path, layout.memory_file):
        return True
    return _has_skill_evidence(root_path)


def _resolve_templates(
    layout: WorkspaceLayout, templates: Mapping[str, str] | None
) -> dict[str, str]:
    supplied = dict(templates or {})
    unknown = set(supplied) - set(layout.seed_order) - {layout.bootstrap_file}
    if unknown:
        raise ValueError(f"templates for files outside the layout: {sorted(unknown)}")
    names = (*layout.seed_order, layout.bootstrap_file)
    return {name: strip_template_front_matter(supplied.get(name, "")) for name in names}


def workspace_profile_looks_configured(
    root: str | os.PathLike[str],
    *,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
    templates: Mapping[str, str] | None = None,
    include_git_evidence: bool = False,
) -> bool:
    """Port of ``workspaceProfileLooksConfigured`` (workspace.ts:332-347).

    True when any profile file (SOUL.md, IDENTITY.md, USER.md) differs from its
    template (a missing file does not differ) or user-content evidence exists.
    """
    root_path = _root_path(root)
    resolved = _resolve_templates(layout, templates)
    if any(
        _differs_from_template(root_path / name, resolved.get(name, ""))
        for name in layout.profile_files
    ):
        return True
    return has_workspace_user_content_evidence(
        root_path, include_git=include_git_evidence, layout=layout
    )


@dataclass(frozen=True)
class _ReconcileResult:
    repaired: bool
    bootstrap_exists: bool
    state: WorkspaceSetupState
    bootstrap_removed: bool = False


def _reconcile_completion_state(
    root: Path,
    *,
    layout: WorkspaceLayout,
    templates: Mapping[str, str],
    state: WorkspaceSetupState,
    bootstrap_exists: bool,
    now_iso: str,
) -> _ReconcileResult:
    """Port of ``reconcileWorkspaceBootstrapCompletionState`` (workspace.ts:413-460)."""
    if state.setup_completed:
        return _ReconcileResult(False, bootstrap_exists, state)
    if state.bootstrap_seeded_at and not bootstrap_exists:
        completed = replace(state, setup_completed_at=now_iso)
        _write_state(root, completed)
        return _ReconcileResult(True, False, completed)
    if not bootstrap_exists or not workspace_profile_looks_configured(
        root, layout=layout, templates=templates
    ):
        return _ReconcileResult(False, bootstrap_exists, state)
    repaired = replace(
        state,
        bootstrap_seeded_at=(
            state.bootstrap_seeded_at if state.bootstrap_seeded_at is not None else now_iso
        ),
        setup_completed_at=now_iso,
    )
    _write_state(root, repaired)
    try:
        os.unlink(root / layout.bootstrap_file)
    except FileNotFoundError:
        pass
    except OSError:
        # Completion state is authoritative; stale BOOTSTRAP cleanup is best-effort.
        return _ReconcileResult(True, True, repaired)
    return _ReconcileResult(True, False, repaired, bootstrap_removed=True)


def initialize_agent_workspace(
    root: str | os.PathLike[str],
    *,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
    templates: Mapping[str, str] | None = None,
    seed_bootstrap: bool = True,
    skip_optional: bool | Collection[str] = False,
    now_ms: int | None = None,
) -> WorkspaceInitResult:
    """Seed a workspace and run the BOOTSTRAP.md lifecycle, like ``ensureAgentWorkspace``.

    The required file (AGENTS.md) is written when missing. Optional files
    (SOUL.md, IDENTITY.md, USER.md; with the memory-core layout also
    PROACTIVE_PREFERENCES.md) are written unless ``skip_optional`` names them
    (``True`` = all) or setup is already complete. MEMORY.md is never seeded, and
    neither are the retired TOOLS.md and HEARTBEAT.md. Existing files are never overwritten. ``templates`` maps file names
    to host-supplied text; every file defaults to an empty template, so a
    workspace initialized without templates gets empty files.

    BOOTSTRAP.md is written (from ``templates["BOOTSTRAP.md"]``, default empty)
    only when the state has neither ``bootstrapSeededAt`` nor
    ``setupCompletedAt``, BOOTSTRAP.md is absent, and the profile does not
    already look configured (a profile file differs from its template, or
    ``memory/``, ``MEMORY.md``, a workspace skill or ``.git`` exists). Create
    memory files after this call, or the workspace counts as configured.
    With an empty BOOTSTRAP.md template the workspace still reports
    ``pending`` until the file is removed or the profile is configured; pass
    ``seed_bootstrap=False`` (extension) when the host has no ritual. Where
    BOOTSTRAP.md would be written, setup is then marked complete instead, so
    optional files a user removes later are not recreated.

    When setup evidence appears while BOOTSTRAP.md exists, the state is marked
    complete and BOOTSTRAP.md is deleted, exactly like upstream's reconcile.
    Layout ``extra_dirs`` (memory-core layout: ``user/``, ``workspace/``) are created.

    Raises :class:`WorkspaceStateMigrationRequiredError`, before touching anything, while
    upstream's retired JSON setup state is in the workspace (upstream's ensure reads its
    canonical state first and fails the same way).
    """
    root_path = _root_path(root)
    assert_no_unmigrated_workspace_state(root_path)
    root_path.mkdir(parents=True, exist_ok=True)
    stamp = _iso_from_ms(now_ms if now_ms is not None else time.time() * 1000)
    resolved = _resolve_templates(layout, templates)

    if skip_optional is True:
        skipped = set(layout.optional_files)
    elif skip_optional is False or skip_optional is None:
        skipped = set()
    elif isinstance(skip_optional, str):
        skipped = {skip_optional}
    else:
        skipped = set(skip_optional)
    # Completed setup: never recreate optional root files a user removed.
    if is_workspace_setup_completed(root_path):
        skipped.update(layout.optional_files)

    created_files: list[str] = []
    for name in layout.seed_order:
        if name in layout.optional_files and name in skipped:
            continue
        if _write_file_if_missing(root_path / name, resolved[name]):
            created_files.append(name)

    created_dirs: list[str] = []
    for dirname in layout.extra_dirs:
        target = root_path / dirname
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            created_dirs.append(dirname)

    state = read_workspace_setup_state(root_path)
    dirty = False
    bootstrap_path = root_path / layout.bootstrap_file
    bootstrap_exists = os.path.exists(bootstrap_path)
    bootstrap_seeded = False
    bootstrap_removed = False
    if not state.bootstrap_seeded_at and bootstrap_exists:
        state = replace(state, bootstrap_seeded_at=stamp)
        dirty = True

    if not state.setup_completed_at:
        repair = _reconcile_completion_state(
            root_path,
            layout=layout,
            templates=resolved,
            state=state,
            bootstrap_exists=bootstrap_exists,
            now_iso=stamp,
        )
        if repair.repaired:
            state = repair.state
            dirty = False
            bootstrap_exists = repair.bootstrap_exists
            bootstrap_removed = repair.bootstrap_removed

    if not state.bootstrap_seeded_at and not state.setup_completed_at and not bootstrap_exists:
        if workspace_profile_looks_configured(
            root_path, layout=layout, templates=resolved, include_git_evidence=True
        ):
            state = replace(state, setup_completed_at=stamp)
            dirty = True
        elif seed_bootstrap:
            wrote = _write_file_if_missing(bootstrap_path, resolved[layout.bootstrap_file])
            bootstrap_exists = True if wrote else os.path.exists(bootstrap_path)
            if wrote:
                bootstrap_seeded = True
                created_files.append(layout.bootstrap_file)
            if bootstrap_exists and not state.bootstrap_seeded_at:
                state = replace(state, bootstrap_seeded_at=stamp)
                dirty = True
        else:
            # Extension (seed_bootstrap=False): no first-run ritual means nothing
            # is pending, so setup completes here, as in the configured branch.
            state = replace(state, setup_completed_at=stamp)
            dirty = True

    if dirty:
        _write_state(root_path, state)

    return WorkspaceInitResult(
        root=root_path,
        created_files=tuple(created_files),
        created_dirs=tuple(created_dirs),
        bootstrap_seeded=bootstrap_seeded,
        bootstrap_removed=bootstrap_removed,
        state=state,
        bootstrap_status=bootstrap_status(root_path, layout),
    )


# --- legacy upstream setup state (doctor import) ---------------------------------------------


class WorkspaceStateMigrationError(RuntimeError):
    """A legacy setup file cannot be imported (doctor's refusal reasons)."""


@dataclass(frozen=True)
class LegacyWorkspaceStateMigration:
    """Outcome of :func:`migrate_legacy_workspace_state`.

    ``imported`` names the source whose markers became memory-core's state (at most one; a
    workspace that already has memory-core state only has its sources archived and removed, like
    upstream's "SQLite owns initialized milestones"). ``archives`` are the verified backups
    written beside each source before it was removed.
    """

    sources: tuple[str, ...]
    imported: str | None
    archives: tuple[str, ...]
    state: WorkspaceSetupState


_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_LEGACY_SETUP_FIELDS = frozenset(
    {"version", "bootstrapSeededAt", "setupCompletedAt", "onboardingCompletedAt"}
)


def _parse_legacy_iso_timestamp(value: object, field: str) -> str | None:
    """``parseIsoTimestamp`` (src/infra/state-migrations.workspace-setup-store.ts)."""
    if value is None:
        return None
    invalid = WorkspaceStateMigrationError(f"legacy workspace setup {field} is invalid")
    if not isinstance(value, str) or not value or not _ISO_TIMESTAMP_RE.match(value):
        raise invalid
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise invalid from exc
    return value


def parse_legacy_workspace_setup(raw: str) -> WorkspaceSetupState:
    """Port of doctor's ``parseSetup`` for a retired JSON setup file (strict, never lenient)."""
    try:
        value = json.loads(raw, parse_constant=_reject_constant)
    except ValueError as exc:
        raise WorkspaceStateMigrationError("legacy workspace setup contains invalid JSON") from exc
    if not isinstance(value, dict):
        raise WorkspaceStateMigrationError("legacy workspace setup is not an object")
    if any(key not in _LEGACY_SETUP_FIELDS for key in value):
        raise WorkspaceStateMigrationError("legacy workspace setup has an unexpected field")
    if "version" in value and (
        isinstance(value["version"], bool) or value["version"] != WORKSPACE_STATE_VERSION
    ):
        raise WorkspaceStateMigrationError("legacy workspace setup has an unsupported version")
    seeded = _parse_legacy_iso_timestamp(value.get("bootstrapSeededAt"), "bootstrap timestamp")
    completed = _parse_legacy_iso_timestamp(value.get("setupCompletedAt"), "completion timestamp")
    onboarding = _parse_legacy_iso_timestamp(
        value.get("onboardingCompletedAt"), "legacy completion timestamp"
    )
    if completed and onboarding and completed != onboarding:
        raise WorkspaceStateMigrationError(
            "legacy workspace setup has conflicting completion timestamps"
        )
    return WorkspaceSetupState(bootstrap_seeded_at=seeded, setup_completed_at=completed or onboarding)


def _read_legacy_source(path: Path) -> bytes:
    """``readBoundedRegularFile``: an unlinked regular file of at most 64 KiB, read no-follow."""
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LEGACY_WORKSPACE_SETUP_MAX_BYTES:
        raise WorkspaceStateMigrationError("legacy workspace source is not a safe regular file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size):
            raise WorkspaceStateMigrationError("legacy workspace source changed while reading")
        data = b""
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            data += chunk
    finally:
        os.close(fd)
    if len(data) != info.st_size:
        raise WorkspaceStateMigrationError("legacy workspace source ended unexpectedly")
    return data


def migrate_legacy_workspace_state(root: str | os.PathLike[str]) -> LegacyWorkspaceStateMigration:
    """Import upstream's retired JSON setup state into memory-core's state, then remove it.

    Ports the setup part of doctor's ``migrateLegacyWorkspaceState``
    (``src/infra/state-migrations.workspace-setup*.ts``): sources in priority order
    (``openclaw-workspace-state.json``, then ``.openclaw/workspace-state.json``), each read as
    an unlinked regular file of at most 64 KiB, valid UTF-8, parsed strictly
    (:func:`parse_legacy_workspace_setup`; ``onboardingCompletedAt`` becomes
    ``setupCompletedAt``). The first source is imported unless memory-core already has state;
    every source is then archived beside itself as ``<source>.migrated.<sha256>.<uuid>``
    (mode 0600, content hash verified) and removed. An interrupted upstream doctor claim
    (``<source>.doctor-importing``) is left alone and refused; so is any source that fails to
    parse, before anything is removed.
    """
    root_path = _root_path(root)
    sources = [path for path in legacy_workspace_state_paths(root_path) if _path_may_exist(path)]
    claims = [
        f"{path}{WORKSPACE_DOCTOR_CLAIM_SUFFIX}"
        for path in legacy_workspace_state_paths(root_path)
        if _path_may_exist(Path(f"{path}{WORKSPACE_DOCTOR_CLAIM_SUFFIX}"))
    ]
    if claims:
        raise WorkspaceStateMigrationError(
            "interrupted doctor claim(s) left untouched: "
            + ", ".join(claims)
            + "; restore the original setup file before migrating"
        )
    snapshots: list[tuple[Path, bytes, WorkspaceSetupState]] = []
    for source in sources:
        data = _read_legacy_source(source)
        try:
            raw = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceStateMigrationError("legacy workspace source is not valid UTF-8") from exc
        snapshots.append((source, data, parse_legacy_workspace_setup(raw)))

    imported: str | None = None
    state = _read_state_file(_state_path(root_path))
    if snapshots and state is None:
        source, _data, parsed = snapshots[0]
        _write_state(root_path, parsed)
        imported = str(source)
        state = parsed
    archives: list[str] = []
    for source, data, _parsed in snapshots:
        digest = hashlib.sha256(data).hexdigest()
        archive = Path(f"{source}.migrated.{digest}.{uuid.uuid4()}")
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise WorkspaceStateMigrationError(
                f"workspace setup backup differs from the claimed source: {archive}"
            )
        if hashlib.sha256(_read_legacy_source(source)).hexdigest() != digest:
            raise WorkspaceStateMigrationError("legacy workspace source changed while migrating")
        os.unlink(source)
        archives.append(str(archive))
    return LegacyWorkspaceStateMigration(
        sources=tuple(str(source) for source in sources),
        imported=imported,
        archives=tuple(archives),
        state=state or WorkspaceSetupState(),
    )
