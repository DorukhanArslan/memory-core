"""Real bootstrap caller and append producer regressions, including kernel EFBIG."""
import json
import os
import stat
import subprocess
import sys

import pytest

from memory_core.atomic_publication import MemoryPublicationPathError, append_memory_content
from memory_core.bootstrap.lifecycle import _write_file_if_missing
from memory_core.workspace import MemoryWorkspace


def test_real_bootstrap_lifecycle_creates_private_complete_file_and_preserves_existing_winner(tmp_path):
    path = tmp_path / 'AGENTS.md'
    assert _write_file_if_missing(path, 'complete bootstrap\n') is True
    assert path.read_bytes() == b'complete bootstrap\n'
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o640)
    assert _write_file_if_missing(path, 'new bootstrap\n') is False
    assert path.read_bytes() == b'complete bootstrap\n'
    assert path.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.iterdir()) == [path]


def test_existing_dangling_bootstrap_alias_remains_an_exclusive_creation_no_op(tmp_path):
    path = tmp_path / 'AGENTS.md'
    path.symlink_to(tmp_path / 'absent')
    assert _write_file_if_missing(path, 'new\n') is False
    assert path.is_symlink()
    assert not (tmp_path / 'absent').exists()


@pytest.mark.parametrize('before,content,after', [
    ('original\n', 'new\n', 'original\nnew\n'),
    ('original', 'new\n', 'original\nnew\n'),
    ('original', '\nnew\n', 'original\nnew\n'),
    ('', 'new\n', 'new\n'),
])
def test_append_obeys_actual_native_newline_prefix_policy(tmp_path, before, content, after):
    path = tmp_path / 'memory.md'
    path.write_text(before)
    append_memory_content(path, content, prepend_newline_if_needed=True)
    assert path.read_text() == after


def test_real_daily_caller_uses_checked_append_without_duplicating_a_leading_newline(tmp_path):
    path = tmp_path / 'memory' / '2026-09-04.md'
    path.parent.mkdir()
    path.write_text('original')
    returned = MemoryWorkspace(tmp_path).append_daily_memory('memory/2026-09-04.md', '\nnew\n')
    assert returned == path
    assert path.read_bytes() == b'original\nnew\n'


def test_append_new_file_is_private_and_newline_prefix_is_not_added_to_an_empty_file(tmp_path):
    path = tmp_path / 'memory.md'
    append_memory_content(path, 'new\n', prepend_newline_if_needed=True)
    assert path.read_bytes() == b'new\n'
    assert path.stat().st_mode & 0o777 == 0o600


def test_append_rechecks_real_caller_authority_before_each_native_sized_write_window(tmp_path):
    path = tmp_path / 'memory.md'
    path.write_bytes(b'prior\n')
    calls = 0
    cancelled = RuntimeError('caller authority expired')

    def assert_current():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise cancelled

    with pytest.raises(RuntimeError) as raised:
        append_memory_content(path, 'x' * (512 * 1024 + 1), before_write=assert_current)
    assert raised.value is cancelled and calls == 2
    assert path.read_bytes() == b'prior\n' + b'x' * (512 * 1024)
    assert not hasattr(raised.value, 'publication')


def test_bootstrap_caller_surfaces_actual_published_receipt_when_parent_sync_fails(tmp_path, monkeypatch):
    path = tmp_path / 'AGENTS.md'
    original = os.fsync
    failure = OSError('literal parent sync failure')
    failure.name, failure.code = 'Error', 'EIO'

    def sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise failure
        return original(descriptor)

    monkeypatch.setattr(os, 'fsync', sync)
    with pytest.raises(MemoryPublicationPathError) as raised:
        _write_file_if_missing(path, 'complete bootstrap\n')
    error = raised.value
    assert error.code == 'helper-failed' and error.category == 'operational'
    assert error.cause is failure and error.details['phase'] == 'publish'
    publication = error.details['publication']
    assert publication['status'] == 'published' and publication['basename'] == 'AGENTS.md'
    assert publication['overwrite'] is False
    assert publication['staged']['identity']['ino'] == path.stat().st_ino
    assert publication['staged']['identity']['size'] == len(b'complete bootstrap\n')
    assert path.read_bytes() == b'complete bootstrap\n' and list(tmp_path.iterdir()) == [path]


