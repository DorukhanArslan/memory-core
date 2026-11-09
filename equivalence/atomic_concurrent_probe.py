"""Retained genuine concurrent writer observations, with no acceptance credit."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from unittest.mock import patch

from equivalence.atomic_publication_probe import ROOT, _codec, _error, _raw_error
from equivalence.release_runtime import prepare_release_runtime


def cases():
    return [
        {'id': 'cooperating-checked-replacements', 'input': {
            'operation': 'replace', 'path': 'MEMORY.md', 'initial': 'original\n', 'mode': 0o640,
            'writers': [{'id': 'first', 'data': 'first writer\n'}, {'id': 'second', 'data': 'second writer\n'}],
        }},
        {'id': 'exclusive-bootstrap-winner-during-staging', 'input': {
            'operation': 'bootstrap-create', 'path': 'AGENTS.md', 'initial': None, 'mode': 0o640,
            'writers': [{'id': 'first', 'data': 'first complete bootstrap\n'}, {'id': 'second', 'data': 'second complete bootstrap\n'}],
        }},
    ]


def arrange(directory, value):
    root = directory / 'workspace'
    root.mkdir(parents=True)
    if value['initial'] is not None:
        target = root / value['path']
        target.write_text(value['initial'])
        target.chmod(value['mode'])
    (directory / 'openclaw.json').write_text(json.dumps({'logging': {'level': 'silent', 'consoleLevel': 'silent',
                                                                 'file': str(directory / 'native.log')}}))
    return root


def sdk_probe(value, directory):
    from memory_core.atomic_publication import commit_memory_content, hash_memory_content
    from memory_core.bootstrap.lifecycle import _write_file_if_missing

    root = arrange(directory, value)
    target = root / value['path']
    raw = {'input': value, 'directory': str(directory), 'calls': [], 'temporaryPaths': []}
    local = threading.local()
    ready = {writer['id']: threading.Event() for writer in value['writers']}
    release = {writer['id']: threading.Event() for writer in value['writers']}
    invoke_open, invoke_sync, invoke_lstat = os.open, os.fsync, os.lstat
    descriptors = {}

    def lstat_file(path, *args, **kwargs):
        try:
            return invoke_lstat(path, *args, **kwargs)
        except OSError as error:
            if value['operation'] == 'bootstrap-create' and getattr(local, 'id', None) == 'second' and Path(path) == target:
                raw['calls'].append({'operation': 'lstat-rejected', 'id': local.id, 'path': str(path),
                                     'error': _raw_error(error)})
                ready['second'].set()
            raise

    def open_file(path, flags, *args):
        descriptor = invoke_open(path, flags, *args)
        descriptors[descriptor] = str(path)
        raw['calls'].append({'operation': 'open', 'id': getattr(local, 'id', None), 'path': str(path), 'flags': flags})
        if flags & os.O_EXCL:
            raw['temporaryPaths'].append(str(path))
            if value['operation'] == 'replace' and local.id == 'first':
                ready['first'].set()
                if not release['first'].wait(10):
                    raise TimeoutError('Concurrent replacement first stage was not released')
        return descriptor

    def sync_file(descriptor):
        result = invoke_sync(descriptor)
        if value['operation'] == 'bootstrap-create' and '.fs-safe-' in descriptors.get(descriptor, ''):
            raw['calls'].append({'operation': 'stage-sync-complete-held', 'id': local.id})
            ready[local.id].set()
            if not release[local.id].wait(10):
                raise TimeoutError('Concurrent bootstrap completed stage was not released')
        return result

    def writer_operation(writer):
        local.id = writer['id']
        raw['calls'].append({'operation': 'writer-start', 'id': writer['id']})
        if writer['id'] == 'second' and value['operation'] == 'replace':
            ready['second'].set()
        try:
            if value['operation'] == 'replace':
                returned = commit_memory_content(target, content=writer['data'], expected_content=value['initial'],
                    expected_hash=hash_memory_content(value['initial']), temp_prefix='.MEMORY.concurrent-probe')
            else:
                returned = _write_file_if_missing(target, writer['data'])
            result = {'id': writer['id'], 'status': 'fulfilled', 'returned': returned}
            raw['calls'].append({'operation': 'writer-fulfilled', 'id': writer['id'], 'returned': returned})
            return result
        except BaseException as error:
            raw['calls'].append({'operation': 'writer-rejected', 'id': writer['id'], 'exception': _raw_error(error)})
            return {'id': writer['id'], 'status': 'rejected', 'error': _error(error, absent_publication=False)}

    with patch('os.open', open_file), patch('os.fsync', sync_file), patch('os.lstat', lstat_file), ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(writer_operation, value['writers'][0])
        if not ready['first'].wait(10):
            raise TimeoutError('First actual writer stage was not reached')
        second = executor.submit(writer_operation, value['writers'][1])
        if not ready['second'].wait(10):
            raise TimeoutError('Second actual writer stage was not reached')
        if value['operation'] == 'bootstrap-create':
            raw['calls'].append({'operation': 'second-precheck-missing-first-complete-stage-held', 'targetExists': target.exists()})
        release['first'].set()
        first_result = first.result(timeout=10)
        release['second'].set()
        outcomes = [first_result, second.result(timeout=10)]
    files = [{'path': str(path), 'kind': 'file' if path.is_file() else 'other',
              'mode': path.stat().st_mode & 0o7777, **({'bytes': path.read_bytes().hex()} if path.is_file() else {})}
             for path in sorted(root.iterdir())]
    raw['result'] = {'outcomes': outcomes, 'files': files}
    return {'result': raw['result'], 'raw': raw}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.absolute()
    args.output.mkdir(parents=True, exist_ok=False)
    before = prepare_release_runtime(args.checkout, args.runtime)
    records = []
    for case in cases():
        directory = args.output / case['id']
        native_dir = directory / 'native'
        arrange(native_dir, case['input'])
        env = {'PATH': str(args.node.parent) + os.pathsep + os.defpath, 'LANG': 'C.UTF-8', 'TZ': 'UTC',
               'OPENCLAW_STATE_DIR': str(native_dir / 'state'), 'OPENCLAW_HOME': str(native_dir),
               'OPENCLAW_CONFIG_PATH': str(native_dir / 'openclaw.json')}
        process = subprocess.run([str(args.node), str(ROOT / 'equivalence/atomic-concurrent-probe.mjs')],
            input=json.dumps({'input': case['input'], 'directory': str(native_dir),
                              'runtimeRoot': str(args.runtime / 'node_modules/openclaw')}),
            env=env, capture_output=True, text=True, timeout=30)
        (directory / 'native.stdout.json').write_text(process.stdout)
        (directory / 'native.stderr.log').write_text(process.stderr)
        if process.returncode:
            raise RuntimeError(f'Concurrent native observation failed: {case["id"]}; original streams retained')
        native = json.loads(process.stdout)
        sdk = sdk_probe(case['input'], directory / 'sdk')
        (directory / 'sdk.raw.json').write_text(json.dumps(sdk, indent=2))
        native_result = _codec(native['result'], native_dir, native['raw']['temporaryPaths'])
        sdk_result = _codec(sdk['result'], directory / 'sdk', sdk['raw']['temporaryPaths'])
        records.append({'id': case['id'], 'input': case['input'], 'native': native_result, 'sdk': sdk_result,
                        'matched': native_result == sdk_result})
    if prepare_release_runtime(args.checkout, args.runtime) != before:
        raise RuntimeError('The authenticated reference runtime changed during concurrent observations')
    report = {'kind': 'uncredited-concurrent-atomic-development-observations', 'coverageCredit': False,
              'protectedExecution': False, 'sourceBuildReproduced': False, 'cases': records,
              'nodeSha256': hashlib.sha256(args.node.read_bytes()).hexdigest()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'cases': len(records), 'matched': sum(row['matched'] for row in records), 'coverageCredit': False}))


if __name__ == '__main__':
    main()
