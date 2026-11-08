"""Process-only session identities cannot enter a durable transcript index."""
import json

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.session_corpus import MemoryCoreSessionCorpus
from memory_core.workspace import MemoryWorkspace


@pytest.mark.parametrize('kind', ['dashboard', 'subagent', 'internal-session-effects'])
def test_legacy_private_transcript_is_excluded_before_reading_and_fts_publication(tmp_path, kind):
    state = tmp_path / 'state'
    directory = state / 'agents' / 'main' / 'sessions'
    directory.mkdir(parents=True)
    private_key = f'agent:main:{kind}:incognito-hidden'
    rows = {
        private_key: {'sessionId': 'hidden', 'sessionFile': 'hidden.jsonl'},
        'agent:main:dm:public': {'sessionId': 'public', 'sessionFile': 'public.jsonl'},
    }
    (directory / 'sessions.json').write_text(json.dumps(rows))
    for name in ('hidden', 'public'):
        (directory / f'{name}.jsonl').write_text(json.dumps({
            'type': 'message', 'message': {'role': 'user', 'content': f'Cobalt {name} fact.'},
        }) + '\n')
    files = MemoryCoreSessionCorpus(state).discover_files()
    assert [file.session_key for file in files] == ['agent:main:dm:public']
    root = tmp_path / 'workspace'
    root.mkdir()
    workspace = MemoryWorkspace(root, openclaw_state_dir=state)
    store = SQLiteMemoryStore(MemoryConfig(workspace_dir=root, flags=FeatureFlags(
        vector_search=False, temporal_decay=False, mmr=False,
    )), None)
    store.reindex(workspace)
    published = store.read_published_index()
    assert [source['path'] for source in published['sources']] == ['sessions/main/public.jsonl']
    assert all('hidden fact' not in row['text'] for row in published['chunks'])
    assert [hit.path for hit in store.search('Cobalt', min_score=0)] == ['sessions/main/public.jsonl']
