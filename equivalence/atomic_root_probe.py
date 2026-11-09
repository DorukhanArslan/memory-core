"""Uncredited real rooted append/create observations, including kernel EFBIG."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
from unittest.mock import patch

from equivalence.atomic_publication_probe import ROOT, _codec, _error, _raw_error
from equivalence.release_runtime import prepare_release_runtime


def _root_error(error):
    # Root owners publish ordinary/FsSafe errors, not a synthetic null
    # commitMemoryContent publication field borrowed from another profile.
    return _error(error, absent_publication=False)


def cases(profile='root'):
    values = [
        ('bootstrap-missing', {'operation': 'bootstrap-create', 'path': 'AGENTS.md', 'initial': None, 'data': 'complete bootstrap data\n'}),
        ('bootstrap-existing', {'operation': 'bootstrap-create', 'path': 'AGENTS.md', 'initial': 'original\n', 'data': 'new\n'}),
        ('bootstrap-real-partial-efbig', {'operation': 'bootstrap-create', 'path': 'AGENTS.md', 'initial': None,
                                           'data': 'complete bootstrap data\n', 'fileLimit': 8}),
        ('append-existing-newline', {'operation': 'append', 'path': 'memory/2026-09-04.md', 'initial': 'original\n', 'data': 'new\n'}),
        ('append-existing-without-newline', {'operation': 'append', 'path': 'memory/2026-09-04.md', 'initial': 'original', 'data': 'new\n'}),
        ('append-leading-newline', {'operation': 'append', 'path': 'memory/2026-09-04.md', 'initial': 'original', 'data': '\nnew\n'}),
        ('append-missing', {'operation': 'append', 'path': 'memory/2026-09-04.md', 'initial': None, 'data': 'new\n'}),
        ('append-real-partial-efbig', {'operation': 'append', 'path': 'memory/2026-09-04.md', 'initial': 'before\n',
                                       'data': 'new complete append data\n', 'fileLimit': 8}),
    ]
    if profile in {'faults', 'no-progress'}:
        values = []
        for operation in ('bootstrap-create', 'append'):
            faults = [('write-zero', None)] if profile == 'no-progress' else [
                ('file-sync', 'EIO'), ('file-sync', 'EPERM'), ('parent-sync', 'EIO'), ('write-partial', 'EIO'),
            ]
            for stage, code in faults:
                values.append((f'{operation}-{stage}-{str(code).lower()}', {
                    'operation': operation, 'path': 'AGENTS.md' if operation == 'bootstrap-create' else 'memory.md',
                    'initial': None, 'data': 'complete written payload\n',
                    'fault': {'stage': stage, 'code': code, 'message': f'literal {stage} fault {code}'},
                }))
    return [{'id': name, 'input': {'umask': 0o022, 'mode': 0o640, **value}} for name, value in values]


@contextmanager
def io_observation(value, root, raw):
    original_open, original_write, original_sync = os.open, os.write, os.fsync
    descriptors, armed = {}, 'fault' in value
    raw['calls'] = []

    def failure(stage):
        nonlocal armed
        armed = False
        raw['calls'].append({'operation': 'injected-error', 'stage': stage, 'facts': value['fault']})
        error = OSError(value['fault']['message'])
        error.name, error.code = 'Error', value['fault']['code']
        return error

    def open_file(path, flags, *arguments):
        descriptor = original_open(path, flags, *arguments)
        if Path(path).absolute().is_relative_to(root.absolute()):
            descriptors[descriptor] = str(path)
            raw['calls'].append({'operation': 'open', 'path': str(path), 'flags': flags, 'fd': descriptor})
        return descriptor

    def write_file(descriptor, data):
        nonlocal armed
        if descriptor in descriptors:
            raw['calls'].append({'operation': 'write', 'path': descriptors[descriptor], 'fd': descriptor,
                                 'bytes': bytes(data).hex()})
            if armed and value['fault']['stage'] == 'write-zero':
                armed = False
                raw['calls'].append({'operation': 'injected-zero-progress-write', 'stage': 'write-zero'})
                return 0
            if armed and value['fault']['stage'] == 'write-partial':
                written = original_write(descriptor, data[:2])
                raw['calls'].append({'operation': 'partial-write-return', 'written': written})
                raise failure('write-partial')
        return original_write(descriptor, data)

    def sync_file(descriptor):
        if descriptor in descriptors:
            stage = 'parent-sync' if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 'file-sync'
            raw['calls'].append({'operation': 'fsync', 'path': descriptors[descriptor], 'fd': descriptor, 'stage': stage})
            if armed and value['fault']['stage'] == stage:
                raise failure(stage)
        return original_sync(descriptor)

    try:
        with patch('os.open', open_file), patch('os.write', write_file), patch('os.fsync', sync_file):
            yield
    finally:
        raw['faultConsumed'] = None if 'fault' not in value else not armed


def arrange(directory, value):
    root = directory / 'workspace'
    target = root / value['path']
    target.parent.mkdir(parents=True)
    if value['initial'] is not None:
        target.write_text(value['initial'])
        target.chmod(value['mode'])
    (directory / 'openclaw.json').write_text(json.dumps({'logging': {'level': 'silent', 'consoleLevel': 'silent',
                                                                 'file': str(directory / 'native.log')}}))
    return root, target


@contextmanager
def process_options(value):
    mask, limits, sig = os.umask(value['umask']), resource.getrlimit(resource.RLIMIT_FSIZE), signal.getsignal(signal.SIGXFSZ)
    try:
        if 'fileLimit' in value:
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (value['fileLimit'], limits[1]))
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, limits)
        signal.signal(signal.SIGXFSZ, sig)
        os.umask(mask)


def sdk_bootstrap(value, directory):
    from memory_core.bootstrap.lifecycle import _write_file_if_missing

    root, target = arrange(directory, value)
    raw = {'input': value, 'directory': str(directory), 'owner': 'bootstrap.lifecycle._write_file_if_missing'}
    try:
        with process_options(value), io_observation(value, root, raw):
            returned = _write_file_if_missing(target, value['data'])
        observed = {'status': 'fulfilled', 'returned': returned}
    except BaseException as error:
        raw['exception'] = _raw_error(error)
        observed = {'status': 'rejected', 'error': _root_error(error)}
    files = []
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        files.append({'path': str(path), 'kind': 'file' if path.is_file() else 'directory' if path.is_dir() else 'other',
                      'mode': stat.S_IMODE(info.st_mode), **({'bytes': path.read_bytes().hex()} if path.is_file() else {})})
    raw['result'] = {**observed, 'files': files}
    return {'result': raw['result'], 'raw': raw}


def sdk_append(value, directory):
    from memory_core.atomic_publication import append_memory_content

    root, target = arrange(directory, value)
    raw = {'input': value, 'directory': str(directory), 'owner': 'atomic_publication.append_memory_content'}
    try:
        with process_options(value), io_observation(value, root, raw):
            returned = append_memory_content(target, value['data'], prepend_newline_if_needed=True)
        observed = {'status': 'fulfilled', 'returned': returned}
    except BaseException as error:
        raw['exception'] = _raw_error(error)
        observed = {'status': 'rejected', 'error': _root_error(error)}
    files = []
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        files.append({'path': str(path), 'kind': 'file' if path.is_file() else 'directory' if path.is_dir() else 'other',
                      'mode': stat.S_IMODE(info.st_mode), **({'bytes': path.read_bytes().hex()} if path.is_file() else {})})
    raw['result'] = {**observed, 'files': files}
    return {'result': raw['result'], 'raw': raw}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=['root', 'faults', 'no-progress'], default='root')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    before = prepare_release_runtime(args.checkout, args.runtime)
    report = {'kind': 'uncredited-default-root-development-observations', 'coverageCredit': False,
              'protectedExecution': False, 'sourceBuildReproduced': False, 'cases': [],
              'nodeSha256': hashlib.sha256(args.node.read_bytes()).hexdigest(),
              'profile': 'Default genuine reference backend. Per-process POSIX umask and RLIMIT_FSIZE are literal fixtures; no test flags or alternate backend. Complete Root append and bootstrap creation returns/errors/files are paired; original exceptions and physical identities remain raw.'}
    for case in cases(args.profile):
        value = case['input']
        directory = args.output / case['id']
        native_dir = directory / 'native'
        arrange(native_dir, value)
        environment = {'PATH': str(args.node.parent) + os.pathsep + os.defpath, 'LANG': 'C.UTF-8', 'TZ': 'UTC',
                       'OPENCLAW_STATE_DIR': str(native_dir / 'state'), 'OPENCLAW_CONFIG_PATH': str(native_dir / 'openclaw.json'),
                       'OPENCLAW_HOME': str(native_dir)}

        def child_limits():
            if 'fileLimit' in value:
                signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
                resource.setrlimit(resource.RLIMIT_FSIZE, (value['fileLimit'], resource.getrlimit(resource.RLIMIT_FSIZE)[1]))

        process = subprocess.run([str(args.node), str(ROOT / 'equivalence/atomic-root-probe.mjs')],
                                 input=json.dumps({'input': value, 'directory': str(native_dir),
                                                   'runtimeRoot': str(args.runtime / 'node_modules/openclaw')}),
                                 env=environment, preexec_fn=child_limits, capture_output=True, text=True, timeout=30)
        (directory / 'native.stdout.json').write_text(process.stdout)
        (directory / 'native.stderr.log').write_text(process.stderr)
        if process.returncode:
            raise RuntimeError(f'Native default Root observation failed: {case["id"]}; original streams retained')
        native = json.loads(process.stdout)
        record = {'id': case['id'], 'input': value, 'native': _codec(native['result'], native_dir, [])}
        sdk = (sdk_bootstrap if value['operation'] == 'bootstrap-create' else sdk_append)(value, directory / 'sdk')
        (directory / 'sdk.raw.json').write_text(json.dumps(sdk, indent=2))
        record['sdk'] = _codec(sdk['result'], directory / 'sdk', [])
        record['diagnostics'] = ([] if 'fault' not in value else [
            f'{name} literal IO fault did not dispatch' for name, observed in [('native', native), ('sdk', sdk)]
            if observed['raw'].get('faultConsumed') is not True
        ])
        record['matched'] = not record['diagnostics'] and record['native'] == record['sdk']
        report['cases'].append(record)
    if prepare_release_runtime(args.checkout, args.runtime) != before:
        raise RuntimeError('The original runtime changed during observations')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'cases': len(report['cases']), 'paired': sum('sdk' in item for item in report['cases']),
                      'matched': sum(item.get('matched', False) for item in report['cases']), 'coverageCredit': False}))


if __name__ == '__main__':
    main()
