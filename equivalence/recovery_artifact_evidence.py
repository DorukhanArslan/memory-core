"""Reopen independently captured SQLite backups and SDK files at every audit and repair."""
import base64
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import zlib

from equivalence.dream_light import RECALL, SIGNALS, canonical
from equivalence.dream_light_evidence import _physical, require, same
from equivalence.recovery_artifact_sdk import ARCHIVE_NAME, public_paths
from equivalence.recovery_repair import validate_case
from equivalence.recovery_repair_fixtures import seed_entries
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import REFERENCE_COMMIT, _owners
from memory_core.consolidation._util import iso_ms, parse_ms

LOCK = "memory/.dreams/short-term-promotion.lock"
GUARD = LOCK + ".guard"
SOURCES = {'extensions/memory-core/src/short-term-promotion-artifacts.ts': ('a54a39e0f28de3556dde50ea8bb60c14b28a712dc372f622655939ce8bc560df',
                                                                  ('export async function '
                                                                   'auditShortTermPromotionArtifacts(params: {',
                                                                   'export async function '
                                                                   'repairShortTermPromotionArtifacts(params: {')),
 'extensions/memory-core/src/dreaming-repair.ts': ('205c3e037d977badb4906d8db1fa24b5f9e840c6c0b5543fd57cad515c1f7180',
                                                   ('export async function auditDreamingArtifacts(params: {',
                                                    'export async function repairDreamingArtifacts(params: {')),
 'extensions/memory-core/src/dreaming-state.ts': ('b115fa0ce1c2757abc282f2822d08dc365c07a3b88c6e90ff7b1e7b87fb64458',
                                                  ('export function configureMemoryCoreDreamingState(openKeyedStore: '
                                                   'MemoryCoreOpenKeyedStore): void {',
                                                   'export function writeMemoryCoreWorkspaceEntries<T>(')),
 'extensions/memory-core/src/short-term-promotion-store.ts': ('556c7e10323eb889e857d2cda41a5a6cd78e7e456ee99b2205b491dac547ea84',
                                                              ('export async function readShortTermStore(',))}
OWNERS = {'configureMemoryCoreDreamingState': ('dist/dreaming-state-VYUvbU-n.mjs', 'p', '7c97cd878aa65b0ee17367683050f50530df0656d54ab52e3e6f0c2d92e279cc'),
 'createPluginStateKeyedStore': ('dist/plugin-state-store-BPUaLoVD.mjs', 'r', '3c4f0e6163afd4d4f9462fe11b1c18410332764b5ea591361ed6c66034d0c203'),
 'closePluginStateDatabaseAsync': ('dist/plugin-state-store-BPUaLoVD.mjs', 'u', 'c648b6b2311377ff1d43593a21ce37b67b4d8b9bce744aae495049043b99da92'),
 'writeMemoryCoreWorkspaceEntries': ('dist/dreaming-state-VYUvbU-n.mjs', 'b', '6d372371cea0ffcefffb4f570212a4cd0bc6f7862c87afcf64909de919fd66eb'),
 'readShortTermStore': ('dist/short-term-promotion-store-B6T388Bo.mjs', 'i', '4c9ea7bd8a2d4bb40f607296fce8c0332eb6b0f255b1f578fa2c56bf39285c84'),
 'auditShortTermPromotionArtifacts': ('dist/short-term-promotion-MX1vHJuE.mjs',
                                      'n',
                                      'e161b8acf6861cfb68653547560ede292b7359979b87782ec21432f930bcd12d'),
 'repairShortTermPromotionArtifacts': ('dist/short-term-promotion-MX1vHJuE.mjs',
                                       'i',
                                       'fed4162c02f8f2f770b0d000a4049806fa7e4a85c94b2ac107a23ef4e44c9876'),
 'auditDreamingArtifacts': ('dist/dreaming-repair-IHhh4uIq.mjs', 't', '906ab30ce4672cc1e1a682d09af4c5ac7b917583fa6aeb61bdc25850ae293140'),
 'repairDreamingArtifacts': ('dist/dreaming-repair-IHhh4uIq.mjs', 'n', '8f2cca6ac39d126595bf0c99698e0252951f71d37f13b63af4faf98847eb1683')}
