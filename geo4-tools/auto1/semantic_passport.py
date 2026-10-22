"""Cross-platform semantic baseline for a completed GEO4 job; aggregate hashes only.
Full value/multiplicity digest, not count-only accuracy. No input mutation or phone access.
Physical SQLite layout/version bindings are separately verified, not compared as source facts.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib
from compiler import ROOT,sha,write

def table_digest(db,table):
    columns=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
    sql='SELECT * FROM '+table+' ORDER BY '+','.join(str(i+1) for i in range(len(columns)))
    h=hashlib.sha256();count=0
    for row in db.execute(sql):
        if table=='meta' and row[0] in ['package_revision','policy','geo_sha256','geo_version']:continue
        values=list(row)
        for i,v in enumerate(values):
            if isinstance(v,bytes):
                if table in ['details','geometry'] and columns[i]=='payload':values[i]=['DECOMPRESSED_UTF8',zlib.decompress(v).decode('utf-8')]
                else:values[i]=['RAW_BLOB_SHA256',hashlib.sha256(v).hexdigest(),len(v)]
        b=json.dumps(values,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8');h.update(len(b).to_bytes(8,'big'));h.update(b);count+=1
    return dict(rows=count,sha256=h.hexdigest())

def passport(job):
    result={}
    for name,path in [('base',job/'mobile.sqlite'),('resolver',job/'resolve1/evidence.sqlite')]:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            if any(not n.replace('_','').isalnum() for n in tables):raise ValueError('TABLE_NAME')
            result[name]={table:table_digest(db,table) for table in tables}
    config=json.loads((job/'CONFIG.json').read_text(encoding='utf-8'));side=json.loads((job/'resolve1/descriptor.json').read_text(encoding='utf-8'));base=json.loads((job/'MOBILE_COMPLETE.json').read_text(encoding='utf-8'))
    if side['geo_sha256']!=base['sha256'] or side['geo_version']!=base['revision']:raise ValueError('PHYSICAL_CLOSURE')
    policy=next(Path(x['path']) for x in config['pins'] if x['role']=='contract:INCLUSION_POLICY.json')
    policy_bytes=json.dumps(json.loads(policy.read_text(encoding='utf-8-sig')),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    algorithms={x['role']:hashlib.sha256(Path(x['path']).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for x in config['pins'] if x['role'].startswith('compiler:') or x['role']=='contract:compile_evidence.py'}
    for p in [ROOT/'taxihelper2_workspace/tools/locality_probe/analyze.py',ROOT/'taxihelper2_workspace/tools/addr2/core.py',ROOT/'taxihelper2_workspace/app/src/main/java/com/example/bolthelper/sep1/S1SectorUniverse.kt']:
        algorithms['compiler_dependency:'+p.name]=hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    return dict(contract='GEO4_CROSS_PLATFORM_SEMANTICS_1',source_sha256=next(x['sha256'] for x in config['pins'] if x['role']=='dated_osm'),tables=result,policy_semantic_sha256=hashlib.sha256(policy_bytes).hexdigest(),algorithm_lf_sha256=algorithms,
                exclusion='Only meta.package_revision, policy raw-file SHA, geo_sha256, geo_version are physical/platform bindings. They are individually validated within each build; policy semantic JSON is unchanged/pinned. No source coordinates, labels, IDs, evidence or duplicate rows excluded.',
                scope='Exact mechanical content; not resolver accuracy or byte-layout equality across different SQLite/zlib/toolchains.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--compare',type=Path);a=p.parse_args();result=passport(a.job)
    if a.compare:
        expected=json.loads(a.compare.read_text(encoding='utf-8'))
        if any(expected[k]!=result[k] for k in ['source_sha256','tables','policy_semantic_sha256','algorithm_lf_sha256']):raise ValueError('CROSS_PLATFORM_SEMANTIC_DIFFERENCE_REQUIRES_REVIEW')
        result['comparison']='PASS_EXACT_SOURCE_VALUES_MULTIPLICITY'
    if a.output.exists():raise FileExistsError('PRESERVE_EXISTING_PASSPORT')
    write(a.output,result);print(json.dumps(dict(status='PASS',source_sha256=result['source_sha256'],table_counts={k:len(v) for k,v in result['tables'].items()}),indent=2))
