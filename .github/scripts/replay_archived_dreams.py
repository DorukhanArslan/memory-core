"""Reopen the ZIP's SDK files and distinguish them from original filesystem metadata.

The sealed live validators already checked the original machine. ZIP transports the
file data, not its inodes or nanosecond timestamps. The original process, source,
complete public result, calls, transitions, SQLite and wire-digest checks continue
through the sealed family reviewers. This module is imported only by the external
archive assessor; it does not modify the sealed checkout or recorded values.
"""
from __future__ import annotations

from contextlib import ExitStack, closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
from types import FunctionType
from unittest.mock import patch

from equivalence import dream_deep_evidence
from equivalence.dream_light_evidence import require, same
from equivalence.harness import _same_json, ROOT
from equivalence.runtime_oracle import MAX_DIAGNOSTIC_BYTES, _owned_regular
import followup_diary
import followup_dreams
import followup_families

_PHASES = ('dream-light-runtime', 'dream-rem-runtime', 'dream-deep-runtime', 'dream-diary-publication-runtime')
_LIGHT_MESSAGE = 'Final SDK snapshot differs from the live fixture'
_DEEP_MESSAGE = 'Retained SDK workspace differs from its final file snapshot'


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _cold_databases(root, files):
    """Check the exact recovered database and WAL bytes without touching the archive."""
    result = {}
    for name in sorted(n for n in files if n.endswith(('.db', '.sqlite'))):
        with TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'db.sqlite'
            for suffix in ('', '-wal', '-journal'):
                source_name = name + suffix
                if source_name in files:
                    raw = _owned_regular(root, root / source_name, 4 * 1024 * 1024)
                    require(sha256(raw).hexdigest() == files[source_name]['sha256'], 'Dream SQLite bytes changed during cold reopen')
                    Path(str(copy) + suffix).write_bytes(raw)
            with closing(sqlite3.connect(copy.as_uri() + '?mode=ro', uri=True)) as connection:
                require(connection.execute('PRAGMA quick_check').fetchall() == [('ok',)], 'Invalid archived dreaming SQLite')
                tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")]
                require(tables, 'Dream database reopened without a schema')
            result[name] = {'sha256': files[name]['sha256'], 'tables': tables}
    return result


def _phase_receipt(expected, physical, root):
    require(expected and set(expected) == set(physical), 'Missing or extra file in the archived dreaming workspace')
    for name, record in expected.items():
        actual = physical[name]
        require(set(actual) == set(record) == {'size', 'sha256', 'mtimeNs'}
                and type(record['mtimeNs']) is int and type(actual['mtimeNs']) is int
                and type(record['size']) is int and record['size'] == actual['size']
                and record['sha256'] == actual['sha256'], 'Archived dreaming file bytes differ from the producer')
    return {'filesVerified': len(expected), 'contentManifestSha256': _digest({n: [v['size'], v['sha256']] for n, v in expected.items()}),
            'producerMtimeNsSha256': _digest({n: v['mtimeNs'] for n, v in expected.items()}),
            'archiveMtimeNsSha256': _digest({n: v['mtimeNs'] for n, v in physical.items()}),
            'mtimeAuthority': 'producer wire and live validation; ZIP times recorded separately',
            'reopenedDatabases': _cold_databases(root, expected)}


def _diary_receipt(raw, directory):
    workspace = directory / 'sdk-diary'
    require(raw['workspace'] == str(workspace) and workspace.resolve() == workspace, 'Diary receipt belongs to another workspace')
    stages = [raw['initial'], *(s['files'] for s in raw['rows'])]
    for files in stages:
        for name, item in files.items():
            require(name == Path(name).as_posix() and not Path(name).is_absolute() and '..' not in Path(name).parts
                    and item['kind'] in ('file', 'link') and all(type(item[k]) is int for k in ('ino', 'mode', 'mtimeNs'))
                    and item['ino'] > 0 and 0 <= item['mode'] <= 0o7777, 'Invalid original diary filesystem observation')
    expected = stages[-1]
    physical = {}
    if workspace.exists():
        require(workspace.is_dir(), 'Unexpected archived diary root type')
        for path in workspace.rglob('*'):
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue  # ZIP can omit empty directories. They are absent from the producer file inventory.
            name = path.relative_to(workspace).as_posix()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and name in expected,
                    'Unrecognized or redirected file in restored diary')
            physical[name] = _owned_regular(workspace, path, 4 * 1024 * 1024)
    require(set(physical) == set(expected), 'Missing archived diary file')
    dereferenced = []
    for name, item in expected.items():
        if item['kind'] == 'link':
            require(name == 'DREAMS.md' and item['target'] == 'owner-copy.md'
                    and expected.get(item['target'], {}).get('kind') == 'file', 'Unexpected original diary link')
            item = expected[item['target']]
            dereferenced.append(name)
        require(physical[name] == item['text'].encode() and sha256(physical[name]).hexdigest() == item['sha256'],
                'Archived diary file or dereferenced link target bytes changed')
    return {'filesVerified': len(physical), 'contentManifestSha256': _digest({n: sha256(v).hexdigest() for n,v in physical.items()}),
            'producerFilesystemMetadataSha256': _digest([{n: {k: v[k] for k in ('kind','mode','ino','mtimeNs')} for n,v in s.items()} for s in stages]),
            'metadataAuthority': 'producer wire and live validation; ZIP inodes, modes and timestamps are not original',
            'archivedLinkContentsVerified': dereferenced, 'capturedStages': len(stages)}