MODULES = {'dist/dreaming-state-VYUvbU-n.mjs': ('8676156b95cc8b73d0cc830e1305bc3460eb90f2bf1114d9e5a6b008269a3e2c',
                                      ('function configureMemoryCoreDreamingState(', 'function writeMemoryCoreWorkspaceEntries(')),
 'dist/plugin-state-store-BPUaLoVD.mjs': ('4d010227d5baea72f1dfc1e117efe2cc1eb596eeab579e6c92c047abf75f7efc',
                                          ('function createPluginStateKeyedStore(', 'function closePluginStateDatabaseAsync(')),
 'dist/short-term-promotion-store-B6T388Bo.mjs': ('704c9fa0e2a1fe7c4dc805aa23ad541562d66c47fbb853351ef74b0604c348b8',
                                                  ('function readShortTermStore(',)),
 'dist/short-term-promotion-MX1vHJuE.mjs': ('be3114e9aa8c448bdeedbd750b41b25ac06bc00ad8a728edb70db376aa3bc1da',
                                            ('function auditShortTermPromotionArtifacts(', 'function repairShortTermPromotionArtifacts(')),
 'dist/dreaming-repair-IHhh4uIq.mjs': ('36362fd7193d1f32759041c1174f2be08e10b0e19772f3d3e763b0db4661d659',
                                       ('function auditDreamingArtifacts(', 'function repairDreamingArtifacts(')),
 'dist/plugin-state-worker-client-7ByaGIDy.mjs': ('bee1c828bf9a23d3aeafd84e91d3dfd2b2d685b2d560fc5a9e01aabcd0346217',
                                                  ('function lookupPluginStateInWorker(',)),
 'dist/infra/sqlite-store.worker.js': ('b6fb8b9d214bd7d35beb77849e1c44926d4963cacd9fc13af40f8c3b43374d69',
                                       ('SQLite store worker requires its host port', 'async function receive(')),
 'dist/state/openclaw-state.worker.js': ('52fdb859d0add218690d0db4358fa5b2f2d2118379163eefb42a35c87f0715d4',
                                         ('function createSqliteWorkerBackend(',)),
 'dist/plugin-state.worker-Bt1nfP3u.mjs': ('d724a51faf2d46e518a733a47528ac9b629e54b1d4f6afa9007d769021bba9f4',
                                           ('function executePluginStateCommand(',))}


def prepare_artifact_bindings(checkout, runtime_root):
    checkout, runtime_root = Path(checkout), Path(runtime_root)
    require(_git(checkout, "rev-parse", "HEAD").decode().strip() == REFERENCE_COMMIT, "Wrong original recovery revision")
    def bindings(root, table, committed):
        return _owners(root, {k:v[0] for k,v in table.items()}, {k:v[1] for k,v in table.items()}, committed=committed)[1]
    return {"kind":"official-recovery-artifacts", "referenceCommit":REFERENCE_COMMIT,
            "sourceBindings":bindings(checkout,SOURCES,True), "compiledBindings":bindings(runtime_root,MODULES,False),
            "sourceFallbackAllowed":False, "sourceBuildReproduced":False}


def _blobs(raw):
    result, total = {}, 0
    for digest, encoded in raw["blobs"].items():
        require(len(encoded) < 8*1024**2, "Oversize compressed recovery artifact")
        dec = zlib.decompressobj(16+zlib.MAX_WBITS)
        body = dec.decompress(base64.b64decode(encoded,validate=True), 4*1024**2+1)
        total += len(body)
        require(len(body) <= 4*1024**2 and total <= 24*1024**2 and dec.eof and not dec.unused_data
                and not dec.unconsumed_tail and sha256(body).hexdigest()==digest, "Wrong recovery artifact digest")
        result[digest] = body
    return result


