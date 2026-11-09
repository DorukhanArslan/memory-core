"""Negative transport guards; these fixtures grant no native-equivalence credit."""
from copy import deepcopy
import errno
import json
import os

import pytest

from equivalence.storage_discovery import build_storage_discovery_cases, run_storage_discovery
from equivalence.storage_discovery_evidence import validate_storage_discovery_diagnostic
from memory_core.workspace import MemorySourceScanError


@pytest.fixture
def actual_sdk_error(tmp_path):
    case = next(case for case in build_storage_discovery_cases() if case['id'] == 'discovery-nested-operational-error')
    result = run_storage_discovery(case['input'], evidence_directory=tmp_path)
    record, = json.loads((tmp_path / 'python-raw.json').read_text())
    return case['input'], result, record


def test_actual_sdk_diagnostic_retains_complete_original_exception_chain(actual_sdk_error):
    arguments, result, record = actual_sdk_error
    validate_storage_discovery_diagnostic(record, arguments, result, side='python')
    error = record['snapshots'][0]['exception']
    assert error['name'] == 'MemorySourceScanError'
    assert 'Traceback (most recent call last)' in error['stack']
    assert error['cause']['properties']['code'] == 'EACCES'
    assert error['properties']['cause'] == error['cause']
    assert error['cause']['properties']['path'].startswith(record['fixtureBase'] + '/')
    assert record['result']['snapshots'][0]['error']['message'] != result['snapshots'][0]['error']['message']


@pytest.mark.parametrize('mutation', ['message', 'cause', 'stack', 'owned-root', 'literal-input', 'wire-cause'])
def test_sdk_discovery_evidence_rejects_lost_messages_causes_and_misbound_roots(actual_sdk_error, mutation):
    arguments, result, record = deepcopy(actual_sdk_error)
    error = record['snapshots'][0]['exception']
    if mutation == 'message':
        error['message'] = 'truncated error'
    elif mutation == 'cause':
        del error['properties']['cause']
        error['cause'] = None
    elif mutation == 'stack':
        del error['stack']
    elif mutation == 'owned-root':
        record['fixtureBase'] += '-peer'
    elif mutation == 'literal-input':
        record['input']['failure']['message'] = 'different IO facts'
    else:
        del result['snapshots'][0]['error']['cause']
    with pytest.raises(ValueError):
        validate_storage_discovery_diagnostic(record, arguments, result, side='python')


def test_scan_error_keeps_a_supplied_native_string_code_and_original_cause(tmp_path):
    cause = OSError('literal IO failure')
    cause.code = 'EIO'
    wrapped = MemorySourceScanError(tmp_path, cause)
    assert wrapped.cause is cause
    assert wrapped.code == 'EIO'
    assert str(wrapped) == f'memory source scan failed at {tmp_path} (EIO): literal IO failure'


def _native_transport_guard_fixture(actual_sdk_error):
    """Synthetic serializer shape solely for negative guard tests, never a native oracle."""
    arguments, result, record = deepcopy(actual_sdk_error)

    def convert(error):
        envelope = error.copy()
        properties = {key: envelope[key] for key in ('message', 'code', 'path')}
        if envelope['cause'] is not None:
            properties['cause'] = convert(envelope['cause'])
        properties['stack'] = envelope['type'] + ': ' + envelope['message']
        return {'type': 'Error', 'name': envelope['type'], 'message': envelope['message'], 'properties': [
            {'key': key, 'value': value, 'kind': 'data', 'writable': True, 'enumerable': False, 'configurable': True}
            for key, value in properties.items()
        ]}

    record['snapshots'][0]['exception'] = convert(record['snapshots'][0]['result']['error'])
    return arguments, result, record


def test_native_error_transport_accepts_complete_properties_and_stack(actual_sdk_error):
    arguments, result, record = _native_transport_guard_fixture(actual_sdk_error)
    validate_storage_discovery_diagnostic(record, arguments, result, side='native')


def test_native_error_transport_keeps_the_actual_v8_stack_accessor_and_its_value(actual_sdk_error):
    arguments, result, record = _native_transport_guard_fixture(actual_sdk_error)
    stack = next(item for item in record['snapshots'][0]['exception']['properties'] if item['key'] == 'stack')
    del stack['writable']
    stack.update(kind='accessor', get={'name': '', 'source': 'function () { [native code] }'},
                 set={'name': '', 'source': 'function () { [native code] }'})
    validate_storage_discovery_diagnostic(record, arguments, result, side='native')