def _scoped_phase_check(validator, case, public, raw, directory, receipts):
    """Keep all semantic comparisons. Route only the named final equal-stat comparison to the ZIP check."""
    deep = case['operation'] == 'dream-deep-runtime'
    label = _DEEP_MESSAGE if deep else _LIGHT_MESSAGE
    checked = []
    expected = raw[0]['snapshots'][-1]
    def compare(left, right, message):
        if message != label:
            return same(left, right, message)
        recorded, restored = (right, left) if deep else (left, right)
        require(not checked and recorded is expected, 'Wrong or repeated final dreaming filesystem measurement')
        checked.append(_phase_receipt(recorded, restored, directory / 'sdk-fixture'))
    # Only the copied evidence validator sees the archive-aware comparison. Its
    # code object and all original helper functions come from the sealed checkout.
    scoped = FunctionType(validator.__code__, {**validator.__globals__, 'same': compare}, validator.__name__, validator.__defaults__, validator.__closure__)
    scoped(case, public, raw, directory)
    require(len(checked) == 1, 'The sealed dreaming validator omitted its final physical observation')
    receipts[case['id']] = checked[0]


def _wrap(original_replay):
    def replay(data, cases, args, runtime):
        receipts = {}
        def archived(original_validator):
            def check(case, public, raw, directory):
                cid, directory = case['id'], Path(directory)
                packets = data['followupRows'][cid]
                record, row = packets['python'], packets['case']
                require(row['runtimeEvidenceValidated'] is True and row['status'] == 'matched' and record['validationStatus'] == 'verified'
                        and record['id'] == cid and record['side'] == 'python' and directory == Path(record['evidenceDirectory'])
                        and cid not in receipts and _same_json(row['python'], public), 'Missing original live validator or unbound archive case')
                original_wire = _owned_regular(ROOT, directory / 'python-raw.json', MAX_DIAGNOSTIC_BYTES)
                require(sha256(original_wire).hexdigest() == record['sha256'] and _same_json(raw, json.loads(original_wire)), 'Original SDK wire digest changed')
                if case['operation'] == 'dream-diary-publication-runtime':
                    receipts[cid] = _diary_receipt(raw[0], directory)
                    original_validator(case, public, raw, directory, archived_workspace=directory / 'sdk-diary')
                else:
                    _scoped_phase_check(original_validator, case, public, raw, directory, receipts)
                receipts[cid].update(producerLiveEvidenceValidated=True, sdkRawSha256=record['sha256'])
            return check
        with ExitStack() as scope:
            # These are verifier dispatch points. The original reference, SDK and returned observations are untouched.
            for module, name in ((followup_dreams, 'validate_sdk'), (dream_deep_evidence, 'validate_deep_sdk'), (followup_diary, 'validate_sdk')):
                scope.enter_context(patch.object(module, name, archived(getattr(module, name))))
            result = original_replay(data, cases, args, runtime)
        require(set(receipts) == {c['id'] for c in cases} and len(result) == len(receipts), 'Incomplete archived dreaming validation')
        for row in result:
            row['archiveSdkWorkspace'] = receipts[row['id']]
        return result
    return replay


def configure():
    """Install before calling the sealed assessor; register each external archive reviewer once."""
    for op in _PHASES:
        family, flag, validator = followup_families.FAMILIES[op]
        require(validator.__module__ in ('followup_diary', 'followup_dreams'), 'Unexpected or already wrapped dreaming reviewer')
        followup_families.FAMILIES[op] = family, flag, _wrap(validator)
