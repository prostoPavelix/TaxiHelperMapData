"""ADDR2 PC-only geometry and policy. No app imports, network or source mutation."""
import math,re,unicodedata,xml.etree.ElementTree as ET,collections
VERSION='ADDR2_SECTOR_LOCALITY_1'
EARTH=6371000.0
EPS=1e-6 # projected numerical boundary guard in metres, not source accuracy

def key(s):return ' '.join(re.sub(r'[^\w]+',' ',unicodedata.normalize('NFKC',str(s)).lower(),flags=re.UNICODE).split())
def dist(a,b):
 la,lo=map(math.radians,a);lb,ob=map(math.radians,b)
 return 2*EARTH*math.asin(min(1,math.sqrt(math.sin((lb-la)/2)**2+math.cos(la)*math.cos(lb)*math.sin((ob-lo)/2)**2)))
def xy(p,at):return (math.radians(p[0]-at[1])*EARTH*math.cos(math.radians(at[0])),math.radians(p[1]-at[0])*EARTH)
def segment_distance(a,b,at):
 ax,ay=xy(a,at);bx,by=xy(b,at);dx,dy=bx-ax,by-ay
 t=max(0,min(1,-(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0
 return math.hypot(ax+t*dx,ay+t*dy)
def ring_state(r,at):
 x,y=at[1],at[0];inside=False;near=float('inf')
 for a,b in zip(r,r[1:]+r[:1]):
  near=min(near,segment_distance(a,b,at))
  if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:inside=not inside
 return inside,near

def shape_state(polys,at):
 inside=False;near=float('inf')
 for poly in polys:
  outer,d=ring_state(poly[0],at);near=min(near,d);hole=False
  for r in poly[1:]:
   h,d=ring_state(r,at);hole|=h;near=min(near,d)
  inside|=outer and not hole
 return inside,near

class ShapeIndex:
 def __init__(self,features):
  self.features=features;self.grid=collections.defaultdict(set)
  for i,f in enumerate(features):
   points=[p for poly in f['polys'] for ring in poly for p in ring]
   a,b,c,d=min(p[0]for p in points),min(p[1]for p in points),max(p[0]for p in points),max(p[1]for p in points)
   for x in range(math.floor(a/.01),math.floor(c/.01)+1):
    for y in range(math.floor(b/.01),math.floor(d/.01)+1):self.grid[x,y].add(i)
 def nearby(self,at,radius=0):
  dy=radius/110000;dx=dy/max(.01,math.cos(math.radians(at[0])));ids=set()
  for x in range(math.floor((at[1]-dx)/.01),math.floor((at[1]+dx)/.01)+1):
   for y in range(math.floor((at[0]-dy)/.01),math.floor((at[0]+dy)/.01)+1):ids.update(self.grid.get((x,y),()))
  return [self.features[i] for i in sorted(ids)]
 def locality(self,at,explicit=None,radius=0):
  hits=[];touch=[]
  for f in self.nearby(at,radius):
   ins,d=shape_state(f['polys'],at)
   if ins:hits.append(f)
   if d<=radius+EPS:touch.append(f['id'])
  names=sorted({key(f['name'])for f in hits});status='unknown';value=None
  if touch or len(names)>1:status='ambiguous'
  elif len(names)==1:status='resolved';value=names[0]
  if explicit and value and key(explicit)!=value:status='conflict';value=None
  return dict(status=status,value=value,source_assertion=explicit or None,method='SETTLEMENT_POLYGON_DISK' if radius else 'SETTLEMENT_POLYGON_POINT',evidence_ids=[f['id']for f in hits],boundary_ids=touch,scope_radius_m=radius)
 def sector(self,at,radius):
  if not all(math.isfinite(x)for x in at) or radius<0:raise ValueError('Invalid point/radius')
  hits=[];touch=[]
  for f in self.nearby(at,radius):
   ins,d=shape_state(f['polys'],at)
   if ins:hits.append(f['id'])
   if d<=radius+EPS:touch.append(f['id'])
  if touch or len(hits)>1:return dict(status='SECTOR_AMBIGUOUS',sectors=sorted(set(hits+touch)),reason='BOUNDARY_OR_OVERLAP_OR_ALTERNATIVE_REGION')
  if len(hits)==1:return dict(status='SECTOR_ONLY',sectors=hits,reason='ENTIRE_ASSUMED_TOLERANCE_INSIDE_SINGLE_SECTOR')
  return dict(status='OUTSIDE_OR_UNRESOLVED',sectors=[],reason='NO_COVERING_SECTOR')

def sector_consensus(results):
 values=sorted({s for r in results for s in r['sectors']})
 if not results or any(r['status']=='OUTSIDE_OR_UNRESOLVED' for r in results):return dict(status='OUTSIDE_OR_UNRESOLVED',sectors=values,reason='UNCOVERED_ALTERNATIVE')
 if any(r['status']!='SECTOR_ONLY'for r in results)or len(values)!=1:return dict(status='SECTOR_AMBIGUOUS',sectors=values,reason='ALTERNATIVES_NOT_SAME_STABLE_SECTOR')
 return dict(status='SECTOR_ONLY',sectors=values,reason='ALL_PLAUSIBLE_ALTERNATIVES_AGREE_NO_IDENTITY_MERGE')

def join_rings(parts):
 parts=[list(p)for p in parts];out=[]
 while parts:
  chain=parts.pop(0)
  while chain[0]!=chain[-1]:
   choices=[(i,p)for i,p in enumerate(parts)if p and chain[-1]in(p[0],p[-1])]
   if len(choices)!=1:raise ValueError('INCOMPLETE_OR_BRANCHING_RING')
   i,p=choices[0];parts.pop(i)
   if p[-1]==chain[-1]:p=p[::-1]
   chain.extend(p[1:])
  if len(chain)<4:raise ValueError('DEGENERATE_RING')
  out.append(chain)
 return out

def osm_inventory(path):
 nodes={};ways={};rels=[];counts=collections.Counter();interesting=[]
 for _,e in ET.iterparse(path,events=['end']):
  if e.tag not in ('node','way','relation'):continue
  typ=e.tag;counts[typ]+=1;tags={t.get('k'):t.get('v')for t in e.findall('tag')};oid=typ+':'+e.get('id')
  if typ=='node':nodes[e.get('id')]=(float(e.get('lon')),float(e.get('lat')))
  if typ=='way':ways[e.get('id')]=[n.get('ref')for n in e.findall('nd')]
  members=[dict(m.attrib)for m in e.findall('member')]
  if any(t in tags for t in ('building','place','boundary','addr:city')):interesting.append(dict(id=oid,tags=tags,geometry_kind=typ,members=members,node_refs=ways.get(e.get('id'),[]) if typ=='way' else [],point=nodes.get(e.get('id'))if typ=='node'else None))
  if typ=='relation' and tags.get('place')in('city','town','village','hamlet'):rels.append((oid,tags,members))
  e.clear()
 boundaries=[];rejected=[]
 for oid,tags,members in rels:
  try:
   if tags.get('type')not in('multipolygon','boundary'):raise ValueError('NOT_A_BOUNDARY_GEOMETRY')
   outer=join_rings([ways[m['ref']]for m in members if m['type']=='way'and m.get('role','')in('outer','')])
   inner=join_rings([ways[m['ref']]for m in members if m['type']=='way'and m.get('role')=='inner'])
   polys=[[[nodes[n]for n in ring]]for ring in outer]
   if not polys:raise ValueError('NO_OUTER_RING')
   for hole in inner:
    r=[nodes[n]for n in hole];owners=[p for p in polys if ring_state(p[0],(r[0][1],r[0][0]))[0]]
    if len(owners)!=1:raise ValueError('AMBIGUOUS_HOLE')
    owners[0].append(r)
   boundaries.append(dict(id=oid,name=tags.get('name',''),entity_type=tags['place'],polys=polys,tags=tags,source='OSM_SETTLEMENT_FEATURE',crs='EPSG:4326',coordinate_order='lon,lat'))
  except (ValueError,KeyError)as ex:rejected.append(dict(id=oid,reason=str(ex)))
 return dict(counts=dict(counts),features=interesting,settlement_polygons=boundaries,rejected_settlement_geometry=rejected,municipalities_not_settlements=sum(x['tags'].get('place')=='municipality'for x in interesting))
