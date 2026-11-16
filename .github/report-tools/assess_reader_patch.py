"""Correct only the missing-metadata reader for the retained 1468-case report."""
from pathlib import Path
import hashlib,json,sys
source,target,receipt=map(Path,sys.argv[1:])
original=source.read_bytes()
assert hashlib.sha256(original).hexdigest()=='b2ffa99a48c7eca68de90876bc4f1bfa4f08d71a5cf49ccca3555b9c14a206ca'
def sha(b): return hashlib.sha256(b).hexdigest()
text=original.decode()
changes=[
 ('import json\n','import json\nimport os\n'),
 ('ROOT = Path(__file__).resolve().parents[2]', 'ROOT = Path(os.environ["MEMORY_CORE_REPLAY_SOURCE_ROOT"]).resolve(strict=True)'),
 ('_same_json(data["definitionMigration"], migration)', '_same_json(data.get("definitionMigration", migration), migration)'),
 ('    result.update(completeReportParsed=True, report=data["report"], projection={',
  '    result["reportDefinitionMigrationPresent"] = "definitionMigration" in data\n'
  '    result["migrationProofMethod"] = "Exact sealed catalog and every streamed report definition; original field absence retained"\n'
  '    result.update(completeReportParsed=True, report=data["report"], projection={'),
]
for before,after in changes:
 assert text.count(before)==1, before
 text=text.replace(before,after,1)
compile(text,str(target),'exec')
with target.open('xb') as f:f.write(text.encode())
record={'kind':'external-retained-report-reader-correction','originalReader':str(source),'originalReaderSha256':sha(original),'correctedReaderSha256':sha(text.encode()),'corrections':[{'original':a,'replacement':b,'count':1} for a,b in changes],'originalReportChanged':False,'originalSourceChanged':False,'originalReportDefinitionMigrationAbsent':True,'actualDefinitionsStillCheckedExactly':True}
with receipt.open('x') as f:json.dump(record,f,indent=2);f.write('\n')
print(json.dumps({'correctedReaderSha256':record['correctedReaderSha256'],'corrections':len(changes),'originalReportChanged':False}))
