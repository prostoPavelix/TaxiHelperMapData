"""Separate locality probe: read immutable ADDR2, classify against newly fetched OSM settlement geometry.
No ADDR2/map/sector/manual-rule/resolver mutation. Results and address keys stay in isolated research output.
"""
from pathlib import Path
import sys,json,sqlite3,collections,hashlib,xml.etree.ElementTree as ET,time
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'taxihelper2_workspace/tools/addr2'))
from core import ShapeIndex,shape_state,join_rings,ring_state,EPS
OUT=ROOT/'MAP_OSM_Visicom/reports/locality_probe_20261015'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def assemble(elements,rid):
 def walk(ref,invert=False,trail=()):
  if ref in trail:raise ValueError('CYCLIC_RELATION')
  e=elements['relation',ref];parts={False:[],True:[]}
  for m in e.findall('member'):
   role=m.get('role','');typ=m.get('type');n=m.get('ref')
   if role not in ['','outer','inner']:continue
   inner=invert^(role=='inner')
   if typ=='way':
    way=elements['way',n];ids=[x.get('ref')for x in way.findall('nd')]
    if any(('node',i)not in elements for i in ids):raise ValueError('MISSING_NODE')
    parts[inner].append(ids)
   elif typ=='relation':
    child=walk(n,inner,trail+(ref,))
    for k,v in child.items():parts[k]+=v
  return parts
 parts=walk(str(rid));outer=join_rings(parts[False]);inner=join_rings(parts[True]);point=lambda n:(float(elements['node',n].get('lon')),float(elements['node',n].get('lat')))
 polygons=[[[point(n)for n in ring]]for ring in outer]
 if not polygons:raise ValueError('NO_OUTERS')
 for ids in inner:
  ring=[point(n)for n in ids];owners=[p for p in polygons if ring_state(p[0],(ring[0][1],ring[0][0]))[0]]
  if len(owners)!=1:raise ValueError('AMBIGUOUS_HOLE_OWNER')
  owners[0].append(ring)
 return polygons

