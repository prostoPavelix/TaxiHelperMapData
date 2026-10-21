"""Only new first-install/publication gates. Tiny synthetic files; no GEO/Android suite."""
import base64,copy,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import stage5 as s
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization as ser

class Stage5Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.c=self.root/'candidate';self.c.mkdir();self.bundle=self.root/'bundle';self.bundle.mkdir();(self.c/'resolve1').mkdir()
  db=sqlite3.connect(self.c/'mobile.sqlite');db.execute('CREATE TABLE example(x TEXT)');db.execute("INSERT INTO example VALUES('SYNTHETIC GEOGRAPHY')");db.commit();db.close()
  version='b'*64;self.base=s.sha(self.c/'mobile.sqlite');sector='19a75b5a16f708c400cefafe8189519936a5545e73142bb8bd834bf065a9709e'
  db=sqlite3.connect(self.c/'resolve1/evidence.sqlite');db.execute('CREATE TABLE meta(key TEXT,value TEXT)');db.executemany('INSERT INTO meta VALUES(?,?)',[('geo_sha256',self.base),('geo_version',version)]);db.commit();db.close()
  s.save(self.c/'MOBILE_COMPLETE.json',{'sha256':self.base,'revision':version})
  s.save(self.c/'resolve1/descriptor.json',{'geo_sha256':self.base,'geo_version':version,'sha256':s.sha(self.c/'resolve1/evidence.sqlite'),'sector_sha256':sector})
  for n in ['VERIFICATION.json','INGESTION.json','ADDRESS_COVERAGE.json','NAME_FIELD_AUDIT.json']:s.save(self.c/n,{'status':'PASS','errors':[],'unexplained_omissions':0})
  s.save(self.c/'CLOSURE_PRIVATE.json',{'reference_missing_count':0});s.save(self.c/'EXTRACTION.json',{'header':{'scope':'SYNTHETIC'}})
  s.save(self.c/'CONFIG.json',{'pins':[{'role':r,'sha256':c*64} for r,c in [('dated_osm','a'),('additional_manifest','c'),('aoi','d')]],'toolchain':{'scope':'SYNTHETIC'}})
  self.m=s.package(self.c,self.bundle,1)
  s.save(self.bundle/'BUILD_RECEIPT.json',{'status':'PASS','logical_identity':self.m['logical_identity'],'compiler_ref':s.source_check()['source_ref'],'source_lock_sha256':s.sha(s.HERE/'SOURCE_LOCK.json'),'config_sha256':s.digest(s.canonical({'osm':{'sha256':'a'*64}})),'target_hashes':{x['role']:x['raw_sha256'] for x in self.m['components']},'routes':{'base':'full','resolver':'full'},'exact_reconstruction':[s.reconstruct(x,self.root/'absent',self.bundle,self.root/(x['role']+'.proof'),'full') for x in self.m['components']]})
  (self.bundle/'NOTICE.txt').write_text('SYNTHETIC',encoding='utf-8')
  # Explicit local test fixture only, never production configuration/key material.
  self.key=Ed25519PrivateKey.from_private_bytes(bytes(range(32)));raw=self.key.public_key().public_bytes(ser.Encoding.Raw,ser.PublicFormat.Raw)
  self.pub={'key_id':'LOCAL_TEST_ONLY','public_key_raw_base64':base64.b64encode(raw).decode(),'fingerprint_sha256':s.digest(raw)}
 def tearDown(self):self.temp.cleanup()
 def test_first_full_exact_reconstruction_and_idempotent_plan(self):
  self.assertEqual(s.verify_bundle(self.bundle),self.m)
  for c in self.m['components']:
   self.assertFalse(c['packs']);self.assertEqual(c['raw_sha256'],c['base_sha256'])
   target=self.root/(c['role']+'.restored');s.reconstruct(c,self.root/'no_predecessor',self.bundle,target,'full');self.assertEqual(s.sha(target),c['raw_sha256'])
  self.assertEqual(s.publication_plan(self.m,None),'CREATE');self.assertEqual(s.publication_plan(self.m,copy.deepcopy(self.m)),'REUSE')
  wrong=copy.deepcopy(self.m);wrong['sequence']=2
  with self.assertRaises(ValueError):s.publication_plan(self.m,wrong)
 def test_signature_tamper_and_wrong_closure_rejected(self):
  envelope=s.sign(self.m,self.key,self.pub['key_id']);self.assertEqual(s.verify_signature(envelope,self.pub),self.m)
  e=json.loads(envelope);e['payload_b64']=base64.b64encode(b'{}').decode()
  with self.assertRaises(Exception):s.verify_signature(s.canonical(e),self.pub)
  p=s.read(self.bundle/'completeness.json');p['resolver_sha256']='0'*64;s.save(self.bundle/'completeness.json',p)
  with self.assertRaises(ValueError):s.verify_bundle(self.bundle)
 def test_incomplete_upload_cannot_change_channel(self):
  calls=[];original=s.read
  def read(p):return self.pub if Path(p)==s.HERE/'PUBLIC_KEY.json' else original(p)
  def api(path,method='GET',obj=None,token=None):
   calls.append((path,method))
   if path.startswith('git/ref/') or path.startswith('releases/tags/'):return None
   if path=='releases' and method=='POST':return {'id':1,'tag_name':'fixture','draft':True,'assets':[]}
   raise AssertionError('Unexpected operation '+path)
  pem=self.key.private_bytes(ser.Encoding.PEM,ser.PrivateFormat.PKCS8,ser.NoEncryption()).decode()
  with patch.object(s,'read',side_effect=read),patch.object(s,'api',side_effect=api),patch.object(s,'upload',side_effect=OSError('SYNTHETIC incomplete upload')),patch.dict(os.environ,{'GITHUB_TOKEN':'LOCAL_FIXTURE_NOT_TOKEN','GITHUB_SHA':'f'*40,'GEO4_SIGNING_KEY_ID':self.pub['key_id'],'GEO4_SIGNING_KEY_PEM':pem,'GEO4_EXPECTED_CHANNEL':'ABSENT'}):
   with self.assertRaises(OSError):s.publish(self.root,{'osm':{'sha256':'a'*64}})
  self.assertFalse(any(path.startswith(('git/refs','git/blobs','git/trees','git/commits')) for path,method in calls))
  with self.assertRaises(ValueError):s.gate_channel('old','other',True)
  with self.assertRaises(ValueError):s.gate_channel('old','old',False)

if __name__=='__main__':unittest.main()
