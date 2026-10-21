"""Independent render-only artifact using existing unchanged visual compiler/codec."""
from common import *
import xml.etree.ElementTree as ET

def run():
 selection=json.loads((OUT/'SELECTION_IDS_PRIVATE.json').read_text(encoding='utf-8'));wanted={'OSM:w:'+str(i) for i in selection['w']}
 root=ET.Element('osm',version='0.6',generator='TaxiHelper-GEO2-visual-subset')
 with ro(OUT/'master.sqlite') as db:
  ways=[];nodes=set()
  for oid,payload in db.execute("SELECT oid,payload FROM objects WHERE source='OSM' AND kind='w' ORDER BY oid"):
   if oid not in wanted:continue
   body=json.loads(payload)
   if 'highway' not in body['tags']:continue
   ways.append(body);nodes.update(c for c,r in body['members'])
  for oid in sorted(nodes):
   row=db.execute('SELECT payload FROM objects WHERE oid=?',(oid,)).fetchone()
   if not row:raise ValueError('VISUAL_NODE_MISSING')
   body=json.loads(row[0]);lat,lon=body['coordinate'];ET.SubElement(root,'node',id=str(body['id']),lat=str(lat),lon=str(lon))
  for body in ways:
   w=ET.SubElement(root,'way',id=str(body['id']))
   for child,role in body['members']:ET.SubElement(w,'nd',ref=child.split(':')[-1])
   for k,v in sorted(body['tags'].items()):ET.SubElement(w,'tag',k=k,v=v)
 source=OUT/'visual-source.osm';ET.ElementTree(root).write(source,encoding='utf-8',xml_declaration=True)
 sys.path.insert(0,str(ROOT/'taxihelper2_workspace/tools'))
 import build_lightweight_visual_map as compiler
 result=compiler.build(source,OUT/'visual_roads.bin',OUT/'visual_manifest.json')
 verified=compiler.verify(OUT/'visual_roads.bin',OUT/'visual_manifest.json')
 dump(OUT/'VISUAL.json',dict(status='PASS_EXISTING_CODEC',result=result,verify=verified,
  upstream_pbf_sha256=sha(SOURCE),source_subset_sha256=sha(source),independent_visual_component=True,
  road_analysis='Old graph/anchor component unchanged, bound to its old OSM snapshot; no new routing graph or mixed Android bundle claimed'))
 print('Visual component',result['artifact'],flush=True)

if __name__=='__main__':run()
