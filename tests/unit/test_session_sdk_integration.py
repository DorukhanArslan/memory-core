"""Trusted session authority reaches public SDK and host tool entry points."""
from __future__ import annotations

import pytest

from memory_core import HostKit, Memory, MemoryConfig, SessionState
from memory_core.flags import FeatureFlags
from memory_core.session_catalog import MemorySessionCatalog


def _catalog(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'state' / 'catalog.sqlite', clock_ms=lambda: 1_790_000_000_000)
    for user in ('alice', 'bob'):
        catalog.upsert_session(f'agent:main:dm:{user}', {
            'sessionId': user, 'chatType': 'direct',
            'updatedAt': 1_790_000_000_000,
        })
        catalog.record_participant(f'agent:main:dm:{user}', {
            'identity': {'type': 'profile', 'id': user}, 'promptedAt': 1_790_000_000_000,
        })
        catalog.append_events(user, [{
            'type': 'message', 'id': f'{user}-one',
            'message': {'role': 'user', 'content': f'Cobalt private {user} preference.',
                        '__openclaw': {'senderIsOwner': True}},
        }], updated_at_ms=1_790_000_000_000)
    return catalog


def _config(root):
    return MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False, mmr=False, temporal_decay=False))


def test_memory_search_uses_captured_catalog_policy_and_actual_requester(tmp_path):
    from memory_core.session_visibility import SessionVisibilityContext, SessionVisibilityPolicy

    catalog = _catalog(tmp_path)
    policy = SessionVisibilityContext.from_catalog(catalog, policy=SessionVisibilityPolicy(visibility='self'))
    memory = Memory.from_workspace(tmp_path / 'workspace', config=_config(tmp_path / 'workspace'),
                                   session_catalog=catalog, session_visibility=policy)
    bob = memory.search('Cobalt', corpus='sessions', min_score=0, max_results=1,
                        agent_session_key='agent:main:dm:bob')
    assert [hit['path'] for hit in bob['results']] == ['sessions/main/bob.jsonl']
    assert bob['debug']['candidateHits'] == 2
    assert bob['debug']['withheldHits'] == 1
    assert memory.search('Cobalt', corpus='sessions', min_score=0)['results'] == []


def test_host_dispatch_uses_session_state_and_ignores_model_authority_fields(tmp_path):
    from memory_core.session_visibility import SessionVisibilityContext, SessionVisibilityPolicy

    catalog = _catalog(tmp_path)
    policy = SessionVisibilityContext.from_catalog(catalog, policy=SessionVisibilityPolicy(visibility='self'))
    kit = HostKit.open(tmp_path / 'workspace', config=_config(tmp_path / 'workspace'),
                       session_catalog=catalog, session_visibility=policy)
    result = kit.dispatch('memory_search', {
        'query': 'Cobalt', 'corpus': 'sessions', 'minScore': 0,
        'visibility': 'all', 'requesterSessionKey': 'agent:main:dm:alice',
        'trustedAgentScope': True,
        'session_visibility': {'visibility': 'all'},
    }, session=SessionState.new(session_key='agent:main:dm:bob', session_id='bob'))
    assert [hit['path'] for hit in result['results']] == ['sessions/main/bob.jsonl']


def test_public_open_rejects_another_agent_catalog_before_workspace_initialization(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / 'state.sqlite', agent_id='another')
    root = tmp_path / 'uncreated'
    with pytest.raises(ValueError, match='different agent'):
        Memory.from_workspace(root, config=_config(root), session_catalog=catalog)
    assert not root.exists()


def test_remember_only_sources_are_indexed_but_require_trusted_recall_context(tmp_path):
    from memory_core.session_visibility import resolve_memory_search_source_policy
    from memory_core.tools.memory_search import MemorySearchToolContext

    catalog = _catalog(tmp_path)
    policy = resolve_memory_search_source_policy(remember_across_conversations=True)
    memory = Memory.from_workspace(
        tmp_path / 'workspace', config=_config(tmp_path / 'workspace'),
        session_catalog=catalog, source_policy=policy,
    )
    assert {row['source'] for row in memory.store.read_published_index()['sources']} == {
        'memory', 'sessions',
    }
    ordinary = memory.search('Cobalt', min_score=0, agent_session_key='agent:main:dm:bob')
    assert ordinary['results'] == []
    recalled = memory.search(
        'Cobalt', min_score=0, agent_session_key='agent:main:dm:bob',
        context=MemorySearchToolContext(conversation_recall={
            'scope': 'same-agent-private', 'anchorSessionKey': 'agent:main:dm:bob',
            'corpus': 'sessions',
        }),
    )
    assert [hit['path'] for hit in recalled['results']] == ['sessions/main/alice.jsonl']
