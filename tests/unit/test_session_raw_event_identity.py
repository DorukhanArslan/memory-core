"""Real catalog imports preserve the SQL writer's event identity ownership."""
from copy import deepcopy

from memory_core.session_catalog import MemorySessionCatalog


def test_replace_keeps_first_trimmed_identity_and_all_unidentified_rows_across_reopen(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    key = 'agent:main:main'
    catalog.upsert_session(key, {'sessionId': 's'})
    first = {'type': 'message', 'id': 'root', 'message': {'role': 'user', 'content': 'First fact'}}
    unidentified = [{'type': 'custom', 'id': ''}, {'type': 'custom', 'id': None},
                    {'type': 'custom'}, {'type': 'custom'}]
    events = [first, {'type': 'leaf', 'id': '\ufeffroot\u00a0'},
              {'type': 'message', 'id': 'root', 'message': {'role': 'user', 'content': 'Later fact'}},
              *unidentified]
    original = deepcopy(events)
    catalog.replace_events('s', events, session_key=key)
    reopened = MemorySessionCatalog(catalog.path)
    assert list(reopened.read_transcript('s', session_key=key).events) == [first, *unidentified]
    assert events == original


def test_append_preserves_prior_identity_owner_and_duplicate_only_replay_does_not_publish(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    key = 'agent:main:main'
    catalog.upsert_session(key, {'sessionId': 's'})
    first = {'type': 'message', 'id': 'one', 'message': {'role': 'user', 'content': 'Original'}}
    catalog.append_events('s', [first], session_key=key)
    reopened = MemorySessionCatalog(catalog.path, clock_ms=lambda: 2000)
    second = {'type': 'message', 'id': 'two', 'message': {'role': 'assistant', 'content': []}}
    replay = {'type': 'leaf', 'id': ' one '}
    reopened.append_events('s', [replay, second, second], session_key=key)
    assert list(reopened.read_transcript('s', session_key=key).events) == [first, second]
    before = reopened.read_transcript('s', session_key=key)
    revision = reopened.snapshot().revision
    reopened.append_events('s', [replay, second], session_key=key)
    assert reopened.read_transcript('s', session_key=key) == before
    assert reopened.snapshot().revision == revision


def test_empty_initial_replacement_does_not_advance_the_first_real_append(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', clock_ms=lambda: 1000)
    key = 'agent:main:main'
    catalog.upsert_session(key, {'sessionId': 's', 'updatedAt': 1000})
    revision = catalog.snapshot().revision
    before = catalog.read_transcript('s', session_key=key)
    catalog.replace_events('s', [], session_key=key)
    assert catalog.read_transcript('s', session_key=key) == before
    assert catalog.snapshot().revision == revision
    catalog.append_message('s', {'role': 'user', 'content': 'First real turn'},
                           session_key=key, event_id='first', cwd='/fixture/workspace')
    assert catalog.read_transcript('s', session_key=key).updated_at_ms == 1002