def _validate(case,public,snapshots,directory,native,archived):
    validate_case(case)
    raw, = snapshots
    val = case["input"]
    directory=Path(directory).resolve()
    wire = directory/("native-raw.json" if native else "python-raw.json")
    require(not wire.is_symlink() and wire.stat().st_size <=16*1024**2, "Oversize or unsafe recovery wire")
    same(json.loads(wire.read_bytes()),snapshots,"Retained recovery wire changed")
    same(val,raw["input"],"Recovery fixture changed")
    workspace = raw["workspace"] if native else raw["root"]
    path=Path(workspace)
    require(path.is_absolute() and (archived or path.is_relative_to(directory)), "Recovery fixture escaped")
    wskey=sha256(workspace.encode()).hexdigest()
    recall = "plugin-state:memory-core/short-term-recall/"+wskey if native else str(path/RECALL)
    lock = "plugin-state:memory-core/short-term-locks/"+wskey if native else str(path/LOCK)
    if native:
        require(raw["root"] == str(path.parent) and raw["env"]["OPENCLAW_STATE_DIR"] == str(path.parent/"state")
                and raw["inputSha256"] == sha256(canonical(val)).hexdigest(), "Wrong database or input")
    else:
        root=Path(__file__).resolve().parents[1]/"memory_core"
        require(set(raw["sdkFiles"])=={"consolidation/"+n+".py" for n in
                ("__init__","audit","dreaming_repair","session_repair","store","store_normalization","light_phase","concepts","recall")},
                "Missing SDK recovery owner")
        for name,digest in raw["sdkFiles"].items():
            require(sha256((root/name).read_bytes()).hexdigest()==digest,"SDK recovery owner changed")
    same(public,{"observations":raw["observations"]},"Recovery output changed")
    sequence=["audit"]+["repair","audit"]*2 if val["repair"] else ["audit"]
    same([s["operation"] for s in raw["stages"]],sequence,"Incomplete repair/retry observations")
    blobs=_blobs(raw)
    used=set()
    stages=raw["stages"]
    for index,(op,stage,obs) in enumerate(zip(sequence,stages,raw["observations"],strict=True)):
        tree=stage["tree"]
        files={}
        for name,data in tree.items():
            rel=Path(name)
            require(not rel.is_absolute() and ".." not in rel.parts and str(rel)==name,"Invalid recovery file")
            digest=data["sha256"] if native else data
            used.add(digest)
            files[name]=blobs[digest]
            if native:
                require(len(files[name])==data["size"],"Incomplete workspace bytes")
        if native:
            digest=stage["databaseSha256"]
            used.add(digest)
            image=blobs[digest]
            stores,_events=_physical({"state/state/openclaw.sqlite":image},workspace,iso_ms(val["nowMs"]))
            with TemporaryDirectory() as scratch:
                fixture_db=Path(scratch)/"captured.sqlite"
                fixture_db.write_bytes(image)
                with closing(sqlite3.connect(fixture_db.as_uri()+"?mode=ro&immutable=1",uri=True)) as db:
                    locks=db.execute("SELECT entry_key,value_json FROM plugin_state_entries WHERE plugin_id='memory-core' AND namespace='short-term-locks'").fetchall()
            require(not locks or len(locks)==1 and locks[0][0]==wskey,"Foreign or duplicate lock")
            current=json.loads(locks[0][1]) if locks else None
            same([stores["recall"],stores["phase"],current],[stage["recall"],stage["signals"],stage["lock"]],"Physical SQLite differs")
        else:
            stores={"recall":json.loads(files[RECALL]),"phase":json.loads(files[SIGNALS])}
            current=None
            if LOCK in files:
                data=json.loads(files[LOCK])
                current={"owner":data["ownerToken"],"acquiredAt":parse_ms(data["createdAt"],-1)}
            files={k:v for k,v in files.items() if k not in {RECALL,SIGNALS,LOCK,GUARD}}
        docs={ARCHIVE_NAME.sub(r"\1.$UUID",k):b.decode() for k,b in files.items()}
        require(len(docs)==len(files),"Duplicate archive aliases")
        same(obs, {"operation":op,"returned":public_paths(stage["returned"],workspace,recall,lock),
            "documents":docs,"lock":current,"recall":stores["recall"],"signals":stores["phase"]},"Unauthenticated public projection")
        if index==0:
            same(stores["recall"]["entries"],seed_entries(val),"Fixture did not really contain the damaged recall rows")
            same([stores["phase"]["entries"],current,docs],[val["signals"],val["lock"],val["files"]],"Derived state, lock or source seed changed")
        if index==len(stages)-1 and not archived:
            actual={p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob("*") if p.is_file()}
            if native:
                same({k:sha256(v).hexdigest() for k,v in actual.items()}, {k:t["sha256"] for k,t in tree.items()}, "Original final workspace changed")
            else:
                same({k:sha256(v).hexdigest() for k,v in actual.items()},tree,"SDK final workspace changed")
    same(sorted(used),sorted(blobs),"Unexpected physical evidence")
    if val["repair"]:
        output=raw["observations"]
        same(output[1]["documents"],output[3]["documents"],"Retry changed workspace bytes")
        same(output[2],output[4],"Second audit disagrees after repeated repair")
        require(output[3]["returned"]["changed"] is False,"Second repair was not idempotent")
        require("retained" in output[4]["recall"]["entries"],"Lost unrelated recall")
    return {"stages":len(stages),"wireSha256":sha256(wire.read_bytes()).hexdigest()}


