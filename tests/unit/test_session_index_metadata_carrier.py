"""Session indexing retains source-backed coordinates, identity and trust facts."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile
from memory_core.session_entry import hash_session_entry_snapshot
from memory_core.workspace import MemoryFile, MemoryWorkspace


def _write_store(state: Path, rows: dict, transcript: bytes | None = None) -> Path:
    directory = state / "agents" / "main" / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sessions.json").write_text(json.dumps(rows), encoding="utf-8")
    for entry in rows.values():
        filename = entry.get("sessionFile") if isinstance(entry, dict) else None
        if isinstance(filename, str) and "/" not in filename and "\\" not in filename:
            path = directory / filename
            if not path.exists():
                path.write_bytes(transcript if transcript is not None else b'\n')
                os.utime(path, ns=(1_767_225_600_123_000_000, 1_767_225_600_123_000_000))
    return directory


def _message(role: str, content: str, *, owner: bool = False, tainted: bool = False) -> dict:
    return {"type": "message", "message": {
        "role": role, "content": content,
        "__openclaw": {"senderIsOwner": owner, "turnTainted": tainted},
    }}


def test_workspace_carries_exact_projection_hash_coordinates_and_provenance(tmp_path):
    state = tmp_path / "state"
    transcript = (
        '{"type":"session","id":"s1"}\n\nmalformed JSON\n'
        + json.dumps(_message("user", "A durable fact", owner=True)) + "\n\n"
        + json.dumps(_message("assistant", "Remembered")) + "\n"
    ).encode()
    _write_store(state, {"agent:main:main": {"sessionFile": "s1.jsonl"}}, transcript)

    files = MemoryWorkspace(tmp_path / "workspace", openclaw_state_dir=state).discover_session_transcript_files()
    file, = files
    entry = file.index_entry
    assert entry is not None
    assert file.index_text == entry.content == "User: A durable fact\nAssistant: Remembered"
    assert not file.index_text.endswith("\n")
    assert entry.line_map == [4, 6]
    assert entry.line_provenance == [
        {"originClass": "owner", "sessionKind": "interactive", "observedAt": 1_767_225_600_123},
        {"originClass": "agent", "sessionKind": "interactive", "observedAt": 1_767_225_600_123},
    ]
    assert entry.reset_recall_cutoff == {"state": "absent"}
    assert entry.hash == hash_session_entry_snapshot(
        entry.content, entry.line_map, entry.message_timestamps_ms,
        entry.line_provenance, entry.reset_recall_cutoff,
    )


def test_compatibility_text_keeps_newline_without_polluting_native_entry(tmp_path):
    transcript = (json.dumps(_message("user", "Keep this")) + "\n").encode()
    _write_store(tmp_path, {"agent:main:main": {"sessionFile": "s1.jsonl"}}, transcript)
    corpus = MemoryCoreSessionCorpus(tmp_path)
    file, = corpus.discover_files()

    assert corpus.read_index_text(file) == "User: Keep this\n"
    assert corpus.read_index_entry(file).content == "User: Keep this"


def test_identical_rendered_text_with_changed_origin_has_a_new_source_hash(tmp_path):
    path = _write_store(tmp_path, {"agent:main:main": {"sessionFile": "s1.jsonl"}}) / "s1.jsonl"
    corpus = MemoryCoreSessionCorpus(tmp_path)
    file, = corpus.discover_files()
    path.write_text(json.dumps(_message("user", "Same words", owner=True)), encoding="utf-8")
    fixed_ns = 1_767_225_600_123_000_000
    os.utime(path, ns=(fixed_ns, fixed_ns))
    before = corpus.read_index_entry(file)
    path.write_text(json.dumps(_message("user", "Same words", owner=False)), encoding="utf-8")
    os.utime(path, ns=(fixed_ns, fixed_ns))
    after = corpus.read_index_entry(file)

    assert before.content == after.content
    assert before.line_map == after.line_map
    assert before.message_timestamps_ms == after.message_timestamps_ms
    assert before.line_provenance[0]["observedAt"] == after.line_provenance[0]["observedAt"]
    assert before.line_provenance[0]["originClass"] == "owner"
    assert after.line_provenance[0]["originClass"] == "untrusted"
    assert before.hash != after.hash


def test_store_classification_changes_hash_without_changing_file_or_text(tmp_path):
    rows = {"agent:main:main": {"sessionFile": "s1.jsonl"}}
    _write_store(tmp_path, rows, (json.dumps(_message("user", "Same words")) + "\n").encode())
    corpus = MemoryCoreSessionCorpus(tmp_path)
    before = corpus.read_index_entry(corpus.discover_files()[0])
    rows["agent:main:main"]["heartbeatIsolatedBaseSessionKey"] = "agent:main:main"
    _write_store(tmp_path, rows)
    after = corpus.read_index_entry(corpus.discover_files()[0])

    assert before.content == after.content
    assert before.session_kind == "interactive"
    assert after.session_kind == "heartbeat"
    assert before.hash != after.hash


@pytest.mark.parametrize("key,metadata,kind,dreaming,cron", [
    ("agent:main:main", {}, "interactive", False, False),
    ("agent:main:channel:peer", {}, "interactive", False, False),
    ("agent:main:main", {"heartbeatIsolatedBaseSessionKey": "\ufeffbase\u00a0"}, "heartbeat", False, False),
    ("agent:main:main", {"heartbeatIsolatedBaseSessionKey": " \t"}, "interactive", False, False),
    ("agent:main:subagent:child", {}, "subagent", False, False),
    ("agent:main:child", {"spawnedBy": "agent:main:main"}, "subagent", False, False),
    ("agent:main:child", {"spawnedBy": {}}, "subagent", False, False),
    ("agent:main:dreaming-narrative-run", {}, "subagent", True, False),
    ("agent:main:child", {"spawnedBy": "agent:main:dreaming-narrative-run"}, "subagent", True, False),
    ("agent:main:cron:job:run:instance", {}, "cron", False, True),
    ("agent:main:child", {"parentSessionKey": "agent:main:cron:gone:run:instance"}, "cron", False, True),
    ("agent:main:child", {"spawnedBy": "agent:main:cron:gone:run:instance", "heartbeatIsolatedBaseSessionKey": "base"}, "cron", False, True),
])
def test_session_kind_comes_from_authoritative_store_lineage(tmp_path, key, metadata, kind, dreaming, cron):
    _write_store(tmp_path, {key: {"sessionFile": "s1.jsonl", **metadata}})
    file, = MemoryCoreSessionCorpus(tmp_path).discover_files()

    assert file.session_key == key
    assert file.session_kind == kind
    assert file.generated_by_dreaming_narrative is dreaming
    assert file.generated_by_cron_run is cron


def test_cron_lineage_propagates_across_registered_parent_and_terminates_cycles(tmp_path):
    _write_store(tmp_path, {
        "agent:main:cron:job:run:instance": {},
        "agent:main:child": {"sessionFile": "child.jsonl", "parentSessionKey": "agent:main:cron:job:run:instance"},
        "agent:main:grandchild": {"sessionFile": "grandchild.jsonl", "spawnedBy": "agent:main:child"},
        "agent:main:cycle-a": {"sessionFile": "cycle-a.jsonl", "parentSessionKey": "agent:main:cycle-b"},
        "agent:main:cycle-b": {"sessionFile": "cycle-b.jsonl", "parentSessionKey": "agent:main:cycle-a"},
    })
    files = {file.session_key: file for file in MemoryCoreSessionCorpus(tmp_path).discover_files()}

    assert files["agent:main:child"].generated_by_cron_run
    assert files["agent:main:grandchild"].session_kind == "cron"
    assert files["agent:main:cycle-a"].session_kind == "interactive"
    assert files["agent:main:cycle-b"].generated_by_cron_run is False


def test_unmapped_file_does_not_infer_interactive_or_cron_from_its_name(tmp_path):
    path = tmp_path / "cron-run.jsonl"
    path.write_text(json.dumps(_message("user", "Fact")), encoding="utf-8")
    file = SessionCorpusFile("sessions/main/cron-run.jsonl", path)
    entry = MemoryCoreSessionCorpus(tmp_path).read_index_entry(file)

    assert entry.session_kind == "unknown"
    assert entry.content == "User: Fact"
    assert entry.generated_by_cron_run is False


def test_jsonl_decode_matches_replacement_semantics_and_retains_raw_line_ordinals(tmp_path):
    transcript = b'\r\n{"type":"message","message":{"role":"user","content":"invalid \xff"}}\r\n'
    _write_store(tmp_path, {"agent:main:main": {"sessionFile": "s1.jsonl"}}, transcript)
    corpus = MemoryCoreSessionCorpus(tmp_path)
    entry = corpus.read_index_entry(corpus.discover_files()[0])

    assert entry.content == "User: invalid \ufffd"
    assert entry.line_map == [2]


def test_explicit_host_file_projection_remains_optional_for_legacy_callers(tmp_path):
    file = MemoryFile("sessions/main/s1.jsonl", tmp_path / "s1.jsonl", "sessions", "User: text\n")
    assert file.index_entry is None
    assert replace(file, index_text="User: another").index_text == "User: another"


@pytest.mark.parametrize("mtime,size", [(0, 0), (1_790_000_000_123, 713)])
def test_authoritative_transcript_metadata_never_stats_a_logical_sqlite_locator(
    tmp_path, monkeypatch, mtime, size,
):
    from memory_core.index.sqlite_store import read_index_source
    from memory_core.session_entry import build_session_entry

    locator = tmp_path / "agent:main:dm:reader"
    entry = build_session_entry([
        _message("user", "Cobalt catalog fact", owner=True),
    ], mtime_ms=mtime, session_kind="interactive")
    file = MemoryFile(
        "sessions/main/recorded-id.jsonl", locator, "sessions",
        index_entry=entry, index_mtime_ms=mtime, index_size=size,
    )
    stat = Path.stat

    def guarded_stat(path, *args, **kwargs):
        assert path != locator, "An accessor identity is not a filesystem source"
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)
    snapshot = read_index_source(file)
    assert (snapshot.mtime, snapshot.size) == (mtime, size)
    assert snapshot.text == "User: Cobalt catalog fact"
    assert snapshot.hash == entry.hash
    assert snapshot.index_entry.line_provenance == entry.line_provenance


def test_explicit_session_activity_reaches_the_published_index(tmp_path):
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.session_entry import build_session_entry

    activity = 1_790_000_000_123
    entry = build_session_entry([
        _message("user", "Cobalt catalog fact", owner=True),
    ], mtime_ms=activity, session_kind="interactive")
    file = MemoryFile(
        "sessions/main/recorded-id.jsonl", tmp_path / "logical-session", "sessions",
        index_entry=entry, index_mtime_ms=activity, index_size=713,
    )

    class CatalogWorkspace(MemoryWorkspace):
        def discover_indexable_files(self):
            return [file]

    config = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False))
    store = SQLiteMemoryStore(config, None)
    store.reindex(CatalogWorkspace(tmp_path))
    stored, = store.read_published_index()["sources"]
    assert (stored["mtime"], stored["size"]) == (activity, 713)
    results = store.search("Cobalt", min_score=0)
    assert [hit.path for hit in results] == [file.rel_path]
    assert results[0].provenance["originClass"] == "owner"