def run():
 start=time.perf_counter();fetch=json.loads((OUT/'BOUNDARY_FETCH.json').read_text(encoding='utf8'));elements={};conflicts=[]
 for p in sorted((OUT/'raw').glob('*full.osm')):
  for e in ET.parse(p).getroot():
   if e.tag not in ['node','way','relation']:continue
   k=(e.tag,e.get('id'))
   if k in elements and elements[k].get('version')!=e.get('version'):conflicts.append(dict(type=k[0],id=k[1],versions=[elements[k].get('version'),e.get('version')]))
   elements[k]=e
 if conflicts:dump(OUT/'VERSION_CONFLICTS.json',conflicts);raise ValueError('CROSS_CAPTURE_ELEMENT_VERSION_CONFLICT')
 features=[];geometry=[]
 for r in fetch:
  rid=str(r['relation_id']);root=elements.get(('relation',rid));tags={}if root is None else{t.get('k'):t.get('v')for t in root.findall('tag')}
  g=dict(relation_id=rid,name=tags.get('name'),place=tags.get('place'),version=r.get('version'),element_timestamp=r.get('element_timestamp'))
  try:
   if tags.get('place')not in ['city','town','village','hamlet']:raise ValueError('NOT_SETTLEMENT_ENTITY')
   polys=assemble(elements,rid);features.append(dict(id=rid,name=tags['name'],polys=polys,tags=tags));g.update(status='COMPLETE_RECURSIVE_GEOMETRY',polygons=len(polys),holes=sum(len(p)-1 for p in polys))
  except (KeyError,ValueError)as ex:g.update(status='REVIEW_REJECTED',reason=str(ex))
  geometry.append(g)
 dump(OUT/'GEOMETRY_COMPLETE.json',geometry);dump(OUT/'POLYGONS_RECURSIVE.json',features)
 index=ShapeIndex(features);cache={};counter=collections.defaultdict(lambda:collections.defaultdict(collections.Counter))
 def classify(at):
  k=tuple(at)
  if k in cache:return cache[k]
  hits=[];near=[]
  for f in index.nearby(at,100):
   inside,d=shape_state(f['polys'],at)
   if inside:hits.append(f['id'])
   if d<=100+EPS:near.append((f['id'],d))
  result={}
  for radius in [0,100]:
   touch=[rid for rid,d in near if d<=radius+EPS]
   if touch or len(hits)>1:state=dict(status='AMBIGUOUS_BOUNDARY_OR_OVERLAP',locality=None,containing=sorted(hits),boundary=touch)
   elif len(hits)==1:state=dict(status='RESOLVED_COORDINATE_MEMBERSHIP',locality=hits[0],containing=hits,boundary=[])
   else:state=dict(status='UNRESOLVED_NO_SELECTED_POLYGON',locality=None,containing=[],boundary=[])
   result[str(radius)]=state
  cache[k]=result;return result
 baseline=ROOT/'MAP_OSM_Visicom/reports/addr2/92d4bc8d3ba61508452ff73f9ca77599a867a24a1f1168b6f78cacfb3fc53950';dbpath=baseline/'catalog.sqlite';before=sha(dbpath);c=sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True)
 with (OUT/'OBJECT_LOCALITY_PRIVATE.jsonl').open('w',encoding='utf8')as out:
  for oid,source,payload in c.execute('select object_id,source,payload_json from objects order by object_id'):
   x=json.loads(payload)
   if source=='OSM':at=(x['lat'],x['lon'])
   elif source=='VISICOM':at=(x['latitude'],x['longitude'])
   else:at=None
   result=classify(at)if at is not None else{str(r):dict(status='UNRESOLVED_NO_COORDINATE',locality=None)for r in [0,100]}
   for radius,state in result.items():
    counter[source][radius]['total']+=1;counter[source][radius][state['status']]+=1
    if state['locality']:counter[source][radius]['locality:'+state['locality']]+=1
   out.write(json.dumps(dict(object_id=oid,source=source,result=result),ensure_ascii=False)+'\n')
 groups=collections.defaultdict(list)
 for payload, in c.execute('select payload_json from candidates order by candidate_id'):
  x=json.loads(payload)
  if x['kind']!='ADR'or not x['full_house']:continue
  states=[classify(p)for p in x['source_coordinate_alternatives']]
  aggregated={}
  for radius in ['0','100']:
   ls={s[radius]['locality']for s in states};known=all(s[radius]['status']=='RESOLVED_COORDINATE_MEMBERSHIP'for s in states)
   aggregated[radius]=next(iter(ls))if known and len(ls)==1 else None
  groups[x['normalized_label']].append(dict(id=x['candidate_id'],source=x['source'],sectors=x['sector']['sectors'],sector_status=x['sector']['status'],eligible=x['autoeligible_test_only'],localities=aggregated))
 target={k:xs for k,xs in groups.items()if len({s for x in xs for s in x['sectors']})>1};assert len(target)==14719,len(target)
 result={}
 with (OUT/'CONFLICT_SIMULATION_PRIVATE.jsonl').open('w',encoding='utf8')as out:
  for radius in ['0','100']:
   counts=collections.Counter();localsplit=collections.Counter()
   for k,xs in target.items():
    counts['baseline_keys']+=1
    counts['single_candidate_key'if len(xs)==1 else'multiple_candidate_key']+=1
    known=all(x['localities'][radius]is not None for x in xs);by=collections.defaultdict(list)
    for x in xs:by[x['localities'][radius]].append(x)
    if known:counts['all_candidates_locality_resolved']+=1
    if known and len(by)>1:
     counts['partitioned_into_multiple_confirmed_localities']+=1
     if all(len({s for x in vs for s in x['sectors']})==1 and all(x['sector_status']=='SECTOR_ONLY'for x in vs)for vs in by.values()):counts['all_locality_partitions_sector_unambiguous']+=1
    lutsk=[x for x in xs if x['localities'][radius]=='1951964'];unknown=[x for x in xs if x['localities'][radius]is None]
    kept=lutsk+unknown if lutsk else xs
    excluded=len(xs)-len(kept);remaining=sorted({s for x in kept for s in x['sectors']})
    if lutsk:counts['has_confirmed_lutsk_candidate']+=1
    if excluded:counts['lutsk_priority_excludes_only_known_other_localities']+=1
    resolved=bool(excluded and kept and len(remaining)==1 and all(x['sector_status']=='SECTOR_ONLY'for x in kept))
    if resolved:
     counts['lutsk_priority_removes_sector_ambiguity']+=1
     if all(x['eligible']for x in kept):counts['also_passes_unchanged_individual_eligibility']+=1
    if len(remaining)>1:counts['still_cross_sector_after_conservative_lutsk_priority']+=1
    if any(x['localities'][radius]is None for x in xs):counts['has_unknown_or_review_locality']+=1
    out.write(json.dumps(dict(radius_m=int(radius),key=k,candidate_count=len(xs),localities=sorted('UNKNOWN'if i is None else i for i in by),kept=len(kept),excluded=excluded,sectors_after=remaining,geometric_ambiguity_removed=resolved),ensure_ascii=False)+'\n')
   result[radius]=dict(counts)
 assert sha(dbpath)==before
 summary=dict(status='INDEPENDENT_PC_PROBE_COMPLETED',catalog_identity=baseline.name,catalog_sha256_before_after=before,catalog_mutated=False,source='Current official OSM API relation/full downloads; independent requests, not one atomic historical snapshot',selected_settlement_relations=len(fetch),complete_recursive_geometries=len(features),version_conflicts=conflicts,classification=dict((s,dict((r,dict(v))for r,v in rs.items()))for s,rs in counter.items()),conflict_analysis=result,elapsed_seconds=time.perf_counter()-start,method='Point and assumed100m disk; all overlapping relation identities remain REVIEW, including same-name duplicate Strumivka relations. Unknown retained in priority simulation; no forced default locality.',limitations=['Coordinate-in-current-polygon evidence, not source-coordinate accuracy or historical/legal boundary certification','Only18selected nearby settlements; outside selected polygons remains unresolved','Boundary dependencies only; no new address collection or current map changes','ADDR2 catalog and production policy unchanged'])
 dump(OUT/'SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=True),flush=True);c.close()
if __name__=='__main__':run()
