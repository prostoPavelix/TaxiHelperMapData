"""Build isolated GEO2 master/mobile bytes. No app/phone/source mutation.
Master keeps scoped OSM originals, independent Visicom semantic evidence and raw references.
Phone is a self-contained semantic projection, not an online/raw-archive-dependent reader.
"""
from common import *
import osmium,collections,time,zlib,struct,xml.etree.ElementTree as ET
from shapely.geometry import Point,shape
from shapely.strtree import STRtree

SCHEMA='''
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE objects(oid TEXT PRIMARY KEY,source TEXT NOT NULL,kind TEXT NOT NULL,tags TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE members(parent TEXT NOT NULL,ordinal INTEGER NOT NULL,child TEXT NOT NULL,role TEXT NOT NULL,PRIMARY KEY(parent,ordinal));
CREATE INDEX member_child ON members(child);
CREATE TABLE aliases(aid TEXT PRIMARY KEY,oid TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,provenance TEXT NOT NULL);
CREATE INDEX alias_object ON aliases(oid);
CREATE TABLE points(pid TEXT PRIMARY KEY,oid TEXT NOT NULL,latitude REAL,longitude REAL,role TEXT NOT NULL,weight REAL,locality TEXT NOT NULL,sector TEXT);
CREATE INDEX point_object ON points(oid);
CREATE TABLE observations(obsid TEXT PRIMARY KEY,oid TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX observation_object ON observations(oid);
CREATE TABLE links(lid TEXT PRIMARY KEY,oid TEXT NOT NULL,target TEXT NOT NULL,role TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX links_object ON links(oid);
CREATE TABLE geometry(oid TEXT PRIMARY KEY,payload TEXT,status TEXT NOT NULL);
'''
MOBILE='''
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE details(oid TEXT PRIMARY KEY,source TEXT NOT NULL,kind TEXT NOT NULL,payload BLOB NOT NULL);
CREATE TABLE aliases(aid TEXT PRIMARY KEY,oid TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,provenance TEXT NOT NULL);
CREATE INDEX alias_object ON aliases(oid);
CREATE TABLE points(pid TEXT PRIMARY KEY,oid TEXT NOT NULL,latitude REAL,longitude REAL,role TEXT NOT NULL,weight REAL,locality TEXT NOT NULL,sector TEXT);
CREATE INDEX point_object ON points(oid);
CREATE TABLE candidates(cid TEXT PRIMARY KEY,oid TEXT NOT NULL,pid TEXT,location_status TEXT NOT NULL,automatic_eligibility TEXT NOT NULL);
CREATE INDEX candidate_object ON candidates(oid);
CREATE TABLE postings(lookup_key TEXT NOT NULL,cid TEXT NOT NULL,PRIMARY KEY(lookup_key,cid)) WITHOUT ROWID;
CREATE TABLE alias_candidates(aid TEXT NOT NULL,cid TEXT NOT NULL,PRIMARY KEY(aid,cid)) WITHOUT ROWID;
CREATE TABLE members(parent TEXT NOT NULL,ordinal INTEGER NOT NULL,child TEXT NOT NULL,role TEXT NOT NULL,PRIMARY KEY(parent,ordinal));
CREATE INDEX member_child ON members(child);
CREATE TABLE geometry(oid TEXT PRIMARY KEY,payload BLOB,status TEXT NOT NULL);
CREATE TABLE observations(obsid TEXT PRIMARY KEY,oid TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX observation_object ON observations(oid);
CREATE TABLE links(lid TEXT PRIMARY KEY,oid TEXT NOT NULL,target TEXT NOT NULL,role TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX links_object ON links(oid);
CREATE TABLE coverage(unit_type TEXT NOT NULL,unit_id TEXT NOT NULL,source TEXT NOT NULL,disposition TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(unit_type,unit_id));
'''

def ident(*parts):return hashlib.sha256(js(parts).encode()).hexdigest()
def alias(db,oid,role,text,provenance):
 if not isinstance(text,str):raise ValueError('ALIAS_NOT_TEXT')
 aid=ident(oid,role,text,provenance)
 db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?,?,?,?)',(aid,oid,role,text,js(provenance)))
def is_poi(tags,kind):return kind=='POI' or any(k in tags for k in ['amenity','shop','tourism','leisure','office','craft','healthcare','historic','entrance'])

