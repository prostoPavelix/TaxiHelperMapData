"""Manual GEO4 first-install pipeline. No compiler changes, APKs, schedules or latest alias.
Only `publish` can mutate GEO4 releases/channel; it requires the protected Environment.
"""
import argparse,base64,hashlib,http.client,json,os,re,shutil,sqlite3,subprocess,sys,time,urllib.request,urllib.error,zlib
from pathlib import Path

HERE=Path(__file__).resolve().parent
SOURCE=HERE/'source'
TOOLS=SOURCE/'taxihelper2_workspace/tools/geo4_build'
sys.path.insert(0,str(TOOLS))
from transport import canonical,digest,validate,reconstruct,sign,DOMAIN,BLOCK,component
REPO='prostoPavelix/TaxiHelperMapData'
CHANNEL='geo4-channel';CHANNEL_FILE='geo4/channels/stable.json'
CHANNEL_DOMAIN=b'TaxiHelper-GEO4-CHANNEL-1\0'
RESERVE=2*1024**3

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,j):Path(p).write_bytes(canonical(j))
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def guard(root,additional=0,minimum=0):
 free=shutil.disk_usage(root).free
 if free<max(minimum,additional+RESERVE):raise ValueError('DISK_ADMISSION')
 return free
def phase(root,name):
 root.mkdir(parents=True,exist_ok=True);save(root/'phase.json',{'phase':name,'time':time.time()})
def fetch(url,target,size,expected):
 if target.exists():raise ValueError('NEW_DOWNLOAD_REQUIRED')
 if not url.startswith('https://'):raise ValueError('HTTPS_REQUIRED')
 h=hashlib.sha256();n=0
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'TaxiHelper-GEO4'}),timeout=120) as r,target.open('xb') as f:
  for b in iter(lambda:r.read(1<<20),b''):
   n+=len(b)
   if n>size:raise ValueError('DOWNLOAD_BOUND')
   h.update(b);f.write(b)
 if n!=size or h.hexdigest()!=expected:raise ValueError('DOWNLOAD_IDENTITY')
def readback(url,size,expected):
 h=hashlib.sha256();n=0
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'TaxiHelper-GEO4-public-readback'}),timeout=120) as r:
  for b in iter(lambda:r.read(1<<20),b''):
   n+=len(b)
   if n>size:raise ValueError('PUBLIC_READBACK_BOUND')
   h.update(b)
 if n!=size or h.hexdigest()!=expected:raise ValueError('PUBLIC_PAYLOAD_READBACK')
 return {'bytes':n,'sha256':h.hexdigest()}

def api(path,method='GET',obj=None,token=None):
 headers={'Accept':'application/vnd.github+json','User-Agent':'TaxiHelper-GEO4','X-GitHub-Api-Version':'2022-11-28'}
 if token:headers['Authorization']='Bearer '+token
 data=canonical(obj) if obj is not None else None
 if data:headers['Content-Type']='application/json'
 req=urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path,headers=headers,data=data,method=method)
 try:
  with urllib.request.urlopen(req,timeout=60) as r:
   b=r.read(8*1024*1024+1)
   if len(b)>8*1024*1024:raise ValueError('API_BOUND')
   return json.loads(b) if b else None
 except urllib.error.HTTPError as e:
  if e.code==404 and method=='GET':return None
  raise RuntimeError('GITHUB_API_HTTP_'+str(e.code)) from None

def config(name):
 if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,80}\.json',name):raise ValueError('CONFIG_NAME')
 j=read(HERE/'config'/name)
 if j['contract']!='GEO4_STAGE5_INPUT_1' or j['route']!='FIRST_INSTALL_FULL':raise ValueError('CONFIG_CONTRACT')
 o=j['osm']
 if not re.fullmatch(r'\d{6}',o['date']) or o['url']!='https://download.geofabrik.de/europe/ukraine-'+o['date']+'.osm.pbf':raise ValueError('DATED_OSM_REQUIRED')
 for s in [o,*j['capsules']]:
  if not re.fullmatch('[a-f0-9]{64}',s['sha256']) or not 0<s['bytes']<2*1024**3:raise ValueError('INPUT_PIN')
 return j
