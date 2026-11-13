"""Pure caller-protocol regression from the retained genuine first baseline.

Only the original V8 request/reply bytes and passive matcher execute. No manager,
worker, host, publication, retry algorithm or acceptance credit is exercised.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]
# Byte-for-byte V8 fields copied from the immutable genuine capture identified
# below. publicationAtReply is its original entry, before actual settlement955.
RETAINED = {'source': {'path': 'work/query-sync-acceptance-boundaries/baseline-001/query-sync-boundaries-typed-conflict-twice-exhaustion/evidence/native-raw.json', 'bytes': 2192783, 'sha256': '12be6feb784676fc89beef45cf61cd62f2ce6cf11ec777f39f85175b9f5edb99', 'requestEnterSeq': 949, 'replySeq': 951, 'publicationSettledSeq': 955}, 'round': {'actualOwnerId': 'ref-1735', 'runSyncCallId': 'method-26', 'expectedRevision': 10}, 'workerId': 'worker-5', 'requestId': 178, 'requestEnterSeq': 949, 'replySeq': 951, 'requestInputHex': 'ff0f6f220474797065221764617461626173652e646f6d61696e2e657865637574652205696e7075746f22026964222430383664666232352d636236632d343436362d386434662d3938666530656435343263622207636f6d6d616e646f220474797065221064617461626173652e7075626c6973682205696e7075746f220a736f757263655061746822e1012f776f726b73706163652f6d656d6f72792d636f72652f776f726b2f71756572792d73796e632d616363657074616e63652d626f756e6461726965732f626173656c696e652d3030312f71756572792d73796e632d626f756e6461726965732d74797065642d636f6e666c6963742d74776963652d65786861757374696f6e2f73746174652f6167656e74732f6d61696e2f6167656e742f6f70656e636c61772d6167656e742e73716c6974652e6d656d6f72792d7265696e6465782d64326432653261612d633038632d343239332d383466312d616132616236643834323763220e736f757263654964656e746974796f2206646576696365220232372205696e6f64652207313937323532337b0222076d6574614b657922146d656d6f72795f696e6465785f6d6574615f7631221065787065637465645265766973696f6e49142210736f75726365486173566563746f7273462213766563746f72496e646578436f6d706c65746554220d657874656e73696f6e506174685f220573746174656f2206766563746f726f2207656e61626c6564462209617661696c61626c65307b0222036674736f2207656e61626c6564542209617661696c61626c65547b02220d657874656e73696f6e506174685f7b037b087b027b027b02', 'replyValueHex': 'ff0f6f22026f6b4622056572726f726f22046e616d6522204d656d6f7279496e6465785265766973696f6e436f6e666c6963744572726f7222076d657373616765226e4d656d6f727920696e646578206368616e676564207768696c652066756c6c207265696e64657820776173206275696c64696e6720286578706563746564207265766973696f6e2031302c20666f756e64203132293b207265747279207468652066756c6c207265696e6465782e7b022207656e7465726564542209636f6d6d6974746564467b04', 'publicationAtReply': {'id': 'publication-5', 'method': 'publishShadow', 'ownerId': 'ref-1735', 'databaseRef': 'ref-2429', 'args': [{'sourcePath': '/workspace/memory-core/work/query-sync-acceptance-boundaries/baseline-001/query-sync-boundaries-typed-conflict-twice-exhaustion/state/agents/main/agent/openclaw-agent.sqlite.memory-reindex-d2d2e2aa-c08c-4293-84f1-aa2ab6d8427c', 'sourceIdentity': {'device': '27', 'inode': '1972523'}, 'metaKey': 'memory_index_meta_v1', 'expectedRevision': 10, 'sourceHasVectors': False, 'vectorIndexComplete': True, 'extensionPath': {'privateType': 'undefined'}}, {'privateType': 'nativeCallback', 'name': '', 'ref': 'ref-2433'}], 'operationContext': {'kind': 'search', 'label': 'naturalRetry', 'runSyncCallId': 'method-26', 'runSyncOwnerId': 'ref-1735'}, 'enterSeq': 945, 'wholeJobId': 'whole-job-4', 'returnedPromiseRef': 'ref-2434'}}

SCRIPT = "\nimport fs from 'node:fs';\nimport {deserialize} from 'node:v8';\nconst{matchOriginalTypedPublicationReply:match}=await import(process.argv[1]);\nconst fixture=JSON.parse(fs.readFileSync(0,'utf8'));\nconst domain=deserialize(Buffer.from(fixture.requestInputHex,'hex'));\nconst returned=deserialize(Buffer.from(fixture.replyValueHex,'hex'));\nconst request={workerId:fixture.workerId,enterSeq:fixture.requestEnterSeq,\n message:{id:fixture.requestId},decodedSerialized:{input:{value:domain}}};\nconst message={id:fixture.requestId,ok:true};\nconst receipt={workerId:fixture.workerId,sequence:fixture.replySeq,\n decodedSerialized:{value:{value:returned}}};\nconst publication=fixture.publicationAtReply;\nconst round=fixture.round;\nswitch(fixture.attack){\n case 'other-domain':domain.type='database.domain.bind';break;\n case 'unwrapped-command':request.decodedSerialized.input.value=domain.input.command;break;\n case 'other-command':domain.input.command.type='source.delete';break;\n case 'other-source':domain.input.command.input.sourcePath+='-foreign';break;\n case 'other-revision':domain.input.command.input.expectedRevision+=1;break;\n case 'other-owner':publication.ownerId='foreign-owner';break;\n case 'other-run-sync':publication.operationContext.runSyncCallId='foreign-run';break;\n case 'settled-publication':publication.returnSeq=fixture.replySeq-1;break;\n case 'future-publication':publication.enterSeq=fixture.requestEnterSeq+1;break;\n case 'other-worker':request.workerId='foreign-worker';break;\n case 'other-request':request.message.id+=1;break;\n case 'other-error':returned.error.name='SourceChangedError';break;\n case 'successful-publication':returned.ok=true;break;\n case 'outer-error':message.ok=false;break;\n}\nconst matched=match(round,receipt,message,[request],[publication]);\nprocess.stdout.write(JSON.stringify(matched?{matched:true,\n sameRequest:matched.request===request,samePublication:matched.publication===publication,\n domainId:matched.domainId,sourcePath:matched.command.input.sourcePath,\n expectedRevision:matched.command.input.expectedRevision}:{matched:false}));\n"

@pytest.fixture(scope="module")
def node():
    configured = os.environ.get("MEMORY_EQ_NODE")
    if not configured:
        pytest.skip("Pure protocol unit requires an explicitly approved Node; no acceptance credit")
    executable = Path(configured).resolve(strict=True)
    prepare_model_node_authority(executable)
    return executable


def invoke(node, attack=None):
    fixture = deepcopy(RETAINED)
    fixture["attack"] = attack
    actor = (ROOT / "equivalence/query-sync-boundaries-runtime.mjs").as_uri()
    process = subprocess.run([str(node), "--input-type=module", "--eval", SCRIPT, actor],
        input=json.dumps(fixture), text=True, capture_output=True, check=True, timeout=15,
        env={"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"})
    return json.loads(process.stdout)


def test_genuine_domain_envelope_selects_same_pending_original_publication(node):
    result = invoke(node)
    assert result == {"matched": True, "sameRequest": True, "samePublication": True,
        "domainId": "086dfb25-cb6c-4466-8d4f-98fe0ed542cb",
        "sourcePath": RETAINED["publicationAtReply"]["args"][0]["sourcePath"],
        "expectedRevision": 10}
    assert RETAINED["source"]["requestEnterSeq"] == 949
    assert RETAINED["source"]["replySeq"] == 951
    assert RETAINED["source"]["publicationSettledSeq"] == 955


@pytest.mark.parametrize("attack", ["other-domain", "unwrapped-command", "other-command", "other-source",
    "other-revision", "other-owner", "other-run-sync", "settled-publication", "future-publication",
    "other-worker", "other-request", "other-error", "successful-publication", "outer-error"])
def test_protocol_matcher_rejects_borrowed_domain_publication_or_reply(node, attack):
    assert invoke(node, attack) == {"matched": False}
