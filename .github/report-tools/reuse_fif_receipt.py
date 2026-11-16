"""Reuse an already authenticated receipt tied to exactly the same report."""
import hashlib,io,json,os,urllib.request,urllib.error,zipfile
from pathlib import Path
from urllib.parse import urlsplit
api='https://api.github.com/repos/DorukhanArslan/memory-core/actions/artifacts/14191067037/zip'
headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return None
try:response=urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(api,headers=headers),timeout=30)
except urllib.error.HTTPError as error:
 assert error.code==302
 url=error.headers['Location'];assert urlsplit(url).scheme=='https';response=urllib.request.urlopen(url,timeout=30)
with response:archive=response.read(584438)
assert len(archive)==584437 and hashlib.sha256(archive).hexdigest()=='805218a1fce43bcca29ff34f10ef453966a0af51cc6d987f2d1fcd901d5d6301'
with zipfile.ZipFile(io.BytesIO(archive)) as z:payload=z.read('forget-family-replay.json')
sha=hashlib.sha256(payload).hexdigest();assert sha=='4a3271a22339f809f3712b16b7661f681535dbbbb7245b74177c6e66b9b5f735'
f=json.loads(payload)
assert f['finalAuthenticationPassed'] is True and f['validCompleteBaseline'] is True and f['candidateFamilyMatched'] is True and f['errors']==[]
assert len(f['cases'])==13 and f['sourceReports'][0]['report']['sha256']=='63a36bff1fcc78c14c56068dfc0dd3ddf39ada113fb591488ab3e3706348a799'
assert f['authority']['sdk']['sourceSha256']=='a90d994bcf005a26a4e15bf40b2e9b95f47a7a8c31cd864ed2131021d9046990'
out=Path('.equivalence-results/reviewed-summary')
with (out/'forget-family-replay.json').open('xb') as p:p.write(payload)
record={'kind':'reuse-exact-authenticated-fif-receipt','sourceReviewRun':43786515249,'sourceSummaryArtifact':14191067037,'sourceSummarySha256':'805218a1fce43bcca29ff34f10ef453966a0af51cc6d987f2d1fcd901d5d6301','receiptSha256':sha,'originalReportSha256':f['sourceReports'][0]['report']['sha256'],'businessComparisonsRerun':False,'fifReplayRepeated':False}
(out/'fif-receipt-reuse.json').write_text(json.dumps(record)+'\n');print(json.dumps(record))