def test_bootstrap_caller_keeps_native_unsupported_filesystem_diagnostic_and_cause(tmp_path, monkeypatch):
    import errno

    path = tmp_path / 'AGENTS.md'
    original = os.fsync

    def sync(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))
        return original(descriptor)

    monkeypatch.setattr(os, 'fsync', sync)
    with pytest.raises(RuntimeError, match='filesystem with hard-link support') as raised:
        _write_file_if_missing(path, 'complete bootstrap\n')
    assert raised.value.name == 'Error' and raised.value.cause.name == 'FsSafeError'
    assert raised.value.cause.cause.code == 'EPERM'
    assert not path.exists() and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('operation', ['bootstrap', 'append'])
def test_rooted_write_with_no_progress_keeps_original_helper_failure_and_surviving_files(tmp_path, monkeypatch, operation):
    path = tmp_path / 'memory.md'
    monkeypatch.setattr(os, 'write', lambda _descriptor, _data: 0)
    with pytest.raises(MemoryPublicationPathError, match='file write made no progress') as raised:
        if operation == 'bootstrap':
            _write_file_if_missing(path, 'new content\n')
        else:
            append_memory_content(path, 'new content\n')
    assert raised.value.code == 'helper-failed' and raised.value.category == 'operational'
    assert not hasattr(raised.value, 'publication')
    if operation == 'bootstrap':
        assert not path.exists() and list(tmp_path.iterdir()) == []
    else:
        assert path.read_bytes() == b'' and list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(sys.platform == 'win32', reason='The genuine kernel fault uses POSIX RLIMIT_FSIZE')
@pytest.mark.parametrize('operation', ['bootstrap', 'append'])
def test_real_kernel_partial_write_retains_each_original_owner_outcome(tmp_path, operation):
    path = tmp_path / ('AGENTS.md' if operation == 'bootstrap' else 'memory.md')
    if operation == 'append':
        path.write_bytes(b'before\n')
    program = r'''
import json,resource,signal,sys
from pathlib import Path
from memory_core.atomic_publication import append_memory_content
from memory_core.bootstrap.lifecycle import _write_file_if_missing
path,operation=Path(sys.argv[1]),sys.argv[2]
before=resource.getrlimit(resource.RLIMIT_FSIZE)
signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE,(8,before[1]))
error=None
try:
    if operation=='bootstrap':_write_file_if_missing(path,'complete bootstrap data\n')
    else:append_memory_content(path,'new complete append data\n',prepend_newline_if_needed=True)
except BaseException as caught:error=caught
finally:resource.setrlimit(resource.RLIMIT_FSIZE,before)
print(json.dumps({'name':getattr(error,'name',type(error).__name__),'code':getattr(error,'code',None),
 'causeCode':getattr(getattr(error,'cause',None),'code',None),'hasPublication':hasattr(error,'publication'),
 'files':{p.name:p.read_bytes().hex() for p in path.parent.iterdir() if p.is_file()}}))
'''
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'LANG', 'TZ', 'PYTHONPATH'}}
    result = subprocess.run([sys.executable, '-c', program, str(path), operation], env=env, capture_output=True,
                            text=True, check=True, timeout=10)
    observed = json.loads(result.stdout)
    if operation == 'bootstrap':
        assert observed == {'name': 'FsSafeError', 'code': 'invalid-path', 'causeCode': 'EFBIG',
                            'hasPublication': False, 'files': {}}
    else:
        assert observed == {'name': 'Error', 'code': 'EFBIG', 'causeCode': None,
                            'hasPublication': False, 'files': {'memory.md': b'before\nn'.hex()}}
