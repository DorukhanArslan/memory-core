"""Automatic bootstrap memory classification through real paths and trust records.

Ports the built-in workspace-path-classifier and memory-path-provenance owners.
The SDK uses its concrete artifact provenance store; no callback provides trust
classes or a preselected list of bootstrap files.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memory_core.bootstrap._js import js_trim

# This is the pinned upstream plugin config identifier, independent of SDK branding.
OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID = "memory-core"

if TYPE_CHECKING:
    from memory_core.bootstrap.files import WorkspaceBootstrapFile
    from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore


class UnsupportedBootstrapMemoryRuntimeError(ValueError):
    """A host selected a plugin runtime the portable SDK does not implement."""


def _builtin_memory_runtime_available(config: Mapping[str, Any] | None) -> bool:
    if config is None:
        return True
    plugins = config.get("plugins")
    if plugins is None:
        return True
    if not isinstance(plugins, Mapping):
        raise TypeError("Bootstrap plugin configuration must be a mapping")
    if plugins.get("enabled") is False:
        return False
    slots = plugins.get("slots")
    selection = slots.get("memory") if isinstance(slots, Mapping) else None
    selection = js_trim(selection) if isinstance(selection, str) else ""
    if selection.lower() == "none":
        return False
    selected = selection or OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID
    denied = plugins.get("deny")
    if isinstance(denied, (list, tuple)) and selected in {
        js_trim(item).lower() for item in denied if isinstance(item, str)
    }:
        return False
    entries = plugins.get("entries")
    enabled = None
    if isinstance(entries, Mapping):
        for key, entry in entries.items():
            if isinstance(key, str) and js_trim(key).lower() == selected and isinstance(entry, Mapping):
                if type(entry.get("enabled")) is bool:
                    enabled = entry["enabled"]
    if enabled is False:
        return False
    if selected != OPENCLAW_BUILTIN_MEMORY_PLUGIN_ID:
        raise UnsupportedBootstrapMemoryRuntimeError(
            f"Bootstrap memory runtime {selected!r} is not implemented by the portable SDK"
        )
    return True


def classify_workspace_memory_paths(
    workspace_dir: str | os.PathLike[str],
    relative_paths: Sequence[str],
    *,
    artifact_provenance: MemoryArtifactProvenanceStore | None = None,
) -> list[dict[str, str]]:
    """Classify current physical workspace paths using the real recorded owner.

    Missing paths, escapes and failed realpath resolution are untrusted. The
    guarded bootstrap reader separately controls which file bytes can be read.
    Recorded quarantine remains authoritative when a file's content changes.
    """
    # Import after bootstrap modules are initialized: index preparation itself
    # uses the package's shared JavaScript text helpers.
    from memory_core.index.preparation import classify_memory_path

    root = Path(workspace_dir)
    try:
        physical_root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return [{"relativePath": relative, "originClass": "untrusted"} for relative in relative_paths]
    classifications = []
    for relative in relative_paths:
        try:
            physical = (root / relative).resolve(strict=True)
            canonical = physical.relative_to(physical_root).as_posix()
            if physical == physical_root:
                raise ValueError("The workspace root is not strictly inside itself")
        except (OSError, RuntimeError, ValueError):
            classifications.append({"relativePath": relative, "originClass": "untrusted"})
            continue
        classification = classify_memory_path(canonical)
        if classification["originClass"] == "agent" and artifact_provenance is not None:
            recorded = artifact_provenance.read(workspace_dir=root, relative_path=canonical)
            if recorded is not None:
                classification = classify_memory_path(canonical, recorded_origin=recorded.origin_class)
        classifications.append({"relativePath": relative, "originClass": classification["originClass"]})
    return classifications


def filter_automatic_bootstrap_memory(
    files: Sequence[WorkspaceBootstrapFile],
    *,
    root: str | os.PathLike[str],
    config: Mapping[str, Any] | None = None,
    artifact_provenance: MemoryArtifactProvenanceStore | None = None,
    warn: Callable[[str], None] | None = None,
) -> list[WorkspaceBootstrapFile]:
    """Run the selected built-in memory owner before the session filters."""
    candidates = [file for file in files if not file.missing and file.name in {"MEMORY.md", "USER.md"}]
    if not candidates or (config is None and artifact_provenance is None):
        return list(files)
    if not _builtin_memory_runtime_available(config):
        return list(files)
    workspace = os.path.abspath(os.fspath(root))
    paths = [os.path.relpath(file.path, workspace).replace(os.sep, "/") for file in candidates]
    try:
        classified = classify_workspace_memory_paths(workspace, paths, artifact_provenance=artifact_provenance)
    except Exception as error:
        if warn is not None:
            warn(f"excluding automatic memory context: {type(error).__name__}: {error}")
        excluded = {id(file) for file in candidates}
    else:
        origins = {item["relativePath"]: item["originClass"] for item in classified}
        excluded = {id(file) for file, relative in zip(candidates, paths, strict=True)
                    if origins.get(relative) not in {"owner", "agent"}}
    return [file for file in files if id(file) not in excluded]
