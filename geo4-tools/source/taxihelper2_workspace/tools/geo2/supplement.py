"""Bounded separately versioned closure supplement, then append into a NEW PC candidate.
Only two missing Styr tributary roots and nine enumerated ways; no address harvest/source overwrite.
Run after build.py. Preserves the initial master/mobile candidates before replacement.
"""
from common import *
from build import alias,search_texts,export_mobile
import xml.etree.ElementTree as ET,datetime,shutil

def parsed(element):
 typ={'node':'n','way':'w','relation':'r'}[element.tag];oid=f'OSM:{typ}:{element.get("id")}'
 timestamp=str(datetime.datetime.fromisoformat(element.get('timestamp').replace('Z','+00:00')))
 body=dict(id=int(element.get('id')),type=typ,version=int(element.get('version')),timestamp=timestamp,tags={t.get('k'):t.get('v') for t in element.findall('tag')},visible=element.get('visible','true')=='true')
 if typ=='n':body['coordinate']=[float(element.get('lat')),float(element.get('lon'))]
 elif typ=='w':body['members']=[['OSM:n:'+x.get('ref'),''] for x in element.findall('nd')]
 else:body['members']=[['OSM:'+{'node':'n','way':'w','relation':'r'}[x.get('type')]+':'+x.get('ref'),x.get('role','')] for x in element.findall('member')]
 return oid,typ,body

def run():
 if (OUT/'SUPPLEMENT_COMPLETE.json').exists():return
 records=json.loads((OUT/'supplement/FETCH.json').read_text(encoding='utf-8'))
 group_file=OUT/'supplement/CAPTURE_GROUPS.json';groups={}
 if group_file.exists():
  captured=json.loads(group_file.read_text(encoding='utf-8'));assert captured['fetch_manifest_sha256']==sha(OUT/'supplement/FETCH.json')
  groups=captured['by_url']
 assert {r['id'] for r in records}=={8534720,8548313,555418233,563704826,563704852,549434033,549628757,334631925,549637942,545086211,364906228}
 for record in records:
  assert sha(OUT/f'supplement/{record.get("type","relation")}-{record["id"]}-full.osm')==record['sha256']
 base=OUT/'master.sqlite';oldmobile=OUT/'mobile.sqlite'
 initial_master=OUT/'master-before-supplement.sqlite';initial_mobile=OUT/'mobile-before-supplement.sqlite'
 if initial_master.exists() or initial_mobile.exists():
  assert initial_master.exists() and initial_mobile.exists()
  original=json.loads((OUT/'MASTER_COMPLETE.json').read_text(encoding='utf-8'))
  assert sha(initial_master)==original['sha256'],'ORIGINAL_MASTER_CHECKPOINT_MISMATCH'
 else:shutil.copy2(base,initial_master);shutil.copy2(oldmobile,initial_mobile)
 db=sqlite3.connect(base);added=[];reused=[];revision=hashlib.sha256(js(records).encode()).hexdigest()
 for record in records:
  for element in ET.parse(OUT/f'supplement/{record.get("type","relation")}-{record["id"]}-full.osm').getroot():
   if element.tag not in ['node','way','relation']:continue
   oid,typ,body=parsed(element);existing=db.execute('SELECT payload FROM objects WHERE oid=?',(oid,)).fetchone()
   if existing:
    previous=json.loads(existing[0]);assert all(previous.get(k)==body.get(k) for k in ['version','timestamp','tags','coordinate','members']),'SUPPLEMENT_OBJECT_VERSION_OR_PAYLOAD_CONFLICT:'+oid
    reused.append(oid);continue
   capture_revision=groups.get(record['url'],revision)
   body['source_snapshot']=dict(kind='BOUNDED_OSM_API_SUPPLEMENT',revision=capture_revision,url=record['url'],raw_sha256=record['sha256'],retrieved_utc=record['retrieved_utc'])
   tags=body['tags'];db.execute('INSERT INTO objects VALUES(?,?,?,?,?)',(oid,'OSM',typ,js(tags),js(body)))
   for role,text in search_texts(tags):alias(db,oid,role,text,dict(source_object=oid,source_version=body['version'],supplement_revision=capture_revision))
   if typ=='n':
    lat,lon=body['coordinate'];db.execute('INSERT INTO points VALUES(?,?,?,?,?,?,?,?)',(oid+':point',oid,lat,lon,'SOURCE_NODE',None,js(dict(source=tags.get('addr:city'),derived=None,status='UNKNOWN_LOCALITY',basis='DEPENDENCY_SUPPLEMENT_OUTSIDE_SELECTED_SETTLEMENT_GEOMETRY')),None))
   else:
    db.executemany('INSERT INTO members VALUES(?,?,?,?)',[(oid,i,child,role) for i,(child,role) in enumerate(body['members'])])
   added.append(oid)
 for oid in added:
  if not oid.startswith('OSM:w:'):continue
  ps=[]
  for child, in db.execute('SELECT child FROM members WHERE parent=? ORDER BY ordinal',(oid,)):
   row=db.execute('SELECT longitude,latitude FROM points WHERE oid=?',(child,)).fetchone();assert row is not None;ps.append(row)
  geometry=dict(type='Polygon',coordinates=[ps]) if len(ps)>=4 and ps[0]==ps[-1] else dict(type='LineString',coordinates=ps)
  db.execute('INSERT INTO geometry VALUES(?,?,?)',(oid,js(geometry),'COMPLETE'))
 db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('osm_supplement_revision',revision));db.commit()
 missing=db.execute('SELECT COUNT(*) FROM members m LEFT JOIN objects o ON o.oid=m.child WHERE o.oid IS NULL').fetchone()[0]
 assert missing==0,'SUPPLEMENT_STILL_INCOMPLETE'
 db.close()
 # Re-export from the augmented master; original candidates remain recoverable locally.
 stage=OUT/'mobile-with-supplement.sqlite';assert not stage.exists();export_mobile(destination=stage)
 stage.replace(oldmobile)
 closure=json.loads((OUT/'CLOSURE_PRIVATE.json').read_text(encoding='utf-8'));closure.update(reference_missing_count=0,missing_examples=[],supplement=dict(revision=revision,added=len(added),reused=len(reused),version_conflicts=0,roots=[8534720,8548313]))
 dump(OUT/'CLOSURE_PRIVATE.json',closure)
 dump(OUT/'MASTER_COMPLETE.json',dict(sha256=sha(base),supplement_revision=revision,original_candidate_retained=initial_master.name))
 dump(OUT/'MOBILE_COMPLETE.json',dict(schema='GEO2_MOBILE_1',revision=sha(base),sha256=sha(oldmobile),bytes=oldmobile.stat().st_size,automatic_activation_allowed=False,original_candidate_retained=initial_mobile.name))
 dump(OUT/'SUPPLEMENT_COMPLETE.json',dict(status='PASS_BOUNDED_SEPARATE_EPOCH_SOURCE',revision=revision,added_objects=len(added),reused_identical_objects=len(reused),version_conflicts=0,total_downloaded_bytes=sum(r['bytes'] for r in records),sources=records,missing_after=missing))
 print('Supplement complete',len(added),'new objects;',len(reused),'identical references; no missing dependencies',flush=True)

if __name__=='__main__':run()
