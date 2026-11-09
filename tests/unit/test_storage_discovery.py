"""Current native discovery regressions, independent of the historical oracle."""
from copy import deepcopy
import errno
import os
from pathlib import Path

import pytest

from equivalence.storage_discovery import build_storage_discovery_cases, run_storage_discovery
from memory_core.workspace import MemorySourceScanError, MemoryWorkspace, list_memory_files


def test_user_profile_is_a_default_indexed_root(tmp_path: Path):
    (tmp_path / "USER.md").write_text("User prefers concise answers.", encoding="utf-8")
    files = MemoryWorkspace(tmp_path).discover_memory_files()
    assert [(entry.rel_path, entry.source) for entry in files] == [("USER.md", "memory")]


def test_tree_is_globally_sorted_by_utf16_after_fixed_roots(tmp_path: Path):
    names = ["memory/a/nested.md", "memory/a.md", "memory/\ue000.md", "memory/\U00010000.md",
             "USER.md", "MEMORY.md"]
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("note", encoding="utf-8")
    assert [path.relative_to(tmp_path).as_posix() for path in list_memory_files(tmp_path)] == [
        "MEMORY.md", "USER.md", "memory/a.md", "memory/a/nested.md",
        "memory/\U00010000.md", "memory/\ue000.md",
    ]


def test_root_operational_failure_is_not_a_successful_empty_scan(tmp_path: Path, monkeypatch):
    real_scan = os.scandir

    def denied(path):
        if path == tmp_path:
            raise PermissionError(errno.EACCES, "permission denied", str(path))
        return real_scan(path)

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(MemorySourceScanError) as caught:
        list_memory_files(tmp_path)
    assert caught.value.code == "EACCES"
    assert caught.value.path == tmp_path
    assert isinstance(caught.value.__cause__, PermissionError)
    assert caught.value.cause is caught.value.__cause__
    assert str(caught.value) == f"memory source scan failed at {tmp_path} (EACCES): {caught.value.cause}"


def test_failed_subdirectory_cannot_publish_partial_discovery(tmp_path: Path, monkeypatch):
    (tmp_path / "memory" / "blocked").mkdir(parents=True)
    (tmp_path / "memory" / "accessible.md").write_text("accessible", encoding="utf-8")
    real_scan = os.scandir

    def denied(path):
        if path == tmp_path / "memory" / "blocked":
            raise PermissionError(errno.EACCES, "permission denied", str(path))
        return real_scan(path)

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(MemorySourceScanError) as caught:
        list_memory_files(tmp_path)
    assert caught.value.path == tmp_path / "memory" / "blocked"
    assert caught.value.code == "EACCES"


def test_root_stat_io_failure_is_reported(tmp_path: Path, monkeypatch):
    real_stat = os.lstat

    def failed(path, *args, **kwargs):
        if path == tmp_path / "USER.md":
            raise OSError(errno.EIO, "I/O error", str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", failed)
    with pytest.raises(MemorySourceScanError) as caught:
        list_memory_files(tmp_path)
    assert caught.value.path == tmp_path / "USER.md"
    assert caught.value.code == "EIO"


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_missing_or_non_directory_workspace_is_not_an_operational_failure(tmp_path: Path, kind):
    root = tmp_path / "workspace"
    if kind == "file":
        root.write_text("file", encoding="utf-8")
    assert list_memory_files(root) == []


def test_fixture_keeps_real_symlink_and_fifo_boundaries():
    cases = {case["id"]: case for case in build_storage_discovery_cases()}
    symlinks = cases["discovery-symlink-files-and-directories"]["input"]
    assert run_storage_discovery(symlinks) == {
        "snapshots": [{"files": ["memory/real/note.md"]}],
    }
    fifos = cases["discovery-fifos"]["input"]
    assert run_storage_discovery(fifos) == {"snapshots": [{"files": ["memory/note.md"]}]}


def test_disappearing_directory_keeps_other_sources():
    case = next(case for case in build_storage_discovery_cases()
                if case["id"] == "discovery-disappearing-directory-during-scan")
    assert run_storage_discovery(case["input"]) == {
        "snapshots": [{"files": ["memory/keep.md"]}],
    }


def test_injected_fixture_failures_restore_os_functions_and_preserve_inputs():
    case = next(case for case in build_storage_discovery_cases()
                if case["id"] == "discovery-nested-operational-error")
    before = deepcopy(case)
    scan, file_stat = os.scandir, os.lstat
    assert run_storage_discovery(case["input"]) == {"snapshots": [{"error": {
        "type": "MemorySourceScanError", "code": "EACCES", "path": "$FIXTURE/workspace/memory/blocked",
        "message": "memory source scan failed at $FIXTURE/workspace/memory/blocked (EACCES): injected filesystem failure",
        "cause": {"type": "Error", "code": "EACCES", "path": "$FIXTURE/workspace/memory/blocked",
                  "message": "injected filesystem failure", "cause": None},
    }}]}
    assert os.scandir is scan and os.lstat is file_stat
    assert case == before


def test_discovery_registry_keeps_coverage_unclaimed_until_complete_native_review():
    cases = build_storage_discovery_cases()
    assert cases == build_storage_discovery_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert len(cases) == 76
    assert all(case["requirement"] == "storage.discovery" and "storage.discovery.outcomes" in case["covers"] for case in cases)
    assert sum("storage.discovery.boundaries" in case["covers"] for case in cases) == 13