def build_master():
 if (OUT/'MASTER_COMPLETE.json').exists():
  saved=json.loads((OUT/'MASTER_COMPLETE.json').read_text(encoding='utf-8'));assert sha(OUT/'master.sqlite')==saved['sha256'],'MASTER_CHECKPOINT_HASH_MISMATCH'
  with ro(OUT/'master.sqlite') as checked:assert checked.execute("SELECT value FROM meta WHERE key='policy'").fetchone()[0]==sha(Path(__file__).with_name('INCLUSION_POLICY.json')),'MASTER_POLICY_REVISION_CHANGED'
  return
 stage=OUT/f'master-building-{time.time_ns()}.sqlite';db=sqlite3.connect(stage);db.executescript(SCHEMA)
 extract=OUT/'selected.osm.pbf';counts=collections.Counter()
 sourceproof=json.loads((OUT/'EXTRACTION.json').read_text(encoding='utf-8'))
 for k,v in dict(schema='GEO2_MASTER_1',osm=sourceproof['source_sha256'],visicom=sha(MERGED),policy=sha(Path(__file__).with_name('INCLUSION_POLICY.json'))).items():db.execute('INSERT INTO meta VALUES(?,?)',(k,v))
 def add(o,typ,members=None):
  oid=f'OSM:{typ}:{o.id}';tags=dict(o.tags)
  body=dict(id=o.id,type=typ,version=o.version,timestamp=str(o.timestamp),tags=tags,visible=o.visible)
  if typ=='n':
   body['coordinate']=[o.lat,o.lon] if o.location.valid() else None
  else:
   body['members']=members
   for ordinal,(child,role) in enumerate(members):db.execute('INSERT INTO members VALUES(?,?,?,?)',(oid,ordinal,child,role))
  db.execute('INSERT INTO objects VALUES(?,?,?,?,?)',(oid,'OSM',typ,js(tags),js(body)))
  for role,text in search_texts(tags):alias(db,oid,role,text,dict(source_object=oid,source_version=o.version))
  if typ=='n':
   db.execute('INSERT INTO points VALUES(?,?,?,?,?,?,?,?)',(oid+':point',oid,o.lat if o.location.valid() else None,o.lon if o.location.valid() else None,'SOURCE_NODE',None,js(dict(source=tags.get('addr:city'),derived=None,status='NOT_CLASSIFIED')),None))
  counts[typ]+=1
 class Import(osmium.SimpleHandler):
  def node(self,n):add(n,'n')
  def way(self,w):add(w,'w',[(f'OSM:n:{n.ref}','') for n in w.nodes])
  def relation(self,r):add(r,'r',[(f'OSM:{m.type}:{m.ref}',m.role) for m in r.members])
 Import().apply_file(str(extract));db.commit();print('OSM master imported',dict(counts),flush=True)
 # Original member refs and source tags are retained; geometry is separate and versioned.
 coords={pid[:-6]:(lon,lat) for pid,lat,lon in db.execute("SELECT pid,latitude,longitude FROM points WHERE latitude IS NOT NULL")}
 for (oid,) in db.execute("SELECT oid FROM objects WHERE kind='w'").fetchall():
  children=[r[0] for r in db.execute('SELECT child FROM members WHERE parent=? ORDER BY ordinal',(oid,))]
  ps=[coords[c] for c in children if c in coords]
  complete=len(ps)==len(children)
  geometry=dict(type='Polygon',coordinates=[ps]) if complete and len(ps)>=4 and ps[0]==ps[-1] else dict(type='LineString',coordinates=ps)
  db.execute('INSERT INTO geometry VALUES(?,?,?)',(oid,js(geometry) if complete and len(ps)>=2 else None,'COMPLETE' if complete and len(ps)>=2 else 'INCOMPLETE_OR_DEGENERATE'))
 # Reuse reviewed recursion with exact nested inner/outer role parity for polygon relations.
 sys.path.insert(0,str(ROOT/'taxihelper2_workspace/tools/locality_probe'))
 from analyze import assemble
 elements={}
 for oid,payload in db.execute("SELECT oid,payload FROM objects WHERE kind='r'"):
  b=json.loads(payload);e=ET.Element('relation',id=str(b['id']),version=str(b['version']))
  for child,role in b['members']:
   _,typ,sid=child.split(':');ET.SubElement(e,'member',type={'n':'node','w':'way','r':'relation'}[typ],ref=sid,role=role)
  elements['relation',str(b['id'])]=e
 for oid,payload in db.execute("SELECT oid,payload FROM objects WHERE kind='w'"):
  b=json.loads(payload);e=ET.Element('way',id=str(b['id']))
  for child,role in b['members']:ET.SubElement(e,'nd',ref=child.split(':')[-1])
  elements['way',str(b['id'])]=e
 for oid,(lon,lat) in coords.items():elements['node',oid.split(':')[-1]]=ET.Element('node',id=oid.split(':')[-1],lat=str(lat),lon=str(lon))
 relation_geometry=[];localities=[]
 for oid,tags_s in db.execute("SELECT oid,tags FROM objects WHERE kind='r'").fetchall():
  tags=json.loads(tags_s)
  if tags.get('type') not in ['multipolygon','boundary'] and tags.get('boundary') is None:continue
  try:
   ps=assemble(elements,oid.split(':')[-1]);geom=dict(type='MultiPolygon',coordinates=ps)
   valid=shape(geom).is_valid
   status='COMPLETE' if valid else 'COMPLETE_INVALID_TOPOLOGY'
   db.execute('INSERT INTO geometry VALUES(?,?,?)',(oid,js(geom),status))
   relation_geometry.append(dict(oid=oid,status=status,polygons=len(ps),holes=sum(len(p)-1 for p in ps)))
   if tags.get('place') in ['city','town','village','hamlet'] and valid:localities.append((oid,shape(geom)))
  except (KeyError,ValueError,RecursionError) as error:
   reason=str(error);db.execute('INSERT INTO geometry VALUES(?,?,?)',(oid,None,'UNRESOLVED:'+reason))
   relation_geometry.append(dict(oid=oid,status='UNRESOLVED',reason=reason))
 db.commit();print('Recursive relation geometry',len(relation_geometry), 'settlements',len(localities),flush=True)
 # Preserve independent Visicom source objects, every observed label and retained hypothesis.
 source_localities={}
 with ro(ADDR2) as old,ro(MERGED) as merged:
  for oid,source,sid,payload in old.execute("SELECT object_id,source,source_id,payload_json FROM objects WHERE source!='OSM' ORDER BY object_id"):
   body=json.loads(payload);kind=body.get('kind','RAW_ONLY')
   db.execute('INSERT INTO objects VALUES(?,?,?,?,?)',(oid,source,kind,'{}',payload))
   if body.get('label'):alias(db,oid,'VISICOM_MERGED_LABEL',body['label'],dict(source_revision=sha_cached_visicom()))
  for oid,text,provenance in old.execute("SELECT v.object_id,v.label,v.provenance_json FROM variants v JOIN objects o ON o.object_id=v.object_id WHERE o.source!='OSM'"):
   alias(db,oid,'VISICOM_PRESERVED_VARIANT',text,dict(original=json.loads(provenance)))
  for payload, in old.execute("SELECT c.payload_json FROM candidates c JOIN objects o ON o.object_id=c.object_id WHERE o.source!='OSM'"):
   body=json.loads(payload)
   source_localities[body['object_id']]=body.get('locality_source')
   for text in body.get('aliases',[]):alias(db,body['object_id'],'ADDR2_RETAINED_ALIAS_HYPOTHESIS',text,dict(original_revision='ADDR2',not_newly_confirmed=True))
  columns=[r[1] for r in merged.execute('PRAGMA table_info(observations)')]
  for row in merged.execute('SELECT * FROM observations ORDER BY source_id,cell_id,source_file'):
   body=dict(zip(columns,row));oid='VISICOM:'+body['source_id'];obsid=ident(body)
   db.execute('INSERT INTO observations VALUES(?,?,?)',(obsid,oid,js(body)))
   pid=ident(oid,body['latitude'],body['longitude'],'VISICOM_SOURCE_POINT')
   db.execute('INSERT OR IGNORE INTO points VALUES(?,?,?,?,?,?,?,?)',(pid,oid,body['latitude'],body['longitude'],'PIXEL_DERIVED_SOURCE',None,js(dict(source=source_localities.get(oid),derived=None,status='NOT_CLASSIFIED')),None))
   if body.get('label'):alias(db,oid,'VISICOM_OBSERVED_LABEL',body['label'],dict(observation=obsid))
  # Raw-only records have semantic text/pixel provenance locally, no fabricated global coordinates.
  for rid,sid,payload in old.execute('SELECT record_id,source_id,payload_json FROM raw_records'):
   oid=('VISICOM:'+sid) if db.execute('SELECT 1 FROM objects WHERE oid=?',('VISICOM:'+sid,)).fetchone() else 'RAW_ONLY:'+sid
   # Raw observations stay independent of normalized source points; IDs always trace back.
   db.execute('INSERT INTO observations VALUES(?,?,?)',('RAW:'+rid,oid,payload))
  for lid,oid,target,role,payload in old.execute("SELECT e.edge_id,e.from_id,e.to_id,e.type,e.payload_json FROM edges e"):
   if db.execute('SELECT 1 FROM objects WHERE oid=?',(oid,)).fetchone():
    db.execute('INSERT INTO links VALUES(?,?,?,?,?)',('ADDR2:'+str(lid),oid,target,'STALE_OSM_LINK_NOT_CURRENT:'+role,payload))
 # Source/derived locality remain separate; no100m circle or forced default.
 if localities:
  tree=STRtree([g for oid,g in localities])
  for pid,lat,lon,loc in db.execute('SELECT pid,latitude,longitude,locality FROM points').fetchall():
   if lat is None or lon is None:continue
   point=Point(lon,lat);indices=tree.query(point);hits=[localities[int(i)][0] for i in indices if localities[int(i)][1].contains(point)]
   touch=any(localities[int(i)][1].boundary.intersects(point) for i in indices)
   state=json.loads(loc);state.update(derived=hits[0] if len(hits)==1 and not touch else None,alternatives=sorted(hits),status='RESOLVED_COORDINATE_MEMBERSHIP' if len(hits)==1 and not touch else 'REVIEW_OVERLAP_OR_BOUNDARY' if hits or touch else 'UNKNOWN_LOCALITY',geometry_revision=sourceproof['source_sha256'])
   db.execute('UPDATE points SET locality=? WHERE pid=?',(js(state),pid))
 # No geometric sector inference is silently applied; retain frozen passport and purpose limits.
 for key,value in [('frozenSectorRevision','19a75b5a16f708c400cefafe8189519936a5545e73142bb8bd834bf065a9709e'),('gridRevision','v2-local-metric-350m-v1'),('automaticEligibility','UNASSESSED_GEO2_NO_RESOLVE1')]:db.execute('INSERT INTO meta VALUES(?,?)',(key,value))
 db.commit()
 missing=db.execute('SELECT COUNT(*) FROM members m LEFT JOIN objects o ON o.oid=m.child WHERE o.oid IS NULL').fetchone()[0]
 missing_local_way_nodes=db.execute("SELECT COUNT(*) FROM members m LEFT JOIN objects o ON o.oid=m.child WHERE o.oid IS NULL AND m.parent LIKE 'OSM:w:%'").fetchone()[0]
 missing_rows=db.execute('SELECT m.parent,m.child,m.role FROM members m LEFT JOIN objects o ON o.oid=m.child WHERE o.oid IS NULL LIMIT 200').fetchall()
 roots=['OSM:r:'+str(n) for n in sourceproof['root_settlements']]
 root_status={oid:db.execute('SELECT status FROM geometry WHERE oid=?',(oid,)).fetchone() for oid in roots}
 graph={oid:[row[0] for row in db.execute("SELECT child FROM members WHERE parent=? AND child LIKE 'OSM:r:%'",(oid,))] for oid, in db.execute("SELECT oid FROM objects WHERE kind='r'").fetchall()}
 visiting=set();done=set();cycles=[]
 def walk(node,path):
  if node in visiting:cycles.append(path+[node]);return
  if node in done:return
  visiting.add(node)
  for child in graph.get(node,[]):walk(child,path+[node])
  visiting.remove(node);done.add(node)
 for node in graph:walk(node,[])
 report=dict(reference_missing_count=missing,missing_way_nodes=missing_local_way_nodes,missing_examples=missing_rows,required_settlements=root_status,relation_geometry=relation_geometry,source_version_conflicts=0,relation_cycles=cycles)
 dump(OUT/'CLOSURE_PRIVATE.json',report)
 db.execute('PRAGMA optimize');db.close();stage.rename(OUT/'master.sqlite')
 dump(OUT/'MASTER_COMPLETE.json',dict(sha256=sha(OUT/'master.sqlite'),objects=dict(counts),scope='AOI-scoped catalog plus dependency closure; full dated Ukraine PBF independently retained',closure='CLOSURE_PRIVATE.json'))
 print('Master complete',flush=True)

