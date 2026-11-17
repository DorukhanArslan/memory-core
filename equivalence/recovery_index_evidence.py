"""Reopen whole committed stage images and verify the isolated damage and repairs."""
import base64
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zlib

from equivalence.entry_provenance_evidence import validate_entry_physical_state
from equivalence.entry_provenance_runtime import _physical
from equivalence.model_runtime_authority import validate_model_node_authority
from equivalence.recovery_index_bindings import METHODS, MODULES
from equivalence.recovery_index_fixtures import recovery_index_cases, STAGES
from equivalence.recovery_index_repair import DAMAGE_SQL, SEARCH
from memory_core.index.publication import read_published_rows


def need(ok, msg):
    if not ok:
        raise ValueError('Index repair: ' + msg)


def unpack(blob, digest):
    size = blob['size']
    need(set(blob) == {'size','gzip'} and type(size) is int and 0 < size <= 4*1024*1024 and len(blob['gzip']) <= 8*1024*1024, 'invalid snapshot size')
    compressed = base64.b64decode(blob['gzip'], validate=True)
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    data = decoder.decompress(compressed, size + 1)
    need(len(data) == size and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail and hashlib.sha256(data).hexdigest() == digest, 'SQLite snapshot digest or frame')
    return data


class ReadImage:
    def __init__(self, path):
        self.uri = path.resolve().as_uri() + '?mode=ro&immutable=1'

    def connect(self):
        return sqlite3.connect(self.uri, uri=True)


def verify_image(path, snap, native, item):
    image = ReadImage(path)
    obs, state = snap['observation'], snap['observation']['state']
    if native:
        validate_entry_physical_state({'state':state, 'physical':_physical(image)})
    with closing(image.connect()) as db:
        if not native:
            revision = db.execute('SELECT revision FROM memory_core_index_sync WHERE id=1').fetchone()[0]
            actual = read_published_rows(db, revision)
            keys = ('sources','chunks','provenance','recall','details','fts','paths')
            need(snap['indexRevision'] == revision and {k:actual[k] for k in keys} == state, 'SDK SQLite revision/published rows')
        sql = ('SELECT id,path,text FROM memory_index_chunks_fts WHERE memory_index_chunks_fts MATCH ? ORDER BY id,text' if native else SEARCH)
        rows = [{'query':q,'rows':[dict(zip(('id','path','text'),row,strict=True)) for row in db.execute(sql,(q,))]} for q in item['searches']]
        need(rows == obs['searches'] and [r[0] for r in db.execute('PRAGMA integrity_check')] == obs['integrity'] == ['ok'], 'physical FTS postings or integrity')
        need(obs['indexIdentity'] == {'status':'valid'}, 'index-format diagnostic changed')
        if native:
            status = snap['status']
            need(status['custom']['indexIdentity'] == obs['indexIdentity'] and status['files'] == len(state['sources']) and status['chunks'] == len(state['chunks']) and status['provider'] == 'none' and status['backend'] == 'builtin', 'genuine provider-none status')


def verify_transitions(obs, item):
    initial, damaged, restored, repeated = obs
    expected = deepcopy(initial['state'])
    target, = [r for r in expected['chunks'] if r['path'] == item['target']]
    need(len(expected['chunks']) == 2 and {r['path'] for r in expected['sources']} == set(item['files']), 'missing initial or unrelated data')
    if item['kind'] == 'derived-text':
        row, = [r for r in expected['fts'] if r['id'] == target['id']]
        row['text'] = item['damage']['args'][0]
    else:
        row, = [r for r in expected['provenance'] if r['chunkId'] == target['id']]
        row['supersedesKey'] = target['provenance']['supersedesKey'] = item['damage']['args'][0]
    need(expected != initial['state'] and damaged['state'] == expected, 'wrong or out-of-scope corruption')
    for step in (restored, repeated):
        need({k:v for k,v in step.items() if k!='stage'} == {k:v for k,v in initial.items() if k!='stage'}, 'real repair/retry changed sound data or left damage')


