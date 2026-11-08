"""Durable participant facts stay separate from transcript access and admission."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from memory_core.session_catalog import MemorySessionCatalog
from memory_core.tools.common import MemoryToolError

KEY = 'agent:main:dm:alice'


def _record(kind='profile', actor='alice', at=10, **namespace):
    return {'identity': {'type': kind, **namespace, 'id': actor}, 'promptedAt': at}


def test_actual_participant_writes_aggregate_and_survive_reopen(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    catalog = MemorySessionCatalog(path, clock_ms=lambda: 90)
    catalog.upsert_session(KEY, {'sessionId': 's1'})
    assert catalog.record_participant(KEY, _record(at=30)) == 'inserted'
    assert catalog.record_participant(KEY, _record(at=10)) == 'updated'
    assert catalog.record_participant(KEY, _record(at=20)) == 'updated'
    assert MemorySessionCatalog(path).list_participants(KEY) == {KEY: [{
        'identity': {'type': 'profile', 'id': 'alice'}, 'contributionCount': 3,
        'firstPromptedAt': 10, 'lastPromptedAt': 30,
    }]}
    returned = catalog.list_participants()
    returned[KEY][0]['identity']['id'] = 'caller mutation'
    assert catalog.list_participants()[KEY][0]['identity']['id'] == 'alice'


def test_five_namespaces_preserve_nulls_and_cannot_alias_same_actor_id(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    identities = [
        _record('profile', 'same', 7), _record('agent', 'same', 7),
        _record('remote', 'same', 7, pluginId='chat', domain='guild', idKind='user'),
        _record('observation', 'same', 7, pluginId=None, accountId=None, senderKind='unknown'),
        _record('legacy', 'same', 7, actorType='human', source=None),
    ]
    for record in identities:
        assert catalog.record_participant(KEY, record) == 'inserted'
    rows = catalog.list_participants(KEY)[KEY]
    assert len(rows) == 5
    assert {row['identity']['type'] for row in rows} == {'agent', 'legacy', 'observation', 'profile', 'remote'}
    assert next(row for row in rows if row['identity']['type'] == 'observation')['identity'] == {
        'type': 'observation', 'pluginId': None, 'accountId': None,
        'senderKind': 'unknown', 'id': 'same',
    }
    assert rows == sorted(rows, key=lambda row: {
        'agent': 0, 'legacy': 1, 'observation': 2, 'profile': 3, 'remote': 4,
    }[row['identity']['type']])


def test_admission_cap_is_cross_namespace_but_existing_updates_and_own_agent_skip_survive(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    for index in range(32):
        assert catalog.record_participant(KEY, _record(actor=f'person-{index}')) == 'inserted'
    assert catalog.record_participant(KEY, _record('agent', 'new-agent')) == 'capped'
    assert catalog.record_participant(KEY, _record(actor='person-0', at=20)) == 'updated'
    assert catalog.record_participant(KEY, {
        **_record('agent', 'main'), 'sessionAgentId': 'main',
    }) is None
    assert catalog.record_participant(KEY, _record(actor='')) is None
    rows = catalog.list_participants(KEY)[KEY]
    assert len(rows) == 32
    assert next(row for row in rows if row['identity']['id'] == 'person-0')['contributionCount'] == 2


def test_unknown_first_timestamp_remains_unknown_after_new_observations(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    catalog.record_participant(KEY, _record())
    with sqlite3.connect(catalog.path) as db:
        db.execute('UPDATE memory_session_participants SET first_prompted_at=NULL,last_prompted_at=NULL')
    catalog.record_participant(KEY, _record(at=20))
    catalog.record_participant(KEY, _record(at=15))
    assert catalog.list_participants()[KEY] == [{
        'identity': {'type': 'profile', 'id': 'alice'}, 'contributionCount': 3,
        'firstPromptedAt': None, 'lastPromptedAt': 20,
    }]


def test_alias_registry_updates_existing_alias_and_prefers_an_exact_retained_row(tmp_path):
    aliases = {'new': ('old-z', 'old-a'), 'exact': ('old-a',)}
    catalog = MemorySessionCatalog(tmp_path / 'c.db', profile_aliases=lambda key: aliases.get(key, ()))
    catalog.record_participant(KEY, _record(actor='old-z', at=30))
    catalog.record_participant(KEY, _record(actor='old-a', at=20))
    assert catalog.record_participant(KEY, _record(actor='new', at=10)) == 'updated'
    catalog.record_participant(KEY, _record(actor='exact', at=40))
    assert catalog.record_participant(KEY, _record(actor='exact', at=50)) == 'updated'
    rows = {row['identity']['id']: row for row in catalog.list_participants(KEY)[KEY]}
    # Alias-only observation updates the lexically first retained alias.
    assert rows['old-a']['contributionCount'] == 4
    assert rows['old-a']['firstPromptedAt'] == 10
    assert rows['old-z']['contributionCount'] == 1
    assert 'new' not in rows and 'exact' not in rows


def test_exact_profile_row_wins_over_other_retained_aliases(tmp_path):
    aliases = []
    catalog = MemorySessionCatalog(tmp_path / 'c.db', profile_aliases=lambda _: aliases)
    catalog.record_participant(KEY, _record(actor='old', at=1))
    catalog.record_participant(KEY, _record(actor='exact', at=2))
    aliases.append('old')
    catalog.record_participant(KEY, _record(actor='exact', at=3))
    rows = {row['identity']['id']: row for row in catalog.list_participants(KEY)[KEY]}
    assert rows['exact']['contributionCount'] == 2
    assert rows['old']['contributionCount'] == 1


def test_shared_database_agent_namespace_and_ordering_are_preserved(tmp_path):
    main = MemorySessionCatalog(tmp_path / 'shared.db', agent_id='main')
    peer = MemorySessionCatalog(main.path, agent_id='peer')
    main.record_participant(KEY, _record(actor='later', at=20))
    main.record_participant(KEY, _record(actor='early', at=1))
    main.record_participant('agent:main:z', _record(actor='last-key', at=0))
    peer.record_participant(KEY, _record(actor='peer', at=0))
    assert list(main.list_participants()) == [KEY, 'agent:main:z']
    assert [row['identity']['id'] for row in main.list_participants(KEY)[KEY]] == ['early', 'later']
    assert peer.list_participants(KEY)[KEY][0]['identity']['id'] == 'peer'
    with pytest.raises(ValueError, match='different catalog agent'):
        main.list_participants(agent_id='peer')
    with pytest.raises(ValueError, match='different catalog agent'):
        main.record_participant(KEY, _record(), agent_id='peer')


def test_reset_retains_participants_and_delete_clears_only_its_session_key(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    catalog.upsert_session(KEY, {'sessionId': 'one'})
    catalog.replace_events('one', [{'type': 'message', 'message': {'role': 'user', 'content': 'history'}}])
    catalog.record_participant(KEY, _record())
    catalog.record_participant('agent:main:other', _record(actor='other'))
    catalog.upsert_session(KEY, {'sessionId': 'two'})
    assert len(catalog.list_participants(KEY)[KEY]) == 1
    catalog.remove_session(KEY)
    assert catalog.list_participants(KEY) == {}
    assert list(catalog.list_participants()) == ['agent:main:other']
    assert catalog.read_transcript('one').events[0]['message']['content'] == 'history'


def test_lone_surrogate_binding_preserves_native_raw_identity_admission_at_cap(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    raw = _record('remote', '\ud800', pluginId='chat', domain='guild', idKind='user')
    assert catalog.record_participant(KEY, raw) == 'inserted'
    for index in range(31):
        catalog.record_participant(KEY, _record(actor=f'p-{index}'))
    assert catalog.record_participant(KEY, raw) == 'capped'
    replaced = next(row for row in catalog.list_participants(KEY)[KEY] if row['identity']['type'] == 'remote')
    assert replaced['identity']['id'] == '\ufffd'
    assert replaced['contributionCount'] == 1


def test_concurrent_distinct_writers_cannot_exceed_the_admission_bound(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda index: catalog.record_participant(KEY, _record(actor=f'p-{index}')), range(48)))
    assert results.count('inserted') == 32
    assert results.count('capped') == 16
    assert len(catalog.list_participants(KEY)[KEY]) == 32


def test_invalid_persisted_namespace_is_reported_without_rewriting_rows(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    catalog.record_participant(KEY, _record())
    with sqlite3.connect(catalog.path) as db:
        db.execute('UPDATE memory_session_participants SET identity_namespace=\'{"type":"unknown"}\'')
    with pytest.raises(MemoryToolError, match='Session participant identity is invalid'):
        catalog.list_participants()


def test_admission_metadata_projects_source_facts_and_excludes_participation_aggregates(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db', clock_ms=lambda: 90)
    catalog.upsert_session(KEY, {
        'sessionId': 'one', 'updatedAt': 30, 'sessionStartedAt': 10, 'chatType': 'direct',
        'hookExternalContentSource': 'webhook',
        'delivery': {'kind': 'external', 'context': {'channel': ' slack ', 'accountId': ' account '}, 'origin': {'provider': 'fallback'}},
        'participants': [{'identity': {'type': 'profile', 'id': 'raw-not-authoritative'}}],
    })
    catalog.record_participant(KEY, _record())
    origin = {'agentId': 'main', 'sessionId': 'one', 'sessionKey': KEY}
    assert catalog.load_session_metadata(origin) == {
        'agentId': 'main', 'sessionId': 'one', 'sessionKey': KEY, 'resolution': 'live',
        'createdAt': 10, 'channel': 'slack', 'accountId': 'account', 'chatType': 'direct',
        'hookExternalContentSource': 'webhook', 'participants': [],
    }
    # Replacing the active incarnation does not grant exact webhook provenance to its old window.
    catalog.upsert_session(KEY, {'sessionId': 'two', 'updatedAt': 40})
    assert catalog.load_session_metadata(origin)['hookExternalContentSource'] is None
    assert catalog.load_session_metadata(origin)['createdAt'] == 10
    assert catalog.load_session_metadata({**origin, 'sessionKey': 'agent:main:wrong'}) is None


@pytest.mark.parametrize('facts', [
    {'pluginOwnerId': ' plugin-owner '},
    {'hookExternalContentSource': 'gmail'},
    {'hookExternalContentSource': 'webhook'},
    {'hookExternalContentSource': 'email'},
    {'acp': {}},
])
def test_omitted_window_source_facts_survive_metadata_replacement_and_retention(tmp_path, facts):
    from memory_core.session_corpus import MemoryCoreSessionCorpus

    state = tmp_path / 'state'
    catalog = MemorySessionCatalog(tmp_path / 'c.db', clock_ms=lambda: 1000)
    corpus = MemoryCoreSessionCorpus(state, catalog=catalog)
    event = {'type': 'message', 'message': {'role': 'user', 'content': 'Cedar private history'}}
    catalog.upsert_session(KEY, {'sessionId': 'old', 'updatedAt': 10, 'label': 'old label', **facts})
    catalog.replace_events('old', [event])
    catalog.upsert_session(KEY, {'sessionId': 'old', 'updatedAt': 20, 'label': 'new label'})
    # Current metadata is replaced, not patched with a stale whole entry.
    current = catalog.snapshot().entries[KEY]
    assert current['label'] == 'new label'
    assert all(name not in current for name in facts)
    catalog.upsert_session(KEY, {'sessionId': 'new', 'updatedAt': 30})
    catalog.replace_events('new', [event])
    reopened = MemorySessionCatalog(catalog.path, clock_ms=lambda: 1000)
    old = next(row for row in reopened.snapshot().instances if row.session_id == 'old')
    if 'pluginOwnerId' in facts:
        assert old.entry['pluginOwnerId'] == 'plugin-owner'
    elif 'hookExternalContentSource' in facts:
        assert old.entry['hookExternalContentSource'] == (
            'webhook' if facts['hookExternalContentSource'] == 'email' else facts['hookExternalContentSource']
        )
    else:
        assert old.acp_owned is True
    assert [row['sessionId'] for row in corpus.discover_entries(include_retained_sqlite=True)] == ['new']


@pytest.mark.parametrize('has_events', [False, True])
def test_migrated_window_cannot_gain_past_provenance_from_a_new_metadata_observation(tmp_path, has_events):
    catalog = MemorySessionCatalog(tmp_path / 'c.db', clock_ms=lambda: 1000)
    catalog.retain_transcript(KEY, {'sessionId': 'old', 'updatedAt': 10}, provenance_known=False)
    if has_events:
        catalog.replace_events('old', [{'type': 'message', 'message': {'role': 'user', 'content': 'Old'}}])
    catalog.upsert_session(KEY, {
        'sessionId': 'old', 'updatedAt': 20, 'pluginOwnerId': 'new-plugin',
        'hookExternalContentSource': 'gmail', 'acp': {},
    })
    with sqlite3.connect(catalog.path) as db:
        facts = db.execute('SELECT provenance_known,acp_owned,plugin_owner_id,hook_external_content_source '
                           'FROM memory_session_windows WHERE session_id=\'old\'').fetchone()
    assert facts == ((0, 0, None, None) if has_events else (1, 1, 'new-plugin', 'gmail'))
    # A second metadata write to the same active unknown incarnation cannot promote it either.
    catalog.upsert_session(KEY, {'sessionId': 'old', 'updatedAt': 30})
    with sqlite3.connect(catalog.path) as db:
        known = db.execute('SELECT provenance_known FROM memory_session_windows WHERE session_id=\'old\'').fetchone()[0]
    assert known == int(not has_events)


def test_new_explicit_category_replaces_its_previous_source_fact_without_clearing_other_facts(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'c.db')
    catalog.upsert_session(KEY, {'sessionId': 'one', 'pluginOwnerId': 'plugin-a', 'hookExternalContentSource': 'gmail'})
    catalog.upsert_session(KEY, {'sessionId': 'one', 'pluginOwnerId': 'plugin-b'})
    catalog.replace_events('one', [{'type': 'message', 'message': {'role': 'user', 'content': 'Cedar'}}])
    window, = catalog.snapshot().instances
    assert window.entry['pluginOwnerId'] == 'plugin-b'
    assert window.entry['hookExternalContentSource'] == 'gmail'
    assert catalog.load_session_metadata({'agentId': 'main', 'sessionId': 'one'})['hookExternalContentSource'] == 'gmail'
