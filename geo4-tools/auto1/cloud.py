"""Trusted AUTO1 cloud adapter. Explicit modes; rehearsal never downloads GEO or mutates stable.
Production signing only in publish/rehearse-sign. Imports the unchanged pinned compiler.
"""
import argparse,base64,datetime as dt,hashlib,json,os,re,shutil,sqlite3,sys,time,urllib.request,urllib.error
from pathlib import Path
HERE=Path(__file__).resolve().parent
CLOUD=HERE.parent if HERE.name=='auto1' else Path(os.environ.get('GEO4_TOOLS','geo4-tools'))
sys.path.insert(0,str(CLOUD));import stage5 as s
sys.path.insert(0,str(HERE));from auto1 import fingerprint,semantic_contract,semantic_equal,compatibility_summary
from auto1_sources import discover,network_fetch
from transport import canonical,digest,validate,component,choose,reconstruct
REPO=s.REPO;STATUS_BRANCH='geo4-status';STATUS_PATH='geo4/status.json'
PUBLIC=s.read(CLOUD/'PUBLIC_KEY.json')

def now():return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def save(p,obj):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(obj))
def bounded(url,limit):
 req=urllib.request.Request(url,headers={'User-Agent':'TaxiHelper-GEO4-AUTO1','Accept-Encoding':'identity'})
 for attempt in range(3):
  try:
   with urllib.request.urlopen(req,timeout=30) as r:
    body=r.read(limit+1)
    if len(body)>limit:raise ValueError('METADATA_BOUND')
    return body
  except (urllib.error.URLError,TimeoutError):
   if attempt==2:raise
   time.sleep(2**attempt)
def api(path,method='GET',obj=None):return s.api(path,method,obj,os.environ.get('GITHUB_TOKEN'))
def channel():
 ref=api('git/ref/heads/'+s.CHANNEL);head=ref['object']['sha']
 body=bounded('https://raw.githubusercontent.com/'+REPO+'/'+head+'/'+s.CHANNEL_FILE,32768)
 c=s.verify_signature(body,PUBLIC,s.CHANNEL_DOMAIN)
 if c['contract']!='GEO4_CHANNEL_1':raise ValueError('CHANNEL_CONTRACT')
 raw=bounded(c['manifest_url'],c['manifest_bytes'])
 if len(raw)!=c['manifest_bytes'] or digest(raw)!=c['manifest_sha256']:raise ValueError('EXACT_MANIFEST')
 m=s.verify_signature(raw,PUBLIC);validate(m)
 if m['sequence']!=c['sequence'] or m['logical_identity']!=c['logical_identity']:raise ValueError('CHANNEL_BINDING')
 tag=c['manifest_url'].split('/releases/download/',1)[1].split('/',1)[0]
 release=api('releases/tags/'+tag)
 if release is None or release['draft'] or release['tag_name']!=tag:raise ValueError('PUBLISHED_PREDECESSOR')
 return dict(head=head,channel=c,manifest=m,manifest_sha256=digest(raw),release_published_at=release['published_at'])
def read_status():
 ref=api('git/ref/heads/'+STATUS_BRANCH)
 if not ref:return None,None
 head=ref['object']['sha']
 return head,json.loads(bounded('https://raw.githubusercontent.com/'+REPO+'/'+head+'/'+STATUS_PATH,16384))
def inputs(cfg):
 # Immutable source lock covers all accepted compiler/ABI/policy/AOI bytes. Runtime paths excluded.
 lock=s.source_check();by={x['path']:x['sha256'] for x in lock['files']}
 def role(role,sha):return role,dict(sha256=sha)
 return dict(contract='GEO4_AUTO1_INPUTS_1',pins=dict([
 role('dated_osm',cfg['osm']['sha256']),role('additional_private_map_data',cfg['capsules'][0]['sha256']),
 role('historical_supplement',cfg['capsules'][1]['sha256']),role('compiler',s.sha(CLOUD/'SOURCE_LOCK.json')),
 role('policy',next(v for k,v in by.items() if k.endswith('/INCLUSION_POLICY.json'))),
 role('aoi',next(v for k,v in by.items() if k.endswith('/AOI_PROPOSAL.geojson'))),
 role('sector',cfg.get('sector_sha256','19a75b5a16f708c400cefafe8189519936a5545e73142bb8bd834bf065a9709e')),
 role('capabilities',digest(canonical(channel_caps())))]))