def source_check():
 lock=read(HERE/'SOURCE_LOCK.json')
 if lock['source_ref']!='a49142154f1166f8d7af014c646acbc3e2fc0182':raise ValueError('COMPILER_REF')
 for s in lock['files']:
  p=SOURCE/s['path']
  if p.stat().st_size!=s['bytes'] or sha(p)!=s['sha256']:raise ValueError('COMPILER_SOURCE_DRIFT')
 return lock

def prepare(root,cfg):
 phase(root,'FETCH_AND_PRECHECK');source_check()
 expected=os.environ.get('GEO4_EXPECTED_CHANNEL','ABSENT')
 current=api('git/ref/heads/'+CHANNEL)
 if (current['object']['sha'] if current else 'ABSENT')!=expected:raise ValueError('EXPECTED_CHANNEL_CHANGED_BEFORE_BUILD')
 if expected!='ABSENT':raise ValueError('FIRST_INSTALL_ONLY_NO_SILENT_SUCCESSOR')
 if api('releases/tags/offline-map-latest')['id']!=cfg['legacy_release_id']:raise ValueError('LEGACY_RELEASE_CHANGED_STOP')
 for s in cfg['capsules']:fetch(s['url'],root/s['name'],s['bytes'],s['sha256'])
 save(root/'PRECHECK.json',{'status':'PASS','config_sha256':digest(canonical(cfg)),'compiler_ref':source_check()['source_ref'],'legacy_release_id':cfg['legacy_release_id'],'expected_channel':expected,'capsule_hashes':[s['sha256'] for s in cfg['capsules']]})

