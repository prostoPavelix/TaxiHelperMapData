"""Explicit bounded historical OSM capture capsule, no acquisition or epoch relabeling."""
import argparse,base64,json,re
from pathlib import Path
from compiler import sha,write
from transport import digest
NAME=re.compile(r'(FETCH\.json|CAPTURE_GROUPS\.json|(?:relation|way|node)-[0-9]+-full\.osm)')
def pack(source,output):
    if output.exists():raise FileExistsError(output)
    rows=[]
    for f in sorted(source.iterdir()):
        if not f.is_file() or not NAME.fullmatch(f.name) or f.is_symlink():raise ValueError('SUPPLEMENT_PATH')
        body=f.read_bytes();rows.append(dict(name=f.name,bytes=len(body),sha256=digest(body),body_b64=base64.b64encode(body).decode('ascii')))
    if not rows or len(rows)>128 or sum(r['bytes'] for r in rows)>8*1024*1024:raise ValueError('SUPPLEMENT_BOUND')
    write(output,dict(contract='GEO4_HISTORICAL_CAPTURE_CAPSULE_1',files=rows))
def unpack(source,expected,output):
    if output.exists():raise FileExistsError(output)
    if source.stat().st_size>12*1024*1024 or sha(source)!=expected:raise ValueError('SUPPLEMENT_HASH_OR_SIZE')
    j=json.loads(source.read_bytes());rows=j['files']
    if j['contract']!='GEO4_HISTORICAL_CAPTURE_CAPSULE_1' or not 1<=len(rows)<=128:raise ValueError('SUPPLEMENT_CONTRACT')
    if len({r['name'] for r in rows})!=len(rows):raise ValueError('SUPPLEMENT_DUPLICATE')
    bodies=[];total=0
    for r in rows:
        if not NAME.fullmatch(r['name']):raise ValueError('SUPPLEMENT_PATH')
        body=base64.b64decode(r['body_b64'],validate=True);total+=len(body)
        if len(body)!=r['bytes'] or digest(body)!=r['sha256'] or total>8*1024*1024:raise ValueError('SUPPLEMENT_ENTRY_HASH_OR_BOUND')
        bodies.append((r['name'],body))
    output.mkdir(parents=True)
    for name,body in bodies:(output/name).write_bytes(body)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['pack','unpack']);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--expected-sha256');a=p.parse_args()
    if a.mode=='pack':pack(a.source,a.output)
    else:unpack(a.source,a.expected_sha256,a.output)