def channel_caps():return dict(schema='GEO2_MASTER_1',reader='GEO3_DISK_1',normalizer='GEO2_NFKC_CASEFOLD_ALNUM_V1',evidence='RESOLVE1_COMPLETE_GEOMETRY_SOURCE_ALIAS_1',adapter='RESOLVE1_GEOMETRY_SOURCE_ALIAS_4',transport='GEO4_PACKED_ZLIB_1')
def plan(root,mode):
 root.mkdir(parents=True,exist_ok=False);s.source_check()
 prior=channel();_,status=read_status();cfg=s.config('osm261019.json')
 result=dict(contract='GEO4_AUTO1_CYCLE_1',started_at=now(),mode=mode,executable_sha=os.environ.get('GITHUB_SHA','LOCAL'),prior=prior,config=cfg,source_lock_sha256=s.sha(CLOUD/'SOURCE_LOCK.json'),legacy_release_id=cfg['legacy_release_id'])
 if api('releases/latest')['id']!=cfg['legacy_release_id']:raise ValueError('LEGACY_LATEST_CHANGED')
 if mode=='resume':result.update(action='RESUME')
 elif mode=='rehearse':
  if prior['manifest']['identity']['source_sha256']!=cfg['osm']['sha256']:raise ValueError('REHEARSAL_NOT_CURRENT_PIN')
  result.update(action='REHEARSAL_UNCHANGED',inputs=inputs(cfg))
 else:
  source=discover(network_fetch,dt.datetime.now(dt.timezone.utc).date());result['discovery']=source
  # Dated identity + stable supplier signals reuse only a previously exact acquired SHA receipt.
  old=(status or {}).get('acquired_source')
  stable_keys=['url','date','bytes','md5','etag','last_modified']
  if old and all(source.get(k)==old.get(k) for k in stable_keys) and re.fullmatch('[a-f0-9]{64}',old.get('sha256','')):
   cfg['osm']=dict(date=dt.date.fromisoformat(source['date']).strftime('%y%m%d'),url=source['url'],bytes=source['bytes'],sha256=old['sha256'])
   exact=inputs(cfg);result['inputs']=exact
   unchanged=status.get('checked_fingerprint')==fingerprint(exact) and status.get('last_successful_check')
   result['action']='UNCHANGED_INPUTS' if unchanged else 'BUILD_ONCE'
  else:result['action']='ACQUIRE_HASH_BUILD_ONCE'
 save(root/'CYCLE.json',result)
 output=os.environ.get('GITHUB_OUTPUT')
 if output:
  with open(output,'a',encoding='utf-8') as f:f.write('action='+result['action']+'\n')
 return result

def acquire(source,target):
 # Exactly one streamed acquisition. Preserve partial output on failure; no automatic second build.
 h=hashlib.sha256();md5=hashlib.md5();n=0
 with urllib.request.urlopen(urllib.request.Request(source['url'],headers={'User-Agent':'TaxiHelper-GEO4-AUTO1','Accept-Encoding':'identity'}),timeout=60) as r,target.open('xb') as out:
  if int(r.headers.get('Content-Length','-1'))!=source['bytes']:raise ValueError('DATED_SIZE_HEADER')
  for data in iter(lambda:r.read(1<<20),b''):
   n+=len(data)
   if n>source['bytes']:raise ValueError('DATED_SIZE_OVERFLOW')
   out.write(data);h.update(data);md5.update(data)
 if n!=source['bytes'] or md5.hexdigest()!=source['md5']:raise ValueError('DATED_TRANSPORT_INTEGRITY')
 return h.hexdigest()
def header_gate(path,source):
 import osmium
 with osmium.io.Reader(str(path),osmium.osm.NOTHING) as r:
  header=r.header();stamp=dt.datetime.fromisoformat(header.get('osmosis_replication_timestamp').replace('Z','+00:00'))
  date=dt.date.fromisoformat(source['date'])
  if not date-dt.timedelta(days=1)<=stamp.date()<=date:raise ValueError('DATED_HEADER_EPOCH')
  bounds=header.box()
  aoi=s.read(s.SOURCE/'docs/taxihelper_2_0/geo1/AOI_PROPOSAL.geojson')['features'][0]['geometry']['coordinates']
  points=[]
  def coordinates(value):
   if len(value)>=2 and all(isinstance(x,(int,float)) for x in value[:2]):points.append(value[:2])
   else:
    for item in value:coordinates(item)
  coordinates(aoi)
  if not bounds.valid() or not points or not all(bounds.bottom_left.lon<=lon<=bounds.top_right.lon and bounds.bottom_left.lat<=lat<=bounds.top_right.lat for lon,lat in points):raise ValueError('DATED_HEADER_COVERAGE')