@pytest.mark.parametrize('mutation', ['message', 'cause', 'stack', 'descriptor'])
def test_native_error_transport_rejects_lost_cause_stack_and_property_descriptors(actual_sdk_error, mutation):
    arguments, result, record = _native_transport_guard_fixture(actual_sdk_error)
    properties = record['snapshots'][0]['exception']['properties']
    if mutation == 'message':
        record['snapshots'][0]['exception']['message'] = 'different wrapper'
    elif mutation in {'cause', 'stack'}:
        properties[:] = [item for item in properties if item['key'] != mutation]
    else:
        del properties[0]['writable']
    with pytest.raises(ValueError):
        validate_storage_discovery_diagnostic(record, arguments, result, side='native')


@pytest.mark.parametrize('code,detail', [
    ('EIO', 'i/o error'), ('EACCES', 'permission denied'), ('ENOMEM', 'not enough memory'),
    ('ENFILE', 'file table overflow'), ('ELOOP', 'too many symbolic links encountered'),
])
def test_real_scan_boundary_bridges_standard_os_error_facts_and_retains_original_exception(tmp_path, monkeypatch, code, detail):
    from memory_core.workspace import list_memory_files

    number = getattr(errno, code)
    original = OSError(number, os.strerror(number), str(tmp_path))

    def failed(_path):
        raise original

    monkeypatch.setattr(os, 'scandir', failed)
    with pytest.raises(MemorySourceScanError) as caught:
        list_memory_files(tmp_path)
    wrapped = caught.value
    assert wrapped.cause.name == 'Error'
    assert wrapped.cause.code == code
    assert wrapped.cause.errno == -number
    assert wrapped.cause.syscall == 'scandir'
    assert wrapped.cause.path == str(tmp_path)
    assert wrapped.cause.original_exception is wrapped.__cause__ is original
    assert str(wrapped.cause) == f"{code}: {detail}, scandir '{tmp_path}'"
    assert str(wrapped) == f"memory source scan failed at {tmp_path} ({code}): {wrapped.cause}"


def test_custom_os_error_messages_are_not_rewritten_at_a_real_scan_boundary(tmp_path, monkeypatch):
    from memory_core.workspace import list_memory_files

    original = OSError(errno.EIO, 'keep this literal custom detail', str(tmp_path))

    def failed(_path):
        raise original

    monkeypatch.setattr(os, 'scandir', failed)
    with pytest.raises(MemorySourceScanError) as caught:
        list_memory_files(tmp_path)
    assert caught.value.cause is caught.value.__cause__ is original
    assert str(caught.value) == f'memory source scan failed at {tmp_path} (EIO): {original}'


def test_actual_symlink_loop_fails_at_scandir_without_resolving_or_rebasing_the_root(tmp_path):
    from memory_core.workspace import list_memory_files

    root = tmp_path / 'loop'
    root.symlink_to(root)
    with pytest.raises(MemorySourceScanError) as caught:
        list_memory_files(root)
    assert caught.value.path == root
    assert caught.value.cause.syscall == 'scandir'
    assert caught.value.cause.original_exception is caught.value.__cause__
    assert caught.value.__cause__.filename == str(root)
    assert caught.value.code == 'ELOOP'


def test_actual_overlong_extra_root_preserves_lstat_operation_and_private_os_data(tmp_path):
    from memory_core.workspace import list_memory_files

    root = tmp_path / ('x' * 260)
    with pytest.raises(MemorySourceScanError) as caught:
        list_memory_files(tmp_path, [str(root)])
    assert caught.value.cause.syscall == 'lstat'
    assert caught.value.code == 'ENAMETOOLONG'
    assert caught.value.cause.original_exception.filename == str(root)


def test_actual_io_bridge_raw_evidence_cannot_drop_the_original_python_os_exception(tmp_path):
    arguments = {'workspaceKind': 'symlink-loop'}
    result = run_storage_discovery(arguments, evidence_directory=tmp_path)
    record, = json.loads((tmp_path / 'python-raw.json').read_text())
    validate_storage_discovery_diagnostic(record, arguments, result, side='python')
    original = record['snapshots'][0]['exception']['properties']['cause']['properties'].pop('original_exception')
    assert original == record['snapshots'][0]['exception']['cause']
    assert original['properties']['errno'] == errno.ELOOP
    assert 'Traceback (most recent call last)' in original['stack']
    with pytest.raises(ValueError):
        validate_storage_discovery_diagnostic(record, arguments, result, side='python')
