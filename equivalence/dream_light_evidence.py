"""Cross-check original light-sweep receipts against the captured files and SQLite."""

from __future__ import annotations

import base64
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
from tempfile import TemporaryDirectory
import zlib

from equivalence.dream_light import RECALL, SIGNALS, canonical, validate_case
from equivalence.dream_light_bindings import COMPILED, FUNCTION_HASHES, REM_COMPILED
from equivalence import dream_rem


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected, message):
    require(canonical(actual) == canonical(expected), message)


def _decode_blobs(raw):
    require(raw['blobEncoding'] == 'gzip-base64', 'Unrecognized native blob encoding')
    blobs = {}
    total = 0
    for sha, encoded in raw['blobs'].items():
        compressed = base64.b64decode(encoded, validate=True)
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        maximum = min(4 * 1024 ** 2, 16 * 1024 ** 2 - total)
        data = decoder.decompress(compressed, maximum + 1)
        require(len(data) <= maximum and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
                and hashlib.sha256(data).hexdigest() == sha, 'Native file size, framing or bytes changed')
        blobs[sha] = data
        total += len(data)
    return blobs


def _tree(tree, blobs):
    result = {}
    for name, info in tree.items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and name == str(path), 'Unsafe capture path')
        data = blobs[info['sha256']]
        require(type(info['size']) is int and info['size'] == len(data), 'Incomplete native file')
        require(type(info['mtimeMs']) in (int, float), 'Native file observation lost its mtime')
        result[name] = data
    return result


def _physical(tree, workspace, now):
    """Read the native capture, including the actual SQLite WAL when present."""
    name = 'state/state/openclaw.sqlite'
    rows = []
    if name in tree:
        with TemporaryDirectory() as directory:
            copy = Path(directory, 'snapshot.sqlite')
            copy.write_bytes(tree[name])
            if name + '-wal' in tree:
                Path(str(copy) + '-wal').write_bytes(tree[name + '-wal'])
            with closing(sqlite3.connect(copy.as_uri() + '?mode=ro', uri=True)) as db:
                require(db.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'Native SQLite is inconsistent')
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='plugin_state_entries'").fetchone():
                    rows = db.execute('SELECT namespace, entry_key, value_json FROM plugin_state_entries '
                                      'WHERE plugin_id=? ORDER BY entry_key', ('memory-core',)).fetchall()
    stores = {kind: {'version': 1, 'updatedAt': now, 'entries': {}} for kind in ('recall', 'phase')}
    events = []
    key = hashlib.sha256(workspace.encode()).hexdigest()
    namespaces = {'short-term-recall': 'recall', 'short-term-phase-signals': 'phase'}
    for ns, row_key, body in rows:
        item = json.loads(body)
        if ns in namespaces or ns == 'short-term-meta':
            require(item['workspaceKey'] == key and item['workspaceDir'] == workspace and
                    row_key == key + ':' + hashlib.sha256(item['key'].encode()).hexdigest(),
                    'Native state row belongs to another workspace or key')
            if ns in namespaces:
                stores[namespaces[ns]]['entries'][item['key']] = item['value']
            elif item['key'] in stores:
                stores[item['key']]['updatedAt'] = item['value']['updatedAt']
        elif ns == 'memory-host.events':
            events.append((item['sequence'], item['event']))
    require(len({seq for seq, _ in events}) == len(events), 'Repeated native event sequence')
    return stores, [event for _, event in sorted(events)]


def _event_paths(events, workspace):
    prefix = workspace + '/'
    return [{k: ('$WORKSPACE/' + v[len(prefix):] if k in ('reportPath', 'inlinePath')
                 and isinstance(v, str) and v.startswith(prefix) else v)
             for k, v in event.items()} for event in events]


