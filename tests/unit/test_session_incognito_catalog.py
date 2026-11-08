"""Private session writes use genuine process-held SQLite, outside the durable corpus."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus
from memory_core.workspace import MemoryWorkspace

KEY = 'agent:main:dashboard:incognito-hidden'
EVENT = {'type': 'message', 'id': 'private-message', 'message': {
    'role': 'user', 'content': 'Cobalt process-only private body',
}}


def _catalog(tmp_path, **options):
    store = tmp_path / 'state' / 'agents' / 'main' / 'sessions' / 'sessions.json'
    store.parent.mkdir(parents=True, exist_ok=True)
    return MemorySessionCatalog(tmp_path / 'catalog.sqlite', store_path=store,
                                clock_ms=lambda: 1000, **options)


@pytest.mark.parametrize('key', [KEY, 'agent:main:subagent:incognito-child',
                                'agent:main:internal-session-effects:incognito-effect'])
def test_private_current_events_and_participants_are_genuine_but_never_durable(tmp_path, key):
    catalog = _catalog(tmp_path)
    catalog.upsert_session(key, {'sessionId': 'private', 'chatType': 'direct'})
    catalog.replace_events('private', [EVENT], session_key=key)
    assert catalog.record_participant(key, {'identity': {'type': 'profile', 'id': 'alice'}}) == 'inserted'
    assert catalog.get_session_entry(key)['sessionId'] == 'private'
    assert catalog.get_session_entry(key)['createdAt'] == 1000
    assert list(catalog.read_transcript('private', session_key=key).events) == [EVENT]
    assert catalog.read_transcript('private') is None
    assert catalog.list_participants(key)[key][0]['identity'] == {'type': 'profile', 'id': 'alice'}
    snapshot = catalog.snapshot()
    assert snapshot.entries == {} and snapshot.instances == () and snapshot.revision == 0
    assert catalog.list_participants() == {}
    with sqlite3.connect(catalog.path) as db:
        for table in ('memory_session_nodes', 'memory_session_windows', 'memory_session_events',
                      'memory_session_participants'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    assert b'Cobalt' not in catalog.path.read_bytes()
    assert not catalog.path.with_name('incognito-openclaw-agent.sqlite').exists()


def test_another_handle_shares_only_this_process_private_owner_and_reopen_keeps_durable_empty(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.upsert_session(KEY, {'sessionId': 'private'})
    # ID-only compatibility finds the registered private identity without writing the durable database.
    catalog.append_events('private', [EVENT])
    reopened = MemorySessionCatalog(catalog.path, store_path=catalog.store_path)
    assert list(reopened.read_transcript('private', session_key=KEY).events) == [EVENT]
    assert reopened.get_session_entry(KEY)['sessionId'] == 'private'
    assert reopened.snapshot().entries == {}
    script = '''
import json,sys
from memory_core.session_catalog import MemorySessionCatalog
c=MemorySessionCatalog(sys.argv[1],store_path=sys.argv[2])
print(json.dumps({'entry':c.get_session_entry(sys.argv[3]),
                  'transcript':c.read_transcript('private',session_key=sys.argv[3]),
                  'catalog':c.snapshot().entries}))
'''
    actual = subprocess.run([sys.executable, '-c', script, str(catalog.path), str(catalog.store_path), KEY],
                            check=True, capture_output=True, text=True)
    assert json.loads(actual.stdout) == {'entry': None, 'transcript': None, 'catalog': {}}


def test_private_identity_collision_requires_the_explicit_writer_scope(tmp_path):
    catalog = _catalog(tmp_path)
    ordinary = 'agent:main:dm:alice'
    catalog.upsert_session(ordinary, {'sessionId': 'same-id'})
    catalog.upsert_session(KEY, {'sessionId': 'same-id'})
    with pytest.raises(ValueError, match='ambiguous'):
        catalog.append_events('same-id', [EVENT])
    catalog.append_events('same-id', [EVENT], session_key=KEY)
    assert catalog.read_transcript('same-id', session_key=ordinary).events == ()
    assert list(catalog.read_transcript('same-id', session_key=KEY).events) == [EVENT]
    assert b'Cobalt' not in catalog.path.read_bytes()


def test_private_owner_cannot_cross_another_path_or_agent(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.upsert_session(KEY, {'sessionId': 'private'})
    catalog.replace_events('private', [EVENT], session_key=KEY)
    other = MemorySessionCatalog(tmp_path / 'other.sqlite', agent_id='main')
    peer = MemorySessionCatalog(catalog.path, agent_id='peer')
    assert other.read_transcript('private', session_key=KEY) is None
    assert peer.get_session_entry('agent:peer:dashboard:incognito-hidden') is None
    assert peer.read_transcript('private') is None


def test_read_only_private_miss_does_not_allocate_an_owner_or_file(tmp_path):
    from memory_core.session_catalog import _process_catalogs
    catalog = _catalog(tmp_path)
    before = set(_process_catalogs)
    assert catalog.get_session_entry(KEY) is None
    assert catalog.read_transcript('missing', session_key=KEY) is None
    assert catalog.list_participants(KEY) == {}
    assert set(_process_catalogs) == before
    assert not catalog.path.with_name('incognito-openclaw-agent.sqlite').exists()


def test_private_delete_and_retained_identity_remain_only_in_memory(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.retain_transcript(KEY, {'sessionId': 'private'}, provenance_known=True)
    catalog.append_events('private', [EVENT], session_key=KEY)
    catalog.upsert_session(KEY, {'sessionId': 'private'})
    catalog.record_participant(KEY, {'identity': {'type': 'profile', 'id': 'alice'}})
    catalog.remove_session(KEY)
    assert catalog.get_session_entry(KEY) is None
    assert catalog.list_participants(KEY) == {}
    assert list(catalog.read_transcript('private', session_key=KEY).events) == [EVENT]
    assert catalog.snapshot().instances == ()


def test_actual_workspace_and_index_cannot_admit_process_only_sources(tmp_path):
    catalog = _catalog(tmp_path)
    catalog.upsert_session(KEY, {'sessionId': 'private'})
    catalog.replace_events('private', [EVENT], session_key=KEY)
    state = catalog.store_path.parents[3]
    corpus = MemoryCoreSessionCorpus(state, catalog=catalog)
    assert corpus.discover_entries(include_retained_sqlite=True) == []
    workspace = MemoryWorkspace(tmp_path / 'workspace', session_catalog=catalog)
    workspace.root.mkdir()
    config = MemoryConfig(workspace_dir=workspace.root, flags=FeatureFlags(vector_search=False))
    store = SQLiteMemoryStore(config, None)
    store.reindex(workspace)
    assert store.search('Cobalt', min_score=0) == []
    assert store.read_published_index()['sources'] == []
