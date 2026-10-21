"""Private PC build paths and stable serialization; no application imports."""
from pathlib import Path
import hashlib,json,sqlite3,sys,unicodedata,re
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'MAP_OSM_Visicom/.geo2-deps'))
OUT=ROOT/'MAP_OSM_Visicom/reports/geo2_20261016'
OUT.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'MAP_OSM_Visicom/data/source_snapshots/geofabrik-ukraine-261015/ukraine-261015.osm.pbf'
ADDR2=ROOT/'MAP_OSM_Visicom/reports/addr2/92d4bc8d3ba61508452ff73f9ca77599a867a24a1f1168b6f78cacfb3fc53950/catalog.sqlite'
MERGED=ROOT/'MAP_OSM_Visicom/reports/visicom_pilot_v4/merged_all_sources.sqlite'
PUBLIC=ROOT/'docs/taxihelper_2_0/geo2'
def js(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def ro(p):
 c=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True);return c
def normalize(s):return ' '.join(''.join(c if c.isalnum() else ' ' for c in unicodedata.normalize('NFKC',s).casefold()).split())
def aoi():
 doc=json.loads((ROOT/'docs/taxihelper_2_0/geo1/AOI_PROPOSAL.geojson').read_text(encoding='utf-8'))
 return doc['features'][0]['geometry']
def search_texts(tags):
 """Source-tag extraction, not ranking or locality inference."""
 values=[]
 for k,v in tags.items():
  name_field=not k.startswith('source:') and any(part=='name' or part.endswith('_name') for part in k.split(':'))
  if name_field or k=='name' or k.startswith(('name:','name_','alt_name','old_name','official_name','short_name','loc_name','int_name','addr:','brand:','operator:')) or k in ['brand','operator','ref','building:name','contact:street','contact:housenumber','contact:city','contact:postcode']:
   values.append((k,v));values.extend((k+':semicolon_component',x.strip()) for x in v.split(';') if ';' in v and x.strip())
 street=tags.get('addr:street') or tags.get('addr:place')
 if street and tags.get('addr:housenumber'):
  full=street+' '+tags['addr:housenumber'];values.append(('structured_address',full))
  if tags.get('addr:city'):values.append(('structured_address_with_city',tags['addr:city']+', '+full))
 return values
