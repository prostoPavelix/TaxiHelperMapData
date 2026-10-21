"""Independent master-to-mobile verifier; does not consume exporter coverage ledger as truth.
Derives expected candidates/postings from master originals using independent normalization.
Traverses every key with actual disk API and compares complete sets, not just row counts.
"""
from common import ROOT,OUT,PUBLIC,ro,js,dump,sha
from reader import DiskReader
import sqlite3,json,zlib,hashlib,unicodedata,re,time,collections

def independent_key(text):
 return ' '.join(re.sub(r'[\W_]+',' ',unicodedata.normalize('NFKC',text).casefold(),flags=re.UNICODE).split())
def candidate_id(oid,pid):
 serialized=json.dumps(['candidate',oid,pid if pid else 'UNKNOWN_LOCATION'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
 return hashlib.sha256(serialized.encode()).hexdigest()


def audit(master,mobile,check_all_keys=True):
 from fast_verify import prove
 return prove(master,mobile,independent_key,candidate_id,check_all_keys)

def ingestion_audit(master):
 """Independent all-OSM-tag semantic check plus original-source identity/observation sets."""
 m=ro(master);errors=collections.Counter();units=0
 for oid,tags_s in m.execute("SELECT oid,tags FROM objects WHERE source='OSM' AND tags!='{}'"):
  tags=json.loads(tags_s);want=[]
  for field,value in tags.items():
   extended_name=not field.startswith('source:') and any(token=='name' or token.endswith('_name') for token in field.split(':'))
   if extended_name or field=='name' or field.startswith(('name:','name_','alt_name','old_name','official_name','short_name','loc_name','int_name','addr:','brand:','operator:')) or field in ('brand','operator','ref','building:name','contact:street','contact:housenumber','contact:city','contact:postcode'):
    want.append((field,value))
    if ';' in value:
     want.extend((field+':semicolon_component',part.strip()) for part in value.split(';') if part.strip())
  road=tags.get('addr:street',tags.get('addr:place'))
  if road and tags.get('addr:housenumber'):
   full=road+' '+tags['addr:housenumber'];want.append(('structured_address',full))
   if tags.get('addr:city'):want.append(('structured_address_with_city',tags['addr:city']+', '+full))
  got=set(m.execute('SELECT role,text FROM aliases WHERE oid=?',(oid,)))
  if set(want)!=got:errors['OSM_source_tag_alias_ingestion_mismatch']+=1
  units+=len(set(want))
 # Revisit actual selected PBF originals, not compiler ledger.
 import osmium
 class SourceCheck(osmium.SimpleHandler):
  seen=collections.Counter()
  def check(self,o,t):
   oid=f'OSM:{t}:{o.id}';row=m.execute('SELECT payload FROM objects WHERE oid=?',(oid,)).fetchone();self.seen[t]+=1
   if not row:errors['raw_object_missing']+=1;return
   body=json.loads(row[0])
   if body['tags']!=dict(o.tags) or body['version']!=o.version or body['timestamp']!=str(o.timestamp):errors['raw_metadata_mismatch']+=1
   if t=='n' and o.location.valid() and body.get('coordinate')!=[o.lat,o.lon]:errors['raw_node_coordinate_mismatch']+=1
   if t=='w' and body.get('members')!=[[f'OSM:n:{n.ref}',''] for n in o.nodes]:errors['raw_way_order_mismatch']+=1
   if t=='r' and body.get('members')!=[[f'OSM:{x.type}:{x.ref}',x.role] for x in o.members]:errors['raw_relation_members_roles_mismatch']+=1
  def node(self,n):self.check(n,'n')
  def way(self,w):self.check(w,'w')
  def relation(self,r):self.check(r,'r')
 handler=SourceCheck();handler.apply_file(str(OUT/'selected.osm.pbf'))
 supplement_checked=0
 if (OUT/'SUPPLEMENT_COMPLETE.json').exists():
  import xml.etree.ElementTree as ET,datetime
  for path in (OUT/'supplement').glob('*-full.osm'):
   for element in ET.parse(path).getroot():
    if element.tag not in ['node','way','relation']:continue
    typ={'node':'n','way':'w','relation':'r'}[element.tag];oid='OSM:'+typ+':'+element.get('id')
    row=m.execute('SELECT payload FROM objects WHERE oid=?',(oid,)).fetchone();supplement_checked+=1
    if not row:errors['supplement_object_missing']+=1;continue
    body=json.loads(row[0]);tags={t.get('k'):t.get('v') for t in element.findall('tag')}
    timestamp=str(datetime.datetime.fromisoformat(element.get('timestamp').replace('Z','+00:00')))
    if body['version']!=int(element.get('version')) or body['timestamp']!=timestamp or body['tags']!=tags:errors['supplement_metadata_mismatch']+=1
    if typ=='n' and body.get('coordinate')!=[float(element.get('lat')),float(element.get('lon'))]:errors['supplement_coordinate_mismatch']+=1
    if typ=='w' and body.get('members')!=[['OSM:n:'+n.get('ref'),''] for n in element.findall('nd')]:errors['supplement_member_order_mismatch']+=1
    if typ=='r' and body.get('members')!=[['OSM:'+{'node':'n','way':'w','relation':'r'}[x.get('type')]+':'+x.get('ref'),x.get('role','')] for x in element.findall('member')]:errors['supplement_member_role_mismatch']+=1
 from common import ADDR2,MERGED
 with ro(ADDR2) as old:
  want=set(r[0] for r in old.execute("SELECT object_id FROM objects WHERE source!='OSM'"));got=set(r[0] for r in m.execute("SELECT oid FROM objects WHERE source!='OSM'"))
  if want!=got:errors['Visicom_object_identity_set_mismatch']+=1
  for oid,text, in old.execute("SELECT v.object_id,v.label FROM variants v JOIN objects o ON o.object_id=v.object_id WHERE o.source!='OSM'"):
   if text.strip() and not m.execute('SELECT 1 FROM aliases WHERE oid=? AND text=?',(oid,text)).fetchone():errors['Visicom_original_alias_missing']+=1
 with ro(MERGED) as raw:
  for sid,lat,lon in raw.execute('SELECT DISTINCT source_id,latitude,longitude FROM observations'):
   if not m.execute('SELECT 1 FROM points WHERE oid=? AND latitude=? AND longitude=?',('VISICOM:'+sid,lat,lon)).fetchone():errors['Visicom_independent_point_missing']+=1
 m.close();return dict(status='PASS' if not errors else 'FAIL',errors=dict(errors),raw_osm_objects_checked=dict(handler.seen),supplement_objects_checked=supplement_checked,osm_tag_alias_units_checked=units,visicom_object_set_checked=len(want),scope='All selected PBF originals, separately versioned supplement and all preserved Visicom IDs/observed variants/coordinate variants, not accuracy of source data')

def run():
 started=time.perf_counter();result=audit(OUT/'master.sqlite',OUT/'mobile.sqlite');dump(OUT/'VERIFICATION.json',result)
 ingestion=ingestion_audit(OUT/'master.sqlite');dump(OUT/'INGESTION.json',ingestion)
 print(js(dict(verification=result,ingestion=ingestion,seconds=time.perf_counter()-started)),flush=True)
 assert result['status']=='PASS' and ingestion['status']=='PASS'

if __name__=='__main__':run()
