"""Explicit authorized dated Geofabrik PBF acquisition, no upload/phone/latest lookup.
New output only; partial failures retained. SHA256 and real header are separate evidence.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import time
import urllib.request

def run(date,expected_bytes,output):
    import re
    if not re.fullmatch(r'\d{6}',date):raise ValueError('DATED_SOURCE_ONLY')
    if not 0<expected_bytes<2*1024**3:raise ValueError('SOURCE_BOUND')
    output.mkdir(parents=True,exist_ok=False);(output/'.gitignore').write_text('*\n',encoding='utf-8')
    url=f'https://download.geofabrik.de/europe/ukraine-{date}.osm.pbf'
    def request(url):return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'TaxiHelper-GEO4-authorized-dated-acquisition'}),timeout=60)
    with request(url+'.md5') as response:
        body=response.read(4097)
        if len(body)>4096:raise ValueError('MD5_BOUND')
        md5=body.decode('ascii').split()[0]
        if not re.fullmatch('[a-f0-9]{32}',md5):raise ValueError('SOURCE_MD5_FORMAT')
    start=time.perf_counter();before=datetime.datetime.now(datetime.timezone.utc).isoformat();h=hashlib.sha256();m=hashlib.md5();total=0
    stage=output/f'ukraine-{date}.osm.pbf.partial'
    with request(url) as response,stage.open('xb') as dst:
        if int(response.headers.get('Content-Length','-1'))!=expected_bytes:raise ValueError('SOURCE_SIZE_HEADER')
        headers=dict(response.headers)
        for b in iter(lambda:response.read(1<<20),b''):
            total+=len(b)
            if total>expected_bytes:raise ValueError('SOURCE_OVERFLOW')
            dst.write(b);h.update(b);m.update(b)
            if total//(100<<20)!=(total-len(b))//(100<<20):print('Dated PBF bytes',total,flush=True)
    if total!=expected_bytes or m.hexdigest()!=md5:raise ValueError('SOURCE_INTEGRITY')
    stage.rename(output/f'ukraine-{date}.osm.pbf')
    result=dict(status='PASS',url=url,bytes=total,sha256=h.hexdigest(),md5=md5,md5_source_body=body.decode('ascii'),started_utc=before,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),download_seconds=time.perf_counter()-start,headers=headers,license='ODbL-1.0; OpenStreetMap contributors')
    (output/'ACQUISITION.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k!='headers'},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--date',required=True);p.add_argument('--expected-bytes',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.date,a.expected_bytes,a.output)
