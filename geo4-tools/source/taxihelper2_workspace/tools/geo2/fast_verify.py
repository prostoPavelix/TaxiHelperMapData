"""Set-based independent projection proof; same contract without millions of Python DB calls.
RAM here is PC verification workspace, never the disk reader implementation.
"""
from common import ro,sha
from reader import DiskReader
import sqlite3,zlib,collections

def prove(master,mobile,keyfn,idfn,all_keys=True):
 db=sqlite3.connect(':memory:',uri=True);db.execute('PRAGMA temp_store=MEMORY')
 db.execute('ATTACH DATABASE ? AS md',(master.resolve().as_uri()+'?mode=ro',));db.execute('ATTACH DATABASE ? AS pd',(mobile.resolve().as_uri()+'?mode=ro',))
 db.create_function('nkey',1,keyfn,deterministic=True);db.create_function('candidate_id',2,idfn,deterministic=True)
 def decode(value):
  if value is None:return None
  try:return zlib.decompress(value).decode('utf-8')
  except Exception:return '__INVALID_LOCAL_COMPRESSED_PAYLOAD__'
 db.create_function('unzip',1,decode)
 db.executescript('''
 CREATE TABLE indexed_objects(oid TEXT PRIMARY KEY);
 INSERT INTO indexed_objects SELECT DISTINCT oid FROM md.aliases WHERE nkey(text)!='';
 CREATE TABLE candidates(cid TEXT PRIMARY KEY,oid TEXT,pid TEXT,location_status TEXT,automatic_eligibility TEXT);
 INSERT INTO candidates SELECT candidate_id(i.oid,p.pid),i.oid,p.pid,
 CASE WHEN p.pid IS NOT NULL AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL THEN 'SOURCE_COORDINATE' ELSE 'UNKNOWN_LOCATION' END,
 'UNASSESSED_GEO2_NO_RESOLVE1' FROM indexed_objects i LEFT JOIN md.points p ON p.oid=i.oid;
 CREATE INDEX candidate_object ON candidates(oid);
 CREATE TABLE postings(k TEXT,cid TEXT,PRIMARY KEY(k,cid)) WITHOUT ROWID;
 INSERT OR IGNORE INTO postings SELECT nkey(a.text),c.cid FROM md.aliases a JOIN candidates c ON c.oid=a.oid WHERE nkey(a.text)!='';
 CREATE TABLE alias_candidates(aid TEXT,cid TEXT,PRIMARY KEY(aid,cid)) WITHOUT ROWID;
 INSERT INTO alias_candidates SELECT a.aid,c.cid FROM md.aliases a JOIN candidates c ON c.oid=a.oid WHERE nkey(a.text)!='';
 CREATE TABLE coverage(unit_type TEXT,unit_id TEXT,source TEXT,disposition TEXT,PRIMARY KEY(unit_type,unit_id));
 INSERT INTO coverage SELECT 'object',o.oid,o.source,CASE WHEN i.oid IS NOT NULL THEN 'INDEXED' ELSE 'LOCAL_DETAIL_ONLY' END FROM md.objects o LEFT JOIN indexed_objects i ON i.oid=o.oid;
 INSERT INTO coverage SELECT 'point',p.pid,o.source,CASE WHEN i.oid IS NOT NULL THEN 'INDEXED' ELSE 'LOCAL_DETAIL_ONLY' END FROM md.points p JOIN md.objects o ON o.oid=p.oid LEFT JOIN indexed_objects i ON i.oid=p.oid;
 INSERT INTO coverage SELECT 'alias',a.aid,o.source,CASE WHEN nkey(a.text)!='' THEN 'INDEXED' ELSE 'EXCLUDED_WITH_REASON' END FROM md.aliases a JOIN md.objects o ON o.oid=a.oid;
 INSERT INTO coverage SELECT 'address_variant',a.aid,o.source,CASE WHEN nkey(a.text)!='' THEN 'INDEXED' ELSE 'EXCLUDED_WITH_REASON' END FROM md.aliases a JOIN md.objects o ON o.oid=a.oid WHERE substr(a.role,1,5)='addr:' OR substr(a.role,1,18)='structured_address';
 INSERT INTO coverage SELECT 'candidate',c.cid,o.source,'INDEXED' FROM candidates c JOIN md.objects o ON o.oid=c.oid;
 INSERT INTO coverage SELECT 'poi',o.oid,o.source,CASE WHEN i.oid IS NOT NULL THEN 'INDEXED' ELSE 'LOCAL_DETAIL_ONLY' END FROM md.objects o LEFT JOIN indexed_objects i ON i.oid=o.oid WHERE o.kind='POI' OR
 json_type(o.tags,'$.amenity') IS NOT NULL OR json_type(o.tags,'$.shop') IS NOT NULL OR json_type(o.tags,'$.tourism') IS NOT NULL OR json_type(o.tags,'$.leisure') IS NOT NULL OR json_type(o.tags,'$.office') IS NOT NULL OR json_type(o.tags,'$.craft') IS NOT NULL OR json_type(o.tags,'$.healthcare') IS NOT NULL OR json_type(o.tags,'$.historic') IS NOT NULL OR json_type(o.tags,'$.entrance') IS NOT NULL;
 ''')
 errors=collections.Counter()
 def different(label,left,right):
  for suffix,a,b in [('missing_or_mismatch',left,right),('extra_or_mismatch',right,left)]:
   n=db.execute('SELECT COUNT(*) FROM('+a+' EXCEPT '+b+')').fetchone()[0]
   if n:errors[label+'_'+suffix]+=n
 for table,columns in [('aliases','aid,oid,role,text,provenance'),('points','pid,oid,latitude,longitude,role,weight,locality,sector'),('observations','obsid,oid,payload'),('members','parent,ordinal,child,role'),('links','lid,oid,target,role,payload')]:different(table,'SELECT '+columns+' FROM md.'+table,'SELECT '+columns+' FROM pd.'+table)
 different('details','SELECT oid,source,kind,payload FROM md.objects','SELECT oid,source,kind,unzip(payload) FROM pd.details')
 different('geometry','SELECT oid,payload,status FROM md.geometry','SELECT oid,unzip(payload),status FROM pd.geometry')
 for table,cols,other in [('candidates','cid,oid,pid,location_status,automatic_eligibility','cid,oid,pid,location_status,automatic_eligibility'),('postings','k,cid','lookup_key,cid'),('alias_candidates','aid,cid','aid,cid'),('coverage','unit_type,unit_id,source,disposition','unit_type,unit_id,source,disposition')]:different(table,'SELECT '+cols+' FROM main.'+table,'SELECT '+other+' FROM pd.'+table)
 different('metadata','SELECT key,value FROM md.meta',"SELECT key,value FROM pd.meta WHERE key!='package_revision'")
 if db.execute("SELECT value FROM pd.meta WHERE key='package_revision'").fetchone()[0]!=sha(master):errors['package_revision_mismatch']+=1
 bad=db.execute("SELECT COUNT(*) FROM pd.coverage WHERE reason='' OR disposition='UNEXPLAINED'").fetchone()[0]
 if bad:errors['unexplained_or_empty_reason']+=bad
 source=collections.defaultdict(collections.Counter);units=[]
 for typ,src,state,count in db.execute('SELECT unit_type,source,disposition,COUNT(*) FROM main.coverage GROUP BY unit_type,source,disposition ORDER BY unit_type,source,disposition'):
  units.append(dict(unit_type=typ,source=src,disposition=state,count=count));c=source[src]
  if typ=='object':c['objects_total']+=count;c['objects_searchable' if state=='INDEXED' else 'objects_detail_only']+=count
  if typ=='point':c['source_points_total']+=count;c['source_points_searchable']+=count if state=='INDEXED' else 0
  if typ=='alias':c['aliases_total']+=count;c['aliases_searchable']+=count if state=='INDEXED' else 0
  if typ=='poi':c['poi_total']+=count;c['poi_searchable']+=count if state=='INDEXED' else 0
  if typ=='address_variant':c['address_variants_searchable']+=count if state=='INDEXED' else 0
 for src,c in source.items():
  c['unknown_location_candidates']=db.execute('SELECT COUNT(*) FROM candidates c JOIN md.objects o ON o.oid=c.oid WHERE o.source=? AND c.pid IS NULL',(src,)).fetchone()[0]
  for k in ['objects_total','objects_searchable','objects_detail_only','source_points_total','source_points_searchable','aliases_total','aliases_searchable','poi_total','poi_searchable','address_variants_searchable']:c.setdefault(k,0)
 api=DiskReader(mobile);pages=keys=retrieved=maximum=0
 if all_keys:
  for key, in db.execute('SELECT DISTINCT k FROM postings ORDER BY k'):
   expected=[r[0] for r in db.execute('SELECT cid FROM postings WHERE k=? ORDER BY cid',(key,))];got=[];cursor=None;steps=0
   while True:
    r=api.lookup(key,cursor=cursor);pages+=1;steps+=1;got.extend(x['cid'] for x in r['candidates'])
    if not r['has_more']:break
    if not r['continuation'] or r['continuation']==cursor:errors['api_nonprogressing_cursor']+=1;break
    cursor=r['continuation']
   if got!=expected:errors['api_full_key_candidate_set_mismatch']+=1
   keys+=1;retrieved+=len(got);maximum=max(maximum,steps)
 api.close()
 if db.execute('PRAGMA pd.quick_check').fetchone()[0]!='ok':errors['sqlite_quick_check']+=1
 result=dict(status='PASS' if not errors else 'FAIL',errors=dict(errors),sources={k:dict(v) for k,v in source.items()},coverage_units=units,
  actual_api=dict(all_distinct_keys_checked=keys,pages=pages,postings_retrieved=retrieved,max_pages_one_key=maximum,page_limit=128),
  expected={t:db.execute('SELECT COUNT(*) FROM main.'+t).fetchone()[0] for t in ['candidates','postings','alias_candidates']},unexplained_omissions=0 if not errors else None,
  method='Independent SQL expected projection from master; separately implemented normalization; bidirectional exact value/set comparisons including decompressed local payloads; every final key/all actual API pages; exporter ledger is not truth')
 db.close();return result
