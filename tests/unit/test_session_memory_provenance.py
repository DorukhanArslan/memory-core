"""Session hook provenance composition (handler.ts:253-271, OpenClaw v2026.9.6)."""

import hashlib
import errno
from pathlib import Path

import pytest

from memory_core import session_memory
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import (
    MemoryArtifactProvenanceFullError,
    MemoryArtifactProvenanceStore,
)
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState
from memory_core.session_memory import save_session_memory

# Existing session-memory save fixtures from handler.test.ts.
NOW_MS = 1767241815000
SESSION_KEY = "agent:main:main"
SESSION_ID = "test-123"


def _save(root: Path, store: MemoryArtifactProvenanceStore, **options):
    return save_session_memory(
        root, session_key=SESSION_KEY, session_id=SESSION_ID, now_ms=NOW_MS,
        artifact_provenance=store, **options,
    )


@pytest.mark.parametrize("owner,origin", [(True, "agent"), (False, "untrusted")])
def test_save_records_the_projection_trust_and_file_hash(tmp_path: Path, owner, origin):
    root = tmp_path / "ws"
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    saved = _save(root, store, messages=[
        {"role": "user", "content": "Hello there", "__openclaw": {"senderIsOwner": owner}},
        {"role": "assistant", "content": "Hi! How can I help?"},
    ])
    record = store.read(workspace_dir=root, relative_path=saved.rel_path)
    assert record is not None
    assert record.origin_class == saved.origin_class == origin
    assert record.file_hash == hashlib.sha256(saved.path.read_bytes()).hexdigest()
    assert (record.session_id, record.session_key, record.observed_at) == (
        SESSION_ID, SESSION_KEY, NOW_MS,
    )


def test_save_reserves_trust_before_publishing(tmp_path: Path, monkeypatch):
    root = tmp_path / "ws"
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    publish = session_memory._publish_new_file

    def checked_publish(directory, filename, data):
        assert not (directory / filename).exists()
        record = store.read(workspace_dir=root, relative_path=f"memory/{filename}")
        assert record is not None and record.file_hash == hashlib.sha256(data).hexdigest()
        return publish(directory, filename, data)

    monkeypatch.setattr(session_memory, "_publish_new_file", checked_publish)
    assert _save(root, store).path.exists()


def test_failed_publish_rolls_back_trust(tmp_path: Path, monkeypatch):
    root = tmp_path / "ws"
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")

    def failed_publish(*args):
        assert len(store.list(root)) == 1
        raise OSError("disk full")

    monkeypatch.setattr(session_memory, "_publish_new_file", failed_publish)
    with pytest.raises(OSError, match="disk full"):
        _save(root, store)
    assert store.list(root) == []
    assert list((root / "memory").iterdir()) == []


def test_full_trust_store_does_not_publish_untracked_file(tmp_path: Path):
    root = tmp_path / "ws"
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite", max_entries=0)
    with pytest.raises(MemoryArtifactProvenanceFullError):
        _save(root, store)
    assert list((root / "memory").iterdir()) == []


def test_lost_filename_race_rolls_back_before_retry(tmp_path: Path, monkeypatch):
    root = tmp_path / "ws"
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    publish = session_memory._publish_new_file
    attempts = []

    def lose_first_race(directory, filename, data):
        attempts.append(filename)
        if len(attempts) == 1:
            (directory / filename).write_text("", encoding="utf-8")
            return False
        assert store.read(workspace_dir=root, relative_path=f"memory/{attempts[0]}") is None
        return publish(directory, filename, data)

    monkeypatch.setattr(session_memory, "_publish_new_file", lose_first_race)
    saved = _save(root, store)
    assert attempts == ["2026-01-01-0430.md", "2026-01-01-0430-2.md"]
    assert saved.rel_path == "memory/2026-01-01-0430-2.md"
    assert [path for path, _ in store.list(root)] == [saved.rel_path]
    assert (root / "memory" / attempts[0]).read_text() == ""


def test_host_new_session_forwards_its_trust_store(tmp_path: Path):
    root = tmp_path / "ws"
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    kit = HostKit(memory, now_ms=lambda: NOW_MS, artifact_provenance=store)
    result = kit.on_new_session(
        SessionState(session_key=SESSION_KEY, session_id=SESSION_ID),
        command="new", session_id="next",
        transcript=[{"role": "user", "content": "Hello there"}],
    )
    record = store.read(workspace_dir=root, relative_path=result.saved.rel_path)
    assert record is not None and record.origin_class == "untrusted"


def test_failed_fallback_fsync_removes_partial_file_before_trust_rollback(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    fsync = session_memory.os.fsync
    calls = []

    def no_hard_links(*args):
        raise OSError(errno.EPERM, "hard links not supported")

    def fail_final_fsync(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("disk full")
        fsync(fd)

    monkeypatch.setattr(session_memory.os, "link", no_hard_links)
    monkeypatch.setattr(session_memory.os, "fsync", fail_final_fsync)
    with pytest.raises(OSError, match="disk full"):
        _save(root, store)
    assert list((root / "memory").iterdir()) == []
    assert store.list(root) == []


def test_temporary_cleanup_failure_keeps_published_file_tracked(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    unlink = session_memory.os.unlink

    def fail_temporary_cleanup(path, *args, **kwargs):
        if str(path).endswith(".tmp"):
            raise OSError("cleanup failed")
        unlink(path, *args, **kwargs)

    monkeypatch.setattr(session_memory.os, "unlink", fail_temporary_cleanup)
    saved = _save(root, store)
    record = store.read(workspace_dir=root, relative_path=saved.rel_path)
    assert record is not None and record.file_hash == hashlib.sha256(saved.path.read_bytes()).hexdigest()
