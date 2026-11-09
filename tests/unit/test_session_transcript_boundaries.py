"""Real source snapshots retain coordinates and distinguish absence from storage failure."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile
from memory_core.workspace import MemoryWorkspace


MTIME_NS = 1_790_000_000_123_000_000


def _message(text: str, entry_id: str = 'message', *, role: str = 'user', parent=None):
    return {'type': 'message', 'id': entry_id, 'parentId': parent,
            'message': {'role': role, 'content': text, '__openclaw': {'senderIsOwner': True}}}


def _compress(data: bytes) -> bytes:
    if sys.version_info >= (3, 14):
        from compression import zstd
        return zstd.compress(data)
    import zstandard
    return zstandard.ZstdCompressor().compress(data)


def _source(tmp_path, data: bytes, *, compressed=False):
    filename = 'recorded.jsonl.reset.2026-11-09T00-00-00.000Z' + ('.zst' if compressed else '')
    path = tmp_path / filename
    path.write_bytes(_compress(data) if compressed else data)
    os.utime(path, ns=(MTIME_NS, MTIME_NS))
    file = SessionCorpusFile(f'sessions/main/{filename}', path, session_kind='interactive',
                             artifact_kind='archive-artifact')
    return MemoryCoreSessionCorpus(tmp_path), file


@pytest.mark.parametrize('compressed', [False, True])
def test_archive_source_keeps_blank_malformed_and_nonrecord_line_ordinals(tmp_path, compressed):
    first = json.dumps(_message('Cedar \U0001f600 first', 'first'), ensure_ascii=False).encode()
    last = json.dumps(_message('last', 'last', role='assistant')).encode()
    data = b'\n{bad JSON}\nnull\n' + first + b'\r\n\n[]\n' + last + b'\n'
    corpus, file = _source(tmp_path, data, compressed=compressed)
    entry = corpus.read_index_entry(file)
    assert entry.content == 'User: Cedar \U0001f600 first\nAssistant: last'
    assert entry.line_map == [4, 7]
    assert entry.reset_recall_cutoff == {'state': 'absent'}
    assert entry._extra['size'] == file.abs_path.stat().st_size
    assert entry._extra['mtimeMs'] == MTIME_NS / 1_000_000
    assert corpus.read_index_text(file) == entry.content + '\n'


def test_invalid_compressed_frame_is_absence_but_malformed_jsonl_is_a_readable_empty_source(tmp_path):
    corpus, archive = _source(tmp_path, b'not JSON\n')
    empty = corpus.read_index_entry(archive)
    assert empty is not None and empty.content == '' and empty.line_map == []
    invalid = replace(archive, abs_path=tmp_path / 'invalid.jsonl.reset.2026-11-09T00-00-00Z.zst')
    invalid.abs_path.write_bytes(b'not a Zstandard frame')
    assert corpus.read_index_entry(invalid) is None
    assert corpus.read_source_entry(invalid) is None
    assert corpus.read_index_text(invalid) == ''


def test_disappeared_and_nonregular_file_sources_return_absence(tmp_path):
    corpus, file = _source(tmp_path, json.dumps(_message('stored')).encode())
    assert corpus.read_source_entry(file)['content'] == 'User: stored'
    file.abs_path.unlink()
    assert corpus.read_index_entry(file) is None
    assert corpus.read_source_entry(file) is None
    file.abs_path.mkdir()
    assert corpus.read_index_entry(file) is None


def test_permission_error_in_file_reader_does_not_invent_an_empty_entry(tmp_path, monkeypatch):
    corpus, file = _source(tmp_path, json.dumps(_message('stored')).encode())
    open_file = os.open

    def denied(path, flags, *args, **kwargs):
        if path == file.abs_path:
            raise PermissionError('declared read failure')
        return open_file(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', denied)
    assert corpus.read_index_entry(file) is None
    assert corpus.read_source_entry(file) is None


@pytest.mark.parametrize('compressed', [False, True])
def test_file_source_rejects_symlinks_before_reading_or_observing_messages(tmp_path, compressed):
    corpus, file = _source(tmp_path, json.dumps(_message('Stored fact')).encode(), compressed=compressed)
    target = tmp_path / 'outside'
    file.abs_path.rename(target)
    file.abs_path.symlink_to(target)
    observed = []
    assert corpus.read_index_entry(file, on_transcript_message=lambda *args: observed.append(args)) is None
    assert observed == []


@pytest.mark.parametrize('compressed', [False, True])
def test_file_swapped_to_a_symlink_after_admission_is_not_read(tmp_path, monkeypatch, compressed):
    corpus, file = _source(tmp_path, json.dumps(_message('Stored fact')).encode(), compressed=compressed)
    target = tmp_path / 'outside'
    target.write_bytes(file.abs_path.read_bytes())
    open_file = os.open

    def swapped(path, flags, *args, **kwargs):
        if path == file.abs_path:
            file.abs_path.unlink()
            file.abs_path.symlink_to(target)
        return open_file(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', swapped)
    observed = []
    assert corpus.read_index_entry(file, on_transcript_message=lambda *args: observed.append(args)) is None
    assert observed == []


def test_projection_callback_errors_are_nullable_for_file_but_operational_for_sqlite(tmp_path):
    def fail(_text):
        raise RuntimeError('declared projection failure')

    _, file = _source(tmp_path, json.dumps(_message('stored')).encode())
    file_corpus = MemoryCoreSessionCorpus(tmp_path, redact_text=fail)
    assert file_corpus.read_index_entry(file) is None
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    catalog.upsert_session('agent:main:main', {'sessionId': 's1'})
    catalog.append_events('s1', [_message('stored')])
    corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog, redact_text=fail)
    sqlite = corpus.discover_files()[0]
    with pytest.raises(RuntimeError, match='declared projection failure'):
        corpus.read_index_entry(sqlite)


def test_missing_sqlite_snapshot_is_absence_and_accessor_exceptions_propagate(tmp_path, monkeypatch):
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog)
    file = SessionCorpusFile('sessions/main/missing.jsonl', Path('agent:main:main'),
                             session_id='missing', transcript_source='sqlite')
    assert corpus.read_index_entry(file) is None
    assert corpus.read_source_entry(file) is None

    def failed_accessor(*_args, **_kwargs):
        raise RuntimeError('declared SQLite read failure')

    monkeypatch.setattr(catalog, 'read_transcript', failed_accessor)
    with pytest.raises(RuntimeError, match='declared SQLite read failure'):
        corpus.read_source_entry(file)


def test_raw_sqlite_snapshot_retains_abandoned_and_side_append_branches(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    catalog.upsert_session('agent:main:main', {'sessionId': 's1'})
    records = [
        _message('root', 'root'),
        _message('abandoned', 'old', role='assistant', parent='root'),
        {'type': 'leaf', 'id': 'switch', 'targetId': 'root'},
        _message('active', 'new', role='assistant', parent='root'),
        {**_message('side', 'side', role='assistant', parent='root'), 'appendMode': 'side'},
    ]
    catalog.replace_events('s1', records)
    corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog)
    file, = corpus.discover_files()
    entry = corpus.read_index_entry(file)
    assert entry.content == 'User: root\nAssistant: abandoned\nAssistant: active\nAssistant: side'
    assert entry.line_map == [1, 2, 4, 5]
    assert list(catalog.read_transcript('s1').events) == records


def test_real_projection_observer_runs_after_a_coherent_sqlite_snapshot_closes(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    catalog.upsert_session('agent:main:main', {'sessionId': 's1'})
    catalog.replace_events('s1', [
        _message('first', 'first'), _message('second', 'second', role='assistant'),
    ])
    corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog)
    file, = corpus.discover_files()
    observed = []

    def observe(message, observed_at):
        observed.append((message['content'], observed_at))
        if len(observed) == 1:
            catalog.append_events('s1', [_message('later append', 'later')])

    entry = corpus.read_index_entry(file, on_transcript_message=observe)
    assert entry.content == 'User: first\nAssistant: second'
    assert observed == [('first', 1000), ('second', 1000)]
    assert len(catalog.read_transcript('s1').events) == 3


def test_observer_failure_preserves_file_absence_vs_sqlite_error_boundary(tmp_path):
    def fail(_message, _observed_at):
        raise RuntimeError('declared observer failure')

    corpus, file = _source(tmp_path, json.dumps(_message('stored')).encode())
    assert corpus.read_index_entry(file, on_transcript_message=fail) is None
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    catalog.upsert_session('agent:main:main', {'sessionId': 's1'})
    catalog.append_events('s1', [_message('stored')])
    sqlite_corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog)
    with pytest.raises(RuntimeError, match='declared observer failure'):
        sqlite_corpus.read_index_entry(sqlite_corpus.discover_files()[0], on_transcript_message=fail)


@pytest.mark.parametrize('boundary,expected', [
    ({'type': 'reset'}, {'state': 'valid', 'cutoffLine': 3}),
    ({'type': 'reset', 'firstKeptEntryId': 'kept'}, {'state': 'valid', 'cutoffLine': 2}),
    ({'type': 'reset', 'firstKeptEntryId': 'gone'}, {'state': 'invalid'}),
    ({'type': 'reset', 'firstKeptEntryId': None}, {'state': 'invalid'}),
])
def test_real_sqlite_reset_projection_preserves_full_text_and_actual_cutoff(tmp_path, boundary, expected):
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    catalog.upsert_session('agent:main:main', {'sessionId': 's1'})
    catalog.replace_events('s1', [_message('before', 'before'), _message('kept', 'kept'), boundary,
                                  _message('after', 'after')])
    corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog)
    entry = corpus.read_index_entry(corpus.discover_files()[0])
    assert entry.content == 'User: before\nUser: kept\nUser: after'
    assert entry.line_map == [1, 2, 4]
    assert entry.reset_recall_cutoff == expected


def test_complete_first_frame_semantics_reach_the_archive_projection(tmp_path):
    first = json.dumps(_message('first frame', 'first')).encode() + b'\n'
    second = json.dumps(_message('second frame', 'second')).encode() + b'\n'
    corpus, file = _source(tmp_path, b'', compressed=True)
    file.abs_path.write_bytes(_compress(first) + _compress(second))
    entry = corpus.read_index_entry(file)
    assert entry.content == 'User: first frame'
    assert entry.line_map == [1]


def test_fresh_source_replacement_never_serves_old_plaintext(tmp_path):
    corpus, file = _source(tmp_path, json.dumps(_message('alpha fact')).encode(), compressed=True)
    before = corpus.read_index_entry(file)
    file.abs_path.write_bytes(_compress(json.dumps(_message('bravo fact')).encode()))
    os.utime(file.abs_path, ns=(MTIME_NS + 1_000_000, MTIME_NS + 1_000_000))
    after = corpus.read_index_entry(file)
    assert before.content == 'User: alpha fact'
    assert after.content == 'User: bravo fact'
    assert after.hash != before.hash
    assert after._extra['mtimeMs'] == before._extra['mtimeMs'] + 1


def test_workspace_skips_unreadable_archive_without_losing_healthy_sources(tmp_path):
    state = tmp_path / 'state'
    directory = state / 'agents/main/sessions'
    directory.mkdir(parents=True)
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', store_path=directory / 'sessions.json',
                                   clock_ms=lambda: 1000)
    catalog.upsert_session('agent:main:main', {'sessionId': 'live'})
    catalog.append_events('live', [_message('healthy source')])
    path = directory / 'old.jsonl.reset.2026-11-09T00-00-00.000Z.zst'
    path.write_bytes(b'invalid compressed source')
    catalog.record_archive(path.name, 'old', session_key='agent:main:old', path=path)
    files = MemoryWorkspace(tmp_path / 'workspace', session_catalog=catalog).discover_session_transcript_files()
    assert [file.rel_path for file in files] == ['sessions/main/live.jsonl']
