"""Acquire only the explicitly approved dated GEO2 PBF; private workspace output.
No phone, Visicom calls, application writes or publication. Reuse verified final bytes.
"""
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
DIRECTORY=ROOT/'MAP_OSM_Visicom/data/source_snapshots/geofabrik-ukraine-261015'
URL='https://download.geofabrik.de/europe/ukraine-261015.osm.pbf'
EXPECTED_BYTES=880542806
EXPECTED_MD5='9b79092ea9a1f43a7958c5b3adf9514b'

def hashes(path):
    a,b=hashlib.sha256(),hashlib.md5()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):a.update(block);b.update(block)
    return a.hexdigest(),b.hexdigest()

def run():
    DIRECTORY.mkdir(parents=True,exist_ok=True)
    dest=DIRECTORY/'ukraine-261015.osm.pbf'
    if dest.exists():
        sha,md5=hashes(dest)
        assert dest.stat().st_size==EXPECTED_BYTES and md5==EXPECTED_MD5,'EXISTING_SOURCE_MISMATCH'
        print('Reused verified PBF',sha,flush=True);return
    stage=dest.with_suffix('.pbf.partial')
    assert not stage.exists(),'Partial preserved; inspect before retry, do not silently overwrite'
    before=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with urllib.request.urlopen(urllib.request.Request(URL,headers={'User-Agent':'TaxiHelper-GEO2-PC-source-build'}),timeout=45) as response:
        assert int(response.headers['Content-Length'])==EXPECTED_BYTES
        headers=dict(response.headers)
        with stage.open('xb') as out:
            total=0;report=0
            while block:=response.read(1<<20):
                out.write(block);total+=len(block)
                if total-report>=100*(1<<20):print('PBF downloaded',total,'/',EXPECTED_BYTES,flush=True);report=total
    sha,md5=hashes(stage)
    assert stage.stat().st_size==EXPECTED_BYTES and md5==EXPECTED_MD5,'SOURCE_DOWNLOAD_MISMATCH'
    stage.rename(dest)
    manifest=dict(url=URL,retrieved_started_utc=before,retrieved_finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),sha256=sha,md5=md5,bytes=EXPECTED_BYTES,headers=headers,license='ODbL-1.0; OpenStreetMap contributors',scope='PC_SOURCE_ONLY')
    (DIRECTORY/'ACQUISITION.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('Verified dated PBF',sha,flush=True)

if __name__=='__main__':run()
