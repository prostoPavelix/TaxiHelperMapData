"""Explicit bounded dependency acquisition. Reuses saved verified responses.
Only missing roots8534720/8548313 and nine enumerated Styr ways.
Each response<=16MiB, aggregate<=64MiB; no new address/Visicom harvest.
"""
from common import *
import urllib.request,datetime,xml.etree.ElementTree as ET

def run():
 directory=OUT/'supplement';directory.mkdir(exist_ok=True)
 records=json.loads((directory/'FETCH.json').read_text(encoding='utf-8')) if (directory/'FETCH.json').exists() else []
 for row in records:assert sha(directory/f'{row.get("type","relation")}-{row["id"]}-full.osm')==row['sha256']
 required=[('relation',8534720),('relation',8548313)]+[('way',n) for n in [555418233,563704826,563704852,549434033,549628757,334631925,549637942,545086211,364906228]]
 for typ,rid in required:
  if any(row['id']==rid and row.get('type','relation')==typ for row in records):continue
  url=f'https://api.openstreetmap.org/api/0.6/{typ}/{rid}/full';path=directory/f'{typ}-{rid}-full.osm'
  assert not path.exists(),'Unmanifested raw response preserved; inspect before reuse'
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'TaxiHelper-GEO2-bounded-dependency-closure'}),timeout=45) as response:data=response.read(16*1024*1024+1)
  assert len(data)<=16*1024*1024
  path.write_bytes(data);doc=ET.fromstring(data);root=next(e for e in doc.findall(typ) if e.get('id')==str(rid))
  records.append(dict(url=url,type=typ,bytes=len(data),sha256=sha(path),retrieved_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),id=rid,version=root.get('version'),timestamp=root.get('timestamp'),counts={t:len(doc.findall(t)) for t in ['node','way','relation']}))
  assert sum(r['bytes'] for r in records)<=64*1024*1024
 dump(directory/'FETCH.json',records)
 print('Bounded supplement captured',sum(x['bytes'] for x in records),'bytes')

if __name__=='__main__':run()