def validate_native(case,public,snapshots,directory,loaded,*,archived=False):
    raw,=snapshots
    corpus=case["input"]["kind"]=="corpus"
    chosen=("auditDreamingArtifacts","repairDreamingArtifacts") if corpus else ("auditShortTermPromotionArtifacts","repairShortTermPromotionArtifacts")
    expected={k:v for k,v in OWNERS.items() if not k.startswith(("audit","repair")) or k in chosen}
    expected_modules={value[0] for value in expected.values()} | {p for p in MODULES if "worker" in p}
    for p in expected_modules:
        require(loaded.get(("node_modules/openclaw",p),{}).get("sha256")==MODULES[p][0],"Missing original recovery owner "+p)
    same(raw["owners"],[{"module":m,"alias":a,"name":k,"sourceSha256":h,"artifactSha256":MODULES[m][0]}
                        for k,(m,a,h) in expected.items()],"Wrong original export, body, or registration order")
    calls=iter(raw["calls"])
    initial=seed_entries(case["input"])
    for ns,data in (("short-term-recall",initial),("short-term-phase-signals",case["input"]["signals"]),
                    ("short-term-meta",{kind:{"updatedAt":case["input"]["updatedAt"]} for kind in ("recall","phase")})):
        receipt=next(calls)
        same(receipt["name"],"writeMemoryCoreWorkspaceEntries","Missing original seed writer")
        args,=receipt["args"]
        same([args["workspaceDir"],args["namespace"],{i["key"]:i["value"] for i in args["entries"]}],
             [raw["workspace"],ns,data],"Wrong carrier seed")
    for stage in raw["stages"]:
        audit=stage["operation"]=="audit"
        args={"workspaceDir":raw["workspace"]}
        if corpus and not audit:
            args.update(archiveDiary=case["input"]["archiveDiary"],now=iso_ms(case["input"]["nowMs"]))
        same(next(calls),{"name":chosen[0 if audit else 1],"args":[args],
                         "returned":{"kind":"value","value":stage["returned"]}},"Missing official audit or repair receipt")
        for kind in ("recall","phase"):
            receipt=next(calls)
            same(receipt,{"name":"readShortTermStore","args":[raw["workspace"],kind,iso_ms(case["input"]["nowMs"])],
                 "returned":{"kind":"value","value":stage["recall" if kind=="recall" else "signals"]}},"Missing official state readback")
    require(next(calls,None) is None,"Unexpected repair calls")
    return _validate(case,public,snapshots,directory,True,archived)


def validate_sdk(case,public,snapshots,directory,*,archived=False):
    return _validate(case,public,snapshots,directory,False,archived)
