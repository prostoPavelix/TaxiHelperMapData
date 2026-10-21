"""Synthetic loss-detection and geography contract tests; private scratch only."""
from common import *
from build import SCHEMA,export_mobile
from verify import audit
from reader import DiskReader
from extract import intersect_way
import unittest,tempfile,shutil,sqlite3
from shapely.geometry import box

class ContractTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.work=Path(tempfile.mkdtemp(prefix='synthetic-',dir=OUT));cls.master=cls.work/'master.sqlite';cls.mobile=cls.work/'mobile.sqlite'
  db=sqlite3.connect(cls.master);db.executescript(SCHEMA);db.execute("INSERT INTO meta VALUES('osm','old')")
  for i in range(300):
   oid=f'fixture:{i:03}';db.execute('INSERT INTO objects VALUES(?,?,?,?,?)',(oid,'SYNTHETIC','POI','{}',js(dict(id=oid,kind='fixture'))))
   db.execute('INSERT INTO aliases VALUES(?,?,?,?,?)',('a'+str(i),oid,'name','Shared Street 1','{}'))
   db.execute('INSERT INTO points VALUES(?,?,?,?,?,?,?,?)',('p'+str(i),oid,50.7,25.3,'SYNTHETIC',None,js(dict(source=None,derived=None,status='UNKNOWN_LOCALITY')),None))
  # One object/many aliases; same text/many points, same-sector vs cross-sector not collapsed.
  db.execute("INSERT INTO aliases VALUES('alternate','fixture:000','old_name','Former Street 1','{}')")
  db.execute("INSERT INTO points VALUES('second','fixture:000',50.71,25.31,'SYNTHETIC',NULL,'{\"status\":\"UNKNOWN_LOCALITY\"}','sector-B')")
  db.execute("INSERT INTO objects VALUES('unknown','VISICOM_RAW_ONLY','RAW_ONLY','{}','{\"id\":\"unknown\"}')")
  db.execute("INSERT INTO aliases VALUES('unknown-name','unknown','name','Unknown location fixture','{}')")
  db.commit();db.close();export_mobile(cls.master,cls.mobile)
 def mutation(self,name,sql):
  path=self.work/(name+'.sqlite');shutil.copy2(self.mobile,path)
  with sqlite3.connect(path) as db:db.executescript(sql)
  result=audit(self.master,path)
  self.assertEqual(result['status'],'FAIL',result);return result
 def test_valid_many_to_many(self):self.assertEqual(audit(self.master,self.mobile)['status'],'PASS')
 def test_deleted_alias_posting(self):self.mutation('lost-alias',"DELETE FROM postings WHERE lookup_key='former street 1'")
 def test_lost_second_point(self):self.mutation('lost-point',"DELETE FROM points WHERE pid='second'")
 def test_null_to_zero(self):self.mutation('zero-weight',"UPDATE points SET weight=0 WHERE pid='p0'")
 def test_unknown_locality_discarded(self):self.mutation('lost-unknown',"DELETE FROM candidates WHERE oid='unknown'")
 def test_unknown_locality_with_known_point_discarded(self):self.mutation('lost-unknown-locality-known-point',"DELETE FROM candidates WHERE pid='p0'")
 def test_missing_detail(self):self.mutation('lost-detail',"DELETE FROM details WHERE oid='fixture:000'")
 def test_more_than_page_limit(self):
  reader=DiskReader(self.mobile);cursor=None;ids=[];pages=0
  while True:
   page=reader.lookup('Shared Street 1',limit=128,cursor=cursor);ids.extend(x['cid'] for x in page['candidates']);pages+=1
   if not page['has_more']:break
   cursor=page['continuation']
  self.assertEqual((len(set(ids)),pages),(301,3));reader.close()
 def test_cursor_query_revision_and_cancel(self):
  reader=DiskReader(self.mobile);page=reader.lookup('Shared Street 1',1)
  with self.assertRaises(ValueError):reader.lookup('Other',1,page['continuation'])
  bad=dict(page['continuation'],revision='other')
  with self.assertRaises(ValueError):reader.lookup('Shared Street 1',1,bad)
  self.assertTrue(reader.lookup('Shared Street 1',cancel=lambda:True)['cancelled']);reader.close()
 def test_geometry_crossing_and_enclosing(self):
  region=box(0,0,1,1)
  self.assertTrue(intersect_way([(-1,.5),(2,.5)],region))
  self.assertTrue(intersect_way([(-1,-1),(2,-1),(2,2),(-1,2),(-1,-1)],region))
  self.assertFalse(intersect_way([(-2,-2),(-1,-1)],region))
 def test_osm_revision_does_not_erase_visicom(self):
  master=self.work/'new-revision-master.sqlite';shutil.copy2(self.master,master)
  with sqlite3.connect(master) as db:db.execute("UPDATE meta SET value='new' WHERE key='osm'")
  new=self.work/'new-revision-mobile.sqlite';export_mobile(master,new)
  reader=DiskReader(new);hits=reader.lookup('Unknown location fixture')['candidates'];self.assertEqual([x['oid'] for x in hits],['unknown']);self.assertEqual(reader.detail('unknown'),dict(id='unknown'));reader.close()

def run():
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests)
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 dump(OUT/'SYNTHETIC_TESTS.json',dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),status='PASS' if result.wasSuccessful() else 'FAIL',scope='Synthetic schema/export/reference API/independent verifier mutations only; not Android'))
 if not result.wasSuccessful():raise SystemExit(1)

if __name__=='__main__':run()