def validate(case, public, snapshots, directory, *, native, archived):
    fixture, = [c for c in recovery_index_cases() if c['id'] == case['id']]
    item = fixture['input']
    need(case['operation'] == fixture['operation'] and case['input'] == item, 'frozen fixture changed')
    raw, = snapshots
    need(raw['input'] == item and type(raw['pid']) is int and raw['pid'] > 0, 'input or producer')
    directory = Path(directory)
    name = 'native-raw.json' if native else 'python-raw.json'
    wire = directory / name
    need(wire.is_file() and not wire.is_symlink() and wire.stat().st_size < 8*1024*1024 and json.loads(wire.read_bytes()) == snapshots, 'capture differs from retained wire')
    base = Path(raw['fixtureBase'])
    prefix = 'native-index-repair-' if native else 'sdk-index-repair-'
    need(base.is_absolute() and base.name.startswith(prefix) and (archived or base.parent == directory.resolve()), 'fixture root changed')
    calls = list(raw['calls'])
    if native:
        validate_model_node_authority(raw['runtime'])
        need(raw['owners'] == METHODS and raw['config']['agents']['defaults']['workspace'] == str(base/'workspace'), 'manager owner/config')
        acquired = calls.pop(0)
        need(acquired['operation'] == 'get' and acquired['agentId'] == 'main' and acquired['purpose'] == 'cli' and acquired['status']['workspaceDir'] == str(base/'workspace'), 'manager acquisition')
        need(calls.pop() == {'operation':'close','completed':True}, 'manager close')
    else:
        need(Path(raw['implementationRoot']).is_absolute(), 'SDK location')
    raw_steps = raw['snapshots']
    observations = [s['observation'] for s in raw_steps]
    need(public == {'observations':observations} and [s['stage'] for s in observations] == list(STAGES), 'complete publication/stage order')
    need(set(raw['blobs']) == {s['sha256'] for s in raw_steps} and 1 <= len(raw['blobs']) <= 4, 'unused or omitted images')
    if not archived:
        need(not base.is_symlink() and base.is_dir(), 'physical fixture missing')
        paths = {p.relative_to(base/'workspace').as_posix():p for p in (base/'workspace').rglob('*.md')}
        need(set(paths) == set(item['files']) and all(not p.is_symlink() and p.read_bytes() == item['files'][rel].encode() and p.stat().st_mtime_ns == item['mtimeMs']*1_000_000 for rel,p in paths.items()), 'physical source notes changed')
    with tempfile.TemporaryDirectory(prefix='index-repair-replay-') as tmp:
        for stage, call, snap in zip(STAGES, calls, raw_steps, strict=True):
            if stage == 'damaged':
                common = {'operation':'inject','stage':stage,'sql':item['damage']['sql'] if native else DAMAGE_SQL[item['kind']], 'args':item['damage']['args']}
                if native:
                    need(set(call['result']) == {'changes','lastInsertRowid'} and type(call['result']['lastInsertRowid']) is int and call['result']['changes'] == 1, 'original SQL mutation receipt')
                    common['result'] = call['result']
                else:
                    common['rowcount'] = 1
                need(call == common, 'wrong damage statement or count')
            elif native:
                need(call == {'operation':'sync','stage':stage,'markedDirty':True,'request':{'reason':'repair-diagnostics-fixture','force':True},'returnedUndefined':True}, 'original forced sync receipt')
            else:
                need(call == {'operation':'reindex','stage':stage,'force':True,'result':len(item['files'])}, 'real SDK repair result')
            expected_db = base/('state/agents/main/agent/openclaw-agent.sqlite' if native else 'main.sqlite')
            main, = [row for row in snap['databaseList'] if row['name'] == 'main']
            need(main == {'seq':0,'name':'main','file':str(expected_db)} and (not native or snap['status']['dbPath'] == str(expected_db)), 'wrong source database')
            obs = snap['observation']
            need(set(obs) == {'stage','documents','state','searches','integrity','indexIdentity'} and obs['documents'] == item['files'], 'document/capture data')
            data = unpack(raw['blobs'][snap['sha256']], snap['sha256'])
            if not archived:
                live = base/(stage+'.sqlite')
                need(live.is_file() and not live.is_symlink() and live.stat().st_size == len(data) and live.read_bytes() == data, 'stage image altered on disk')
            image = Path(tmp)/(stage+'.sqlite')
            image.write_bytes(data)
            verify_image(image,snap,native,item)
    verify_transitions(observations,item)
    return {'stages':len(raw_steps),'sqliteImages':len(raw_steps),'imageBytes':sum(raw['blobs'][s['sha256']]['size'] for s in raw_steps),'captureSha256':hashlib.sha256(wire.read_bytes()).hexdigest()}


def validate_native(case,public,snapshots,evidence_directory,loaded,*,archived=False):
    for path,(digest,_) in MODULES.items():
        authority = loaded.get(('node_modules/openclaw',path))
        need(isinstance(authority,dict) and authority['sha256']==digest, 'original loaded owner '+path)
    return validate(case,public,snapshots,evidence_directory,native=True,archived=archived)


def validate_sdk(case,public,snapshots,directory,*,archived=False):
    return validate(case,public,snapshots,directory,native=False,archived=archived)