def validate_dream_light_native(case, public, snapshots, evidence_directory, loaded):
    phase = 'rem' if case.get('operation') == dream_rem.OPERATION else 'light'
    if phase == 'rem':
        from equivalence import dream_rem_evidence as rem
        dream_rem.validate_case(case)
    else:
        validate_case(case)
    require(isinstance(snapshots, list) and len(snapshots) == 1, 'One complete native capture required')
    raw = snapshots[0]
    value = case['input']
    root = Path(raw['root'])
    workspace = str(root / 'workspace')
    require(root.is_absolute() and root.parent == Path(evidence_directory) and root.name.startswith(f'native-{phase}-')
            and raw['workspace'] == workspace, 'Native sweep lost its owned workspace')
    require(raw['kind'] == f'official-{phase}-sweep' and raw.get('completed') is True
            and raw.get('storeClosed') is True and raw.get('clockRestored') is True
            and not ({'error', 'closeError', 'snapshotError'} & raw.keys()), 'Original sweep did not close')
    same(raw['input'], value, 'Native input changed')
    require(raw['inputSha256'] == hashlib.sha256(canonical(value)).hexdigest(), 'Native input hash changed')
    compiled = {**COMPILED, **REM_COMPILED} if phase == 'rem' else COMPILED
    for owner, (sha, _) in compiled.items():
        item = loaded.get(('node_modules/openclaw', owner))
        require(isinstance(item, dict) and item['sha256'] == sha, 'Missing original runtime module ' + owner)
    store = 'dist/short-term-promotion-store-B6T388Bo.mjs'
    keyed = 'dist/plugin-state-store-BPUaLoVD.mjs'
    expected = {'configureMemoryCoreDreamingState': ('dist/dreaming-state-VYUvbU-n.mjs', 'p'),
                'createPluginStateKeyedStore': (keyed, 'r'), 'closePluginStateDatabaseAsync': (keyed, 'u'),
                'runDreamingSweepPhases': ('dist/dreaming-phases-rmgXNBLP.mjs', 'r'),
                'readShortTermStore': (store, 'i'), 'readStore': (store, 'a'),
                'readPhaseSignalStore': (store, 'r'),
                'readMemoryHostEventRecords': ('dist/plugin-sdk/memory-host-events.js', 'readMemoryHostEventRecords')}
    if RECALL in value['files']:
        expected['writeStore'] = (store, 'l')
    if SIGNALS in value['files']:
        expected['writePhaseSignalStore'] = (store, 'c')
    require(len(raw['owners']) == len(expected) and {o['name'] for o in raw['owners']} == set(expected),
            'Missing or duplicated original function')
    for owner in raw['owners']:
        module, alias = expected[owner['name']]
        require((owner['relative'], owner['alias']) == (module, alias) and owner['artifactSha256'] == COMPILED[module][0]
                and owner['sourceSha256'] == FUNCTION_HASHES[owner['name']], 'Wrong original function target')
    cfg = {'agents': {'defaults': {'workspace': workspace, 'userTimezone': 'UTC'},
                     'list': [{'id': 'main', 'workspace': workspace}]},
           'logging': {'level': 'silent', 'consoleLevel': 'silent', 'file': str(root / 'openclaw.log')}}
    env = {'OPENCLAW_STATE_DIR': str(root / 'state'), 'OPENCLAW_HOME': str(root),
           'OPENCLAW_CONFIG_PATH': str(root / 'openclaw.json')}
    opts = value['options']
    if phase == 'rem':
        phases = rem.phase_config(opts)
        rem.validate_callbacks(raw, opts)
    else:
        phases = {'light': {'enabled': True, **{k: opts[k] for k in ('limit', 'lookbackDays', 'dedupeSimilarity')}},
                  'rem': {'enabled': False}}
    plugin = {'dreaming': {'enabled': opts['enabled'], 'timezone': opts['timezone'],
                           'storage': {'mode': opts['storageMode']}, 'phases': phases}}
    same(raw['cfg'], cfg, 'Native configuration changed')
    same(raw['env'], env, 'Native storage escaped its owned fixture')
    same(raw['pluginConfig'], plugin, 'Native phase configuration changed')
    require(raw['factoryCalls'], 'Original SQLite state factory was not called')
    for call in raw['factoryCalls']:
        require(call['pluginId'] == 'memory-core' and call['returnedMethods'], 'Wrong native state factory')
        same(call['selectedOptions'], {**call['options'], 'env': env}, 'Native SQLite options changed')

    calls = deque(raw['calls'])

    def take(name, args, *, undefined=False):
        require(calls, 'Missing native call ' + name)
        receipt = calls.popleft()
        require(set(receipt) == {'name', 'args', 'returned'} and receipt['name'] == name, 'Unexpected native call')
        same(receipt['args'], args, name + ' input changed')
        result = receipt['returned']
        if undefined:
            same(result, {'kind': 'undefined'}, name + ' returned a different outcome')
        else:
            require(result.keys() == {'kind', 'value'} and result['kind'] == 'value', 'Missing return from ' + name)
            return result['value']

    blobs = _decode_blobs(raw)
    require(len(raw['snapshots']) == len(value['operations']) + 1, 'Native filesystem boundary is missing')
    trees = [_tree(row, blobs) for row in raw['snapshots']]
    same(json.loads(trees[0]['openclaw.json']), cfg, 'Physical configuration disagrees with invocation')
    initial_files = {k[len('workspace/'):]: v.decode() for k, v in trees[0].items() if k.startswith('workspace/')}
    same(initial_files, value['files'], 'Native seed files changed')
    now_ms = value['operations'][0]['nowMs']
    for file, method in [(RECALL, 'writeStore'), (SIGNALS, 'writePhaseSignalStore')]:
        if file in value['files']:
            take(method, [workspace, json.loads(value['files'][file])], undefined=True)
    observations = []
    model_calls, sweep_results = [], []
    for operation, tree in zip(value['operations'], trees[1:], strict=True):
        if operation['op'] == phase:
            now_ms = operation['nowMs']
        now = datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        if operation['op'] == phase:
            args = {'workspaceDir': workspace, 'cfg': cfg, 'pluginConfig': plugin, 'nowMs': now_ms}
            agent = opts['agentId'] if phase == 'rem' else 'main'
            if agent is not None:
                args['agentId'] = agent
            outcome = take('runDreamingSweepPhases', [args])
            require(set(outcome) == {'degradedPhases', 'pendingNarratives'} and all(type(n) is int for n in outcome.values()),
                    'Incomplete original sweep return')
            if phase == 'rem':
                model_calls.extend(rem.callback_effects(raw, now_ms, now, workspace, take))
                sweep_results.append(outcome)
        else:
            require('workspace/' + operation['path'] not in tree, 'Removed input still exists')
        physical, recorded = _physical(tree, workspace, now)
        for kind in ('recall', 'phase'):
            same(take('readShortTermStore', [workspace, kind, now]), physical[kind], 'Native SQLite store differs from its API')
        recall = take('readStore', [workspace, now])
        signals = take('readPhaseSignalStore', [workspace, now])
        events = take('readMemoryHostEventRecords', [{'workspaceDir': workspace, 'env': env}])
        same(events, recorded, 'Native SQLite event stream differs from its API')
        documents = {k[len('workspace/'):]: v.decode() for k, v in tree.items() if k.startswith('workspace/') and k.endswith('.md')}
        observations.append({'operation': operation, 'documents': documents, 'recall': recall,
                             'signals': signals, 'events': _event_paths(events, workspace)})
        if phase == 'rem':
            observations[-1].update(modelCalls=list(model_calls), sweepResults=list(sweep_results))
    if phase == 'rem':
        same(model_calls, [entry['request'] for entry in raw['modelCalls']], 'Native callback escaped its invocation')
        rem.validate_publication(case, raw, trees, observations)
    require(not calls, 'Unexpected native invocation')
    same(raw['observations'], observations, 'Native observation differs from its actual state')
    same(public, {'observations': observations}, 'Public result lost original fields')
