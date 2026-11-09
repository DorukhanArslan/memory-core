"""Real files, real publication races and actual caller settlement receipts."""
import os
from pathlib import Path
import stat

import pytest

from memory_core.atomic_publication import (
    MemoryAtomicPublicationError, MemoryWriteConflictError, commit_memory_content, hash_memory_content,
)
from memory_core.consolidation.forget import commit_memory_content as forget_commit
from memory_core.curation import ADD_MEMORY_ENTRY, CurationPublicationError, MemoryCurator


class LiteralIOError(OSError):
    name = 'Error'

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _file(tmp_path, text='original\n'):
    path = tmp_path / 'MEMORY.md'
    path.write_text(text)
    path.chmod(0o640)
    return path


def test_replace_keeps_existing_mode_and_creates_private_new_targets(tmp_path):
    path = _file(tmp_path)
    commit_memory_content(path, content='new\n', expected_hash=hash_memory_content('original\n'))
    assert path.read_text() == 'new\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    new = tmp_path / 'NEW.md'
    commit_memory_content(new, content='private\n', expected_hash=hash_memory_content(''))
    assert stat.S_IMODE(new.stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ['MEMORY.md', 'NEW.md']


@pytest.mark.parametrize('code,raises', [('EPERM', False), ('EIO', True)])
def test_temp_sync_policy_matches_observed_native_owner_and_cleans_failed_temps(tmp_path, monkeypatch, code, raises):
    path = _file(tmp_path)
    actual = os.fsync
    failure = LiteralIOError(code, 'literal file sync failure')

    def sync(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise failure
        return actual(fd)

    monkeypatch.setattr(os, 'fsync', sync)
    if raises:
        with pytest.raises(LiteralIOError) as caught:
            commit_memory_content(path, content='new\n', expected_hash=hash_memory_content('original\n'))
        assert caught.value is failure
        assert path.read_text() == 'original\n'
    else:
        commit_memory_content(path, content='new\n', expected_hash=hash_memory_content('original\n'))
        assert path.read_text() == 'new\n'
    assert list(tmp_path.iterdir()) == [path]


def test_directory_sync_failure_keeps_actual_committed_success(tmp_path, monkeypatch):
    path = _file(tmp_path)
    actual = os.fsync

    def sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise LiteralIOError('EIO', 'literal parent sync failure')
        return actual(fd)

    monkeypatch.setattr(os, 'fsync', sync)
    commit_memory_content(path, content='new\n', expected_hash=hash_memory_content('original\n'))
    assert path.read_text() == 'new\n'


def test_rejected_permission_rename_with_unchanged_preimage_is_not_misreported_as_dispatched(tmp_path, monkeypatch):
    path = _file(tmp_path)
    failure = LiteralIOError('EACCES', 'literal rename refusal')

    def refused(_source, _destination):
        raise failure

    monkeypatch.setattr(os, 'replace', refused)
    with pytest.raises(LiteralIOError) as caught:
        commit_memory_content(path, content='new\n', expected_hash=hash_memory_content('original\n'))
    assert caught.value is failure
    assert path.read_text() == 'original\n'
    assert list(tmp_path.iterdir()) == [path]


def test_actual_forget_caller_preserves_uncertain_mutation_and_original_cause(tmp_path, monkeypatch):
    path = _file(tmp_path)
    actual = os.replace
    failure = LiteralIOError('EIO', 'literal dispatched rename failure')

    def mutated(source, destination):
        actual(source, destination)
        raise failure

    monkeypatch.setattr(os, 'replace', mutated)
    with pytest.raises(MemoryAtomicPublicationError) as caught:
        forget_commit(path, expected_content='original\n', content='new\n', label='MEMORY.md')
    assert caught.value.publication == 'uncertain'
    assert caught.value.cause is caught.value.__cause__ is failure
    assert path.read_text() == 'new\n'


@pytest.mark.parametrize('stage,state', [('mutated-rename', 'uncertain'), ('replacement-after-rename', 'committed')])
def test_actual_curated_tool_retains_owner_publication_state_without_success_hook(tmp_path, monkeypatch, stage, state):
    path = _file(tmp_path, '# Memory\n\n## Notes\n- original\n')
    actual, hooks = os.replace, []
    failure = LiteralIOError('EIO', 'literal dispatched rename failure')

    def race(source, destination):
        actual(source, destination)
        if stage == 'mutated-rename':
            raise failure
        replacement = tmp_path / 'external'
        replacement.write_text('external replacement\n')
        actual(replacement, destination)

    monkeypatch.setattr(os, 'replace', race)
    curator = MemoryCurator(tmp_path, after_write=hooks.append)
    with pytest.raises(CurationPublicationError) as caught:
        curator.dispatch(ADD_MEMORY_ENTRY, {'section': 'Notes', 'text': 'new'})
    assert caught.value.publication == state
    assert caught.value.cause.publication == state
    assert caught.value.to_tool_error()['publication'] == state
    assert caught.value.to_tool_error()['status'] == 'error'
    assert hooks == []
    if stage == 'mutated-rename':
        assert 'new' in path.read_text()
    else:
        assert path.read_text() == 'external replacement\n'


def test_external_in_place_edit_of_same_inode_retains_actual_native_acceptance(tmp_path, monkeypatch):
    path = _file(tmp_path)
    actual = os.replace

    def race(source, destination):
        actual(source, destination)
        Path(destination).write_text('external in-place edit\n')

    monkeypatch.setattr(os, 'replace', race)
    commit_memory_content(path, content='new\n', expected_hash=hash_memory_content('original\n'))
    assert path.read_text() == 'external in-place edit\n'


def test_preimage_change_uses_original_conflict_contract_and_removes_private_temp(tmp_path):
    path = _file(tmp_path)
    with pytest.raises(MemoryWriteConflictError, match='literal conflict'):
        commit_memory_content(path, content='new\n', expected_hash=hash_memory_content('stale\n'), conflict_message='literal conflict')
    assert path.read_text() == 'original\n'
    assert list(tmp_path.iterdir()) == [path]


def test_host_dispatch_keeps_the_production_publication_marker_in_the_model_tool_payload(tmp_path, monkeypatch):
    from memory_core import Memory, MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.host import HostKit, SessionState

    path = _file(tmp_path, '# Memory\n\n## Notes\n- original\n')
    memory = Memory.from_workspace(tmp_path, initialize=False,
                                   config=MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False)))
    kit = HostKit(memory)
    actual = os.replace

    def mutated(source, destination):
        actual(source, destination)
        raise LiteralIOError('EIO', 'literal dispatched rename failure')

    monkeypatch.setattr(os, 'replace', mutated)
    payload = kit.dispatch(ADD_MEMORY_ENTRY, {'section': 'Notes', 'text': 'new'},
                           session=SessionState.new(session_key='agent:main:main', session_id='atomic-fixture'))
    assert payload == {'status': 'error', 'tool': ADD_MEMORY_ENTRY,
                       'error': 'literal dispatched rename failure', 'publication': 'uncertain'}
    assert 'new' in path.read_text()
