"""What reaches the model, per session kind: WorkspaceContext -> PromptView and FileEntry.

Thin views over :func:`memory_core.bootstrap.build_workspace_context`. Exclusion
reasons are attributed by running the package's own filter functions one at a
time (``filter_root_memory_bootstrap_files``, ``filter_bootstrap_files_for_session``,
``filter_completed_bootstrap_file``, ``apply_context_mode_filter``), never by
re-implementing them. The Lab model gets no generic ``read`` tool, so the
bootstrap mode is resolved with ``has_bootstrap_file_access=False``; the
package still counts non-empty BOOTSTRAP.md content as file access (upstream's
hook-content rule), which the payload names.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from demo.lab_runtime import LabError, LabRuntime, LabSession
from memory_core.bootstrap import (
    WorkspaceContext,
    WorkspaceLayout,
    apply_context_mode_filter,
    build_workspace_context,
    filter_bootstrap_files_for_session,
    filter_completed_bootstrap_file,
    filter_root_memory_bootstrap_files,
    format_bootstrap_truncation_warning_lines,
    is_workspace_setup_completed,
    load_workspace_bootstrap_files,
)
from memory_core.bootstrap._js import utf16_len
from memory_core.bootstrap.files import NON_PRIVATE_SESSION_KINDS
from memory_core.bootstrap.render import prepare_context_files
from memory_core.bootstrap.budget import ContextFile
from memory_core.session_memory import SESSION_MEMORY_FILE_RE
from memory_core.workspace import MemoryWorkspace

_DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
# v2026.9.6 BootstrapContextRunKind (commitment-only is gone).
RUN_KINDS = ("default", "heartbeat", "cron")
# v2026.9.6 retired workspace files the explorer names when a workspace still has them.
RETIRED_FILE_NOTES = {
    "TOOLS.md": "v2026.9.6: TOOLS.md emekli; yerel araç notları AGENTS.md ## Tools bölümünde (migrate_tools_md)",
    "HEARTBEAT.md": "v2026.9.6: HEARTBEAT.md bootstrap dosyası değil; heartbeat görünümü okur (monitor scratch portu bekliyor)",
}
CONTEXT_MODES = ("full", "lightweight")


@dataclass(frozen=True)
class PromptOptions:
    kind: str = "main"
    run_kind: str | None = None
    context_mode: str = "full"
    context_injection: str | None = None
    max_chars: int | None = None
    total_max_chars: int | None = None
    layout: str | None = None


def prompt_options(payload: dict[str, Any], *, default_kind: str = "main") -> PromptOptions:
    kind = str(payload.get("sessionKind") or default_kind)
    run_kind = payload.get("runKind")
    if run_kind is not None and run_kind not in RUN_KINDS:
        raise LabError(400, f"runKind must be one of {', '.join(RUN_KINDS)}", code="invalid_run_kind")
    context_mode = payload.get("contextMode")
    if context_mode is None:
        context_mode = "lightweight" if payload.get("lightContext") else "full"
    if context_mode not in CONTEXT_MODES:
        raise LabError(400, "contextMode must be 'full' or 'lightweight'", code="invalid_context_mode")
    injection = payload.get("contextInjection")
    if injection is not None and injection not in ("always", "continuation-skip", "never"):
        raise LabError(
            400, "contextInjection must be always, continuation-skip or never", code="invalid_injection"
        )
    return PromptOptions(
        kind=kind,
        run_kind=run_kind,
        context_mode=context_mode,
        context_injection=injection,
        max_chars=_optional_positive_int(payload.get("maxChars"), "maxChars"),
        total_max_chars=_optional_positive_int(payload.get("totalMaxChars"), "totalMaxChars"),
        layout=payload.get("layout"),
    )


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise LabError(400, f"{name} must be a positive integer", code="invalid_number")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LabError(400, f"{name} must be a positive integer", code="invalid_number") from exc
    if parsed <= 0:
        raise LabError(400, f"{name} must be a positive integer", code="invalid_number")
    return parsed


def _run_kind(options: PromptOptions) -> str:
    if options.run_kind:
        return options.run_kind
    if options.kind == "heartbeat":
        return "heartbeat"
    if options.kind == "cron":
        return "cron"
    return "default"


def lab_workspace_context(
    lab: LabRuntime, options: PromptOptions, *, session: LabSession | None = None
) -> WorkspaceContext:
    layout = lab.layout_for(options.layout)
    if options.kind not in ("main", "group", "channel", "direct", "subagent", "cron", "heartbeat"):
        raise LabError(400, "unknown sessionKind", code="invalid_kind")
    settings = lab.settings
    return build_workspace_context(
        lab.root,
        layout=layout,
        session_kind=options.kind,  # type: ignore[arg-type]
        run_kind=options.run_kind,  # type: ignore[arg-type]
        context_mode=options.context_mode,  # type: ignore[arg-type]
        context_injection=(options.context_injection or settings.context_injection),  # type: ignore[arg-type]
        has_completed_bootstrap_turn=bool(session and session.completed_bootstrap_turn),
        has_bootstrap_file_access=False,
        max_chars=options.max_chars or settings.max_chars,
        total_max_chars=options.total_max_chars or settings.total_max_chars,
        truncation_warning_mode=settings.warning_mode,  # type: ignore[arg-type]
        seen_truncation_signatures=tuple(session.seen_truncation_signatures) if session else (),
    )


def explain_exclusions(
    lab: LabRuntime, options: PromptOptions, wc: WorkspaceContext
) -> list[dict[str, str]]:
    """Why each layout file that exists is not in Project Context, step by step."""
    layout = lab.layout_for(options.layout)
    loaded = load_workspace_bootstrap_files(lab.root, layout)
    reasons: dict[str, str] = {}

    def drop(before: list, after: list, reason: str) -> list:
        kept = {file.name for file in after}
        for file in before:
            if file.name not in kept and file.name not in reasons:
                reasons[file.name] = reason
        return after

    step = list(loaded)
    if options.kind in NON_PRIVATE_SESSION_KINDS:
        step = drop(
            step,
            filter_root_memory_bootstrap_files(step, lab.root, layout),
            f"{options.kind}: kök MEMORY.md paylaşılan oturumda yüklenmez (upstream #119198)",
        )
    allow = sorted(layout.subagent_files if options.kind == "subagent" else layout.cron_files)
    step = drop(
        step,
        filter_bootstrap_files_for_session(step, options.kind, layout, root=lab.root),  # type: ignore[arg-type]
        f"{options.kind}: yalnız {', '.join(allow)}",
    )
    step = drop(
        step,
        filter_completed_bootstrap_file(
            step, setup_completed=is_workspace_setup_completed(lab.root), root=lab.root, layout=layout
        ),
        "bootstrap tamamlandı",
    )
    step = drop(
        step,
        apply_context_mode_filter(step, context_mode=options.context_mode),  # type: ignore[arg-type]
        "lightContext (lightweight): bootstrap dosyası yok",
    )
    injected = {Path(file.path).name for file in wc.files}
    for file in step:
        if file.name in reasons or file.name in injected:
            continue
        if wc.injection_skipped:
            reasons[file.name] = "contextInjection: enjeksiyon atlandı"
        elif file.name == layout.bootstrap_file and wc.bootstrap_mode != "full":
            reasons[file.name] = f"bootstrap modu {wc.bootstrap_mode}"
        elif not file.missing and not (file.content or "").strip():
            reasons[file.name] = "boş"
        else:
            reasons[file.name] = "toplam bütçe doldu"
    return [{"name": name, "reason": reason} for name, reason in reasons.items()]


def bootstrap_mode_reason(wc: WorkspaceContext, options: PromptOptions) -> str:
    if wc.bootstrap_mode == "none":
        if wc.bootstrap_status == "complete":
            return "bootstrap tamam"
        if options.kind == "subagent":
            return "birincil çalıştırma değil (subagent)"
        return f"çalıştırma türü {_run_kind(options)}: bootstrap modu none"
    if wc.bootstrap_mode == "limited":
        return "okuma aracı yok (Lab modeli genel read aracı almaz)"
    return (
        "BOOTSTRAP.md içeriği dosya erişimi sayılır (upstream hook-content kuralı; "
        "Lab modelinde read aracı yok)"
    )


def truncation_by_name(wc: WorkspaceContext) -> dict[str, dict[str, Any]]:
    lines = format_bootstrap_truncation_warning_lines(
        wc.analysis, max_files=max(1, len(wc.analysis.truncated_files))
    )
    result: dict[str, dict[str, Any]] = {}
    for file in wc.analysis.truncated_files:
        pct = round(((file.raw_chars - file.injected_chars) / file.raw_chars) * 100) if file.raw_chars else 0
        cause = "max/total" if "total-limit" in file.causes and "per-file-limit" not in file.causes else "max/file"
        line = next((entry for entry in lines if entry.startswith(f"{file.name}:") or entry.startswith(f"{file.name} (")), "")
        result[file.name] = {
            "raw": file.raw_chars,
            "injected": file.injected_chars,
            "pct": pct,
            "cause": cause,
            "warningLine": line,
        }
    return result


def prompt_view(
    lab: LabRuntime,
    options: PromptOptions,
    wc: WorkspaceContext,
    *,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layout = lab.layout_for(options.layout)
    truncation = truncation_by_name(wc)
    files = []
    for file in wc.files:
        name = Path(file.path).name
        files.append(
            {
                "path": _relative(lab.root, file.path),
                "name": name,
                "chars": utf16_len(file.content),
                "truncated": name in truncation,
            }
        )
    view: dict[str, Any] = {
        "sessionKind": options.kind,
        "runKind": _run_kind(options),
        "contextMode": options.context_mode,
        "layout": layout.name,
        "bootstrapMode": wc.bootstrap_mode,
        "bootstrapModeReason": bootstrap_mode_reason(wc, options),
        "bootstrapStatus": wc.bootstrap_status,
        "bootstrapText": wc.bootstrap_text,
        "workspaceFilesText": wc.workspace_files_text,
        "stableText": wc.stable_text,
        "promptText": wc.prompt_text,
        "files": files,
        "excluded": explain_exclusions(lab, options, wc),
        "warnings": list(wc.warnings),
        "truncationWarningLines": list(wc.truncation_warning_lines),
        "truncationNotice": wc.truncation_notice,
        "truncationWarning": {
            "mode": lab.settings.warning_mode,
            "shown": wc.prompt_warning.warning_shown,
            "signature": wc.prompt_warning.signature,
            "truncatedFiles": sorted(truncation),
        },
        "injectionSkipped": wc.injection_skipped,
        "workspaceNotes": list(wc.workspace_notes),
        "budget": {
            "maxChars": wc.analysis.bootstrap_max_chars,
            "totalMaxChars": wc.analysis.bootstrap_total_max_chars,
            "injectedChars": wc.analysis.injected_chars,
            "rawChars": wc.analysis.raw_chars,
            "files": [
                {
                    "name": file.name,
                    "raw": file.raw_chars,
                    "injected": file.injected_chars,
                    "truncated": file.truncated,
                    "missing": file.missing,
                    "nearLimit": file.near_limit,
                    "causes": list(file.causes),
                }
                for file in wc.analysis.files
            ],
        },
        "cacheBoundary": "yalnız görsel: sohbet motoru prompt_text'i tek sistem metni olarak gönderir",
    }
    if extras:
        view.update(extras)
    return view


def _relative(root: Path, path: str) -> str:
    try:
        relative = os.path.relpath(path, os.path.abspath(root))
    except ValueError:
        return path
    return path if relative.startswith("..") else Path(relative).as_posix()


# --- explorer entries ------------------------------------------------------------------------


def _file_meta(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except OSError:
        return {"exists": False, "chars": 0, "bytes": 0, "mtimeMs": None, "sha256": None}
    if not path.is_file() or path.is_symlink():
        return {"exists": True, "chars": 0, "bytes": info.st_size, "mtimeMs": info.st_mtime_ns // 1_000_000, "sha256": None}
    raw = path.read_bytes() if info.st_size <= 2 * 1024 * 1024 else b""
    text = raw.decode("utf-8", errors="replace")
    return {
        "exists": True,
        "chars": utf16_len(text),
        "bytes": info.st_size,
        "mtimeMs": info.st_mtime_ns // 1_000_000,
        "sha256": hashlib.sha256(raw).hexdigest() if raw or info.st_size == 0 else None,
    }


def render_order(layout: WorkspaceLayout) -> list[str]:
    prepared = prepare_context_files((ContextFile(name, "") for name in layout.load_order), layout)
    return [file.path for file in prepared.ordered]


def file_entries(lab: LabRuntime, options: PromptOptions) -> list[dict[str, Any]]:
    """FileEntry[] for the explorer: layout files, memory/, extension folders, hidden stores."""
    layout = lab.layout_for(options.layout)
    wc = lab_workspace_context(lab, options, session=lab.sessions.get(options.kind))
    injected = {Path(file.path).name for file in wc.files}
    missing = {file.name for file in wc.bootstrap_files if file.missing}
    unreadable = {
        file.name: file.unreadable_reason for file in wc.bootstrap_files if file.unreadable_reason
    }
    excluded = {entry["name"]: entry["reason"] for entry in explain_exclusions(lab, options, wc)}
    truncation = truncation_by_name(wc)
    order = render_order(layout)
    entries: list[dict[str, Any]] = []
    for index, name in enumerate(layout.load_order, start=1):
        path = lab.root / name
        meta = _file_meta(path)
        badges: list[str] = []
        entry: dict[str, Any] = {"path": name, "kind": "bootstrap", **meta}
        if name in layout.extension_files:
            entry["kind"] = "extension"
            badges.append("extension")
        if not meta["exists"]:
            # USER.md, MEMORY.md and the extensions are skipped when absent (no [MISSING]).
            if name in layout.skip_absent_files:
                badges.append("absent")
            else:
                badges.append("missing")
        if name in unreadable:
            badges.append("unreadable")
            entry["unreadableReason"] = unreadable[name]
        if name in injected:
            badges.insert(0, "injected")
        if name in truncation:
            badges.append("truncated")
            entry["truncation"] = truncation[name]
        if name in missing and "missing" not in badges:
            badges.append("missing")
        if name in excluded:
            reason = excluded[name]
            if reason == "boş":
                badges.append("empty")
            else:
                badges.append("excluded")
            entry["excludedReason"] = reason
        if name == layout.bootstrap_file and meta["exists"] and wc.bootstrap_status == "pending":
            badges.append("pending")
        entry["badges"] = badges
        entry["loadIndex"] = index
        entry["renderIndex"] = order.index(name) + 1 if name in order else None
        changed = lab.snapshots.last_turn_changed(name)
        if changed is not None:
            entry["changedInTurn"] = changed
        # BOOTSTRAP.md is listed only while it exists; other absent files show their badge.
        if meta["exists"] or name != layout.bootstrap_file:
            entries.append(entry)
    entries.extend(_outside_layout_entries(lab, layout))
    entries.extend(_memory_entries(lab))
    entries.extend(_extension_dir_entries(lab, layout))
    entries.extend(_hidden_entries(lab))
    return entries


def _outside_layout_entries(lab: LabRuntime, layout: WorkspaceLayout) -> list[dict[str, Any]]:
    entries = []
    if not lab.root.is_dir():
        return entries
    for path in sorted(lab.root.iterdir()):
        if path.name.startswith(".") or not path.is_file() or path.name in layout.load_order:
            continue
        badges = ["outside_layout"]
        entry: dict[str, Any] = {"path": path.name, "kind": "bootstrap", **_file_meta(path)}
        if path.name in RETIRED_FILE_NOTES:
            badges.append("retired")
            entry["retiredNote"] = RETIRED_FILE_NOTES[path.name]
            if path.name == "TOOLS.md":
                entry["migration"] = "tools_md"
        entry["badges"] = badges
        entry["excludedReason"] = RETIRED_FILE_NOTES.get(path.name, "etkin düzen bu dosyayı yüklemez")
        entries.append(entry)
    return entries


def _memory_entries(lab: LabRuntime) -> list[dict[str, Any]]:
    memory_dir = lab.root / "memory"
    entries: list[dict[str, Any]] = []
    if not memory_dir.is_dir():
        return entries
    entries.append(
        {"path": "memory", "kind": "folder", "exists": True, "chars": 0, "bytes": 0,
         "mtimeMs": None, "sha256": None, "badges": [], "note": "indexed, not injected"}
    )
    today = f"{lab.today()}.md"
    yesterday = f"{lab.yesterday()}.md"
    workspace = MemoryWorkspace(lab.root)
    discovered = sorted(
        (
            file.rel_path
            for file in workspace.discover_memory_files()
            if file.rel_path.startswith("memory/")
            and not any(part.startswith(".") for part in file.rel_path.split("/"))
        ),
        reverse=True,
    )
    for rel_path in discovered:
        name = rel_path.rsplit("/", 1)[-1]
        if _DAILY_RE.match(name) and rel_path.count("/") == 1:
            kind = "memory_daily"
            badges = ["today"] if name == today else ["yesterday"] if name == yesterday else []
        elif SESSION_MEMORY_FILE_RE.match(name) and rel_path.count("/") == 1:
            kind = "memory_session"
            badges = ["session"]
        else:
            kind = "memory_other"
            badges = []
        entry = {"path": rel_path, "kind": kind, **_file_meta(lab.root / rel_path), "badges": badges}
        changed = lab.snapshots.last_turn_changed(rel_path)
        if changed is not None:
            entry["changedInTurn"] = changed
        entries.append(entry)
    return entries


def _extension_dir_entries(lab: LabRuntime, layout: WorkspaceLayout) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for dirname in ("user", "workspace"):
        folder = lab.root / dirname
        if not folder.is_dir() or folder.is_symlink():
            continue
        in_layout = dirname in layout.extra_dirs
        entries.append(
            {"path": dirname, "kind": "folder", "exists": True, "chars": 0, "bytes": 0,
             "mtimeMs": None, "sha256": None,
             "badges": ["extension"] if in_layout else ["outside_layout"],
             "note": "not injected, not indexed"}
        )
        for path in sorted(folder.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            rel_path = path.relative_to(lab.root).as_posix()
            entries.append(
                {"path": rel_path, "kind": "extension", **_file_meta(path),
                 "badges": ["extension"] if in_layout else ["outside_layout"]}
            )
    return entries


def _hidden_entries(lab: LabRuntime) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    dreams = lab.root / "memory" / ".dreams"
    if dreams.is_dir() and not dreams.is_symlink():
        for path in sorted(dreams.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            entries.append(
                {"path": path.relative_to(lab.root).as_posix(), "kind": "hidden",
                 **_file_meta(path), "badges": [], "note": "consolidation store"}
            )
    return entries
