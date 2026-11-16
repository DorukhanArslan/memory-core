"""Read one bounded part of the existing reviewed summary; no engine execution."""
import base64,hashlib,json,os,urllib.request,urllib.error
from urllib.parse import urlsplit
artifact=os.environ['ARTIFACT_ID']; assert artifact.isdigit()
expected=os.environ['ARTIFACT_SHA'].split(':')[-1]
api='https://api.github.com/repos/DorukhanArslan/memory-core/actions/artifacts/'+artifact
headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
metadata=json.load(urllib.request.urlopen(urllib.request.Request(api,headers=headers),timeout=30))
assert metadata['workflow_run']['id']==int(os.environ['GITHUB_RUN_ID'])
assert metadata['workflow_run']['head_sha']==os.environ['GITHUB_SHA']
assert metadata['digest'].split(':')[-1]==expected
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl): return None
try: response=urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(api+'/zip',headers=headers),timeout=30)
except urllib.error.HTTPError as error:
 assert error.code==302
 target=error.headers['Location']; assert urlsplit(target).scheme=='https'
 response=urllib.request.urlopen(target,timeout=30)
with response: archive=response.read(640001)
assert len(archive)==metadata['size_in_bytes'] and len(archive)<=640000
assert hashlib.sha256(archive).hexdigest()==expected
part=int(os.environ['REPORT_PART']); assert 0<=part<8
width=(len(archive)+7)//8; payload=archive[part*width:(part+1)*width]
encoded=base64.b64encode(payload).decode('ascii')
print(f'REPORT_ZIP_BEGIN:{artifact}:{part}:{len(payload)}')
for ordinal,offset in enumerate(range(0,len(encoded),8192)):
 print(f'REPORT_ZIP_CHUNK:{part}:{ordinal}:'+encoded[offset:offset+8192])
print(f'REPORT_ZIP_END:{artifact}:{part}')
