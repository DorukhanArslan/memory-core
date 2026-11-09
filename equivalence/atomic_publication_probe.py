"""Uncredited genuine native/current SDK atomic-publication baseline.

This does not use or change the shared acceptance harness. Compiled artifacts
are authenticated before/after, but process execution is development-only.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import traceback
from unittest.mock import patch

from equivalence.release_runtime import prepare_release_runtime


ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'extensions/memory-core/src/short-term-promotion-memory-write.ts'
ARTIFACTS = ('dist/short-term-promotion-memory-write-DLJgScco.mjs',
             'dist/short-term-promotion-memory-write-HTLC95gL.mjs')


def cases():
    seed = {'initial': '# Memory\n\n- original\n', 'replacement': '# Memory\n\n- replacement\n', 'mode': 0o640}
    return [{'id': name, 'input': {**seed, **extra}} for name, extra in [
        ('ordinary-replace', {}),
        ('temp-file-fsync-eperm', {'fault': {'stage': 'temp-sync', 'code': 'EPERM', 'message': 'literal fsync refusal'}}),
        ('temp-file-fsync-eio', {'fault': {'stage': 'temp-sync', 'code': 'EIO', 'message': 'literal sync failure'}}),
        ('parent-directory-fsync-eio', {'fault': {'stage': 'parent-sync', 'code': 'EIO', 'message': 'literal directory sync failure'}}),
        ('rename-rejected-before-mutation', {'fault': {'stage': 'rename-before', 'code': 'EACCES', 'message': 'literal rename refusal'}}),
        ('rename-mutates-then-rejects', {'fault': {'stage': 'rename-after', 'code': 'EIO', 'message': 'literal dispatched rename failure'}}),
        ('published-target-external-inplace-edit', {'fault': {'stage': 'published-replaced'}, 'external': '# External edit\n'}),
        ('published-target-rename-replacement', {'fault': {'stage': 'published-renamed'}, 'external': '# External replacement\n'}),
    ]]


def _error(error):
    return {'name': getattr(error, 'name', type(error).__name__), 'message': str(error),
            'code': getattr(error, 'code', errno.errorcode.get(getattr(error, 'errno', None))),
            'path': str(error.path) if hasattr(error, 'path') else None,
            'publication': getattr(error, 'publication', None),
            'cause': _error(error.__cause__) if error.__cause__ is not None else None}


def _raw_error(error):
    properties = {key: _raw_error(value) if isinstance(value, BaseException) else str(value) if isinstance(value, Path) else value
                  for key, value in vars(error).items()}
    properties.update({key: getattr(error, key) for key in ('errno', 'strerror', 'filename', 'filename2') if hasattr(error, key)})
    return {'type': type(error).__name__, 'module': type(error).__module__, 'message': str(error),
            'properties': properties, 'args': error.args, 'stack': ''.join(traceback.format_exception(error)),
            'cause': _raw_error(error.__cause__) if error.__cause__ is not None else None}


def sdk_probe(input, directory):
    from memory_core.curation import MemoryCurator

    root = directory / 'workspace'
    root.mkdir(parents=True)
    target = root / 'MEMORY.md'
    if input['initial'] is not None:
        target.write_text(input['initial'])
        target.chmod(input['mode'])
    raw = {'input': input, 'directory': str(directory), 'pid': os.getpid(), 'calls': [], 'tempPaths': []}
    original = {name: getattr(os, name) for name in ('open', 'fsync', 'replace', 'unlink', 'chmod', 'close')}
    paths = {}
    armed = True

    class ProbeIOError(OSError):
        name = 'Error'

        def __init__(self, facts, path):
            super().__init__(facts['message'])
            self.code, self.path, self.syscall = facts['code'], str(path), facts['stage']

    def fault(stage, path):
        nonlocal armed
        if armed and input.get('fault', {}).get('stage') == stage:
            armed = False
            raw['calls'].append({'operation': 'injected-error', 'stage': stage, 'path': str(path), 'facts': input['fault']})
            raise ProbeIOError(input['fault'], path)

    def io_open(path, flags, mode=0o777, *args, **kwargs):
        fd = original['open'](path, flags, mode, *args, **kwargs)
        paths[fd] = str(path)
        raw['calls'].append({'operation': 'open', 'path': str(path), 'flags': flags, 'mode': mode, 'fd': fd})
        if flags & os.O_CREAT and flags & os.O_EXCL:
            raw['tempPaths'].append(str(path))
        return fd

    def fsync(fd):
        path = paths.get(fd)
        raw['calls'].append({'operation': 'fsync', 'fd': fd, 'path': path,
                             'kind': 'file' if stat.S_ISREG(os.fstat(fd).st_mode) else 'directory'})
        if path in raw['tempPaths']:
            fault('temp-sync', path)
        if path == str(root):
            fault('parent-sync', path)
        return original['fsync'](fd)

    def replace(source, destination):
        raw['calls'].append({'operation': 'replace', 'source': str(source), 'destination': str(destination)})
        fault('rename-before', destination)
        returned = original['replace'](source, destination)
        fault('rename-after', destination)
        nonlocal armed
        if input.get('fault', {}).get('stage') == 'published-replaced' and armed:
            armed = False
            Path(destination).write_text(input['external'])
            raw['calls'].append({'operation': 'external-write-after-rename', 'path': str(destination), 'text': input['external']})
        if input.get('fault', {}).get('stage') == 'published-renamed' and armed:
            armed = False
            external = root / 'external-next'
            external.write_text(input['external'])
            original['replace'](external, destination)
            raw['calls'].append({'operation': 'external-rename-after-rename', 'source': str(external),
                                 'path': str(destination), 'text': input['external']})
        return returned

    def observed(name):
        def call(*args, **kwargs):
            raw['calls'].append({'operation': name, 'arguments': [str(item) if isinstance(item, Path) else item for item in args]})
            return original[name](*args, **kwargs)
        return call

    try:
        with ExitStack() as stack:
            for name, function in [('open', io_open), ('fsync', fsync), ('replace', replace),
                                   *[(name, observed(name)) for name in ('unlink', 'chmod', 'close')]]:
                stack.enter_context(patch.object(os, name, function))
            returned = MemoryCurator(root)._write_target('MEMORY.md', input['initial'], input['replacement'])
        result = {'status': 'fulfilled', 'returned': returned}
    except BaseException as error:
        raw['exception'] = _raw_error(error)
        result = {'status': 'rejected', 'error': _error(error)}
    raw['faultConsumed'] = not armed
    files = []
    for path in sorted(root.iterdir()):
        info = path.lstat()
        files.append({'path': str(path), 'mode': stat.S_IMODE(info.st_mode),
                      'kind': 'file' if path.is_file() else 'symlink' if path.is_symlink() else 'other',
                      **({'bytes': path.read_bytes().hex()} if path.is_file() else {})})
    raw['result'] = {**result, 'files': files}
    return {'result': raw['result'], 'raw': raw}


def _codec(value, directory, temporary):
    if isinstance(value, str):
        for index, filename in enumerate(temporary):
            value = value.replace(filename, f'$TEMPFILE-{index}')
        return value.replace(str(directory) + '/', '$FIXTURE/')
    if isinstance(value, list):
        return [_codec(item, directory, temporary) for item in value]
    if isinstance(value, dict):
        return {key: _codec(item, directory, temporary) for key, item in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = prepare_release_runtime(args.checkout, args.runtime)
    records = []
    provenance = {'sourceBuildReproduced': False, 'protectedExecution': False, 'coverageCredit': False,
                  'referenceCommit': runtime['referenceCommit'] if 'referenceCommit' in runtime else 'bcfc88812a35243893585dbeca87ca41b48272ca',
                  'source': {'path': SOURCE, 'sha256': hashlib.sha256((args.checkout / SOURCE).read_bytes()).hexdigest()},
                  'artifacts': {name: hashlib.sha256((args.runtime / 'node_modules/openclaw' / name).read_bytes()).hexdigest() for name in ARTIFACTS},
                  'node': {'path': str(args.node.resolve()), 'sha256': hashlib.sha256(args.node.read_bytes()).hexdigest()},
                  'normalization': 'Only exact owned fixture prefix and each actual exclusive-open temp pathname map to fixed labels. Complete raw original values remain retained; no publication marker is inferred.'}
    for case in cases():
        directory = args.output / case['id']
        directory.mkdir()
        native_dir = directory / 'native'
        native_dir.mkdir()
        request = {'input': case['input'], 'directory': str(native_dir), 'runtimeRoot': str(args.runtime / 'node_modules/openclaw')}
        environment = {'PATH': str(args.node.parent) + os.pathsep + os.defpath, 'LANG': 'C.UTF-8', 'TZ': 'UTC',
                       'OPENCLAW_STATE_DIR': str(native_dir / 'state'), 'OPENCLAW_CONFIG_PATH': str(native_dir / 'openclaw.json'),
                       'OPENCLAW_HOME': str(native_dir)}
        (native_dir / 'openclaw.json').write_text(json.dumps({'logging': {'level': 'silent', 'consoleLevel': 'silent', 'file': str(native_dir / 'native.log')}}))
        process = subprocess.run([str(args.node), str(ROOT / 'equivalence/atomic-publication-probe.mjs')],
                                 input=json.dumps(request), text=True, capture_output=True, env=environment, timeout=30)
        (directory / 'native.stdout.json').write_text(process.stdout)
        (directory / 'native.stderr.log').write_text(process.stderr)
        if process.returncode:
            raise RuntimeError(f'Native development probe failed: {case["id"]}; streams retained')
        native = json.loads(process.stdout)
        sdk = sdk_probe(case['input'], directory / 'sdk')
        (directory / 'sdk.raw.json').write_text(json.dumps(sdk, indent=2))
        native_result = _codec(native['result'], native_dir, native['raw']['tempPaths'])
        sdk_result = _codec(sdk['result'], directory / 'sdk', sdk['raw']['tempPaths'])
        records.append({'id': case['id'], 'input': case['input'], 'matched': native_result == sdk_result,
                        'native': native_result, 'sdk': sdk_result})
    if prepare_release_runtime(args.checkout, args.runtime) != runtime:
        raise RuntimeError('The authenticated runtime changed during development observations')
    report = {'kind': 'uncredited-atomic-publication-development-observations', 'provenance': provenance, 'cases': records}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'matched': sum(item['matched'] for item in records), 'cases': len(records), 'coverageCredit': False}))


if __name__ == '__main__':
    main()
