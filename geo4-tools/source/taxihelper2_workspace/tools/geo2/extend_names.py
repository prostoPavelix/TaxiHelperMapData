"""Correct the audited V1 name-field gap without repeating the regional PBF selection.
Only task-owned candidate DBs change. Before-name candidates/proofs are retained privately.
Run after the initial verification process has closed its files; then rerun final proofs.
"""
from common import *
from build import alias,ident
import shutil

def run():
 assert not (OUT/'NAME_EXTENSION.json').exists(),'Completed extension preserved'
 assert json.loads((OUT/'VERIFICATION.json').read_text())['status']=='PASS'
 assert json.loads((OUT/'INGESTION.json').read_text())['status']=='PASS'
 for name in ['master.sqlite','mobile.sqlite','VERIFICATION.json','INGESTION.json','ADDRESS_VARIANT_LEDGER.sqlite','ADDRESS_COVERAGE.json']:
  path=OUT/name
  if path.exists():
   copy=path.with_name(path.stem+'-before-name-extension'+path.suffix);assert not copy.exists();shutil.copy2(path,copy)
 master=sqlite3.connect(OUT/'master.sqlite');phone=sqlite3.connect(OUT/'mobile.sqlite');new=0;new_objects=set()
 for oid,tags_s,payload in master.execute("SELECT oid,tags,payload FROM objects WHERE source='OSM' AND tags LIKE '%name%'").fetchall():
  tags=json.loads(tags_s);body=json.loads(payload);existing=set(master.execute('SELECT role,text FROM aliases WHERE oid=?',(oid,)))
  for role,text in search_texts(tags):
   if (role,text) in existing:continue
   provenance=dict(source_object=oid,source_version=body['version'])
   if body.get('source_snapshot'):provenance['supplement_revision']=body['source_snapshot']['revision']
   aid=ident(oid,role,text,provenance);alias(master,oid,role,text,provenance)
   phone.execute('INSERT INTO aliases VALUES(?,?,?,?,?)',(aid,oid,role,text,js(provenance)))
   key=normalize(text)
   if not key:
    phone.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('alias',aid,'OSM','EXCLUDED_WITH_REASON','EMPTY_OR_NON_ALPHANUMERIC_SEARCH_TEXT_RETAINED_AS_ALIAS_DETAIL'));continue
   points=master.execute('SELECT * FROM points WHERE oid=? ORDER BY pid',(oid,)).fetchall()
   for point in (points or [None]):
    pid=point[0] if point else None;cid=ident('candidate',oid,pid if pid else 'UNKNOWN_LOCATION')
    known=point is not None and point[2] is not None and point[3] is not None
    phone.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?)',(cid,oid,pid,'SOURCE_COORDINATE' if known else 'UNKNOWN_LOCATION','UNASSESSED_GEO2_NO_RESOLVE1'))
    phone.execute('INSERT OR IGNORE INTO coverage VALUES(?,?,?,?,?)',('candidate',cid,'OSM','INDEXED','INDEPENDENT_POINT_OR_EXPLICIT_UNKNOWN_LOCATION'))
    phone.execute('INSERT OR IGNORE INTO postings VALUES(?,?)',(key,cid));phone.execute('INSERT INTO alias_candidates VALUES(?,?)',(aid,cid))
   phone.execute("UPDATE coverage SET disposition='INDEXED',reason='SEARCHABLE_SOURCE_TEXT' WHERE unit_type IN('object','poi') AND unit_id=?",(oid,))
   phone.execute("UPDATE coverage SET disposition='INDEXED',reason='SEARCHABLE_SOURCE_TEXT' WHERE unit_type='point' AND unit_id IN(SELECT pid FROM points WHERE oid=?)",(oid,))
   phone.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('alias',aid,'OSM','INDEXED','ALL_ALIAS_CANDIDATE_POSTINGS_PRESENT'))
   new+=1;new_objects.add(oid)
 policy=sha(Path(__file__).with_name('INCLUSION_POLICY.json'));master.execute("UPDATE meta SET value=? WHERE key='policy'",(policy,));master.commit();master.close()
 revision=sha(OUT/'master.sqlite');phone.execute("UPDATE meta SET value=? WHERE key='policy'",(policy,));phone.execute("UPDATE meta SET value=? WHERE key='package_revision'",(revision,));phone.commit();phone.close()
 dump(OUT/'MASTER_COMPLETE.json',dict(sha256=revision,policy=policy,extended_names=True))
 dump(OUT/'MOBILE_COMPLETE.json',dict(schema='GEO2_MOBILE_1',revision=revision,sha256=sha(OUT/'mobile.sqlite'),bytes=(OUT/'mobile.sqlite').stat().st_size,automatic_activation_allowed=False))
 # Full address-variant proof is recreated on final bytes; old ledger stays available.
 ledger=OUT/'ADDRESS_VARIANT_LEDGER.sqlite'
 if ledger.exists():ledger.rename(OUT/'ADDRESS_VARIANT_LEDGER-before-final-proof.sqlite')
 dump(OUT/'NAME_EXTENSION.json',dict(status='APPLIED_REQUIRES_FINAL_INDEPENDENT_PROOF',added_search_aliases=new,source_objects=len(new_objects),policy='GEO2_SEARCH_COVERAGE_V2',
  reason='Independent raw-name tag inventory found real full/local/regional/historical/bridge/seamark name fields missing from V1 postings; source objects and source data unchanged'))
 print('Extended searchable names',new,'on',len(new_objects),'source objects',flush=True)

if __name__=='__main__':run()