_visicom_sha=None
def sha_cached_visicom():
 global _visicom_sha
 if _visicom_sha is None:_visicom_sha=sha(MERGED)
 return _visicom_sha

def export_mobile(master_path=None,destination=None):
 master_path=master_path or OUT/'master.sqlite';destination=destination or OUT/'mobile.sqlite'
 assert not destination.exists(),destination
 db=sqlite3.connect(destination);db.executescript(MOBILE)
 with ro(master_path) as src:
  for row in src.execute('SELECT * FROM meta ORDER BY key'):db.execute('INSERT INTO meta VALUES(?,?)',row)
  revision=sha(master_path);db.execute('INSERT INTO meta VALUES(?,?)',('package_revision',revision))
  for oid,source,kind,tags,payload in src.execute('SELECT * FROM objects ORDER BY oid'):
   db.execute('INSERT INTO details VALUES(?,?,?,?)',(oid,source,kind,zlib.compress(payload.encode(),6)))
   aliases=list(src.execute('SELECT aid,oid,role,text,provenance FROM aliases WHERE oid=? ORDER BY aid',(oid,)))
   points=list(src.execute('SELECT * FROM points WHERE oid=? ORDER BY pid',(oid,)))
   usable=[a for a in aliases if normalize(a[3])]
   status='INDEXED' if usable else 'LOCAL_DETAIL_ONLY';reason='SEARCHABLE_SOURCE_TEXT' if usable else 'STRUCTURAL_OR_UNNAMED_CONTEXT_WITH_LOCAL_DETAIL'
   db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('object',oid,source,status,reason))
   if is_poi(json.loads(tags),kind):db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('poi',oid,source,status,reason))
   for row in points:
    db.execute('INSERT INTO points VALUES(?,?,?,?,?,?,?,?)',row)
    db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('point',row[0],source,status,reason))
   cids=[]
   if usable:
    for point in (points or [None]):
     cid=ident('candidate',oid,point[0] if point else 'UNKNOWN_LOCATION');cids.append(cid)
     known=point is not None and point[2] is not None and point[3] is not None
     db.execute('INSERT INTO candidates VALUES(?,?,?,?,?)',(cid,oid,point[0] if point else None,'SOURCE_COORDINATE' if known else 'UNKNOWN_LOCATION','UNASSESSED_GEO2_NO_RESOLVE1'))
     db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('candidate',cid,source,'INDEXED','INDEPENDENT_POINT_OR_EXPLICIT_UNKNOWN_LOCATION'))
   for row in aliases:
    aid,_,role,text,prov=row;db.execute('INSERT INTO aliases VALUES(?,?,?,?,?)',row)
    if not normalize(text):
     db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('alias',aid,source,'EXCLUDED_WITH_REASON','EMPTY_OR_NON_ALPHANUMERIC_SEARCH_TEXT_RETAINED_AS_ALIAS_DETAIL'))
     if role.startswith(('addr:','structured_address')):db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('address_variant',aid,source,'EXCLUDED_WITH_REASON','EMPTY_OR_NON_ALPHANUMERIC_SEARCH_TEXT_RETAINED_AS_ALIAS_DETAIL'))
     continue
    db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('alias',aid,source,'INDEXED','ALL_ALIAS_CANDIDATE_POSTINGS_PRESENT'))
    if role.startswith('addr:') or role.startswith('structured_address'):db.execute('INSERT INTO coverage VALUES(?,?,?,?,?)',('address_variant',aid,source,'INDEXED','ADDRESS_TEXT_LOCAL_AND_SEARCHABLE'))
    for cid in cids:
     db.execute('INSERT OR IGNORE INTO postings VALUES(?,?)',(normalize(text),cid));db.execute('INSERT INTO alias_candidates VALUES(?,?)',(aid,cid))
  for table,cols in [('members',4),('observations',3),('links',5)]:
   db.executemany('INSERT INTO '+table+' VALUES('+','.join('?'*cols)+')',src.execute('SELECT * FROM '+table))
  for oid,payload,status in src.execute('SELECT * FROM geometry'):
   db.execute('INSERT INTO geometry VALUES(?,?,?)',(oid,zlib.compress(payload.encode(),6) if payload else None,status))
 db.commit();assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok';db.close()
 return revision

def run():
 started=time.perf_counter();build_master()
 if not (OUT/'MOBILE_COMPLETE.json').exists():
  stage=OUT/f'mobile-building-{time.time_ns()}.sqlite';revision=export_mobile(destination=stage);stage.rename(OUT/'mobile.sqlite')
  dump(OUT/'MOBILE_COMPLETE.json',dict(schema='GEO2_MOBILE_1',revision=revision,sha256=sha(OUT/'mobile.sqlite'),bytes=(OUT/'mobile.sqlite').stat().st_size,automatic_activation_allowed=False,seconds=time.perf_counter()-started))
 print('Mobile complete',flush=True)

if __name__=='__main__':run()