def reconstruct_prior(root,prior):
 dest=root/'previous';dest.mkdir();assets=dest/'assets';assets.mkdir()
 for c in prior['manifest']['components']:
  s.guard(root,additional=c['full']['bytes']+c['raw_bytes'])
  asset=c['full'];s.fetch(prior['channel']['manifest_url'].rsplit('/',1)[0]+'/'+asset['name'],assets/asset['name'],asset['bytes'],asset['sha256'])
  target=dest/('mobile.sqlite' if c['role']=='base' else 'resolve1/evidence.sqlite');target.parent.mkdir(exist_ok=True)
  reconstruct(c,dest/'NO_BASE',assets,target,'full');(assets/asset['name']).unlink()
 return dest

def build(root):
 c=s.read(root/'CYCLE.json');cfg=c['config'];s.guard(root,minimum=16*1024**3);s.source_check()
 source=c['discovery'];pbf=root/'dated.osm.pbf';exact=acquire(source,pbf);header_gate(pbf,source)
 cfg['osm']=dict(date=dt.date.fromisoformat(source['date']).strftime('%y%m%d'),url=source['url'],bytes=source['bytes'],sha256=exact)
 for asset in cfg['capsules']:s.fetch(asset['url'],root/asset['name'],asset['bytes'],asset['sha256'])
 sys.path.insert(0,str(s.TOOLS));from unpack_input import unpack;from portable_supplement import unpack as supplement
 unpack(root/cfg['capsules'][0]['name'],cfg['capsules'][0]['sha256'],root/'inputs');supplement(root/cfg['capsules'][1]['name'],cfg['capsules'][1]['sha256'],root/'supplement')
 s.command('prepare.py','--source',pbf,'--additional',root/'inputs/additional','--dependencies',root/'inputs/dependencies','--supplement',root/'supplement','--output',root/'candidate')
 for phase in ['extract','build','supplement','verify','sidecar']:s.guard(root);s.phase(root,'AUTO1_'+phase);s.command('compiler.py','--config',root/'candidate/CONFIG.json','--phase',phase)
 from semantic_passport import passport
 target=root/'candidate';new=passport(target);previous=reconstruct_prior(root,c['prior'])
 m=c['prior']['manifest'];b=next(x for x in m['components'] if x['role']=='base');r=next(x for x in m['components'] if x['role']=='resolver')
 old_config=s.read(target/'CONFIG.json')
 for pin in old_config['pins']:
  if pin['role']=='dated_osm':pin['sha256']=m['identity']['source_sha256']
 save(previous/'CONFIG.json',old_config);save(previous/'MOBILE_COMPLETE.json',dict(sha256=b['raw_sha256'],revision=b['version']))
 save(previous/'resolve1/descriptor.json',dict(geo_sha256=b['raw_sha256'],geo_version=b['version']))
 old=passport(previous)
 # Before parity exclusions, old raw policy binding must match the pinned policy exactly.
 policy=next(Path(x['path']) for x in old_config['pins'] if x['role']=='contract:INCLUSION_POLICY.json')
 with sqlite3.connect((previous/'mobile.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:meta=dict(db.execute('SELECT key,value FROM meta'))
 can_compare=meta.get('policy')==s.sha(policy) and m['capabilities']==channel_caps() and m['identity']['aoi_sha256']==next(x['sha256'] for x in old_config['pins'] if x['role']=='aoi')
 c.update(config=cfg,inputs=inputs(cfg),acquired_source=dict(source,sha256=exact),semantic_contract=semantic_contract(inputs(cfg)))
 save(root/'SEMANTIC_NEW.json',new);save(root/'SEMANTIC_OLD.json',old)
 if can_compare and semantic_equal(old,new):c['action']='UNCHANGED_CONTENT'
 else:
  bundle=root/'bundle';bundle.mkdir();s.guard(root,additional=6*1024**3)
  manifest=s.package(target,bundle,m['sequence']+1,previous)
  checks=[]
  for spec in manifest['components']:
   prior_file=previous/('mobile.sqlite' if spec['role']=='base' else 'resolve1/evidence.sqlite')
   for mode in ['full','compact']:
    path=root/'reconstruct-test.sqlite';s.guard(root,additional=spec['raw_bytes']);checks.append(dict(role=spec['role'],**reconstruct(spec,prior_file,bundle,path,mode)));path.unlink()
  save(bundle/'BUILD_RECEIPT.json',dict(status='PASS',contract='GEO4_AUTO1_BUILD_1',source_lock_sha256=c['source_lock_sha256'],config_sha256=digest(canonical(cfg)),logical_identity=manifest['logical_identity'],prior_head=c['prior']['head'],prior_manifest_sha256=c['prior']['manifest_sha256'],exact_reconstruction=checks,semantic_sha256=digest(canonical(new))))
  save(bundle/'SEMANTIC.json',new);shutil.copyfile(CLOUD/'INPUT_NOTICE.txt',bundle/'NOTICE.txt');save(bundle/'CYCLE.json',c)
  c['action']='VERIFIED_RELEASE'
 save(root/'CYCLE.json',c)
 output=os.environ.get('GITHUB_OUTPUT')
 if output:
  with open(output,'a',encoding='utf-8') as f:f.write('action='+c['action']+'\n')

def verify_bundle(bundle):
 m=s.read(bundle/'manifest.unsigned.json');validate(m);receipt=s.read(bundle/'BUILD_RECEIPT.json');cycle=s.read(bundle/'CYCLE.json')
 if cycle.get('executable_sha')!=os.environ.get('GITHUB_SHA','LOCAL'):raise ValueError('RESUME_EXECUTABLE_REF')
 if receipt['contract']!='GEO4_AUTO1_BUILD_1' or receipt['status']!='PASS' or receipt['source_lock_sha256']!=s.sha(CLOUD/'SOURCE_LOCK.json'):raise ValueError('RESUME_SOURCE_LOCK')
 if receipt['config_sha256']!=digest(canonical(cycle['config'])) or receipt['logical_identity']!=m['logical_identity'] or m['sequence']!=cycle['prior']['manifest']['sequence']+1:raise ValueError('RESUME_CONFIG_SEQUENCE')
 if m['identity']['source_sha256']!=cycle['config']['osm']['sha256']:raise ValueError('RESUME_SOURCE')
 if receipt['prior_head']!=cycle['prior']['head'] or receipt['prior_manifest_sha256']!=cycle['prior']['manifest_sha256']:raise ValueError('RESUME_PREDECESSOR')
 if digest(canonical(s.read(bundle/'SEMANTIC.json')))!=receipt['semantic_sha256']:raise ValueError('RESUME_SEMANTICS')
 checks=receipt['exact_reconstruction']
 for spec in m['components']:
  for mode in ['full','compact']:
   matching=[x for x in checks if x.get('role')==spec['role'] and x.get('mode')==mode and x.get('sha256')==spec['raw_sha256'] and x.get('raw_bytes')==spec['raw_bytes']]
   if len(matching)!=1:raise ValueError('RESUME_RECONSTRUCTION')
  for asset in [spec['full'],*spec['packs']]:
   p=bundle/asset['name']
   if p.stat().st_size!=asset['bytes'] or s.sha(p)!=asset['sha256']:raise ValueError('RESUME_PAYLOAD')
 proof=s.read(bundle/'completeness.json')
 if (bundle/'completeness.json').stat().st_size!=m['proof']['bytes'] or s.sha(bundle/'completeness.json')!=m['proof']['sha256'] or proof['logical_identity']!=m['logical_identity']:raise ValueError('RESUME_PROOF_BINDING')
 base=next(x for x in m['components'] if x['role']=='base');resolver=next(x for x in m['components'] if x['role']=='resolver')
 if proof['base_sha256']!=base['raw_sha256'] or proof['base_version']!=base['version'] or proof['resolver_sha256']!=resolver['raw_sha256']:raise ValueError('RESUME_BASE_SIDECAR_BINDING')
 for key in ['raw_to_master','master_to_mobile','postal_units','name_fields']:
  if proof[key]['status']!='PASS' or proof[key].get('errors') or proof[key].get('unexplained_omissions',0):raise ValueError('RESUME_COMPLETENESS')
 return m

def rehearse_sign(root):
 from cryptography.hazmat.primitives.serialization import load_pem_private_key,Encoding,PublicFormat
 key=load_pem_private_key(os.environ['GEO4_SIGNING_KEY_PEM'].encode(),password=None)
 if digest(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))!=PUBLIC['fingerprint_sha256'] or os.environ['GEO4_SIGNING_KEY_ID']!=PUBLIC['key_id']:raise ValueError('KEY_MISMATCH')
 c=s.read(root/'CYCLE.json');message=canonical(dict(contract='GEO4_AUTO1_READINESS_1',run=os.environ['GITHUB_RUN_ID'],head=c['prior']['head']))
 domain=b'TaxiHelper-GEO4-AUTO1-READINESS-1\0';signature=key.sign(domain+message);key.public_key().verify(signature,domain+message)
 if channel()['head']!=c['prior']['head']:raise ValueError('REHEARSAL_CHANNEL_CHANGED')
 save(root/'READINESS.json',dict(status='PASS',key_id=PUBLIC['key_id'],signature_verified=True,stable_unchanged=True,new_release=False,payload_download_bytes=0))

def resume_origin(run_id):
 if not re.fullmatch('[1-9][0-9]{0,19}',run_id):raise ValueError('RESUME_RUN_ID')
 run=api('actions/runs/'+run_id)
 if run['head_sha']!=os.environ['GITHUB_SHA'] or run['head_branch']!='main' or run['event'] not in ['schedule','workflow_dispatch'] or run['path']!='.github/workflows/geo4-auto1.yml' or run['head_repository']['full_name']!=REPO:raise ValueError('RESUME_RUN_ORIGIN')
 jobs=api('actions/runs/'+run_id+'/jobs?per_page=100')['jobs']
 if not any(x['name']=='GEO4 build' and x['conclusion']=='success' for x in jobs):raise ValueError('RESUME_BUILD_NOT_VERIFIED')

def publish(root):
 c=s.read(root/'bundle/CYCLE.json');os.environ['GEO4_EXPECTED_CHANNEL']=c['prior']['head'];s.publish(root,c['config'],verify_bundle,True)
 save(root/'CYCLE.json',dict(c,action='PUBLISHED',published=verify_bundle(root/'bundle')['logical_identity']))

def status(root,outcome):
 if not (root/'CYCLE.json').exists():
  root.mkdir(parents=True,exist_ok=True);save(root/'CYCLE.json',dict(prior=channel()))
 c=s.read(root/'CYCLE.json');head,previous=read_status();previous=previous or {}
 success=outcome in ['UNCHANGED_INPUTS','UNCHANGED_CONTENT','PUBLISHED']
 record=dict(contract='GEO4_CLOUD_STATUS_1',checked_at=now(),outcome=outcome,last_successful_check=now() if success else previous.get('last_successful_check',c['prior'].get('release_published_at')),last_published=c.get('published',previous.get('last_published',c['prior']['manifest']['logical_identity'])),error_category=None if success or outcome=='REHEARSAL_UNCHANGED' else 'CYCLE_FAILED',run_url='https://github.com/'+REPO+'/actions/runs/'+os.environ['GITHUB_RUN_ID'])
 for key in ['checked_fingerprint','acquired_source','semantic_contract']:
  if key in previous:record[key]=previous[key]
 if success:
  record['checked_fingerprint']=fingerprint(c['inputs']);record['semantic_contract']=semantic_contract(c['inputs'])
  if 'acquired_source' in c:record['acquired_source']=c['acquired_source']
 if len(canonical(record))>16384:raise ValueError('STATUS_BOUND')
 blob=api('git/blobs','POST',dict(content=base64.b64encode(canonical(record)).decode(),encoding='base64'))
 tree_arg=dict(tree=[dict(path=STATUS_PATH,mode='100644',type='blob',sha=blob['sha'])])
 if head:tree_arg['base_tree']=api('git/commits/'+head)['tree']['sha']
 tree=api('git/trees','POST',tree_arg);commit=api('git/commits','POST',dict(message='GEO4 real cycle '+outcome,tree=tree['sha'],parents=[head] if head else []))
 if head:api('git/refs/heads/'+STATUS_BRANCH,'PATCH',dict(sha=commit['sha'],force=False))
 else:api('git/refs','POST',dict(ref='refs/heads/'+STATUS_BRANCH,sha=commit['sha']))
 actual=bounded('https://raw.githubusercontent.com/'+REPO+'/'+commit['sha']+'/'+STATUS_PATH,16384)
 if actual!=canonical(record):raise ValueError('STATUS_READBACK')
 save(root/'STATUS_RECEIPT.json',dict(status='PASS',commit=commit['sha'],stable_head=channel()['head'],outcome=outcome))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['plan','build','publish','rehearse-sign','status','resume-origin']);p.add_argument('--root',type=Path,required=True);p.add_argument('--cycle-mode',choices=['rehearse','cycle','resume'],default='rehearse');p.add_argument('--outcome',default='FAILED');a=p.parse_args()
 if a.mode=='plan':plan(a.root,a.cycle_mode)
 elif a.mode=='build':build(a.root)
 elif a.mode=='publish':publish(a.root)
 elif a.mode=='rehearse-sign':rehearse_sign(a.root)
 elif a.mode=='resume-origin':resume_origin(os.environ['GEO4_RESUME_RUN'])
 else:status(a.root,a.outcome)
