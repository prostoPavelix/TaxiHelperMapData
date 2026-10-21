"""One PC spatial selection with full same-snapshot reference closure, preserving tags.
Uses native PBF area assembly to detect enclosing geometry without AOI-internal vertices.
BackReferenceWriter is followed by independent explicit missing/cycle checks in build.
"""
from common import *
import osmium,time,collections,tempfile,gzip
from shapely.geometry import shape,LineString,Polygon
from shapely import wkb

def intersect_way(points,region):
 if len(points)<2:return False
 xs=[p[0] for p in points];ys=[p[1] for p in points];a,b,c,d=region.bounds
 if max(xs)<a or min(xs)>c or max(ys)<b or min(ys)>d:return False
 if points[0]==points[-1] and len(points)>=4:
  return Polygon(points).intersects(region)
 return LineString(points).intersects(region)

def run():
 final=OUT/'selected.osm.pbf'
 if final.exists() and (OUT/'EXTRACTION.json').exists():
  saved=json.loads((OUT/'EXTRACTION.json').read_text(encoding='utf-8'))
  assert sha(final)==saved['extract_sha256'] and sha(SOURCE)==saved['source_sha256'],'EXISTING_SOURCE_OR_EXTRACT_MISMATCH'
  print('Reusing verified selected extract',flush=True);return
 assert not final.exists(),'Preserve incomplete output; inspect before retry'
 start=time.perf_counter();region=shape(aoi());west,south,east,north=region.bounds
 roots={int(x['id']) for x in json.loads((ROOT/'docs/taxihelper_2_0/geo1/AOI_EVIDENCE.json').read_text(encoding='utf-8'))['settlement_roots']}
 temp=OUT/'writer-temp';temp.mkdir(exist_ok=True);tempfile.tempdir=str(temp)
 relations={}
 class Relations(osmium.SimpleHandler):
  def relation(self,r):relations[r.id]=dict(tags=dict(r.tags),members=[(m.type,m.ref,m.role) for m in r.members])
 scanner=Relations()
 with osmium.io.Reader(str(SOURCE),osmium.osm.RELATION) as reader:
  h=reader.header();header={k:h.get(k) for k in ['generator','osmosis_replication_timestamp','osmosis_replication_sequence_number','osmosis_replication_base_url']};osmium.apply(reader,scanner)
 print('Relation metadata',len(relations),'header',header,flush=True)
 selected={'n':set(),'w':set(),'r':set()};counts=collections.Counter();area_relations=set();factory=osmium.geom.WKBFactory()
 writer=osmium.BackReferenceWriter(str(final),str(SOURCE),remove_tags=False,relation_depth=0)
 class Select(osmium.SimpleHandler):
  def node(self,n):
   counts['nodes_seen']+=1
   if n.location.valid() and west<=n.lon<=east and south<=n.lat<=north:
    selected['n'].add(n.id);writer.add_node(n)
   if counts['nodes_seen']%10000000==0:print('Scanned nodes',counts['nodes_seen'],flush=True)
  def way(self,w):
   counts['ways_seen']+=1
   try:ps=[(n.lon,n.lat) for n in w.nodes]
   except osmium.InvalidLocationError:counts['source_ways_invalid_location']+=1;return
   if intersect_way(ps,region):selected['w'].add(w.id);writer.add_way(w)
   if counts['ways_seen']%1000000==0:print('Scanned ways',counts['ways_seen'],flush=True)
  def area(self,a):
   # Complete multipolygons, including enclosing rings whose vertices all lie outside.
   if a.from_way():return
   ps=[(n.lon,n.lat) for ring in a.outer_rings() for n in ring]
   if not ps:return
   xs=[x[0] for x in ps];ys=[x[1] for x in ps];west,south,east,north=region.bounds
   if max(xs)<west or min(xs)>east or max(ys)<south or min(ys)>north:return
   try:
    geom=wkb.loads(factory.create_multipolygon(a),hex=True)
    if geom.intersects(region):area_relations.add(a.orig_id())
   except Exception:counts['area_geometry_error_near_aoi']+=1
 Select().apply_file(str(SOURCE),locations=True,idx='flex_mem')
 initial=roots|area_relations
 for rid,r in relations.items():
  if any(typ in ['n','w'] and ref in selected[typ] for typ,ref,role in r['members']):initial.add(rid)
 selected['r']=set(initial);pending=list(initial);cycles=[];missing_rel=[]
 while pending:
  rid=pending.pop();r=relations.get(rid)
  if not r:missing_rel.append(rid);continue
  for typ,ref,role in r['members']:
   if typ=='r' and ref not in selected['r']:selected['r'].add(ref);pending.append(ref)
 class WriteRelations(osmium.SimpleHandler):
  def relation(self,r):
   if r.id in selected['r']:writer.add_relation(r)
 with osmium.io.Reader(str(SOURCE),osmium.osm.RELATION) as r:osmium.apply(r,WriteRelations())
 print('Selected roots', {k:len(v) for k,v in selected.items()},'closing same-snapshot dependencies',flush=True)
 writer.close()
 dump(OUT/'SELECTION_IDS_PRIVATE.json',{k:sorted(v) for k,v in selected.items()})
 dump(OUT/'EXTRACTION.json',dict(header=header,source_sha256=sha(SOURCE),extract_sha256=sha(final),
  initial_relation_count=len(initial),root_settlements=sorted(roots),root_missing=sorted(roots-set(relations)),
  area_relations_intersecting=len(area_relations),selected_counts={k:len(v) for k,v in selected.items()},counts=dict(counts),
  missing_relations_during_selection=missing_rel,seconds=time.perf_counter()-start,
  method='Geometry intersection + enclosing multipolygon assembly + direct parent relations + full recursive child relations + same-snapshot way/node completion; remove_tags=False. Independent closure check required.'))
 print('Extract complete',final.stat().st_size,'bytes',flush=True)

if __name__=='__main__':run()
