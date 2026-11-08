"""Regressions exposed by the genuine session comparison, not fixture normalization."""
import json
from pathlib import Path

import pytest

from memory_core import Memory, MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus
from memory_core.session_visibility import (
    SessionAgentSelectionRequiredError, SessionVisibilityContext, SessionVisibilityPolicy,
)
from memory_core.tools.memory_search import MemorySearchToolContext, execute_memory_search_tool


def test_archive_enumeration_follows_native_scandir_order_before_admission(tmp_path, monkeypatch):
    directory = tmp_path / 'state' / 'agents' / 'main' / 'sessions'
    directory.mkdir(parents=True)
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite', store_path=directory / 'sessions.json')
    legacy = directory / 'bob.jsonl.reset.2026-11-09T00-00-00Z'
    prior = directory / 'bob-prior.jsonl.reset.2026-11-09T00-00-00Z'
    for path in (legacy, prior):
        path.write_text(json.dumps({'type': 'message', 'message': {'role': 'user', 'content': 'Cobalt'}}))
    original = Path.iterdir

    def entries(path):
        return iter((legacy, prior)) if path == directory else original(path)

    monkeypatch.setattr(Path, 'iterdir', entries)
    corpus = MemoryCoreSessionCorpus(tmp_path / 'state', catalog=catalog)
    assert [Path(row['sessionFile']).name for row in corpus.discover_entries()] == [prior.name, legacy.name]
    assert [Path(row['sessionFile']).name for row in corpus.discover_admitted_entries()] == [prior.name, legacy.name]


@pytest.mark.parametrize('corpus', ['sessions', 'memory'])
def test_agent_selection_errors_escape_the_tool_boundary_and_do_not_poison_cooldown(tmp_path, corpus):
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'MEMORY.md').write_text('Cobalt workspace fact.\n')
    catalog = MemorySessionCatalog(tmp_path / 'catalog.sqlite')
    key = 'agent:main:direct:bob'
    catalog.upsert_session(key, {'sessionId': 'bob', 'chatType': 'direct'})
    catalog.append_events('bob', [{'type': 'message', 'message': {'role': 'user', 'content': 'Cobalt session fact.'}}])
    visibility = SessionVisibilityContext.from_catalog(catalog, SessionVisibilityPolicy(
        visibility='agent', configured_agent_ids=('main', 'peer'),
    ))
    memory = Memory.from_workspace(root, initialize=False, session_catalog=catalog, config=MemoryConfig(
        workspace_dir=root, flags=FeatureFlags(vector_search=False, temporal_decay=False, mmr=False),
    ))
    context = MemorySearchToolContext(session_visibility=visibility)
    arguments = {'query': 'Cobalt', 'corpus': corpus, 'minScore': 0}
    with pytest.raises(SessionAgentSelectionRequiredError) as caught:
        execute_memory_search_tool(memory.config, memory.store, arguments,
                                   agent_session_key='agent:peer:direct:carol', context=context)
    assert caught.value.code == 'AGENT_SELECTION_REQUIRED'
    assert caught.value.agentIds == ['main', 'peer']
    assert caught.value.surface == 'session agent resolution'
    assert caught.value.hint == 'The agent-scoped session key belongs to "peer", not "main".'
    assert caught.value.name == 'AgentSelectionRequiredError'
    assert not hasattr(caught.value, 'status')
    later = execute_memory_search_tool(memory.config, memory.store, arguments,
                                       agent_session_key=key, context=context)
    assert later['results']
    assert not later.get('unavailable')


def test_tool_owner_resolution_precedes_invalid_model_arguments_and_search(tmp_path, monkeypatch):
    memory = Memory.from_workspace(tmp_path, initialize=False, config=MemoryConfig(
        workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False),
    ))
    monkeypatch.setattr(memory.store, 'search', lambda *_args, **_kwargs: pytest.fail('Search must not run'))
    monkeypatch.setattr('memory_core.tools.memory_search.record_memory_search_tool_cooldown',
                       lambda *_args, **_kwargs: pytest.fail('Owner errors must not record cooldown'))
    with pytest.raises(SessionAgentSelectionRequiredError) as caught:
        execute_memory_search_tool(memory.config, memory.store, {'query': None, 'corpus': 'memory'},
                                   agent_session_key='agent:peer:direct:carol')
    assert caught.value.agentIds == ['main']
    assert caught.value.code == 'AGENT_SELECTION_REQUIRED'
