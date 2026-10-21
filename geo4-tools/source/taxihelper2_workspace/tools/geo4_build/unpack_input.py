"""Bounded exact source-capsule restoration for Windows/Linux local or future CI.
No network. Explicit expected archive SHA required. Never extracts into an existing root.
"""
import argparse
import json
from pathlib import Path,PurePosixPath
import stat
import zipfile
from compiler import sha,write

def unpack(archive,expected,output,maximum=2*1024**3):
    if sha(archive)!=expected:raise ValueError('CAPSULE_HASH')
    if output.exists():raise FileExistsError('NEW_CAPSULE_OUTPUT_REQUIRED')
    with zipfile.ZipFile(archive) as src:
        entries=src.infolist()
        if len(entries)>4096 or sum(e.file_size for e in entries)>maximum:raise ValueError('CAPSULE_BOUND')
        seen=set()
        for e in entries:
            p=PurePosixPath(e.filename)
            if e.filename in seen or p.is_absolute() or '..' in p.parts or '\\' in e.filename or ':' in e.filename or p.parts[0] not in ['additional','dependencies'] or e.is_dir() or stat.S_ISLNK(e.external_attr>>16):raise ValueError('CAPSULE_PATH')
            seen.add(e.filename)
        output.mkdir(parents=True);(output/'.gitignore').write_text('*\n',encoding='utf-8');total=0
        for e in entries:
            target=output/e.filename;target.parent.mkdir(parents=True,exist_ok=True);size=0
            with src.open(e) as f,target.open('xb') as dst:
                for b in iter(lambda:f.read(1<<20),b''):
                    size+=len(b);total+=len(b)
                    if size>e.file_size or total>maximum:raise ValueError('CAPSULE_DECODE_BOUND')
                    dst.write(b)
            if size!=e.file_size:raise ValueError('CAPSULE_TRUNCATED')
    a=output/'additional';d=output/'dependencies';m=json.loads((a/'manifest.json').read_text(encoding='utf-8'));refs=json.loads((d/'manifest.json').read_text(encoding='utf-8'))
    if m['status']!='PASS' or refs['status']!='PASS' or refs['additional_manifest_sha256']!=sha(a/'manifest.json'):raise ValueError('CAPSULE_CLOSURE')
    for f in m['files']:
        p=(a/f['path']).resolve()
        if not p.is_relative_to(a.resolve()) or p.stat().st_size!=f['bytes'] or sha(p)!=f['sha256']:raise ValueError('CAPSULE_RAW_FILE')
    for f in refs['references']:
        p=(output/f['portable_location']).resolve()
        if not p.is_relative_to(output.resolve()) or p.stat().st_size!=f['bytes'] or sha(p)!=f['sha256']:raise ValueError('CAPSULE_PROVENANCE_FILE')
    result=dict(status='PASS',archive_sha256=expected,entries=len(entries),raw_bytes=total,additional_files=len(m['files']),provenance_references=len(refs['references']),unresolved_references=0)
    write(output/'ROUND_TRIP.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--expected-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(unpack(a.archive,a.expected_sha256,a.output),indent=2))
