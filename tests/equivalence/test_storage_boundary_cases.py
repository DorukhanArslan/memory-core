"""Real SDK separation checks; native parity requires the protected comparison."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.cases import build_cases, run_python
from equivalence.storage_boundaries import build_workspace_isolation_cases
from memory_core.index.identity import INDEX_SOURCES_TABLE


def test_storage_flow_registration_keeps_the_fixed_original_scope_and_no_unearned_credit():
    cases = build_workspace_isolation_cases()
    assert len(cases) == 3
    assert cases == build_workspace_isolation_cases()
    registered = {case['id']: case for case in build_cases()}
    for case in cases:
        assert registered[case['id']] == case
        assert case['requirement'] == 'storage.workspace-isolation'
        assert case['operation'] == 'workspace-isolation-runtime'
        assert case['covers'] == ['storage.workspace-isolation.outcomes', 'storage.workspace-isolation.boundaries']
        assert all('expected' not in step for step in case['input']['steps'])


@pytest.mark.parametrize('case', build_workspace_isolation_cases(), ids=lambda case: case['id'])
def test_actual_shared_sdk_config_keeps_all_subject_files_indexes_recalls_and_checkpoints_separate(tmp_path, case):
    original = deepcopy(case)
    requested = {**case, '_diagnosticDirectory': tmp_path}
    result = run_python(requested)
    assert case == original
    first, changed, reopened = result['steps']

    def owner(step, identity):
        return next(item for item in step['owners'] if item['agentId'] == identity)

    def query(step, identity, query_id):
        return next(item for item in owner(step, identity)['queries'] if item['id'] == query_id)['result']['details']['results']

    assert query(first, 'alice', 'alice-own')
    assert query(first, 'bob', 'bob-own')
    assert query(first, 'alice', 'alice-cannot-search-bob') == []
    assert query(first, 'bob', 'bob-cannot-search-alice') == []
    assert query(changed, 'alice', 'alice-updated')
    assert query(changed, 'bob', 'bob-preserved')
    assert query(changed, 'bob', 'bob-cannot-search-alice-update') == []
    assert query(reopened, 'alice', 'alice-deleted') == []
    assert query(reopened, 'bob', 'bob-after-reopen')
    assert owner(first, 'alice')['dailyIngestionState']['files']
    assert owner(first, 'bob')['dailyIngestionState']['files'] == {}
    assert owner(changed, 'alice')['dailyIngestionState'] != owner(changed, 'bob')['dailyIngestionState']
    for identity in ('alice', 'bob'):
        assert owner(changed, identity)['dailyIngestionState'] == owner(reopened, identity)['dailyIngestionState']
        assert owner(changed, identity)['recallStore'] == owner(reopened, identity)['recallStore']
        for entry in owner(reopened, identity)['recallStore']['entries'].values():
            assert identity in entry['snippet']
            assert ('bob' if identity == 'alice' else 'alice') not in entry['snippet']

    raw, = json.loads((tmp_path / 'python-raw.json').read_text())
    assert raw['sharedConfiguration']['agent_id'] == 'main'
    assert raw['sharedConfiguration']['workspace_dir'] == raw['fixtureBase']
    for snapshot in raw['snapshots']:
        paths = [item['indexDatabasePath'] for item in snapshot['owners']]
        assert len(set(paths)) == len(paths) == 2
        for actual in snapshot['owners']:
            assert actual['config']['agent_id'] == 'main'
            assert actual['config']['workspace_dir'] == actual['workspace']
            assert Path(actual['indexDatabasePath']).is_relative_to(actual['workspace'])
            assert {'chunks', INDEX_SOURCES_TABLE} <= set(actual['fullSql'])
            assert actual['stateFiles']
    assert len(raw['pythonSearchEnvelopes']) == sum(len(step.get('queries', [])) for step in case['input']['steps'])
    assert len(raw['pythonGetEnvelopes']) == sum(len(step.get('reads', [])) for step in case['input']['steps'])
