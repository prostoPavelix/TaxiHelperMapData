import copy,json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import cloud
from auto1 import fingerprint,semantic_contract,semantic_equal,publication_gate,resume_gate
from auto1_sources import discover

class CloudTest(unittest.TestCase):
 def test_exact_inputs_and_summary_gate(self):
  cfg=cloud.s.config('osm261019.json');value=cloud.inputs(cfg)
  self.assertEqual(64,len(fingerprint(value)));self.assertEqual(64,len(semantic_contract(value)))
  changed=copy.deepcopy(value);changed['pins']['capabilities']['sha256']='f'*64
  self.assertNotEqual(semantic_contract(value),semantic_contract(changed))
  del value['pins']['dated_osm']
  with self.assertRaises(ValueError):fingerprint(value)
 def test_dated_discovery_never_gets_pbf(self):
  import datetime as dt
  calls=[]
  def fetch(url,method,maximum):
   calls.append((url,method))
   if url.endswith('.html'):return 200,{},b'ukraine-261021.osm.pbf'
   if method=='HEAD':return 200,{'content-length':'10'},b''
   return 200,{},b'a'*32+b' ukraine-261021.osm.pbf'
  self.assertEqual('2026-10-21',discover(fetch,dt.date(2026,10,22))['date'])
  self.assertFalse(any(method=='GET' and url.endswith('.pbf') for url,method in calls))
 def test_uncertain_semantics_and_provenance_never_skip(self):
  p=dict(contract='GEO4_CROSS_PLATFORM_SEMANTICS_1',tables={k:{'geometry':dict(rows=1,sha256='a'*64)} for k in ['base','resolver']},policy_semantic_sha256='b'*64,algorithm_lf_sha256={'compiler':'c'*64})
  self.assertTrue(semantic_equal(p,copy.deepcopy(p)))
  changed=copy.deepcopy(p);changed['tables']['resolver']['provenance']=dict(rows=1,sha256='d'*64)
  self.assertFalse(semantic_equal(p,changed));self.assertFalse(semantic_equal(p,None))
 def test_publication_cas_and_resume_identity(self):
  self.assertEqual('READY_FOR_ATOMIC_REF_CAS',publication_gate('a'*64,'a'*64,1,2,{'public':True},True))
  with self.assertRaises(ValueError):publication_gate('a'*64,'b'*64,1,2,{'public':True},True)
  receipt=dict(status='VERIFIED',source_sha256='a'*64,compiler_sha256='b'*64,manifest_sha256='c'*64,payload_sha256='d'*64)
  self.assertEqual('PUBLISH_ONLY_NO_REBUILD',resume_gate(receipt,receipt,'e'*64,'e'*64))
  with self.assertRaises(ValueError):resume_gate(receipt,dict(receipt,payload_sha256='f'*64),'e'*64,'e'*64)
 def test_rehearsal_no_payload_no_stable_mutation(self):
  from unittest.mock import patch
  cfg=cloud.s.config('osm261019.json')
  prior=dict(head='a'*40,manifest=dict(logical_identity='b'*64,identity=dict(source_sha256=cfg['osm']['sha256'])))
  with tempfile.TemporaryDirectory(dir=os.environ.get("GEO4_TEST_TMP")) as temp,patch.object(cloud,'channel',return_value=prior),patch.object(cloud,'read_status',return_value=(None,None)),patch.object(cloud,'api',return_value={'id':cfg['legacy_release_id']}),patch.object(cloud,'discover',side_effect=AssertionError('NO_SOURCE_DISCOVERY_IN_REHEARSAL')),patch.object(cloud,'acquire',side_effect=AssertionError('NO_GEO_ACQUISITION')):
   result=cloud.plan(Path(temp)/'cycle','rehearse');self.assertEqual('REHEARSAL_UNCHANGED',result['action'])
 def test_untrusted_resume_run_rejected(self):
  from unittest.mock import patch
  run=dict(head_sha='a'*40,head_branch='pull-request',event='pull_request',path='.github/workflows/geo4-auto1.yml',head_repository={'full_name':cloud.REPO})
  with patch.dict(os.environ,{'GITHUB_SHA':'a'*40}),patch.object(cloud,'api',return_value=run):
   with self.assertRaises(ValueError):cloud.resume_origin('1234')
 def test_status_failure_preserves_success_and_never_writes_stable(self):
  from unittest.mock import patch
  calls=[];blob_body={}
  prior=dict(manifest=dict(logical_identity='b'*64),head='a'*40)
  old=dict(last_successful_check='2026-10-21T20:00:00Z',last_published='b'*64,checked_fingerprint='c'*64)
  def api(path,method='GET',obj=None):
   calls.append((path,method))
   if path=='git/blobs':blob_body['value']=__import__('base64').b64decode(obj['content']);return {'sha':'blob'}
   if path=='git/trees':return {'sha':'tree'}
   if path=='git/commits':return {'sha':'commit'}
   return {}
  with tempfile.TemporaryDirectory(dir=os.environ.get('GEO4_TEST_TMP')) as tmp,patch.dict(os.environ,{'GITHUB_RUN_ID':'1234'}),patch.object(cloud,'channel',return_value=prior),patch.object(cloud,'read_status',return_value=(None,old)),patch.object(cloud,'api',side_effect=api),patch.object(cloud,'bounded',side_effect=lambda *_:blob_body['value']):
   cloud.status(Path(tmp),'FAILED')
   written=json.loads(blob_body['value']);self.assertEqual(old['last_successful_check'],written['last_successful_check']);self.assertEqual(old['checked_fingerprint'],written['checked_fingerprint'])
   self.assertFalse(any('geo4-channel' in path for path,_ in calls));self.assertIn(('git/refs','POST'),calls)
 def test_header_epoch_and_entire_aoi_admission(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  bounds=SimpleNamespace(valid=lambda:True,bottom_left=SimpleNamespace(lon=0,lat=0),top_right=SimpleNamespace(lon=90,lat=90))
  class Reader:
   def __enter__(self):return self
   def __exit__(self,*_):pass
   def header(self):return SimpleNamespace(get=lambda _: '2026-10-21T20:00:00Z',box=lambda:bounds)
  fake=SimpleNamespace(io=SimpleNamespace(Reader=lambda *_:Reader()),osm=SimpleNamespace(NOTHING=0))
  with patch.dict(sys.modules,{'osmium':fake}):
   cloud.header_gate(Path('not-opened'),{'date':'2026-10-21'})
   bounds.top_right.lon=1
   with self.assertRaisesRegex(ValueError,'COVERAGE'):cloud.header_gate(Path('not-opened'),{'date':'2026-10-21'})
   with self.assertRaisesRegex(ValueError,'EPOCH'):cloud.header_gate(Path('not-opened'),{'date':'2026-10-25'})
 def test_workflow_has_no_pr_secrets_or_build_write(self):
  path=Path(__file__).resolve().parent/'geo4-auto1.yml'
  if not path.exists():path=cloud.CLOUD.parent/'.github/workflows/geo4-auto1.yml'
  text=path.read_text(encoding='utf-8');build=text.split('  build:\n',1)[1].split('  publish:\n',1)[0]
  self.assertNotIn('secrets.',build);self.assertNotIn('contents: write',build)
  self.assertEqual(1,text.count('secrets.GEO4_SIGNING_KEY_PEM'))
  self.assertIn("github.ref == 'refs/heads/main'",text);self.assertIn('cancel-in-progress: false',text)
  self.assertIn("run['head_branch']!='main'",Path(cloud.__file__).read_text(encoding='utf-8'))
 def test_monthly_bundle_exact_resume_and_tamper(self):
  import stage5
  from test_stage5 import Stage5Tests
  fixture=Stage5Tests();fixture.setUp()
  try:
   bundle=fixture.root/'monthly';bundle.mkdir();manifest=stage5.package(fixture.c,bundle,2,fixture.c)
   cfg={'osm':{'sha256':'a'*64}};prior={'head':'b'*40,'manifest_sha256':'c'*64,'manifest':fixture.m}
   cycle=dict(executable_sha=os.environ.get('GITHUB_SHA','LOCAL'),config=cfg,prior=prior)
   stage5.save(bundle/'CYCLE.json',cycle);stage5.save(bundle/'SEMANTIC.json',{'synthetic':True})
   checks=[]
   for component in manifest['components']:
    source=fixture.c/('mobile.sqlite' if component['role']=='base' else 'resolve1/evidence.sqlite')
    for mode in ['full','compact']:
     target=fixture.root/(component['role']+'-'+mode);checks.append(dict(role=component['role'],**stage5.reconstruct(component,source,bundle,target,mode)))
   stage5.save(bundle/'BUILD_RECEIPT.json',dict(contract='GEO4_AUTO1_BUILD_1',status='PASS',source_lock_sha256=stage5.sha(stage5.HERE/'SOURCE_LOCK.json'),config_sha256=stage5.digest(stage5.canonical(cfg)),logical_identity=manifest['logical_identity'],prior_head=prior['head'],prior_manifest_sha256=prior['manifest_sha256'],semantic_sha256=stage5.digest(stage5.canonical({'synthetic':True})),exact_reconstruction=checks))
   self.assertEqual(manifest,cloud.verify_bundle(bundle))
   payload=bundle/manifest['components'][0]['full']['name'];payload.write_bytes(payload.read_bytes()+b'corruption')
   with self.assertRaisesRegex(ValueError,'RESUME_PAYLOAD'):cloud.verify_bundle(bundle)
  finally:fixture.tearDown()
 def test_existing_full_and_monthly_compact_are_exact(self):
  from transport import component,reconstruct,choose
  with tempfile.TemporaryDirectory(dir=os.environ.get("GEO4_TEST_TMP")) as temp:
   root=Path(temp);old=root/'old';new=root/'new';import random;randomizer=random.Random(42);shared=randomizer.randbytes(262144);old.write_bytes(shared+randomizer.randbytes(262144));new.write_bytes(shared+randomizer.randbytes(262144))
   spec,_=component(old,new,'base',root,'a'*64)
   self.assertEqual('compact',choose(spec,spec['base_sha256']))
   for mode in ['full','compact']:
    target=root/(mode+'.out');reconstruct(spec,old,root,target,mode);self.assertEqual(new.read_bytes(),target.read_bytes())

if __name__=='__main__':unittest.main()