def command(name,*args):subprocess.run([sys.executable,str(TOOLS/name),*map(str,args)],check=True)
def build(root,cfg):
 phase(root,'BUILD_ADMISSION');guard(root,minimum=14*1024**3)
 if read(root/'PRECHECK.json')['status']!='PASS':raise ValueError('PRECHECK_REQUIRED')
 from unpack_input import unpack
 from portable_supplement import unpack as supplement
 unpack(root/cfg['capsules'][0]['name'],cfg['capsules'][0]['sha256'],root/'inputs')
 supplement(root/cfg['capsules'][1]['name'],cfg['capsules'][1]['sha256'],root/'supplement')
 phase(root,'DATED_OSM_FETCH')
 o=cfg['osm'];fetch(o['url'],root/'dated.osm.pbf',o['bytes'],o['sha256'])
 command('prepare.py','--source',root/'dated.osm.pbf','--additional',root/'inputs/additional','--dependencies',root/'inputs/dependencies','--supplement',root/'supplement','--output',root/'candidate')
 for step in ['extract','build','supplement','verify','sidecar']:
  phase(root,'COMPILER_'+step.upper());guard(root);command('compiler.py','--config',root/'candidate/CONFIG.json','--phase',step)
 phase(root,'PACK_ADMISSION')
 c=root/'candidate';bundle=root/'bundle';bundle.mkdir()
 raw=sum(p.stat().st_size for p in [c/'mobile.sqlite',c/'resolve1/evidence.sqlite'])
 # Worst-case zlib payload + largest reconstruction + artifact archive scratch, plus2GiB.
 guard(root,additional=2*(raw+raw//1000+65536)+(c/'mobile.sqlite').stat().st_size)
 manifest=package(c,bundle,1)
 phase(root,'EXACT_FULL_RECONSTRUCTION')
 restored=[]
 for s in manifest['components']:
  guard(root,additional=s['raw_bytes']);p=root/('reconstructed-'+s['role']+'.sqlite')
  result=reconstruct(s,root/'NO_PUBLISHED_PREDECESSOR',bundle,p,'full')
  # Sidecar's independently compiled exact binding checked before deleting each target.
  if s['role']=='resolver':
   with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:
    meta=dict(db.execute('SELECT key,value FROM meta'))
   base=next(x for x in manifest['components'] if x['role']=='base')
   if meta['geo_sha256']!=base['raw_sha256'] or meta['geo_version']!=base['version']:raise ValueError('RECONSTRUCTED_SIDECAR_BINDING')
  restored.append(result);p.unlink()
 save(bundle/'BUILD_RECEIPT.json',{'status':'PASS','compiler_ref':source_check()['source_ref'],'source_lock_sha256':sha(HERE/'SOURCE_LOCK.json'),'logical_identity':manifest['logical_identity'],'target_hashes':{x['role']:x['raw_sha256'] for x in manifest['components']},'routes':{'base':'full','resolver':'full'},'exact_reconstruction':restored,'no_published_predecessor':True,'config_sha256':digest(canonical(cfg))})
 shutil.copyfile(HERE/'INPUT_NOTICE.txt',bundle/'NOTICE.txt')
 phase(root,'VERIFIED_BUNDLE_READY')

def full_component(path,role,out,version=''):
 raw=hashlib.sha256();enc=hashlib.sha256();total=encoded=0;chunks=[];z=zlib.compressobj(6);target=out/(role+'.full.z')
 with path.open('rb') as src,target.open('xb') as dst:
  for b in iter(lambda:src.read(BLOCK),b''):
   chunks.append({'target_offset':total,'bytes':len(b),'sha256':digest(b),'source':'base','base_offset':total})
   raw.update(b);total+=len(b);data=z.compress(b);dst.write(data);enc.update(data);encoded+=len(data)
  data=z.flush();dst.write(data);enc.update(data);encoded+=len(data)
 h=raw.hexdigest()
 # Self-identity means skip only for an already exact installed target; all other clients use
 # mandatory full. No fictional predecessor, packs, or advertised compact route is produced.
 return {'role':role,'version':version,'raw_bytes':total,'raw_sha256':h,'base_bytes':total,'base_sha256':h,'packs':[],'chunks':chunks,'full':{'name':target.name,'bytes':encoded,'sha256':enc.hexdigest(),'codec':'zlib'}}

def package(c,out,sequence,previous=None):
 for n in ['VERIFICATION.json','INGESTION.json','ADDRESS_COVERAGE.json','NAME_FIELD_AUDIT.json']:
  if read(c/n)['status']!='PASS':raise ValueError('SOURCE_PROOF_FAILED')
 if read(c/'CLOSURE_PRIVATE.json')['reference_missing_count']!=0:raise ValueError('SOURCE_CLOSURE')
 mb=read(c/'MOBILE_COMPLETE.json');side=read(c/'resolve1/descriptor.json')
 if side['geo_sha256']!=mb['sha256'] or side['geo_version']!=mb['revision']:raise ValueError('SIDECAR_CLOSURE')
 cfg=read(c/'CONFIG.json');pins={p['role']:p for p in cfg['pins']}
 compiler={k:v['sha256'] for k,v in pins.items() if k.startswith('compiler:') or k=='contract:compile_evidence.py'}
 compiler.update({'compiler_dependency:'+p.name:sha(p) for p in [SOURCE/'taxihelper2_workspace/tools/locality_probe/analyze.py',SOURCE/'taxihelper2_workspace/tools/addr2/core.py',SOURCE/'taxihelper2_workspace/app/src/main/java/com/example/bolthelper/sep1/S1SectorUniverse.kt']})
 identity={'source_sha256':pins['dated_osm']['sha256'],'additional_sha256':pins['additional_manifest']['sha256'],'aoi_sha256':pins['aoi']['sha256'],'sector_sha256':side['sector_sha256'],'compiler_sha256':digest(canonical(compiler)),'toolchain_sha256':digest(canonical(cfg['toolchain']))}
 components=[full_component(c/'mobile.sqlite','base',out,mb['revision']),full_component(c/'resolve1/evidence.sqlite','resolver',out)] if previous is None else [
  component(previous/'mobile.sqlite',c/'mobile.sqlite','base',out,mb['revision'])[0],component(previous/'resolve1/evidence.sqlite',c/'resolve1/evidence.sqlite','resolver',out)[0]]
 if components[0]['raw_sha256']!=mb['sha256'] or components[1]['raw_sha256']!=side['sha256']:raise ValueError('COMPLETED_INPUT_CHANGED')
 proof={'contract':'GEO4_SOURCE_TO_PHONE_PROOF_1','status':'PASS','logical_identity':digest(canonical(identity)),'base_sha256':mb['sha256'],'base_version':mb['revision'],'resolver_sha256':side['sha256'],'raw_to_master':read(c/'INGESTION.json'),'master_to_mobile':read(c/'VERIFICATION.json'),'postal_units':read(c/'ADDRESS_COVERAGE.json'),'name_fields':read(c/'NAME_FIELD_AUDIT.json'),'source_epoch':read(c/'EXTRACTION.json')['header']}
 save(out/'completeness.json',proof)
 m={'contract':'GEO4_RELEASE_1','sequence':sequence,'logical_identity':proof['logical_identity'],'identity':identity,'capabilities':{'schema':'GEO2_MASTER_1','reader':'GEO3_DISK_1','normalizer':'GEO2_NFKC_CASEFOLD_ALNUM_V1','evidence':'RESOLVE1_COMPLETE_GEOMETRY_SOURCE_ALIAS_1','adapter':'RESOLVE1_GEOMETRY_SOURCE_ALIAS_4','transport':'GEO4_PACKED_ZLIB_1'},'components':components,'proof':{'name':'completeness.json','bytes':(out/'completeness.json').stat().st_size,'sha256':sha(out/'completeness.json')}}
 validate(m)
 if (out/'completeness.json').stat().st_size>1024**2 or len(canonical(m))>5*1024**2:raise ValueError('ANDROID_PROOF_OR_ENVELOPE_BOUND')
 save(out/'manifest.unsigned.json',m);return m

def verify_bundle(bundle):
 m=read(bundle/'manifest.unsigned.json');validate(m);proof=read(bundle/'completeness.json');receipt=read(bundle/'BUILD_RECEIPT.json')
 if proof['status']!='PASS' or receipt['status']!='PASS' or receipt['logical_identity']!=m['logical_identity'] or receipt['compiler_ref']!=source_check()['source_ref'] or receipt['source_lock_sha256']!=sha(HERE/'SOURCE_LOCK.json'):raise ValueError('BUILD_RECEIPT_BINDING')
 for name in ['raw_to_master','master_to_mobile','postal_units','name_fields']:
  if proof[name]['status']!='PASS' or proof[name].get('errors') or proof[name].get('unexplained_omissions',0)!=0:raise ValueError('COMPLETENESS_NOT_PASS')
 b=next(c for c in m['components'] if c['role']=='base');s=next(c for c in m['components'] if c['role']=='resolver')
 if receipt.get('target_hashes')!={x['role']:x['raw_sha256'] for x in m['components']} or receipt.get('routes')!={'base':'full','resolver':'full'}:raise ValueError('RECONSTRUCTION_RECEIPT_BINDING')
 restored=receipt.get('exact_reconstruction',[])
 if len(restored)!=2 or any(r.get('mode')!='full' or r.get('sha256')!=c['raw_sha256'] or r.get('raw_bytes')!=c['raw_bytes'] for r,c in zip(restored,m['components'])):raise ValueError('EXACT_RECONSTRUCTION_NOT_PROVEN')
 if proof['base_sha256']!=b['raw_sha256'] or proof['base_version']!=b['version'] or proof['resolver_sha256']!=s['raw_sha256'] or proof['logical_identity']!=m['logical_identity']:raise ValueError('PROOF_CLOSURE')
 for f in [m['proof'],*[x['full'] for x in m['components']]]:
  p=bundle/f['name']
  if p.stat().st_size!=f['bytes'] or sha(p)!=f['sha256']:raise ValueError('BUNDLE_ASSET')
 for c in m['components']:
  if c['packs'] or c['base_sha256']!=c['raw_sha256']:raise ValueError('FIRST_INSTALL_FULL_ONLY')
 return m

def publication_plan(m,existing):
 if existing is None:return 'CREATE'
 if canonical(m)!=canonical(existing):raise ValueError('IMMUTABLE_RELEASE_EQUIVOCATION')
 return 'REUSE'
def gate_channel(expected,current,readback_ok):
 if not readback_ok:raise ValueError('CHANNEL_BEFORE_READBACK')
 if expected!=current:raise ValueError('CHANNEL_CAS_CONFLICT')
def verify_signature(envelope,public,domain=DOMAIN):
 from nacl.signing import VerifyKey
 if len(envelope)>8*1024**2:raise ValueError('ENVELOPE_BOUND')
 e=json.loads(envelope)
 if e['contract']!='GEO4_SIGNED_ENVELOPE_1' or e['key_id']!=public['key_id']:raise ValueError('TRUST_KEY')
 body=base64.b64decode(e['payload_b64'],validate=True);sig=base64.b64decode(e['signature_b64'],validate=True)
 if len(body)>5*1024**2 or len(sig)!=64:raise ValueError('SIGNATURE_BOUND')
 VerifyKey(base64.b64decode(public['public_key_raw_base64'])).verify(domain+body,sig)
 obj=json.loads(body)
 if canonical(obj)!=body:raise ValueError('NON_CANONICAL')
 return obj

def upload(release,path,token):
 # No redirects or secret URLs; raw bytes are streamed, never shell-expanded.
 conn=http.client.HTTPSConnection('uploads.github.com',timeout=120)
 try:
  conn.putrequest('POST','/repos/'+REPO+'/releases/'+str(release['id'])+'/assets?name='+path.name)
  for k,v in {'Authorization':'Bearer '+token,'User-Agent':'TaxiHelper-GEO4','Content-Type':'application/octet-stream','Content-Length':str(path.stat().st_size)}.items():conn.putheader(k,v)
  conn.endheaders()
  with path.open('rb') as f:
   for data in iter(lambda:f.read(1<<20),b''):conn.send(data)
  response=conn.getresponse();body=response.read(2*1024*1024)
  if response.status!=201:raise RuntimeError('ASSET_UPLOAD_HTTP_'+str(response.status))
  j=json.loads(body)
  if j['size']!=path.stat().st_size or j.get('digest')!='sha256:'+sha(path):raise ValueError('UPLOAD_METADATA_MISMATCH')
  return j
 finally:conn.close()

def publish(root,cfg,bundle_verifier=verify_bundle,with_summary=False):
 phase(root,'PUBLICATION_VERIFY_BUNDLE');guard(root);bundle=root/'bundle';m=bundle_verifier(bundle)
 if m['identity']['source_sha256']!=cfg['osm']['sha256'] or read(bundle/'BUILD_RECEIPT.json').get('config_sha256')!=digest(canonical(cfg)):raise ValueError('CONFIG_SOURCE_BINDING')
 expected=os.environ.get('GEO4_EXPECTED_CHANNEL','ABSENT');token=os.environ['GITHUB_TOKEN']
 prior=api('git/ref/heads/'+CHANNEL,token=token);prior_id=prior['object']['sha'] if prior else 'ABSENT'
 gate_channel(expected,prior_id,True)
 from cryptography.hazmat.primitives.serialization import load_pem_private_key,Encoding,PublicFormat
 public=read(HERE/'PUBLIC_KEY.json');key=load_pem_private_key(os.environ['GEO4_SIGNING_KEY_PEM'].encode(),password=None)
 if digest(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))!=public['fingerprint_sha256'] or public['key_id']!=os.environ['GEO4_SIGNING_KEY_ID']:raise ValueError('PRODUCTION_KEY_MISMATCH')
 envelope=sign(m,key,public['key_id']);assert verify_signature(envelope,public)==m
 save(bundle/'manifest.signed.json',json.loads(envelope))
 tag='geo4-r'+str(m['sequence'])+'-'+m['logical_identity'][:24]
 release=api('releases/tags/'+tag,token=token)
 if release and release['tag_name']!=tag:raise ValueError('RELEASE_NAMESPACE')
 if release and not release['draft']:
  with urllib.request.urlopen('https://github.com/'+REPO+'/releases/download/'+tag+'/manifest.signed.json',timeout=60) as r:existing_manifest=verify_signature(r.read(8*1024*1024+1),public)
  publication_plan(m,existing_manifest)
 files=[bundle/'manifest.signed.json',bundle/m['proof']['name'],*[bundle/a['name'] for c in m['components'] for a in [c['full'],*c['packs']]],bundle/'NOTICE.txt',bundle/'BUILD_RECEIPT.json']
 if with_summary:files += [bundle/'SEMANTIC.json']
 if not release:release=api('releases','POST',{'tag_name':tag,'target_commitish':os.environ['GITHUB_SHA'],'name':tag,'draft':True,'prerelease':False,'make_latest':'false','body':'GEO4 first-install full closure. No legacy/latest update. Public readback gates signed channel.'},token)
 existing={a['name']:a for a in release['assets']}
 if set(existing)-{p.name for p in files}:raise ValueError('UNEXPECTED_IMMUTABLE_ASSET')
 for p in files:
  if p.name in existing:
   a=existing[p.name]
   if a['size']!=p.stat().st_size or a.get('digest')!='sha256:'+sha(p):raise ValueError('IMMUTABLE_ASSET_MISMATCH_NO_CLOBBER')
  else:
   if not release['draft']:raise ValueError('PUBLISHED_RELEASE_INCOMPLETE_STOP')
   upload(release,p,token)
 if release['draft']:release=api('releases/'+str(release['id']),'PATCH',{'draft':False,'make_latest':'false'},token)
 phase(root,'UNAUTHENTICATED_PUBLIC_READBACK');proof=[]
 for p in files:
  url='https://github.com/'+REPO+'/releases/download/'+tag+'/'+p.name
  proof.append({'name':p.name,**readback(url,p.stat().st_size,sha(p))})
 # Public bytes, not upload response, are independently signature-verified.
 url='https://github.com/'+REPO+'/releases/download/'+tag+'/manifest.signed.json'
 with urllib.request.urlopen(url,timeout=60) as r:actual=r.read(8*1024*1024+1)
 if canonical(verify_signature(actual,public))!=canonical(m):raise ValueError('PUBLIC_SIGNATURE')
 guard(root)
 resources=root/'RESOURCE_RECEIPT.json'
 if resources.exists() and read(resources)['minimum_free_bytes']<RESERVE:raise ValueError('RESOURCE_RESERVE_BEFORE_CHANNEL')
 if api('releases/latest')['id']!=cfg['legacy_release_id']:raise ValueError('LEGACY_LATEST_CHANGED_BEFORE_CHANNEL')
 current=api('git/ref/heads/'+CHANNEL,token=token);current_id=current['object']['sha'] if current else 'ABSENT';gate_channel(expected,current_id,True)
 channel={'contract':'GEO4_CHANNEL_1','sequence':m['sequence'],'logical_identity':m['logical_identity'],'manifest_url':url,'manifest_bytes':len(actual),'manifest_sha256':digest(actual)}
 if with_summary:
  from auto1 import compatibility_summary
  channel['compatibility']=compatibility_summary(verify_signature(actual,public),digest(actual),20047)
 signed=sign(channel,key,public['key_id'],CHANNEL_DOMAIN);assert verify_signature(signed,public,CHANNEL_DOMAIN)==channel
 blob=api('git/blobs','POST',{'content':base64.b64encode(signed).decode(),'encoding':'base64'},token)
 body={'tree':[{'path':CHANNEL_FILE,'mode':'100644','type':'blob','sha':blob['sha']}]}
 if current:
  old=api('git/commits/'+current_id,token=token);body['base_tree']=old['tree']['sha']
 tree=api('git/trees','POST',body,token)
 commit=api('git/commits','POST',{'message':'Publish verified GEO4 channel '+tag,'tree':tree['sha'],'parents':[] if not current else [current_id]},token)
 if current:api('git/refs/heads/'+CHANNEL,'PATCH',{'sha':commit['sha'],'force':False},token)
 else:api('git/refs','POST',{'ref':'refs/heads/'+CHANNEL,'sha':commit['sha']},token)
 with urllib.request.urlopen('https://raw.githubusercontent.com/'+REPO+'/'+commit['sha']+'/'+CHANNEL_FILE,timeout=60) as r:got=r.read(16385)
 if got!=signed or verify_signature(got,public,CHANNEL_DOMAIN)!=channel:raise ValueError('CHANNEL_READBACK')
 if api('releases/latest')['id']!=cfg['legacy_release_id']:raise ValueError('LEGACY_LATEST_CHANGED')
 save(root/'PUBLICATION_RECEIPT.json',{'status':'PASS','tag':tag,'logical_identity':m['logical_identity'],'sequence':m['sequence'],'channel_commit':commit['sha'],'public_readback':proof,'production_key_id':public['key_id'],'legacy_latest_unchanged':True,'quota_cost':'UNKNOWN','routes':{'base':'full','resolver':'full'}})
 phase(root,'COMPLETE')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','build','publish']);p.add_argument('--root',type=Path,required=True);p.add_argument('--config',default='osm261019.json');a=p.parse_args()
 try:globals()[a.mode](a.root,config(a.config))
 except Exception as e:
  a.root.mkdir(parents=True,exist_ok=True);save(a.root/'FAILURE.json',{'status':'FAIL','phase':read(a.root/'phase.json') if (a.root/'phase.json').exists() else None,'exception_type':type(e).__name__,'reason':str(e)[:240],'no_automatic_retry':True});raise
